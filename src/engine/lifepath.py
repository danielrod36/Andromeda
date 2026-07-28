"""Lifepath engine for Cepheus Engine SRD character generation (U3).

Implements the full CE SRD lifepath: characteristic rolling, career qualification,
multi-term loop (survival/advancement/skills/aging), and mustering out.

Each step is a Command applied through the Engine funnel, producing audit events.
The LifepathRunner orchestrates the sequence and handles death-mode branching.

No LLM required — this is the standalone v0.1 chargen layer (AE7, R9, R10).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from src.engine.audit import Event, EventKind
from src.engine.commands import Command, Engine, RollCharacteristicCommand
from src.engine.dice import RollResult, Roller
from src.engine.state import Character, GameState
from src.rulesets.base import SkillTableEntry
from src.rulesets.cepheus import CepheusRuleSet
from src.themepacks.base import LoadedThemePack

_CHARACTERISTICS = ("STR", "DEX", "END", "INT", "EDU", "SOC")
_PHYSICAL_CHARACTERISTICS = ("STR", "DEX", "END")
_AGING_TARGET = 8


# ---------------------------------------------------------------------------
# Table lookup helpers.
# ---------------------------------------------------------------------------


def lookup_table_result(
    entries: list[SkillTableEntry], roll: int
) -> SkillTableEntry:
    """Find the table entry matching the roll value.

    If the roll falls outside the table range (after DMs), clamp to the
    nearest entry.
    """
    for entry in entries:
        if entry.min <= roll <= entry.max:
            return entry
    sorted_entries = sorted(entries, key=lambda e: e.min)
    if roll < sorted_entries[0].min:
        return sorted_entries[0]
    return sorted_entries[-1]


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
    """Roll qualification check (2D6 + char DM vs target)."""

    command_type: ClassVar[str] = "lifepath_qualification"
    career_id: str
    characteristic: str
    target: int

    def resolve(self, state: GameState, roller: Roller) -> RollResult:
        char_value = state.character.characteristics.get(self.characteristic, 7)
        dm = CepheusRuleSet().characteristic_dm(char_value)
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
        success = roll.total >= self.target
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
    """Roll on a skill table and apply the result to the character."""

    command_type: ClassVar[str] = "lifepath_skill_roll"
    table_name: str
    entries: list[SkillTableEntry]
    num_dice: int = 2
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
            description=(
                f"Skill roll ({self.table_name}): "
                f"{roll.total} -> {entry.result}"
            ),
            roll=roll,
            changes={
                "table_name": self.table_name,
                "roll_total": roll.total,
                "result_text": entry.result,
                "gain_type": gain_type,
                "gain_name": gain_name,
            },
        )


class AgingCommand(Command):
    """Roll aging check at age 34+. Reduce characteristics on failure."""

    command_type: ClassVar[str] = "lifepath_aging"

    def resolve(self, state: GameState, roller: Roller) -> RollResult:
        return roller.roll("lifepath", 2, 6)

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        assert roll is not None
        success = roll.total >= _AGING_TARGET
        reductions: dict[str, int] = {}
        if not success:
            raw = sum(roll.rolls)
            if raw <= 2:
                stats = _CHARACTERISTICS
            else:
                stats = _PHYSICAL_CHARACTERISTICS
            for stat in stats:
                current = state.character.characteristics.get(stat, 0)
                if current > 1:
                    state.character.characteristics[stat] = current - 1
                    reductions[stat] = 1
        return Event(
            kind=EventKind.ROLL,
            command_type=self.command_type,
            description=(
                f"Aging check: 2D6={sum(roll.rolls)} vs {_AGING_TARGET} -> "
                f"{'no effect' if success else 'aging ' + str(reductions)}"
            ),
            roll=roll,
            changes={
                "raw_roll": sum(roll.rolls),
                "target": _AGING_TARGET,
                "success": success,
                "reductions": reductions,
            },
        )


class BenefitRollCommand(Command):
    """Roll one mustering-out benefit (cash or material)."""

    command_type: ClassVar[str] = "lifepath_benefit"
    benefit_type: str
    entries: list[SkillTableEntry]
    num_dice: int = 1
    die_size: int = 6
    dm: int = 0

    def resolve(self, state: GameState, roller: Roller) -> RollResult:
        return roller.roll(
            "lifepath", self.num_dice, self.die_size, modifiers=self.dm
        )

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        assert roll is not None
        entry = lookup_table_result(self.entries, roll.total)
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
            },
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
    # Step 2: Qualification.
    # ------------------------------------------------------------------

    def qualify(self, career_id: str) -> QualificationResult:
        """Attempt qualification for a career. Sets career on success."""
        career = self._get_career(career_id)
        cmd = QualificationCommand(
            career_id=career_id,
            characteristic=career.qualification.characteristic,
            target=career.qualification.target,
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

    # ------------------------------------------------------------------
    # Step 3: Run one term.
    # ------------------------------------------------------------------

    def run_term(
        self,
        career_id: str,
        term_number: int,
        skill_table_choices: list[str] | None = None,
    ) -> TermResult:
        """Execute one 4-year term: survival, advancement, skills, aging."""
        career = self._get_career(career_id)
        state = self.engine.state
        age_before = state.character.age
        rank_before = state.character.rank

        result = TermResult(
            term_number=term_number,
            career_id=career_id,
            career_name=career.name,
            age_before=age_before,
            age_after=age_before + 4,
            rank_before=rank_before,
            survival_target=career.survival.target,
            advancement_target=career.advancement.target,
        )

        # --- 1. Survival ---
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
        result.rank_after = rank_before

        if result.died or result.mishap:
            return result

        # --- 2. Advancement ---
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

        # --- 3. Skill rolls ---
        num_rolls = 1  # base
        if result.advancement_success:
            num_rolls += 1
        if state.character.rank >= 3:
            num_rolls += 1

        table_names = [t.name for t in career.skill_tables]
        if skill_table_choices is None:
            skill_table_choices = [
                table_names[i % len(table_names)]
                for i in range(num_rolls)
            ]

        for table_name in skill_table_choices[:num_rolls]:
            table = next(
                (t for t in career.skill_tables if t.name == table_name),
                career.skill_tables[0],
            )
            skill_cmd = SkillTableRollCommand(
                table_name=table.name,
                entries=table.entries.entries,
                num_dice=table.entries.num_dice,
                die_size=table.entries.die_size,
            )
            skill_event = self.engine.apply(skill_cmd)
            sec = skill_event.changes
            result.skill_gains.append(
                SkillGain(
                    table_name=table.name,
                    roll=sec["roll_total"],
                    result_text=sec["result_text"],
                    gain_type=sec["gain_type"],
                    gain_name=sec["gain_name"],
                )
            )

        # --- 4. Aging (age 34+) ---
        if state.character.age >= 34:
            aging_cmd = AgingCommand()
            aging_event = self.engine.apply(aging_cmd)
            agc = aging_event.changes
            result.aging_raw = agc["raw_roll"]
            result.aging_success = agc["success"]
            result.aging_reductions = agc.get("reductions", {})

        # Set rank title.
        if career.ranks:
            matching = [
                r for r in career.ranks if r.rank == state.character.rank
            ]
            if matching:
                result.rank_title = matching[0].title

        return result

    # ------------------------------------------------------------------
    # Step 4: Mustering out.
    # ------------------------------------------------------------------

    def muster_out(self, career_id: str | None = None) -> MusteringOutResult:
        """Compute mustering-out benefits from career cash/material tables."""
        cid = career_id or self.engine.state.character.career
        if not cid:
            return MusteringOutResult()
        career = self._get_career(cid)
        state = self.engine.state
        terms = state.character.terms
        rank = state.character.rank

        result = MusteringOutResult(
            terms_served=terms,
            final_rank=rank,
            career_name=career.name,
        )

        # Cash benefits: up to 3 rolls with DM per term/rank.
        if career.mustering_out_cash and terms > 0:
            table = career.mustering_out_cash
            dm = table.dm_per_term * terms + table.dm_per_rank * rank
            for _ in range(min(terms, 3)):
                cmd = BenefitRollCommand(
                    benefit_type="cash",
                    entries=table.entries.entries,
                    num_dice=table.entries.num_dice,
                    die_size=table.entries.die_size,
                    dm=dm,
                )
                event = self.engine.apply(cmd)
                c = event.changes
                result.cash_benefits.append(c["result_text"])
                result.cash_rolls.append(c["adjusted_roll"])

        # Material benefits: one per term.
        if career.mustering_out_material and terms > 0:
            table = career.mustering_out_material
            dm = table.dm_per_term * terms + table.dm_per_rank * rank
            for _ in range(terms):
                cmd = BenefitRollCommand(
                    benefit_type="material",
                    entries=table.entries.entries,
                    num_dice=table.entries.num_dice,
                    die_size=table.entries.die_size,
                    dm=dm,
                )
                event = self.engine.apply(cmd)
                c = event.changes
                result.material_benefits.append(c["result_text"])
                result.material_rolls.append(c["adjusted_roll"])

        return result

    # ------------------------------------------------------------------
    # Full lifepath.
    # ------------------------------------------------------------------

    def run_lifepath(
        self,
        career_id: str,
        num_terms: int,
        skill_table_choices: list[str] | None = None,
    ) -> LifepathResult:
        """Run the full lifepath from characteristics to mustering out.

        Flow:
          1. Roll 6 characteristics.
          2. Qualify for career (fallback to drifter on failure).
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
            # Fallback: try drifter.
            if "drifter" in self.pack.careers and career_id != "drifter":
                career_id = "drifter"
                qual2 = self.qualify(career_id)
                result.qualification = qual2
                if not qual2.success:
                    # Even drifter failed — muster out with 0 terms.
                    result.mustering_out = self.muster_out(career_id)
                    result.character_alive = self.engine.state.character.alive
                    result.career_id = career_id
                    return result
            else:
                result.mustering_out = self.muster_out(career_id)
                result.character_alive = self.engine.state.character.alive
                result.career_id = career_id
                return result

        # 3. Terms.
        for term_num in range(1, num_terms + 1):
            term_result = self.run_term(
                career_id, term_num, skill_table_choices
            )
            result.terms.append(term_result)

            if term_result.died:
                result.character_alive = False
                break

            if term_result.mishap:
                break  # leaves career → muster out

        # 4. Mustering out (if alive).
        if self.engine.state.character.alive:
            result.mustering_out = self.muster_out(career_id)

        result.character_alive = self.engine.state.character.alive
        result.career_id = career_id
        return result
