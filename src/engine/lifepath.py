"""Lifepath engine for Cepheus Engine SRD character generation (U3).

Implements the full CE SRD lifepath: roll-six-then-assign pool characteristics,
career qualification, multi-term loop (survival/advancement/skills/graduated
aging), and mustering out.

Each step is a Command applied through the Engine funnel, producing audit events.
The LifepathRunner orchestrates the sequence and handles death-mode branching.

No LLM required — this is the standalone v0.1 chargen layer (AE7, R9, R10).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import ClassVar

from src.engine.audit import Event, EventKind
from src.engine.commands import Command, Engine, RollCharacteristicCommand
from src.engine.dice import Roller, RollResult
from src.engine.state import AgingSlot, CareerTermRecord, Character, GameState, Injury
from src.rulesets.base import SkillTableEntry
from src.rulesets.cepheus import CepheusRuleSet
from src.themepacks.base import LoadedThemePack

_CHARACTERISTICS = ("STR", "DEX", "END", "INT", "EDU", "SOC")
_PHYSICAL_CHARACTERISTICS = ("STR", "DEX", "END")

#: CE SRD graduated aging table (B4). Key: adjusted roll (2D6 - terms),
#: clamped at -6. Value: slots of (group, points) the player distributes
#: across characteristics of that group via ApplyAgingReductionCommand.
_AGING_TABLE: dict[int, list[tuple[str, int]]] = {
    -6: [("physical", 2), ("physical", 2), ("physical", 2), ("mental", 1)],
    -5: [("physical", 2), ("physical", 2), ("physical", 2)],
    -4: [("physical", 2), ("physical", 2), ("physical", 1)],
    -3: [("physical", 2), ("physical", 1), ("physical", 1)],
    -2: [("physical", 1), ("physical", 1), ("physical", 1)],
    -1: [("physical", 1), ("physical", 1)],
    0: [("physical", 1)],
}

#: Regex to parse cash benefit strings like "50,000 Cr" (B15/FR2).
# Also matches fantasy "gold crowns" so fantasy cash benefits persist to
# credits (T12 review finding — fantasy packs use "gold crowns" not "Cr").
_CASH_RE = re.compile(r"([\d,]+)\s*(?:Cr|gold crowns)")


def benefit_rolls_for(terms: int, rank: int) -> int:
    """Total mustering-out benefit rolls: terms + rank bonus (B15).

    Rank bonus: +1 at rank 4, +2 at rank 5, +3 at rank 6.
    """
    return terms + {4: 1, 5: 2, 6: 3}.get(rank, 0)


def material_dm_for(rank: int) -> int:
    """DM on the material benefits table from officer rank (B15).

    Returns +1 at rank >= 5, enabling row 7 of the material table.
    SRD-verified 2026-07-30: "characters of rank O5 or O6 gain +1 on
    Material Benefit rolls."
    """
    return 1 if rank >= 5 else 0


# ---------------------------------------------------------------------------
# Table lookup helpers.
# ---------------------------------------------------------------------------


def lookup_table_result(entries: list[SkillTableEntry], roll: int) -> SkillTableEntry:
    """Find the table entry matching the roll value.

    Raises ``IndexError`` if the roll falls outside every entry's range —
    out-of-range rolls indicate a data or DM bug and must surface, never
    be silently clamped (N4).
    """
    for entry in entries:
        if entry.min <= roll <= entry.max:
            return entry
    raise IndexError(
        f"Roll {roll} outside table range "
        f"[{min(e.min for e in entries)}..{max(e.max for e in entries)}]"
    )


def apply_skill_result(character: Character, result: str) -> tuple[str, str]:
    """Apply a skill table result string to the character.

    Returns (gain_type, gain_name) where gain_type is 'skill' or 'characteristic'.
    Result strings like ``+1 STR`` increment a characteristic; everything else
    is treated as a skill name and incremented by 1.
    """
    result = result.strip()
    if result.startswith("+"):
        parts = result.split()
        amount = int(parts[0])
        stat = parts[1]
        current = character.characteristics.get(stat, 0)
        character.characteristics[stat] = current + amount
        return ("characteristic", stat)
    else:
        current = character.skills.get(result, 0)
        character.skills[result] = current + 1
        return ("skill", result)


def apply_injury_result(
    character: Character, result: str, chosen_stat: str | None
) -> dict[str, int]:
    """Apply an injury-table result string; returns ``{stat: amount}`` reduced.

    Strings: ``-N STAT`` (fixed stat) or ``-N PHYSICAL`` (player-chosen,
    requires ``chosen_stat`` to be one of STR/DEX/END). ``0 PHYSICAL`` is a
    no-effect result (lightly injured). Characteristics floor at 0 — the
    caller checks for the injury crisis (stat at 0) afterwards (B13).
    """
    parts = result.split()
    amount = abs(int(parts[0]))
    stat = parts[1].upper()
    if stat == "PHYSICAL":
        chosen_stat = chosen_stat.upper() if chosen_stat else None
        if chosen_stat not in _PHYSICAL_CHARACTERISTICS:
            raise ValueError("Player must choose a physical characteristic")
        stat = chosen_stat
    current = character.characteristics.get(stat, 0)
    applied = min(amount, current)
    character.characteristics[stat] = current - applied
    return {stat: applied}


# ---------------------------------------------------------------------------
# Result dataclasses (transient — not serialized).
# ---------------------------------------------------------------------------


@dataclass
class QualificationResult:
    career_id: str
    career_name: str
    characteristic: str
    char_value: int
    char_dm: int
    raw_roll: int
    adjusted_total: int
    target: int
    success: bool

    @property
    def margin(self) -> int:
        return self.adjusted_total - self.target


@dataclass
class SkillGain:
    table_name: str
    roll: int
    result_text: str
    gain_type: str
    gain_name: str
    cascade_parent: str | None = None


@dataclass
class TermResult:
    term_number: int
    career_id: str
    career_name: str
    age_before: int
    age_after: int
    survival_raw: int = 0
    survival_dm: int = 0
    survival_total: int = 0
    survival_target: int = 0
    survival_success: bool = True
    died: bool = False
    mishap: bool = False
    commission_raw: int = 0
    commission_dm: int = 0
    commission_total: int = 0
    commission_target: int = 0
    commission_success: bool = False
    advancement_raw: int = 0
    advancement_dm: int = 0
    advancement_total: int = 0
    advancement_target: int = 0
    advancement_success: bool = False
    skill_gains: list[SkillGain] = field(default_factory=list)
    rank_before: int = 0
    rank_after: int = 0
    rank_title: str = ""
    aging_raw: int = 0
    aging_success: bool = True
    aging_reductions: dict[str, int] = field(default_factory=dict)

    @property
    def survival_margin(self) -> int:
        return self.survival_total - self.survival_target


@dataclass
class MusteringOutResult:
    terms_served: int = 0
    final_rank: int = 0
    career_name: str = ""
    # Plan fields (Task 12): computed by muster_out() without rolling.
    total_rolls: int = 0  # benefit_rolls_for(terms, rank)
    cash_dm: int = 0  # always 0 for cash
    material_dm: int = 0  # material_dm_for(rank)
    # Populated by claim_benefit (batch or TUI per-roll allocation):
    cash_benefits: list[str] = field(default_factory=list)
    material_benefits: list[str] = field(default_factory=list)
    cash_rolls: list[int] = field(default_factory=list)
    material_rolls: list[int] = field(default_factory=list)


@dataclass
class LifepathResult:
    characteristics: dict[str, int] = field(default_factory=dict)
    qualification: QualificationResult | None = None
    terms: list[TermResult] = field(default_factory=list)
    mustering_out: MusteringOutResult | None = None
    character_alive: bool = True
    career_id: str = ""

    @property
    def num_terms(self) -> int:
        return len(self.terms)


# ---------------------------------------------------------------------------
# Lifepath commands — each goes through the Engine.apply() funnel.
# ---------------------------------------------------------------------------


class QualificationCommand(Command):
    """Roll qualification check (2D6 + char DM + extra_dm vs target).

    ``extra_dm`` carries optional modifiers the runner derives from outside
    the character's intrinsic stat — most notably the career-change DM
    (Task 11) for characters entering a second career. It defaults to ``0``
    so single-career qualification is unchanged.
    """

    command_type: ClassVar[str] = "lifepath_qualification"
    career_id: str
    characteristic: str
    target: int
    extra_dm: int = 0

    def resolve(self, state: GameState, roller: Roller) -> RollResult:
        char_value = state.character.characteristics.get(self.characteristic, 7)
        dm = CepheusRuleSet().characteristic_dm(char_value) + self.extra_dm
        return roller.roll("lifepath", 2, 6, modifiers=dm)

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        assert roll is not None
        success = roll.total >= self.target
        if success:
            state.character.career = self.career_id
        return Event(
            kind=EventKind.ROLL,
            command_type=self.command_type,
            description=(
                f"Qualification for {self.career_id}: "
                f"2D6={sum(roll.rolls)}+DM({roll.modifiers})="
                f"{roll.total} vs {self.target} -> "
                f"{'success' if success else 'failure'}"
            ),
            roll=roll,
            changes={
                "career_id": self.career_id,
                "characteristic": self.characteristic,
                "raw_roll": sum(roll.rolls),
                "char_dm": roll.modifiers,
                "adjusted_total": roll.total,
                "target": self.target,
                "success": success,
            },
        )


class EnterCareerCommand(Command):
    """Enter an always-open career (e.g. Drifter) without a qualification roll.

    Always-open careers (``CareerData.always_open``) auto-qualify per SRD — no
    dice are rolled, no career-change DM applies. Routing the career assignment
    through the funnel ensures it is recorded as an audited :class:`Event` with a
    sequence number, preserving the replay/checkpoint guarantee (Key Invariant
    #1) that a direct ``GameState`` write would break.
    """

    command_type: ClassVar[str] = "lifepath_enter_career"
    career_id: str

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        state.character.career = self.career_id
        return Event(
            kind=EventKind.STATE_CHANGE,
            command_type=self.command_type,
            description=f"Entered career {self.career_id} (always open).",
            changes={"career_id": self.career_id, "always_open": True},
        )


class DraftCommand(Command):
    """Submit to the draft (B16): 1D6 indexes the pack draft table.

    Once per character: validates ``character.drafted`` is False and that the
    supplied ``careers`` list has exactly 6 entries (the SRD draft table
    size). Rolls 1D6 on the lifepath stream, sets ``character.career`` to the
    indexed entry, and marks ``character.drafted = True`` so the player can
    never be re-drafted. The runner is responsible for passing the pack's
    draft table (``LoadedThemePack.draft_table``); the command itself stays a
    thin mechanical step, agnostic of the pack.
    """

    command_type: ClassVar[str] = "lifepath_draft"
    careers: list[str]

    def validate(self, state: GameState) -> None:
        if state.character.drafted:
            raise ValueError("A character can only be drafted once")
        if len(self.careers) != 6:
            raise ValueError("Draft table must have exactly 6 careers")

    def resolve(self, state: GameState, roller: Roller) -> RollResult:
        return roller.roll("lifepath", 1, 6)

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        assert roll is not None
        career_id = self.careers[roll.total - 1]
        state.character.career = career_id
        state.character.drafted = True
        return Event(
            kind=EventKind.ROLL,
            command_type=self.command_type,
            description=f"Draft: {roll.total} -> {career_id}",
            roll=roll,
            changes={"career_id": career_id, "roll_total": roll.total},
        )


class EndCareerCommand(Command):
    """Close the current career into ``career_history`` (B17).

    Appends a :class:`CareerTermRecord` capturing how far the character got
    in the just-ended career, then clears ``career`` and ``rank`` so a new
    career can begin. ``terms`` (total terms served) is intentionally NOT
    reset — it governs aging and the 7-term retirement cap across the whole
    lifepath. ``ended_by`` records the reason: ``"mishap" | "muster_out" |
    "death" | "career_change"``.
    """

    command_type: ClassVar[str] = "lifepath_end_career"
    ended_by: str

    def validate(self, state: GameState) -> None:
        if not state.character.career:
            raise ValueError("Cannot end a career when none is active")

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        ch = state.character
        record = CareerTermRecord(
            career_id=ch.career,
            terms=ch.terms,
            final_rank=ch.rank,
            ended_by=self.ended_by,
        )
        ch.career_history.append(record)
        ch.career = ""
        ch.rank = 0
        return Event(
            kind=EventKind.STATE_CHANGE,
            command_type=self.command_type,
            description=f"Career ended: {record.career_id} ({self.ended_by})",
            changes=record.model_dump(),
        )


class SurvivalCommand(Command):
    """Roll survival check. Ironman death -> alive=False; other modes -> mishap."""

    command_type: ClassVar[str] = "lifepath_survival"
    career_id: str
    characteristic: str
    target: int
    death_mode: str = "narrative"

    def validate(self, state: GameState) -> None:
        if not state.character.alive:
            raise ValueError("Cannot run survival check for a dead character")

    def resolve(self, state: GameState, roller: Roller) -> RollResult:
        char_value = state.character.characteristics.get(self.characteristic, 7)
        dm = CepheusRuleSet().characteristic_dm(char_value)
        return roller.roll("lifepath", 2, 6, modifiers=dm)

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        assert roll is not None
        raw = sum(roll.rolls)
        success = raw != 2 and roll.total >= self.target  # natural 2 always fails (N1)
        died = False
        mishap = False
        if not success:
            if self.death_mode == "ironman":
                state.character.alive = False
                died = True
            else:
                mishap = True
        outcome = "success" if success else ("DEATH" if died else "mishap")
        return Event(
            kind=EventKind.ROLL,
            command_type=self.command_type,
            description=(
                f"Survival for {self.career_id}: "
                f"2D6={sum(roll.rolls)}+DM({roll.modifiers})="
                f"{roll.total} vs {self.target} -> {outcome}"
            ),
            roll=roll,
            changes={
                "career_id": self.career_id,
                "raw_roll": sum(roll.rolls),
                "char_dm": roll.modifiers,
                "adjusted_total": roll.total,
                "target": self.target,
                "success": success,
                "died": died,
                "mishap": mishap,
                "death_mode": self.death_mode,
            },
        )


class CommissionCommand(Command):
    """Roll commission check (hierarchy careers, rank 0). Success -> rank 1 (B8).

    Attemptable only at rank 0 for a hierarchy career with a commission block;
    the runner-level :meth:`LifepathRunner.commission_available` also excludes
    draftees in their first term of the drafted career. The command itself
    enforces only ``alive`` and ``rank == 0`` — the career/draftee gating is
    the runner's responsibility so the command stays a thin mechanical step.
    """

    command_type: ClassVar[str] = "lifepath_commission"
    career_id: str
    characteristic: str
    target: int

    def validate(self, state: GameState) -> None:
        if not state.character.alive:
            raise ValueError("Cannot run commission for a dead character")
        if state.character.rank != 0:
            raise ValueError("Commission is only available at rank 0")

    def resolve(self, state: GameState, roller: Roller) -> RollResult:
        char_value = state.character.characteristics.get(self.characteristic, 7)
        dm = CepheusRuleSet().characteristic_dm(char_value)
        return roller.roll("lifepath", 2, 6, modifiers=dm)

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        assert roll is not None
        success = roll.total >= self.target
        if success:
            state.character.rank = 1
        return Event(
            kind=EventKind.ROLL,
            command_type=self.command_type,
            description=(
                f"Commission ({self.career_id}): "
                f"2D6={sum(roll.rolls)}+DM({roll.modifiers})="
                f"{roll.total} vs {self.target} -> "
                f"{'commissioned' if success else 'no commission'}"
            ),
            roll=roll,
            changes={
                "career_id": self.career_id,
                "raw_roll": sum(roll.rolls),
                "char_dm": roll.modifiers,
                "adjusted_total": roll.total,
                "target": self.target,
                "success": success,
            },
        )


class AdvancementCommand(Command):
    """Roll advancement check. Success -> rank up (if career has ranks)."""

    command_type: ClassVar[str] = "lifepath_advancement"
    career_id: str
    characteristic: str
    target: int
    has_ranks: bool = True

    def validate(self, state: GameState) -> None:
        if not state.character.alive:
            raise ValueError("Cannot run advancement for a dead character")
        if state.character.rank < 1:
            raise ValueError("Advancement requires rank 1 or higher (B1)")
        if state.character.rank >= 6:
            raise ValueError("Rank 6 is the maximum (B5)")

    def resolve(self, state: GameState, roller: Roller) -> RollResult:
        char_value = state.character.characteristics.get(self.characteristic, 7)
        dm = CepheusRuleSet().characteristic_dm(char_value)
        return roller.roll("lifepath", 2, 6, modifiers=dm)

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        assert roll is not None
        success = roll.total >= self.target
        new_rank = state.character.rank
        if success and self.has_ranks:
            state.character.rank += 1
            new_rank = state.character.rank
        return Event(
            kind=EventKind.ROLL,
            command_type=self.command_type,
            description=(
                f"Advancement for {self.career_id}: "
                f"2D6={sum(roll.rolls)}+DM({roll.modifiers})="
                f"{roll.total} vs {self.target} -> "
                f"{'promoted' if success and self.has_ranks else 'success' if success else 'no advancement'}"
            ),
            roll=roll,
            changes={
                "career_id": self.career_id,
                "raw_roll": sum(roll.rolls),
                "char_dm": roll.modifiers,
                "adjusted_total": roll.total,
                "target": self.target,
                "success": success,
                "new_rank": new_rank,
            },
        )


class SkillTableRollCommand(Command):
    """Roll on a 1D6 skill table and apply the result to the character."""

    command_type: ClassVar[str] = "lifepath_skill_roll"
    table_name: str
    entries: list[SkillTableEntry]
    num_dice: int = 1
    die_size: int = 6

    def resolve(self, state: GameState, roller: Roller) -> RollResult:
        return roller.roll("lifepath", self.num_dice, self.die_size)

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        assert roll is not None
        entry = lookup_table_result(self.entries, roll.total)
        gain_type, gain_name = apply_skill_result(state.character, entry.result)
        return Event(
            kind=EventKind.ROLL,
            command_type=self.command_type,
            description=(f"Skill roll ({self.table_name}): {roll.total} -> {entry.result}"),
            roll=roll,
            changes={
                "table_name": self.table_name,
                "roll_total": roll.total,
                "result_text": entry.result,
                "gain_type": gain_type,
                "gain_name": gain_name,
            },
        )


class AgingRollCommand(Command):
    """Roll aging: 2D6 - total terms against the graduated table (B4).

    Produces ``pending_aging`` slots on the character; the player chooses
    which characteristics take the reductions (ApplyAgingReductionCommand).
    Aged only at 34+ (gated by the runner); this command just resolves the
    table for the current term count.
    """

    command_type: ClassVar[str] = "lifepath_aging"

    def resolve(self, state: GameState, roller: Roller) -> RollResult:
        return roller.roll("lifepath", 2, 6)

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        assert roll is not None
        adjusted = roll.total - state.character.terms
        slots: list[AgingSlot] = []
        if adjusted < 1:
            for group, points in _AGING_TABLE[max(adjusted, -6)]:
                slots.append(AgingSlot(group=group, points=points))
        state.character.pending_aging = slots
        success = not slots
        return Event(
            kind=EventKind.ROLL,
            command_type=self.command_type,
            description=(
                f"Aging: 2D6={roll.total} - terms({state.character.terms}) = "
                f"{adjusted} -> {slots or 'no effect'}"
            ),
            roll=roll,
            changes={
                "raw_roll": roll.total,
                "adjusted": adjusted,
                "success": success,
                "slots": [{"group": s.group, "points": s.points} for s in slots],
            },
        )


class ApplyAgingReductionCommand(Command):
    """Player assigns ``points`` of pending aging reduction to a characteristic.

    Validates that enough pending points remain in the characteristic's group
    (physical vs mental); consumes from matching slots; reduces the stat
    (floored at 0). If the result hits 0 the event's ``changes["crisis"]`` is
    set so the caller routes to :class:`ResolveInjuryCrisisCommand` (B13/B4).
    """

    command_type: ClassVar[str] = "lifepath_aging_apply"
    characteristic: str
    points: int

    def validate(self, state: GameState) -> None:
        group = "physical" if self.characteristic in _PHYSICAL_CHARACTERISTICS else "mental"
        available = sum(s.points for s in state.character.pending_aging if s.group == group)
        if self.points < 1 or self.points > available:
            pending_groups = sorted({s.group for s in state.character.pending_aging})
            raise ValueError(
                f"Cannot assign {self.points} points to {self.characteristic} "
                f"({group}): {available} {group} points available; "
                f"pending groups: {pending_groups}"
            )

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        group = "physical" if self.characteristic in _PHYSICAL_CHARACTERISTICS else "mental"
        remaining = self.points
        new_slots: list[AgingSlot] = []
        for slot in state.character.pending_aging:
            if slot.group == group and remaining > 0:
                take = min(slot.points, remaining)
                slot = AgingSlot(group=slot.group, points=slot.points - take)
                remaining -= take
            if slot.points > 0:
                new_slots.append(slot)
        state.character.pending_aging = new_slots
        current = state.character.characteristics.get(self.characteristic, 0)
        state.character.characteristics[self.characteristic] = max(0, current - self.points)
        crisis = state.character.characteristics[self.characteristic] == 0
        return Event(
            kind=EventKind.STATE_CHANGE,
            command_type=self.command_type,
            description=(
                f"Aging: -{self.points} {self.characteristic} "
                f"(now {state.character.characteristics[self.characteristic]})"
            ),
            changes={
                "characteristic": self.characteristic,
                "points": self.points,
                "new_value": state.character.characteristics[self.characteristic],
                "crisis": crisis,
            },
        )


class BenefitRollCommand(Command):
    """Roll one mustering-out benefit and persist it to the character (FR2).

    Cash results (e.g. "50,000 Cr" or "1,000 gold crowns") add the parsed
    amount to ``credits``; material results append the text to ``inventory``.
    """

    command_type: ClassVar[str] = "lifepath_benefit"
    benefit_type: str  # "cash" | "material"
    entries: list[SkillTableEntry]
    num_dice: int = 1
    die_size: int = 6
    dm: int = 0

    def resolve(self, state: GameState, roller: Roller) -> RollResult:
        first = roller.roll("lifepath", self.num_dice, self.die_size, modifiers=self.dm)
        if self.benefit_type != "material":
            return first
        entry = lookup_table_result(self.entries, first.total)
        already_has = entry.result in state.character.inventory
        needs_reroll = (entry.once and already_has) or (
            entry.on_duplicate == "reroll" and already_has
        )
        if needs_reroll:
            return roller.roll("lifepath", self.num_dice, self.die_size, modifiers=self.dm)
        return first

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        assert roll is not None
        entry = lookup_table_result(self.entries, roll.total)
        if self.benefit_type == "cash":
            m = _CASH_RE.search(entry.result)
            if m:
                state.character.credits += int(m.group(1).replace(",", ""))
        else:
            already_has = entry.result in state.character.inventory
            if entry.once and already_has:
                pass  # reroll already happened in resolve; if still a dup, forfeit
            elif entry.on_duplicate and already_has:
                if entry.on_duplicate.startswith("skill:"):
                    skill_id = entry.on_duplicate.split(":", 1)[1]
                    current = state.character.skills.get(skill_id, 0)
                    state.character.skills[skill_id] = current + 1
                # else: "reroll" — handled in resolve; forfeit if still dup
            else:
                state.character.inventory.append(entry.result)
        return Event(
            kind=EventKind.ROLL,
            command_type=self.command_type,
            description=(
                f"Benefit ({self.benefit_type}): "
                f"roll={sum(roll.rolls)}+DM({roll.modifiers})="
                f"{roll.total} -> {entry.result}"
            ),
            roll=roll,
            changes={
                "benefit_type": self.benefit_type,
                "adjusted_roll": roll.total,
                "result_text": entry.result,
                "credits": state.character.credits,
            },
        )


class MishapRollCommand(Command):
    """Roll 1D6 on the career's mishap table (B13).

    Entries 1 and 6 chain to the pack injury table; the runner performs
    that chain.
    """

    command_type: ClassVar[str] = "lifepath_mishap"
    career_id: str
    entries: list[SkillTableEntry]

    def resolve(self, state: GameState, roller: Roller) -> RollResult:
        return roller.roll("lifepath", 1, 6)

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        assert roll is not None
        entry = lookup_table_result(self.entries, roll.total)
        is_injury = roll.total in (1, 6)
        effects_applied: list[str] = []

        # G3: apply mechanical effects from the mishap entry (P3.T5).
        if entry.effects:
            for effect in entry.effects:
                etype = str(effect.get("type", ""))
                if etype == "debt":
                    amount = int(effect.get("amount", 0))
                    state.character.debt_cr += amount
                    effects_applied.append(f"debt:{amount}")
                elif etype == "lose_benefits":
                    state.character.benefits_lost = True
                    effects_applied.append("lose_benefits")
                elif etype == "injury":
                    is_injury = True
                    effects_applied.append("injury")

        return Event(
            kind=EventKind.ROLL,
            command_type=self.command_type,
            description=f"Mishap ({self.career_id}): {roll.total} -> {entry.result}",
            roll=roll,
            changes={
                "career_id": self.career_id,
                "roll_total": roll.total,
                "result_text": entry.result,
                "injury": is_injury,
                "effects_applied": effects_applied,
            },
        )


class InjuryRollCommand(Command):
    """Roll 1D6 on the pack injury table and apply the reduction (B13).

    Where the table says "one physical characteristic", the player picks
    (``chosen_stat``) — validated as physical.
    """

    command_type: ClassVar[str] = "lifepath_injury"
    entries: list[SkillTableEntry]
    chosen_stat: str | None = None

    def resolve(self, state: GameState, roller: Roller) -> RollResult:
        return roller.roll("lifepath", 1, 6)

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        assert roll is not None
        entry = lookup_table_result(self.entries, roll.total)
        reductions = apply_injury_result(state.character, entry.result, self.chosen_stat)
        return Event(
            kind=EventKind.ROLL,
            command_type=self.command_type,
            description=f"Injury: {roll.total} -> {entry.result} ({reductions})",
            roll=roll,
            changes={
                "roll_total": roll.total,
                "result_text": entry.result,
                "reductions": reductions,
            },
        )


class ResolveInjuryCrisisCommand(Command):
    """Resolve a characteristic-at-0 crisis (B13).

    ``pay=True`` requires Cr10,000 and floors the stat at 1. ``pay=False`` (or
    unaffordable) applies the campaign death mode: ironman → death;
    narrative/checkpoint → stat floored at 1 + a severe lasting Injury.
    """

    command_type: ClassVar[str] = "lifepath_injury_crisis"
    stat: str
    pay: bool
    crisis_cost_cr: int = 10_000

    def validate(self, state: GameState) -> None:
        if self.pay and state.character.credits < self.crisis_cost_cr:
            raise ValueError(f"Cannot afford Cr{self.crisis_cost_cr} crisis payment")

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        ch = state.character
        outcome = ""
        if self.pay:
            ch.credits -= self.crisis_cost_cr
            ch.characteristics[self.stat] = max(1, ch.characteristics.get(self.stat, 0))
            outcome = f"paid_cr{self.crisis_cost_cr}"
        elif state.campaign.death_mode == "ironman":
            ch.alive = False
            outcome = "death"
        else:
            ch.characteristics[self.stat] = 1
            state.entities.append(
                Injury(
                    name=f"Crisis scar ({self.stat})",
                    severity="severe",
                    description="Permanent damage from a near-fatal injury.",
                )
            )
            outcome = "scarred"
        return Event(
            kind=EventKind.STATE_CHANGE,
            command_type=self.command_type,
            description=f"Injury crisis ({self.stat}): {outcome}",
            changes={"stat": self.stat, "outcome": outcome},
        )


class AdvanceTermCommand(Command):
    """Advance the character's age and term count via the funnel (R9, R10).

    Bumps ``character.age`` by 4 (one CE SRD term) and increments
    ``character.terms``. Routed through the funnel so the event log captures
    these changes, allowing a replay tool to reconstruct state.
    """

    command_type: ClassVar[str] = "lifepath_advance_term"
    years_per_term: int = 4

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        old_age = state.character.age
        old_terms = state.character.terms
        state.character.age = old_age + self.years_per_term
        state.character.terms = old_terms + 1
        return Event(
            kind=EventKind.STATE_CHANGE,
            command_type=self.command_type,
            description=(
                f"Term advanced: age {old_age} -> {state.character.age}, "
                f"terms {old_terms} -> {state.character.terms}"
            ),
            changes={
                "age_before": old_age,
                "age_after": state.character.age,
                "terms_before": old_terms,
                "terms_after": state.character.terms,
            },
        )


class ReenlistmentCommand(Command):
    """Roll re-enlistment at term end (B12).

    Outcomes (``changes["outcome"]``):

    * ``must_retire``  — character has served 7+ terms; mandatory retirement,
      no roll.
    * ``must_continue`` — natural 12 on the 2D6 roll; the SRD forces another
      term.
    * ``must_leave``   — roll total below the career's ``re_enlistment``
      target; the career releases the character.
    * ``may_continue`` — total meets/exceeds the target (or the career has no
      ``re_enlistment`` data); the player chooses whether to continue.

    No characteristic DM applies to re-enlistment per SRD, so ``resolve`` rolls
    a plain 2D6 on the lifepath stream. ``resolve`` returns ``None`` (no roll)
    when the character is already at 7+ terms or the career has no target.
    """

    command_type: ClassVar[str] = "lifepath_reenlistment"
    career_id: str
    target: int | None = None

    def resolve(self, state: GameState, roller: Roller) -> RollResult | None:
        # No roll when mandatory retirement applies, or when the career
        # provides no re-enlistment target (treated as player choice).
        if state.character.terms >= 7 or self.target is None:
            return None
        return roller.roll("lifepath", 2, 6)

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        if state.character.terms >= 7:
            outcome = "must_retire"
        elif self.target is None:
            outcome = "may_continue"
        else:
            assert roll is not None
            # Natural 12 forces another term (B12). Use the RAW 2D6 sum —
            # modifiers don't apply to re-enlistment per SRD, so this is
            # equivalent to ``roll.total`` today but stays correct if a DM
            # is ever introduced.
            raw = sum(roll.rolls)
            if raw == 12:
                outcome = "must_continue"
            elif roll.total < self.target:
                outcome = "must_leave"
            else:
                outcome = "may_continue"
        return Event(
            kind=EventKind.ROLL if roll is not None else EventKind.STATE_CHANGE,
            command_type=self.command_type,
            description=f"Re-enlistment ({self.career_id}): {outcome}",
            roll=roll,
            changes={
                "career_id": self.career_id,
                "outcome": outcome,
                "roll_total": roll.total if roll else None,
            },
        )


class RollCharacteristicPoolCommand(Command):
    """Roll 2D6 and append to the unassigned characteristic pool (Task 4).

    The player later assigns pool values to characteristics (design
    principle: more choice). Rolls are sequential on the lifepath stream;
    ``position`` must equal the current pool length so a resumed game
    can't double-roll a slot.
    """

    command_type: ClassVar[str] = "lifepath_pool_roll"
    position: int

    def validate(self, state: GameState) -> None:
        if self.position != len(state.character.unassigned_rolls):
            raise ValueError("Pool rolls must be sequential")
        if len(state.character.unassigned_rolls) >= 6:
            raise ValueError("Characteristic pool is already full")

    def resolve(self, state: GameState, roller: Roller) -> RollResult:
        return roller.roll("lifepath", 2, 6)

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        assert roll is not None
        state.character.unassigned_rolls.append(roll.total)
        return Event(
            kind=EventKind.ROLL,
            command_type=self.command_type,
            description=f"Characteristic pool roll #{self.position + 1}: {roll.total}",
            roll=roll,
            changes={"position": self.position, "value": roll.total},
        )


class AssignCharacteristicCommand(Command):
    """Assign one pool value to a characteristic (no dice, Task 4)."""

    command_type: ClassVar[str] = "lifepath_assign_characteristic"
    characteristic: str
    pool_index: int

    def validate(self, state: GameState) -> None:
        if self.characteristic not in _CHARACTERISTICS:
            raise ValueError(f"Unknown characteristic {self.characteristic!r}")
        if self.characteristic in state.character.characteristics:
            raise ValueError(f"{self.characteristic} is already assigned")
        if not 0 <= self.pool_index < len(state.character.unassigned_rolls):
            raise ValueError(f"Invalid pool index {self.pool_index}")

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        value = state.character.unassigned_rolls.pop(self.pool_index)
        state.character.characteristics[self.characteristic] = value
        return Event(
            kind=EventKind.STATE_CHANGE,
            command_type=self.command_type,
            description=f"Assigned {value} to {self.characteristic}",
            changes={"characteristic": self.characteristic, "value": value},
        )


class GainSkillCommand(Command):
    """Set a skill to at least ``level`` — level-0 grants never stack (Task 9).

    Applies ``skills[id] = max(current, level)`` so a level-0 grant from
    background skills or basic training does not reduce an existing level.
    Routed through the funnel so every skill gain is audited.
    """

    command_type: ClassVar[str] = "lifepath_gain_skill"
    skill_id: str
    level: int = 0

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        current = state.character.skills.get(self.skill_id)
        new_level = max(current if current is not None else -1, self.level)
        state.character.skills[self.skill_id] = new_level
        return Event(
            kind=EventKind.STATE_CHANGE,
            command_type=self.command_type,
            description=f"Skill {self.skill_id} set to {new_level}",
            changes={"skill_id": self.skill_id, "level": new_level},
        )


class SetBackgroundPicksCommand(Command):
    """Set ``background_picks_remaining`` (Task 9 funnel command, no dice)."""

    command_type: ClassVar[str] = "lifepath_set_background_picks"
    picks: int

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        old = state.character.background_picks_remaining
        state.character.background_picks_remaining = self.picks
        return Event(
            kind=EventKind.STATE_CHANGE,
            command_type=self.command_type,
            description=f"Background picks remaining: {old} -> {self.picks}",
            changes={"picks": self.picks},
        )


class DecrementBackgroundPicksCommand(Command):
    """Decrement ``background_picks_remaining`` by one (Task 9, no dice)."""

    command_type: ClassVar[str] = "lifepath_decrement_background_picks"

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        old = state.character.background_picks_remaining
        state.character.background_picks_remaining = old - 1
        return Event(
            kind=EventKind.STATE_CHANGE,
            command_type=self.command_type,
            description=f"Background picks remaining: {old} -> {old - 1}",
            changes={"picks": old - 1},
        )


class SetBasicTrainingDoneCommand(Command):
    """Set ``basic_training_done`` to True (Task 9 funnel command, no dice)."""

    command_type: ClassVar[str] = "lifepath_set_basic_training_done"

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        state.character.basic_training_done = True
        return Event(
            kind=EventKind.STATE_CHANGE,
            command_type=self.command_type,
            description="Basic training completed",
            changes={"basic_training_done": True},
        )


class RerollCharacteristicPoolCommand(Command):
    """Discard the pool for one full reroll (once, before any assignment).

    This command only clears ``unassigned_rolls`` and sets ``pool_rerolled``;
    the runner re-rolls the six new values via
    :class:`RollCharacteristicPoolCommand` immediately after, so the whole
    reroll is one atomic player-visible action that still goes through the
    funnel command-by-command for audit/replay.
    """

    command_type: ClassVar[str] = "lifepath_pool_reroll"

    def validate(self, state: GameState) -> None:
        if state.character.pool_rerolled:
            raise ValueError("Pool reroll already used")
        if state.character.characteristics:
            raise ValueError("Cannot reroll after assignment has begun")

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        old = list(state.character.unassigned_rolls)
        state.character.unassigned_rolls = []
        state.character.pool_rerolled = True
        return Event(
            kind=EventKind.STATE_CHANGE,
            command_type=self.command_type,
            description=f"Characteristic pool rerolled (discarded {old})",
            changes={"discarded": old},
        )


# ---------------------------------------------------------------------------
# LifepathRunner — orchestrates the full chargen flow.
# ---------------------------------------------------------------------------


class LifepathRunner:
    """Orchestrates CE SRD lifepath character generation.

    Takes an Engine (with injected Roller), a LoadedThemePack, and an optional
    CepheusRuleSet. Each step applies commands through the Engine funnel so
    every roll and mutation is audited.

    Death mode branching (R10, AE2):
      - ironman: failed survival -> character dies, lifepath ends immediately.
      - narrative/checkpoint: failed survival -> mishap, character leaves
        career and can muster out.
    """

    def __init__(
        self,
        engine: Engine,
        pack: LoadedThemePack,
        ruleset: CepheusRuleSet | None = None,
    ) -> None:
        self.engine = engine
        self.pack = pack
        self.ruleset = ruleset or CepheusRuleSet()
        # Cash rolls taken in the current muster-out session (Task 12).
        # Reconstructed from events on resume via _count_cash_benefit_events().
        self._cash_rolls_taken: int = 0

    def _get_career(self, career_id: str):
        if career_id not in self.pack.careers:
            raise KeyError(
                f"Career '{career_id}' not found in pack '{self.pack.id}'. "
                f"Available: {sorted(self.pack.careers.keys())}"
            )
        return self.pack.careers[career_id]

    # ------------------------------------------------------------------
    # Step 1: Roll characteristics.
    # ------------------------------------------------------------------

    def roll_characteristics(self) -> dict[str, int]:
        """Roll 2D6 for each of the 6 characteristics via the funnel."""
        for char in _CHARACTERISTICS:
            self.engine.apply(RollCharacteristicCommand(characteristic=char))
        return dict(self.engine.state.character.characteristics)

    # ------------------------------------------------------------------
    # Step 1 (alt): Roll-six-then-assign characteristic pool (Task 4).
    # ------------------------------------------------------------------

    def roll_pool(self) -> list[int]:
        """Roll the six-value characteristic pool (player assigns after).

        Rolls six 2D6 values into ``character.unassigned_rolls`` via the
        funnel. Characteristics are NOT set by this method — the player
        assigns each pool value to a characteristic via
        :meth:`assign_characteristic`.
        """
        for i in range(6):
            self.engine.apply(RollCharacteristicPoolCommand(position=i))
        return list(self.engine.state.character.unassigned_rolls)

    def assign_characteristic(self, characteristic: str, pool_index: int) -> None:
        """Assign one pool value (by index) to a characteristic."""
        self.engine.apply(
            AssignCharacteristicCommand(characteristic=characteristic, pool_index=pool_index)
        )

    def reroll_pool(self) -> None:
        """Discard the pool and re-roll all six values (once, pre-assignment).

        Applies :class:`RerollCharacteristicPoolCommand` (which clears the
        pool and marks ``pool_rerolled``), then immediately re-rolls six
        fresh 2D6 values via :class:`RollCharacteristicPoolCommand`. The
        clear command's validation gates the whole action: it raises if the
        reroll was already used or any characteristic is already assigned.
        """
        self.engine.apply(RerollCharacteristicPoolCommand())
        for i in range(6):
            self.engine.apply(RollCharacteristicPoolCommand(position=i))

    # ------------------------------------------------------------------
    # Background skills phase (B10) and basic training (B11) — Task 9.
    # ------------------------------------------------------------------

    def start_background_phase(self) -> int:
        """Background skills (B10): 3 + EDU DM picks at level 0.

        Idempotent: once ``background_picks_remaining`` is set (not -1),
        subsequent calls return the stored count without re-computing.
        """
        if self.engine.state.character.background_picks_remaining != -1:
            return self.engine.state.character.background_picks_remaining
        edu = self.engine.state.character.characteristics.get("EDU", 7)
        picks = max(0, 3 + self.ruleset.characteristic_dm(edu))
        self.engine.apply(SetBackgroundPicksCommand(picks=picks))
        return picks

    def pick_background_skill(self, skill_id: str) -> None:
        """Pick one background skill at level 0; decrements the pick count."""
        if skill_id not in self.pack.background_skills:
            raise ValueError(
                f"{skill_id!r} is not a background skill. Available: {self.pack.background_skills}"
            )
        self.engine.apply(GainSkillCommand(skill_id=skill_id, level=0))
        self.engine.apply(DecrementBackgroundPicksCommand())

    def run_basic_training(self, career_id: str, chosen_skill: str | None = None) -> None:
        """Basic training (B11, P1.T6): first career → all Service skills at 0;
        each NEW later career → one player-chosen Service skill at 0.

        First-career training is tracked by ``character.basic_training_done``.
        Later-career grants need no flag: a career already in
        ``career_history`` cannot be re-entered (``qualify`` raises; drifter
        re-entry is guarded below), so each new career triggers exactly one
        grant. ``chosen_skill`` is required (player choice) for later careers.
        """
        state = self.engine.state
        career = self._get_career(career_id)
        service = next(
            (t for t in career.skill_tables if t.name == "Service Skills"),
            None,
        )
        if service is None:
            raise KeyError(
                f"Career {career_id!r} has no 'Service Skills' table; "
                f"available: {[t.name for t in career.skill_tables]}"
            )
        history = state.character.career_history
        if not history:
            if state.character.basic_training_done:
                return
            for entry in service.entries.entries:
                if not entry.result.startswith("+"):
                    self.engine.apply(GainSkillCommand(skill_id=entry.result, level=0))
            self.engine.apply(SetBasicTrainingDoneCommand())
            return
        # Later career (B11): one player-chosen Service skill at level 0.
        if career_id in {r.career_id for r in history}:
            return  # re-entered career (drifter) — training already received
        valid = {e.result for e in service.entries.entries if not e.result.startswith("+")}
        if chosen_skill not in valid:
            raise ValueError(f"Choose one Service skill from {sorted(valid)}; got {chosen_skill!r}")
        self.engine.apply(GainSkillCommand(skill_id=chosen_skill, level=0))

    # ------------------------------------------------------------------
    # Step 2: Qualification.
    # ------------------------------------------------------------------

    def career_change_dm(self) -> int:
        """Career-change qualification DM (B17): ``-2`` per career already in
        ``career_history``. Zero for a first career (no history)."""
        return -2 * len(self.engine.state.character.career_history)

    def qualify(self, career_id: str, extra_dm: int = 0) -> QualificationResult:
        """Attempt qualification for a career. Sets career on success.

        ``extra_dm`` is added to the intrinsic characteristic DM. The
        career-change DM (B17, ``-2`` per previous career) is applied
        automatically when ``career_history`` is non-empty and stacks with any
        caller-supplied ``extra_dm``. A career already present in history
        cannot be re-entered — except the Drifter, which may always be
        re-entered.
        """
        history = self.engine.state.character.career_history
        left = {r.career_id for r in history}
        if career_id in left and career_id != "drifter":
            raise ValueError(f"Cannot return to career {career_id!r} already left (B17)")
        career = self._get_career(career_id)
        # P3.T8b: always_open careers (drifter) auto-qualify — no roll consumed.
        if career.always_open:
            self.engine.apply(EnterCareerCommand(career_id=career_id))
            return QualificationResult(
                career_id=career_id,
                career_name=career.name,
                characteristic=career.qualification.characteristic,
                char_value=self.engine.state.character.characteristics.get(
                    career.qualification.characteristic, 0
                ),
                char_dm=0,
                raw_roll=0,
                adjusted_total=0,
                target=career.qualification.target,
                success=True,
            )
        dm = extra_dm + self.career_change_dm()
        cmd = QualificationCommand(
            career_id=career_id,
            characteristic=career.qualification.characteristic,
            target=career.qualification.target,
            extra_dm=dm,
        )
        event = self.engine.apply(cmd)
        c = event.changes
        char_value = self.engine.state.character.characteristics.get(
            career.qualification.characteristic, 0
        )
        return QualificationResult(
            career_id=career_id,
            career_name=career.name,
            characteristic=career.qualification.characteristic,
            char_value=char_value,
            char_dm=c["char_dm"],
            raw_roll=c["raw_roll"],
            adjusted_total=c["adjusted_total"],
            target=c["target"],
            success=c["success"],
        )

    def run_draft(self) -> str:
        """Submit to the draft (B16): 1D6 indexes ``pack.draft_table``.

        Once per character — :class:`DraftCommand` rejects a character whose
        ``drafted`` flag is already True. Sets ``character.career`` to the
        indexed entry and ``character.drafted`` to True, then returns the
        chosen career id. Requires ``pack.draft_table`` to be populated
        (loader-enforced for every pack that defines a draft section).
        """
        if not self.pack.draft_table:
            raise ValueError(
                f"Pack '{self.pack.id}' has no draft table; the draft fallback is unavailable"
            )
        event = self.engine.apply(DraftCommand(careers=list(self.pack.draft_table)))
        return event.changes["career_id"]

    # ------------------------------------------------------------------
    # Step 3: Run one term — individual sub-step methods.
    # ------------------------------------------------------------------

    def start_term(self, career_id: str, term_number: int) -> TermResult:
        """Create an initial :class:`TermResult` for a new term.

        Does not roll any dice — just sets up the dataclass with static
        info from the career and current character state.
        """
        career = self._get_career(career_id)
        state = self.engine.state
        return TermResult(
            term_number=term_number,
            career_id=career_id,
            career_name=career.name,
            age_before=state.character.age,
            age_after=state.character.age + 4,
            rank_before=state.character.rank,
            survival_target=career.survival.target,
            advancement_target=career.advancement.target if career.advancement else 0,
        )

    def run_survival_step(self, career_id: str, result: TermResult) -> None:
        """Roll survival check and advance the term counter.

        Modifies *result* in place.  After this call ``result.died`` /
        ``result.mishap`` indicate whether the term ended prematurely.
        Age and term count always advance (even on death/mishap).
        """
        career = self._get_career(career_id)
        state = self.engine.state

        surv_cmd = SurvivalCommand(
            career_id=career_id,
            characteristic=career.survival.characteristic,
            target=career.survival.target,
            death_mode=state.campaign.death_mode,
        )
        surv_event = self.engine.apply(surv_cmd)
        sc = surv_event.changes
        result.survival_raw = sc["raw_roll"]
        result.survival_dm = sc["char_dm"]
        result.survival_total = sc["adjusted_total"]
        result.survival_success = sc["success"]
        result.died = sc.get("died", False)
        result.mishap = sc.get("mishap", False)

        # Age always advances, even on death/mishap.
        advance_event = self.engine.apply(AdvanceTermCommand())
        ac = advance_event.changes
        result.age_after = ac["age_after"]
        result.rank_after = result.rank_before

    def commission_available(self, career_id: str) -> bool:
        """Whether commission can be attempted this term (B8).

        True when the career has hierarchy with a commission block, the
        character is at rank 0, and (for draftees) this is not their first
        term in the drafted career. The command itself additionally enforces
        ``alive`` and ``rank == 0``; this method gates the career/draftee
        rules so the TUI can decide whether to offer the choice.
        """
        career = self._get_career(career_id)
        state = self.engine.state
        if not (career.has_hierarchy and career.commission):
            return False
        if state.character.rank != 0:
            return False
        return not (state.character.drafted and self._terms_in_current_career(state) == 0)

    @staticmethod
    def _terms_in_current_career(state: GameState) -> int:
        """Count terms served in the current career.

        Uses the last ``CareerTermRecord`` matching ``character.career``;
        falls back to ``character.terms`` when no history exists (the
        common case during chargen before mustering out).
        """
        if state.character.career_history:
            for record in reversed(state.character.career_history):
                if record.career_id == state.character.career:
                    return record.terms
            return 0
        return state.character.terms

    def run_commission_step(self, career_id: str, result: TermResult) -> None:
        """Roll the commission check and update rank/skill rolls (B8).

        No-op when :meth:`commission_available` is False. On success sets
        rank to 1 and flags ``result.commission_success`` so the downstream
        :meth:`compute_num_skill_rolls` grants the extra roll.
        """
        if not self.commission_available(career_id):
            return
        career = self._get_career(career_id)
        assert career.commission is not None
        event = self.engine.apply(
            CommissionCommand(
                career_id=career_id,
                characteristic=career.commission.characteristic,
                target=career.commission.target,
            )
        )
        c = event.changes
        result.commission_raw = c["raw_roll"]
        result.commission_dm = c["char_dm"]
        result.commission_total = c["adjusted_total"]
        result.commission_target = c["target"]
        result.commission_success = c["success"]
        if c["success"]:
            self._grant_rank_bonus_skills(career_id, 1)

    def _grant_rank_bonus_skills(self, career_id: str, new_rank: int) -> list[str]:
        """Grant bonus skills for attaining ``new_rank`` in ``career_id`` (G1, P3.T2).

        Returns a list of human-readable grant descriptions for the caller's event.
        """
        career = self._get_career(career_id)
        grants: list[str] = []
        for rank_entry in career.ranks:
            if rank_entry.rank == new_rank and rank_entry.bonus_skills:
                for bonus in rank_entry.bonus_skills:
                    skill_id = str(bonus["skill"])
                    level = int(bonus.get("level", 0))
                    self.engine.apply(GainSkillCommand(skill_id=skill_id, level=level))
                    grants.append(f"{skill_id}-{level} (rank {new_rank})")
        return grants

    def advancement_available(self, career_id: str) -> bool:
        """Whether advancement can be attempted this term (B1/B5, P1.T1).

        True when the career has an advancement block and ranks and the
        character holds rank 1-5. SRD: advancement attempts require rank 1+;
        rank 6 is the cap. ``AdvancementCommand.validate`` enforces the same
        bounds so direct ``Engine.apply`` calls are gated too.
        """
        career = self._get_career(career_id)
        if career.advancement is None or not career.ranks:
            return False
        return 1 <= self.engine.state.character.rank < 6

    def run_advancement_step(self, career_id: str, result: TermResult) -> None:
        """Roll advancement check and update rank (gated: rank 1-5, B1/B5).

        No-op when :meth:`advancement_available` is False (rank 0, rank 6, or
        a career without advancement/ranks). Should only be called after a
        successful survival check.
        """
        if not self.advancement_available(career_id):
            return
        career = self._get_career(career_id)
        state = self.engine.state

        adv_cmd = AdvancementCommand(
            career_id=career_id,
            characteristic=career.advancement.characteristic,
            target=career.advancement.target,
            has_ranks=bool(career.ranks),
        )
        adv_event = self.engine.apply(adv_cmd)
        ac = adv_event.changes
        result.advancement_raw = ac["raw_roll"]
        result.advancement_dm = ac["char_dm"]
        result.advancement_total = ac["adjusted_total"]
        result.advancement_success = ac["success"]
        result.rank_after = state.character.rank
        if ac["success"] and result.rank_after > result.rank_before:
            self._grant_rank_bonus_skills(career_id, result.rank_after)

    def compute_num_skill_rolls(self, result: TermResult) -> int:
        """Compute the number of skill table rolls for this term.

        2 for non-hierarchy careers, else 1; +1 commission success, +1
        advancement success (B8/B9). The rank>=3 bonus has no SRD basis and
        was removed (N2).
        """
        career = self._get_career(result.career_id)
        num = 1 if career.has_hierarchy else 2
        if result.commission_success:
            num += 1
        if result.advancement_success:
            num += 1
        return num

    def run_skill_roll_step(self, career_id: str, result: TermResult, table_name: str) -> SkillGain:
        """Roll one skill on the chosen table.

        Appends a :class:`SkillGain` to ``result.skill_gains`` and
        returns it.  Raises ``KeyError`` if *table_name* doesn't match
        any table on the career.  Raises ``ValueError`` for the Advanced
        Education table when EDU < 8 (B7).
        """
        # B7: Advanced Education requires EDU 8+.
        if table_name == "Advanced Education":
            edu = self.engine.state.character.characteristics.get("EDU", 0)
            if edu < 8:
                raise ValueError("Advanced Education requires EDU 8+ (B7)")
        career = self._get_career(career_id)
        table = next(
            (t for t in career.skill_tables if t.name == table_name),
            None,
        )
        if table is None:
            available = [t.name for t in career.skill_tables]
            raise KeyError(f"Unknown skill table {table_name!r}; available: {available}")
        skill_cmd = SkillTableRollCommand(
            table_name=table.name,
            entries=table.entries.entries,
            num_dice=table.entries.num_dice,
            die_size=table.entries.die_size,
        )
        skill_event = self.engine.apply(skill_cmd)
        sec = skill_event.changes
        gain = SkillGain(
            table_name=table.name,
            roll=sec["roll_total"],
            result_text=sec["result_text"],
            gain_type=sec["gain_type"],
            gain_name=sec["gain_name"],
        )
        result.skill_gains.append(gain)
        return gain

    def run_aging_step(self, result: TermResult) -> bool:
        """Roll aging check if character is 34+.

        Modifies *result* in place.  Returns ``True`` if an aging check
        was performed, ``False`` if the character is too young.  Produces
        ``pending_aging`` slots on the character when the adjusted roll
        indicates reduction; the player (or batch runner) assigns them via
        :class:`ApplyAgingReductionCommand`. ``aging_reductions`` is
        populated from the slot totals for narration.
        """
        if self.engine.state.character.age >= 34:
            aging_cmd = AgingRollCommand()
            aging_event = self.engine.apply(aging_cmd)
            agc = aging_event.changes
            result.aging_raw = agc["raw_roll"]
            result.aging_success = agc["success"]
            # Aggregate pending slots by group for narration. The actual
            # distribution to specific characteristics is player-driven.
            reductions: dict[str, int] = {}
            for slot in self.engine.state.character.pending_aging:
                reductions[slot.group] = reductions.get(slot.group, 0) + slot.points
            result.aging_reductions = reductions
            return True
        return False

    def finalize_term(self, career_id: str, result: TermResult) -> None:
        """Set rank title based on current rank. Call after all steps."""
        career = self._get_career(career_id)
        if career.ranks:
            matching = [r for r in career.ranks if r.rank == self.engine.state.character.rank]
            if matching:
                result.rank_title = matching[0].title

    def run_reenlistment_step(self, career_id: str) -> str:
        """Resolve the SRD re-enlistment roll at term end (B12).

        Applies :class:`ReenlistmentCommand` through the funnel and returns the
        outcome string (``must_continue`` | ``may_continue`` | ``must_leave`` |
        ``must_retire``). The caller (TUI or batch) honors forced outcomes:
        ``must_continue`` advances to the next term automatically,
        ``must_leave``/``must_retire`` proceed to mustering out, and
        ``may_continue`` offers the player the Continue/Muster Out choice.

        The career's ``re_enlistment`` target is read from the loaded pack;
        careers without that data produce ``may_continue`` without a roll.
        """
        career = self._get_career(career_id)
        event = self.engine.apply(
            ReenlistmentCommand(career_id=career_id, target=career.re_enlistment)
        )
        return event.changes["outcome"]

    # ------------------------------------------------------------------
    # Step 3 (legacy): Run one term — convenience wrapper.
    # ------------------------------------------------------------------

    def run_term(
        self,
        career_id: str,
        term_number: int,
        skill_table_choices: list[str] | None = None,
    ) -> TermResult:
        """Execute one 4-year term: survival, advancement, skills, aging.

        This is the legacy all-in-one entry point.  It delegates to the
        individual ``run_*_step`` methods so the TUI can call them
        interactively while engine tests and ``run_lifepath`` still get
        the same behaviour in a single call.
        """
        result = self.start_term(career_id, term_number)
        self.run_survival_step(career_id, result)

        if result.died:
            return result
        if result.mishap:
            # Roll the career mishap table and auto-resolve any injury crisis
            # (batch path — TUI drives run_mishap interactively). (B13/N1)
            outcome = self.run_mishap(career_id)
            if outcome.get("crisis") and outcome.get("crisis_stat"):
                self.auto_resolve_crisis(outcome["crisis_stat"])
            return result

        self.run_commission_step(career_id, result)
        self.run_advancement_step(career_id, result)

        num_rolls = self.compute_num_skill_rolls(result)
        career = self._get_career(career_id)
        table_names = [t.name for t in career.skill_tables]
        if skill_table_choices is None:
            skill_table_choices = [table_names[i % len(table_names)] for i in range(num_rolls)]

        for table_name in skill_table_choices[:num_rolls]:
            self.run_skill_roll_step(career_id, result, table_name)

        self.run_aging_step(result)
        self._auto_apply_aging()
        self.finalize_term(career_id, result)
        return result

    # ------------------------------------------------------------------
    # Step 4: Mustering out.
    # ------------------------------------------------------------------

    def _effective_muster_rank(self, career_id: str) -> int:
        """Rank used for mustering-out benefits (B2, P1.T4).

        ``EndCareerCommand`` resets ``character.rank`` to 0 when it closes the
        career into ``career_history``, so a plan computed after the career
        ends must read the matching :class:`CareerTermRecord`'s ``final_rank``
        — the only durable source. While the career is still active (plan
        computed before EndCareer, e.g. the TUI's player-chosen path) the
        live rank applies. Both sources agree, so every muster path gets
        identical rank-based bonuses.
        """
        ch = self.engine.state.character
        if ch.career:
            return ch.rank
        for record in reversed(ch.career_history):
            if record.career_id == career_id:
                return record.final_rank
        return 0

    def _compute_cash_dm(self) -> int:
        """Cash benefit DM: +1 if Gambling skill or retired (7 terms) (G2, P3.T3)."""
        ch = self.engine.state.character
        dm = 0
        if ch.skills.get("gambler", 0) > 0:
            dm += 1
        if ch.terms >= 7:  # mandatory retirement
            dm += 1
        return dm

    def muster_out(self, career_id: str | None = None) -> MusteringOutResult:
        """Compute the mustering-out plan (counts + DMs) without rolling (B15).

        Returns a :class:`MusteringOutResult` with ``total_rolls``,
        ``cash_dm``, and ``material_dm`` populated. The benefit lists are
        empty — the caller (TUI per-roll or batch auto-allocation) fills them
        via :meth:`claim_benefit`.
        """
        ch = self.engine.state.character
        cid = (
            career_id or ch.career or (ch.career_history[-1].career_id if ch.career_history else "")
        )
        if not cid:
            return MusteringOutResult()
        # G3: mishap "Lose all benefits" zeroes all benefit rolls.
        if ch.benefits_lost:
            career = self._get_career(cid)
            return MusteringOutResult(
                terms_served=ch.terms,
                final_rank=self._effective_muster_rank(cid),
                career_name=career.name,
                total_rolls=0,
                cash_dm=0,
                material_dm=0,
            )
        career = self._get_career(cid)
        terms = ch.terms
        rank = self._effective_muster_rank(cid)
        cash_dm = self._compute_cash_dm()

        return MusteringOutResult(
            terms_served=terms,
            final_rank=rank,
            career_name=career.name,
            total_rolls=benefit_rolls_for(terms, rank),
            cash_dm=cash_dm,
            material_dm=material_dm_for(rank),
        )

    def _count_cash_benefit_events(self) -> int:
        """Count cash benefit events since mustering started (resume safety)."""
        return sum(
            1
            for e in self.engine.state.events
            if e.command_type == "lifepath_benefit" and e.changes.get("benefit_type") == "cash"
        )

    @property
    def cash_rolls_taken(self) -> int:
        """Number of cash benefits claimed in this muster-out session."""
        return self._cash_rolls_taken

    def reconstruct_muster_counters(self, total_rolls: int) -> int:
        """Rebuild cash/material counters from the event log (resume-safe).

        Syncs ``_cash_rolls_taken`` from events and counts material events,
        then returns the number of benefit rolls remaining.
        """
        self._cash_rolls_taken = self._count_cash_benefit_events()
        material_taken = sum(
            1
            for e in self.engine.state.events
            if e.command_type == "lifepath_benefit" and e.changes.get("benefit_type") == "material"
        )
        return total_rolls - self._cash_rolls_taken - material_taken

    def claim_benefit(self, career_id: str, table: str, dm: int = 0) -> str:
        """Roll one mustering-out benefit and persist it (FR2, agency).

        ``table`` is ``"cash"`` or ``"material"``. Cash rolls are capped at 3
        per muster-out session (tracked via ``_cash_rolls_taken``). Returns
        the result text (e.g. ``"50,000 Cr"`` or ``"High Passage"``).
        """
        career = self._get_career(career_id)
        if table == "cash":
            if self._cash_rolls_taken >= 3:
                raise ValueError("cash rolls capped at 3 per muster-out session")
            benefit_table = career.mustering_out_cash
        elif table == "material":
            benefit_table = career.mustering_out_material
        else:
            raise ValueError(f"Unknown benefit table: {table!r}")

        if benefit_table is None:
            raise ValueError(f"Career {career_id!r} has no {table} benefit table")

        cmd = BenefitRollCommand(
            benefit_type=table,
            entries=benefit_table.entries.entries,
            num_dice=benefit_table.entries.num_dice,
            die_size=benefit_table.entries.die_size,
            dm=dm,
        )
        event = self.engine.apply(cmd)
        if table == "cash":
            self._cash_rolls_taken += 1
        return event.changes["result_text"]

    def _batch_muster_out(self, career_id: str) -> MusteringOutResult:
        """Auto-allocate benefit rolls for the batch path (cash-first, then material).

        Computes the plan via :meth:`muster_out`, then allocates cash rolls
        first (up to 3, limited by ``total_rolls``) and material rolls for the
        remainder. Populates the benefit lists on the result for narration.
        """
        plan = self.muster_out(career_id)
        career = self._get_career(career_id)

        # Reconstruct cash_rolls_taken from events (resume safety).
        self._cash_rolls_taken = self._count_cash_benefit_events()

        total = plan.total_rolls
        if total == 0:
            return plan

        # Allocate cash first (up to 3), then material.
        cash_to_take = min(3, total)
        for _ in range(cash_to_take):
            if career.mustering_out_cash is None:
                break
            result_text = self.claim_benefit(career_id, "cash", dm=0)
            plan.cash_benefits.append(result_text)

        material_to_take = total - len(plan.cash_benefits)
        if career.mustering_out_material is not None:
            for _ in range(material_to_take):
                result_text = self.claim_benefit(career_id, "material", dm=plan.material_dm)
                plan.material_benefits.append(result_text)

        # Populate roll values from events for narration.
        benefit_events = [
            e for e in self.engine.state.events if e.command_type == "lifepath_benefit"
        ]
        for ev in benefit_events[-total:]:
            if ev.changes.get("benefit_type") == "cash":
                plan.cash_rolls.append(ev.changes["adjusted_roll"])
            else:
                plan.material_rolls.append(ev.changes["adjusted_roll"])

        return plan

    # ------------------------------------------------------------------
    # Mishap roll + injury chain (Task 5: B13).
    # ------------------------------------------------------------------

    def _highest_physical_stat(self) -> str:
        """Return the current highest physical characteristic (batch default)."""
        chars = self.engine.state.character.characteristics
        return max(_PHYSICAL_CHARACTERISTICS, key=lambda s: chars.get(s, 0))

    def _stat_at_zero(self) -> str | None:
        """Return the first characteristic at or below 0, or None."""
        for stat, value in self.engine.state.character.characteristics.items():
            if value <= 0:
                return stat
        return None

    def run_mishap(self, career_id: str, chosen_stat: str | None = None) -> dict:
        """Roll the career mishap table; on entries 1/6 chain to the injury table.

        Returns a dict with ``injury`` (bool), ``crisis`` (bool), ``result``
        (str), plus ``crisis_stat`` (str | None) and ``reductions`` (dict) when
        applicable. Does NOT auto-resolve the crisis — the caller (batch
        runner or TUI) applies :class:`ResolveInjuryCrisisCommand` (B13).
        """
        career = self._get_career(career_id)
        if career.mishap_table is None:
            return {"injury": False, "crisis": False, "result": ""}

        mishap_cmd = MishapRollCommand(career_id=career_id, entries=career.mishap_table.entries)
        mishap_event = self.engine.apply(mishap_cmd)
        mc = mishap_event.changes
        result_text = mc["result_text"]
        is_injury = mc["injury"]

        if not is_injury or self.pack.injury_table is None:
            # No injury applied — either the entry doesn't chain to injury,
            # or the pack has no injury table to roll on.
            return {"injury": False, "crisis": False, "result": result_text}

        # Chain to the pack injury table.
        if chosen_stat is None:
            chosen_stat = self._highest_physical_stat()
        injury_cmd = InjuryRollCommand(
            entries=self.pack.injury_table.entries,
            chosen_stat=chosen_stat,
        )
        injury_event = self.engine.apply(injury_cmd)
        ic = injury_event.changes
        result_text = f"{result_text} -> {ic['result_text']}"

        crisis_stat = self._stat_at_zero()
        return {
            "injury": True,
            "crisis": crisis_stat is not None,
            "result": result_text,
            "crisis_stat": crisis_stat,
            "reductions": ic["reductions"],
        }

    def auto_resolve_crisis(self, stat: str) -> str:
        """Apply :class:`ResolveInjuryCrisisCommand` with the deterministic default.

        Pays Cr10,000 if the character can afford it; otherwise applies the
        death-mode fallback (ironman → death, narrative/checkpoint → scar).
        Returns the outcome string (``paid_cr10000`` | ``death`` | ``scarred``).
        """
        can_afford = self.engine.state.character.credits >= 10_000
        event = self.engine.apply(ResolveInjuryCrisisCommand(stat=stat, pay=can_afford))
        return event.changes["outcome"]

    _MENTAL_CHARACTERISTICS = ("INT", "EDU", "SOC")

    def _auto_apply_aging(self) -> None:
        """Distribute pending aging slots deterministically (batch path).

        Each pending slot is applied to the current highest characteristic in
        its group; after any reduction that drives a stat to 0, the crisis is
        auto-resolved via :meth:`auto_resolve_crisis` (B13/B4). Stops early if
        the character dies. The interactive TUI drives this per-slot with
        player choice instead.
        """
        while self.engine.state.character.pending_aging:
            if not self.engine.state.character.alive:
                return
            slot = self.engine.state.character.pending_aging[0]
            chars = self.engine.state.character.characteristics
            pool = (
                _PHYSICAL_CHARACTERISTICS
                if slot.group == "physical"
                else self._MENTAL_CHARACTERISTICS
            )
            stat = max(pool, key=lambda s: chars.get(s, 0))
            event = self.engine.apply(
                ApplyAgingReductionCommand(characteristic=stat, points=slot.points)
            )
            if event.changes.get("crisis"):
                self.auto_resolve_crisis(stat)

    # ------------------------------------------------------------------
    # Full lifepath.
    # ------------------------------------------------------------------

    def run_lifepath(
        self,
        career_id: str,
        num_terms: int,
        skill_table_choices: list[str] | None = None,
        fallback_choice: str | None = None,
    ) -> LifepathResult:
        """Run the full lifepath from characteristics to mustering out.

        Flow:
          1. Roll 6 characteristics.
          2. Qualify for career. On failure, apply ``fallback_choice``:

             * ``None``           — failure stands; lifepath ends with 0 terms.
             * ``"draft"``        — submit to the draft (1D6 on pack table).
             * ``"drifter"``      — attempt drifter qualification.
             * any other string   — re-attempt qualification for that career.

             The batch path never silently picks a fallback — the caller owns
             the choice (F2 / "always more player choice"). The interactive
             TUI surfaces the choice via ``choose_qualification_fallback``.
          3. Run N terms (survival/advancement/skills/aging per term).
          4. Muster out (if alive).

        Death mode branching:
          - ironman: death ends character, no mustering out.
          - narrative/checkpoint: mishap ends career, mustering out proceeds.
        """
        result = LifepathResult()

        # 1. Characteristics.
        result.characteristics = self.roll_characteristics()

        # 2. Qualification.
        qual = self.qualify(career_id)
        result.qualification = qual

        if not qual.success:
            career_id = self._apply_fallback_choice(career_id, fallback_choice, result)
            # If the fallback still didn't qualify the character, end with 0
            # terms. ``_apply_fallback_choice`` already updated
            # ``result.qualification`` to the final attempt.
            if not result.qualification.success:
                result.mustering_out = self._batch_muster_out(career_id)
                result.character_alive = self.engine.state.character.alive
                result.career_id = career_id
                return result

        # 3. Terms.
        for term_num in range(1, num_terms + 1):
            term_result = self.run_term(career_id, term_num, skill_table_choices)
            result.terms.append(term_result)

            if term_result.died:
                result.character_alive = False
                break

            if term_result.mishap:
                break  # leaves career → muster out

        # 4. Mustering out (if alive).
        if self.engine.state.character.alive:
            result.mustering_out = self._batch_muster_out(career_id)

        result.character_alive = self.engine.state.character.alive
        result.career_id = career_id
        return result

    def _apply_fallback_choice(
        self,
        original_career_id: str,
        fallback_choice: str | None,
        result: LifepathResult,
    ) -> str:
        """Apply a qualification-failure fallback (F2) and return the career id.

        * ``None`` — no fallback; the failed qualification stands. The
          character has no career assigned (``character.career`` stays "").
        * ``"draft"`` — submit to the draft; sets career via DraftCommand.
          Assumes the pack has a draft table (validated by the caller).
        * ``"drifter"`` — attempt drifter qualification. If that also fails
          the character has no career.
        * any other string — treat as a career id and re-attempt
          qualification against it.

        ``result.qualification`` is updated to the new attempt (or left as the
        original failure when ``fallback_choice is None``). The returned
        career id is what the caller should treat as the lifepath's career:
        the drafted/qualified id on success, or ``original_career_id`` when
        every path failed (so ``muster_out`` has *some* id to report, even
        though no career was actually entered — mustering out yields no
        benefits with zero terms).
        """
        if fallback_choice is None:
            return original_career_id

        if fallback_choice == "draft":
            drafted_id = self.run_draft()
            # Synthesise a successful QualificationResult for narration/audit
            # — the draft always assigns a career by construction.
            result.qualification = QualificationResult(
                career_id=drafted_id,
                career_name=self._get_career(drafted_id).name,
                characteristic="",
                char_value=0,
                char_dm=0,
                raw_roll=0,
                adjusted_total=0,
                target=0,
                success=True,
            )
            return drafted_id

        if fallback_choice == "drifter":
            qual2 = self.qualify("drifter")
            result.qualification = qual2
            return "drifter"

        # Treat as an explicit career id re-attempt.
        qual2 = self.qualify(fallback_choice)
        result.qualification = qual2
        return fallback_choice
