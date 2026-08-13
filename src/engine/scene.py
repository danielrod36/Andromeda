"""Scene engine: oracle scaffolding, choice generation, resolution (U7).

A scene is one F4 cycle: oracle roll -> options -> choice -> resolution ->
consequences -> narration. The engine derives a scaffold from theme-pack
oracle tables (deterministic from RNG state), generates 2-4 structured
options each pre-mapped to an engine-known check, resolves the selected
check via the active resolution profile, and persists consequences through
the command funnel (R12, R13, R15, R22).

v0.3b adds free-text classification (R14, AE5): the LLM (or template
classifier) interprets free-text input into an engine-known check, shown
to the player before resolution. The player may accept, reject to rephrase,
or fall back to a structured option.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from src.engine.audit import Event, EventKind
from src.engine.commands import Command, Engine, FlagDegradationCommand
from src.engine.dice import Roller, RollResult
from src.engine.lifepath import lookup_table_result
from src.engine.skills import skill_display_name, skill_level_for
from src.engine.state import GameState, Injury, NarrativeFact, NpcRecord
from src.rulesets.base import OutcomeQuality, SkillTableEntry
from src.rulesets.cepheus import CepheusRuleSet
from src.rulesets.profiles import (
    ClassicProfile,
    NarrativeProfile,
    ResolutionProfile,
)
from src.themepacks.base import ComplicationMap, LoadedThemePack, OptionTemplate

# ---------------------------------------------------------------------------
# Commands — oracle rolls, scene checks, consequence application.
# ---------------------------------------------------------------------------


class OracleRollCommand(Command):
    """Roll 2D6 on the oracle stream and record in the audit log (R22, AE14).

    Oracle scaffolding rolls don't change game-state fields; they advance the
    RNG stream (so determinism is preserved) and log an event for audit.
    """

    command_type: ClassVar[str] = "oracle_roll"
    table_id: str

    def resolve(self, state: GameState, roller: Roller) -> RollResult:
        return roller.roll("oracle", ndice=2, sides=6)

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        assert roll is not None
        return Event(
            kind=EventKind.ROLL,
            command_type=self.command_type,
            description=f"Oracle roll ({self.table_id}): {roll.total}",
            roll=roll,
            changes={"table_id": self.table_id, "roll_total": roll.total},
        )


class ComplicationRollCommand(Command):
    """Roll 2D6 on a pack complication/consequence table (Task 18, R7).

    Used on the weak-hit path (complication table) and the miss path
    (consequence table). Rolls on the ``oracle`` stream so determinism is
    preserved alongside other scene-oracle rolls. The rolled entry text is
    registered as a :class:`NarrativeFact` (persists per R15) and returned as
    the consequence description in the event ``changes``.
    """

    command_type: ClassVar[str] = "complication_roll"
    table_id: str
    entries: list[SkillTableEntry]

    def resolve(self, state: GameState, roller: Roller) -> RollResult:
        return roller.roll("oracle", ndice=2, sides=6)

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        assert roll is not None
        entry = lookup_table_result(self.entries, roll.total)
        state.entities.append(
            NarrativeFact(
                name=entry.result,
                description=f"Complication from {self.table_id}",
            )
        )
        return Event(
            kind=EventKind.ROLL,
            command_type=self.command_type,
            description=f"{self.table_id}: {roll.total} -> {entry.result}",
            roll=roll,
            changes={
                "table_id": self.table_id,
                "roll_total": roll.total,
                "result_text": entry.result,
            },
        )


class SceneCheckCommand(Command):
    """Roll a skill check for a scene action (R13, R15).

    Rolls 2D6 on the combat stream, computes characteristic DM and skill DM,
    and resolves via the active profile. The outcome is recorded in the event
    log with all inputs for auditability.
    """

    command_type: ClassVar[str] = "scene_check"

    skill: str
    characteristic: str
    difficulty: str
    profile: str = "narrative"
    ratified: tuple[str, ...] = ()
    #: When True, mutate also clears ``state.pending_freetext`` — used when
    #: resolving a free-text check so the clear is atomic with the resolution
    #: (no two-command crash window where a save could capture the resolution
    #: event but leave the pending prompt stale). (U3/TUI-6)
    clear_pending_freetext: bool = False

    def resolve(self, state: GameState, roller: Roller) -> RollResult:
        return roller.roll("combat", ndice=2, sides=6)

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        assert roll is not None
        ruleset = CepheusRuleSet()

        char_value = state.character.characteristics.get(self.characteristic, 7)
        char_dm = ruleset.characteristic_dm(char_value)
        # Skill lookup canonicalizes to lifepath-stored IDs: exact match wins,
        # then the best cascade specialization ({skill_id}_*), else the CE SRD
        # untrained DM (-3). Level 0 counts as trained (FR1).
        skill_level, trained = skill_level_for(state.character, self.skill)
        difficulty_dm = ruleset.difficulty_modifier(self.difficulty)
        total_dm = char_dm + skill_level + difficulty_dm

        # Resolve via the appropriate profile strategy.
        profile_obj: ResolutionProfile
        profile_obj = ClassicProfile() if self.profile == "classic" else NarrativeProfile()
        outcome = profile_obj.resolve(roll.total, total_dm)

        # U3/TUI-6: atomically clear pending_freetext when resolving a
        # free-text check, so a save between resolve and clear is impossible.
        if self.clear_pending_freetext:
            state.pending_freetext = None

        return Event(
            kind=EventKind.ROLL,
            command_type=self.command_type,
            description=(
                f"Scene check ({self.skill}): 2D6={roll.rolls}={roll.total} "
                f"char_dm={char_dm:+d} skill={skill_level} "
                f"diff_dm={difficulty_dm:+d} total_dm={total_dm:+d} -> "
                f"{outcome.quality.value} (effect {outcome.effect:+d})"
            ),
            roll=roll,
            changes={
                "skill": self.skill,
                "characteristic": self.characteristic,
                "difficulty": self.difficulty,
                "profile": self.profile,
                "raw_roll": roll.total,
                "dice": list(roll.rolls),
                "char_dm": char_dm,
                "skill_level": skill_level,
                "trained": trained,
                "difficulty_dm": difficulty_dm,
                "total_dm": total_dm,
                "success": outcome.success,
                "effect": outcome.effect,
                "quality": outcome.quality.value,
                "description": outcome.description,
                "ratified": list(self.ratified),
            },
        )


class RegisterFactCommand(Command):
    """Register a narrative fact entity in canonical state (R24, AE9).

    LLM-introduced NPCs/places/items are registered as narrative facts.
    They are mechanically inert until the engine generates stats when a
    check targets them.
    """

    command_type: ClassVar[str] = "register_fact"

    name: str
    description: str = ""
    #: Provenance stamp — set to ``"llm"`` by LLM tool wrappers so pill
    #: extraction can distinguish LLM-originated events from engine-originated
    #: ones (KTD-R4, R13).  Engine code never sets this field.
    origin: str | None = None

    def validate(self, state: GameState) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("Fact name must be non-empty")

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        fact = NarrativeFact(
            name=self.name.strip(),
            description=self.description,
        )
        state.entities.append(fact)
        changes: dict = {"name": self.name, "description": self.description}
        if self.origin is not None:
            changes["origin"] = self.origin
        return Event(
            kind=EventKind.STATE_CHANGE,
            command_type=self.command_type,
            description=f"Registered narrative fact: {self.name}",
            changes=changes,
        )


class AddOpenThreadCommand(Command):
    """Add an open narrative thread to canonical state (R15, R25).

    Mission hooks are added as open threads on accept so the curated view
    and fact retrieval can reference them; resolved on mission end.
    """

    command_type: ClassVar[str] = "add_open_thread"
    thread: str

    def validate(self, state: GameState) -> None:
        if not self.thread or not self.thread.strip():
            raise ValueError("Open thread must be non-empty")

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        thread = self.thread.strip()
        if thread not in state.open_threads:
            state.open_threads.append(thread)
        return Event(
            kind=EventKind.STATE_CHANGE,
            command_type=self.command_type,
            description=f"Open thread added: {thread}",
            changes={"thread": thread},
        )


class RemoveOpenThreadCommand(Command):
    """Remove an open narrative thread (on mission resolve)."""

    command_type: ClassVar[str] = "remove_open_thread"
    thread: str

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        thread = self.thread.strip()
        if thread in state.open_threads:
            state.open_threads.remove(thread)
        return Event(
            kind=EventKind.STATE_CHANGE,
            command_type=self.command_type,
            description=f"Open thread removed: {thread}",
            changes={"thread": thread},
        )


class AddInjuryCommand(Command):
    """Add an injury to the character (R15)."""

    command_type: ClassVar[str] = "add_injury"

    name: str
    severity: str = "moderate"
    description: str = ""

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        injury = Injury(
            name=self.name,
            severity=self.severity,
            description=self.description,
        )
        state.entities.append(injury)
        return Event(
            kind=EventKind.STATE_CHANGE,
            command_type=self.command_type,
            description=f"Injury added: {self.name} ({self.severity})",
            changes={
                "name": self.name,
                "severity": self.severity,
                "description": self.description,
            },
        )


class RatifyFactCommand(Command):
    """Ratify a narrative fact as an NPC with mechanical stats (R24, AE9).

    Updates the fact's description to mark it as mechanically active, and
    **logs the ratification event** so a replay tool can reconstruct state
    from the event log. The fact must already exist in ``state.entities``;
    this command finds it by name and updates its description.
    """

    command_type: ClassVar[str] = "ratify_fact"

    fact_name: str
    stats_description: str
    #: Provenance stamp — reserved for a future LLM ratification tool that
    #: would pass ``origin="llm"`` so pill extraction can distinguish
    #: LLM-originated events from engine-originated ones (KTD-R4, R13).
    #: No LLM tool wraps RatifyFactCommand yet; the only call site
    #: (retrieval.py:ratify_fact_as_npc) is engine-side and never sets it.
    origin: str | None = None

    def validate(self, state: GameState) -> None:
        if not self.fact_name or not self.fact_name.strip():
            raise ValueError("Fact name must be non-empty")

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        fact = next(
            (
                e
                for e in state.entities
                if isinstance(e, NarrativeFact) and e.name == self.fact_name
            ),
            None,
        )
        if fact is None:
            raise ValueError(f"Cannot ratify fact {self.fact_name!r}: not found in entities")
        fact.description = (f"{fact.description} {self.stats_description}").strip()
        changes: dict = {
            "fact_name": self.fact_name,
            "stats_description": self.stats_description,
        }
        if self.origin is not None:
            changes["origin"] = self.origin
        return Event(
            kind=EventKind.STATE_CHANGE,
            command_type=self.command_type,
            description=(f"Ratified narrative fact as NPC: {self.fact_name}"),
            changes=changes,
        )


class NpcReactionRollCommand(Command):
    """Roll 2D6 on the oracle stream for a ratified NPC's reaction (G6).

    Mirrors :class:`src.engine.mission.MissionTableRollCommand`: the roll
    advances the oracle stream and is recorded for audit; the caller looks
    up the pack's ``npc_reaction`` table with the returned total.
    """

    command_type: ClassVar[str] = "npc_reaction_roll"

    def resolve(self, state: GameState, roller: Roller) -> RollResult:
        return roller.roll("oracle", ndice=2, sides=6)

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        assert roll is not None
        return Event(
            kind=EventKind.ROLL,
            command_type=self.command_type,
            description=f"NPC reaction roll (npc_reaction): {roll.total}",
            roll=roll,
            changes={"table_id": "npc_reaction", "roll_total": roll.total},
        )


class CreateNpcRecordCommand(Command):
    """Create the canonical :class:`NpcRecord` for a ratified fact (G6).

    Idempotent by name: a second application for the same NPC records a
    no-op event instead of duplicating the entity (the first write wins).
    """

    command_type: ClassVar[str] = "create_npc_record"

    name: str
    disposition: int = 0  # -2 hostile .. +2 allied
    description: str = ""

    def validate(self, state: GameState) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("NPC name must be non-empty")
        if not -2 <= self.disposition <= 2:
            raise ValueError(f"disposition must be in [-2, +2], got {self.disposition}")

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        existing = next(
            (e for e in state.entities if isinstance(e, NpcRecord) and e.name == self.name),
            None,
        )
        if existing is not None:
            return Event(
                kind=EventKind.STATE_CHANGE,
                command_type=self.command_type,
                description=f"NPC record already exists: {self.name}",
                changes={"name": self.name, "already_existed": True},
            )
        state.entities.append(
            NpcRecord(
                name=self.name.strip(),
                disposition=self.disposition,
                description=self.description,
            )
        )
        return Event(
            kind=EventKind.STATE_CHANGE,
            command_type=self.command_type,
            description=f"NPC record created: {self.name} (disposition {self.disposition:+d})",
            changes={
                "name": self.name.strip(),
                "disposition": self.disposition,
                "description": self.description,
            },
        )


# ---------------------------------------------------------------------------
# Data structures (transient — not serialized).
# ---------------------------------------------------------------------------


class SetPendingFreetextCommand(Command):
    """Set or clear the pending free-text interpretation state (TUI-6, R7).

    When ``payload`` is a dict, stores it in ``state.pending_freetext`` so a
    quit/resume restores the exact accept/reject prompt. When ``None``,
    clears the field (player rejected the interpretation).

    The payload carries:
    - ``text``: the original free-text input
    - ``check``: serialized :class:`SceneOption` (label, skill, characteristic,
      difficulty, life_threatening — all fields that drive DM math and defeat
      handling, so a thin payload would resolve a different check)
    - ``scaffold``: serialized :class:`SceneScaffold` snapshot
    - ``options``: list of serialized :class:`SceneOption` the scaffold produced

    Accept-path clearing is handled by :class:`SceneCheckCommand` with
    ``clear_pending_freetext=True`` so the clear is atomic with the resolution
    (no two-command crash window).
    """

    command_type: ClassVar[str] = "set_pending_freetext"

    payload: dict | None = None

    def validate(self, state: GameState) -> None:
        if self.payload is not None:
            required = {"text", "check", "scaffold", "options"}
            missing = required - set(self.payload.keys())
            if missing:
                raise ValueError(f"pending_freetext payload missing required keys: {missing}")
            check = self.payload["check"]
            if not isinstance(check, dict):
                raise ValueError("pending_freetext check must be a dict")
            check_keys = {"label", "skill", "characteristic", "difficulty"}
            missing_check = check_keys - set(check.keys())
            if missing_check:
                raise ValueError(f"pending_freetext check missing required keys: {missing_check}")

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        state.pending_freetext = self.payload
        return Event(
            kind=EventKind.STATE_CHANGE,
            command_type=self.command_type,
            description=(
                "Free-text interpretation pending"
                if self.payload is not None
                else "Free-text interpretation resolved"
            ),
            changes={"pending_freetext": self.payload},
        )


@dataclass
class SceneScaffold:
    """Oracle-derived scaffold for a scene (AE14).

    Produced from oracle table rolls. Same RNG state + same tables produces
    the same scaffold deterministically.
    """

    focus: str
    focus_description: str
    situation: str
    npc_hint: str | None = None
    oracle_rolls: list[int] = field(default_factory=list)


@dataclass
class SceneOption:
    """A structured choice pre-mapped to an engine-known check (R12, R13)."""

    label: str
    skill: str
    characteristic: str
    difficulty: str
    description: str = ""
    life_threatening: bool = False


@dataclass
class FreeTextClassification:
    """Result of classifying free-text input (R14, AE5).

    ``interpreted_check`` is the engine-known check the LLM derived from the
    free text. Shown to the player before resolution; player may accept,
    reject to rephrase, or fall back to a structured option.
    """

    original_text: str
    interpreted_check: SceneOption


@dataclass
class SceneCheckResult:
    """Outcome of resolving a scene check."""

    skill: str
    difficulty: str
    raw_roll: int
    char_dm: int
    skill_level: int
    difficulty_dm: int
    total_dm: int
    success: bool
    effect: int
    quality: str
    description: str
    # Task 16/20: dice values and trained flag for inline mechanics display.
    dice: list[int] = field(default_factory=list)
    trained: bool = True
    # Task 23: facts ratified as NPCs because the check targeted them (AE9).
    ratified: list[str] = field(default_factory=list)


@dataclass
class SceneResult:
    """Full result of one scene cycle."""

    scaffold: SceneScaffold
    options: list[SceneOption]
    chosen_option: SceneOption | None = None
    check_result: SceneCheckResult | None = None
    narration: str = ""
    consequences: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Generic fallback templates (R13 degradation path).
# ---------------------------------------------------------------------------
#
# These two OptionTemplate constants are the deterministic last-resort options
# used when pack option data is missing or yields fewer than two options. They
# reference skills that ship in every pack (athletics is present in both the
# sci-fi and fantasy packs' skills.yaml). When this path is taken, the engine
# also appends a FlagDegradationCommand so the degraded behavior is visible in
# the audit log.

_GENERIC_FALLBACK_OPTIONS: tuple[OptionTemplate, OptionTemplate] = (
    OptionTemplate(
        label="Take direct action",
        skill="athletics",
        characteristic="END",
        difficulty="average",
        life_threatening=False,
    ),
    OptionTemplate(
        label="Push through regardless",
        skill="athletics",
        characteristic="STR",
        difficulty="difficult",
        life_threatening=False,
    ),
)


# ---------------------------------------------------------------------------
# Scene engine.
# ---------------------------------------------------------------------------


class SceneEngine:
    """Orchestrates scene generation, choice resolution, and consequences.

    Usage::

        engine = SceneEngine(engine, pack)
        scaffold = engine.generate_scaffold()
        options = engine.generate_options(scaffold)
        result = engine.resolve_scene(scaffold, options[0])

    Determinism (AE14): same oracle RNG state + same oracle tables produces
    the same scaffold. Tests inject ForcedRoller with queued results.
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

    # ------------------------------------------------------------------
    # Scaffold generation (R22, AE14).
    # ------------------------------------------------------------------

    def generate_scaffold(self) -> SceneScaffold:
        """Roll on oracle tables to produce a scene scaffold.

        Rolls scene_focus (determines what the scene is about) and
        action_outcome (determines the base situation). The NPC hint is
        derived from the focus description, not an additional roll.

        Same RNG state -> same scaffold deterministically.
        """
        rolls: list[int] = []

        # 1. Scene focus — what aspect of the story the scene centers on.
        focus_table = self._get_oracle_table("scene_focus")
        focus_roll = self._oracle_roll("scene_focus")
        rolls.append(focus_roll)
        focus_entry = lookup_table_result(focus_table.entries.entries, focus_roll)
        focus_text = focus_entry.result

        # Parse the category keyword (first word before " — ").
        focus_category = focus_text.split(" —")[0].split(" —")[0].strip()
        if "—" in focus_text:
            focus_category = focus_text.split("—")[0].strip()
        focus_desc = focus_text.split("—", 1)[1].strip() if "—" in focus_text else focus_text

        # 2. Action outcome — the base situation context.
        outcome_table = self._get_oracle_table("action_outcome")
        outcome_roll = self._oracle_roll("action_outcome")
        rolls.append(outcome_roll)
        outcome_entry = lookup_table_result(outcome_table.entries.entries, outcome_roll)
        situation = outcome_entry.result

        # Derive NPC hint from focus category (no additional roll).
        npc_hint: str | None = None
        if focus_category.lower() in ("social", "political", "plot twist"):
            npc_hint = "An important NPC is central to this scene."

        return SceneScaffold(
            focus=focus_category,
            focus_description=focus_desc,
            situation=situation,
            npc_hint=npc_hint,
            oracle_rolls=rolls,
        )

    # ------------------------------------------------------------------
    # Option generation (R12, R13, AE10).
    # ------------------------------------------------------------------

    def generate_options(self, scaffold: SceneScaffold) -> list[SceneOption]:
        """Derive 2-4 structured options from the scaffold + theme-pack data.

        Resolution order (R13 degradation fallback):

        1. Look up ``pack.option_templates.focus_options`` by the scaffold's
           focus keyword (case-insensitive substring match).
        2. On no match, use ``pack.option_templates.default_options``.
        3. If the pack has no option templates, or the resolved set has fewer
           than two entries, fall back to the deterministic generic options
           (``_GENERIC_FALLBACK_OPTIONS``) and append a
           :class:`FlagDegradationCommand` to the audit log.

        Each option pre-maps to an engine-known check (skill id + difficulty).
        """
        templates = self._resolve_option_templates(scaffold.focus)
        options = [self._template_to_option(t) for t in templates]

        # R13: fewer than 2 options triggers the deterministic degradation
        # path. Flag the audit log so the degraded behavior is inspectable.
        if len(options) < 2:
            self.engine.apply(
                FlagDegradationCommand(
                    area="options",
                    reason=(
                        f"pack={self.pack.id!r} focus={scaffold.focus!r} "
                        f"yielded {len(options)} option(s); using generic fallback"
                    ),
                )
            )
            # Use the generic fallback templates; preserve any pack-derived
            # option we did get (it is still a valid pack id).
            fallback = [self._template_to_option(t) for t in _GENERIC_FALLBACK_OPTIONS]
            seen_skills = {o.skill for o in options}
            for opt in fallback:
                if len(options) >= 4:
                    break
                if opt.skill not in seen_skills:
                    options.append(opt)
                    seen_skills.add(opt.skill)
            # Absolute floor: if even the fallback templates collided, top up
            # deterministically from the fallback list without the dedup gate.
            i = 0
            while len(options) < 2 and i < len(fallback):
                options.append(fallback[i])
                i += 1

        return options[:4]  # Cap at 4.

    def _template_to_option(self, template: OptionTemplate) -> SceneOption:
        """Convert a pack :class:`OptionTemplate` into a runtime :class:`SceneOption`.

        Uses :func:`skill_display_name` so the ``description`` shows a
        human-readable skill name rather than the raw pack id (e.g.
        "Gun Combat (Slug Rifle)" instead of "gun_combat_slug_rifle").
        """
        display = skill_display_name(self.pack, template.skill)
        return SceneOption(
            label=template.label,
            skill=template.skill,
            characteristic=template.characteristic,
            difficulty=template.difficulty,
            description=f"{display} check ({template.difficulty}) using {template.characteristic}",
            life_threatening=template.life_threatening,
        )

    def _resolve_option_templates(self, focus: str) -> list[OptionTemplate]:
        """Pick the pack option-template list for ``focus`` (R13 fallback chain).

        1. Pack ``focus_options`` matched case-insensitively on the focus.
        2. Pack ``default_options`` on no focus match.
        3. Empty list — caller applies the generic degradation fallback.
        """
        templates = self.pack.option_templates
        if templates is None:
            return []

        focus_lower = focus.lower()
        for keyword, opts in templates.focus_options.items():
            if keyword.lower() in focus_lower and opts:
                return list(opts)

        if templates.default_options:
            return list(templates.default_options)
        return []

    # ------------------------------------------------------------------
    # Check resolution (R13, R15).
    # ------------------------------------------------------------------

    def resolve_scene(
        self,
        scaffold: SceneScaffold,
        option: SceneOption,
        *,
        clear_pending_freetext: bool = False,
    ) -> SceneCheckResult:
        """Resolve a scene check through the command funnel.

        Rolls 2D6 on the combat stream, applies the active resolution
        profile, and returns the outcome. The check is recorded in the
        event log via SceneCheckCommand.

        Before resolving, if any unratified :class:`NarrativeFact` name
        appears in the option label/description or scaffold text, the fact
        is ratified as an NPC via :func:`ratify_fact_as_npc` (R24, AE9).
        Ratified fact names are recorded on the check result so narration
        can reference the mechanical activation.

        Args:
            clear_pending_freetext: When True, the SceneCheckCommand also
                clears ``state.pending_freetext`` atomically (U3/TUI-6) —
                used when resolving a free-text check the player accepted.
        """
        # Deferred import: retrieval.py imports RatifyFactCommand from this
        # module, so a top-level import would create a circular dependency.
        from src.engine.retrieval import ratify_fact_as_npc

        # AE9: ratify facts whose names are targeted by this check.
        ratified: list[str] = []
        haystack = " ".join(
            [
                option.label,
                option.description,
                scaffold.focus_description,
                scaffold.situation,
            ]
        ).lower()
        for fact in [e for e in self.engine.state.entities if isinstance(e, NarrativeFact)]:
            if "NPC stats" in fact.description:
                continue  # already ratified
            if fact.name.lower() in haystack:
                ratify_fact_as_npc(fact, engine=self.engine, pack=self.pack)
                ratified.append(fact.name)

        cmd = SceneCheckCommand(
            skill=option.skill,
            characteristic=option.characteristic,
            difficulty=option.difficulty,
            profile=self.engine.state.campaign.resolution_profile,
            ratified=tuple(ratified),
            clear_pending_freetext=clear_pending_freetext,
        )
        event = self.engine.apply(cmd)
        c = event.changes
        return SceneCheckResult(
            skill=c["skill"],
            difficulty=c["difficulty"],
            raw_roll=c["raw_roll"],
            char_dm=c["char_dm"],
            skill_level=c["skill_level"],
            difficulty_dm=c["difficulty_dm"],
            total_dm=c["total_dm"],
            success=c["success"],
            effect=c["effect"],
            quality=c["quality"],
            description=c["description"],
            dice=list(c["dice"]),
            trained=c["trained"],
            ratified=list(c.get("ratified", [])),
        )

    # ------------------------------------------------------------------
    # Free-text classification (R14, AE5).
    # ------------------------------------------------------------------

    def classify_freetext(
        self,
        text: str,
        scaffold: SceneScaffold,
        *,
        llm_classifier=None,
    ) -> FreeTextClassification | None:
        """Classify free-text input into an engine-known check (AE5, R14).

        When ``llm_classifier`` is provided (a sync callable taking
        ``(text, scaffold)`` and returning a :class:`FreeTextCheck` or
        ``None``), the LLM classification is tried first. If it returns a
        result, it is converted to a :class:`FreeTextClassification`.

        If the LLM classifier returns ``None`` (exhaustion, failure, or not
        provided), the pack keyword map (Task 17) is used as the fallback.
        Keywords are matched as case-insensitive substrings of ``text``,
        sorted by keyword length descending so longer phrases win.

        Returns ``None`` if neither the LLM classifier nor the keyword map
        produces a match.
        """
        # R14: try LLM classifier first.
        if llm_classifier is not None:
            try:
                check = llm_classifier(text, scaffold)
            except Exception:
                check = None
            if check is not None:
                option = SceneOption(
                    label=check.label,
                    skill=check.skill_id,
                    characteristic=check.characteristic,
                    difficulty=check.difficulty,
                    description=f"Interpreted from: '{text}'",
                    life_threatening=check.life_threatening,
                )
                return FreeTextClassification(
                    original_text=text,
                    interpreted_check=option,
                )

        # Keyword fallback (Task 17).
        templates = self.pack.option_templates
        if templates is None or not templates.freetext_keywords:
            return None

        text_lower = text.lower().strip()
        # Longest keyword first to reduce false positives.
        for template in sorted(
            templates.freetext_keywords,
            key=lambda t: len(t.keyword),
            reverse=True,
        ):
            if template.keyword.lower() in text_lower:
                option = SceneOption(
                    label=f"[Free-text] {template.label}",
                    skill=template.skill,
                    characteristic=template.characteristic,
                    difficulty=template.difficulty,
                    description=f"Interpreted from: '{text}'",
                    life_threatening=template.life_threatening,
                )
                return FreeTextClassification(
                    original_text=text,
                    interpreted_check=option,
                )

        return None

    # ------------------------------------------------------------------
    # Consequence application (R15, R7 — Task 18 pack-table complications).
    # ------------------------------------------------------------------

    def apply_consequences(
        self,
        check_result: SceneCheckResult,
        scaffold: SceneScaffold,
    ) -> list[str]:
        """Apply consequences based on the check outcome via the funnel.

        Weak hits roll the focus-mapped complication table; misses roll the
        focus-mapped consequence table and *additionally* apply the existing
        injury-by-effect tiers for severe misses. Strong hits register an
        advantage as a narrative fact. When the pack supplies no table for
        the resolved kind/focus, the engine falls back to a
        :class:`FlagDegradationCommand` so the gap is inspectable in the
        audit log (R13).
        """
        consequences: list[str] = []
        quality = check_result.quality

        if quality == OutcomeQuality.MISS.value:
            # Failure: roll the consequence table, then keep the existing
            # injury-by-effect tiers for severe misses.
            self._roll_pack_table_into("consequence", scaffold, consequences)
            if check_result.effect <= -4:
                self.engine.apply(
                    AddInjuryCommand(
                        name=f"Injury from {scaffold.focus} scene",
                        severity="severe",
                        description="A serious injury sustained in failure.",
                    )
                )
                consequences.append("Severe injury sustained.")
            elif check_result.effect <= -2:
                self.engine.apply(
                    AddInjuryCommand(
                        name=f"Wound from {scaffold.focus} scene",
                        severity="moderate",
                        description="A painful wound from the failed attempt.",
                    )
                )
                consequences.append("Moderate wound sustained.")

        elif quality == OutcomeQuality.WEAK_HIT.value:
            # Weak hit: roll the complication table; no hardcoded string.
            self._roll_pack_table_into("complication", scaffold, consequences)

        elif quality == OutcomeQuality.STRONG_HIT.value:
            # Strong hit: register an advantage as a narrative fact.
            advantage_name = f"Advantage from {scaffold.focus} scene"
            self.engine.apply(
                RegisterFactCommand(
                    name=advantage_name,
                    description="A lasting advantage gained from a strong success.",
                )
            )
            consequences.append("Strong success — a lasting advantage gained.")

        # Log narration to the narrative log.
        self.engine.apply(_LogNarrationCommand(text=self._narrate_result(check_result, scaffold)))

        return consequences

    def _roll_pack_table_into(
        self,
        kind: str,
        scaffold: SceneScaffold,
        consequences: list[str],
    ) -> None:
        """Resolve ``kind`` (complication/consequence) for ``scaffold.focus``.

        Focus-mapped selection with default fallback, then any table whose id
        contains the kind; if no table is available, a
        :class:`FlagDegradationCommand` is appended and a generic line is
        emitted so the caller still has a human-readable consequence (R13).
        Rolled text is appended to ``consequences`` in place.
        """
        table_id = self._resolve_table_id(kind, scaffold.focus)
        if table_id is None:
            self.engine.apply(
                FlagDegradationCommand(
                    area=f"{kind}_table",
                    reason=(
                        f"pack={self.pack.id!r} focus={scaffold.focus!r} "
                        f"kind={kind!r}: no table mapped and no id-contains "
                        f"fallback; emitting generic consequence"
                    ),
                )
            )
            consequences.append(
                "Complication arises."
                if kind == "complication"
                else "The attempt fails with consequences."
            )
            return

        table = self.pack.complication_tables[table_id]
        event = self.engine.apply(
            ComplicationRollCommand(table_id=table_id, entries=table.entries.entries)
        )
        consequences.append(event.changes["result_text"])

    def _resolve_table_id(self, kind: str, focus: str) -> str | None:
        """Pick the pack table id for ``kind`` (complication/consequence) + focus.

        Resolution chain (R7 + R13 fallback):

        1. ``pack.complication_map.<kind>`` — case-insensitive substring match
           on the focus keyword, then the ``default`` entry.
        2. Any complication table whose id contains ``kind`` (so a pack with
           only ``combat_complication`` still resolves the complication path).
        3. ``None`` — caller flags degradation.
        """
        cmap: ComplicationMap | None = self.pack.complication_map
        if cmap is not None:
            kind_map = getattr(cmap, kind, {}) or {}
            if kind_map:
                focus_lower = focus.lower()
                for keyword, table_id in kind_map.items():
                    if keyword == "default":
                        continue
                    if keyword.lower() in focus_lower:
                        return table_id
                if "default" in kind_map:
                    return kind_map["default"]

        # Last-resort: any complication table whose id mentions the kind.
        for candidate_id in sorted(self.pack.complication_tables):
            if kind in candidate_id:
                return candidate_id
        return None

    # ------------------------------------------------------------------
    # Full scene cycle (convenience).
    # ------------------------------------------------------------------

    def run_scene(self) -> SceneResult:
        """Run a complete scene cycle: scaffold -> options.

        The caller selects an option and calls :meth:`resolve_scene` +
        :meth:`apply_consequences` to complete the cycle. This method
        produces the scaffold and options only; the choice is the player's.
        """
        scaffold = self.generate_scaffold()
        options = self.generate_options(scaffold)
        return SceneResult(scaffold=scaffold, options=options)

    # ------------------------------------------------------------------
    # Internal helpers.
    # ------------------------------------------------------------------

    def _get_oracle_table(self, table_id: str):
        """Look up an oracle table by id, raising if not found."""
        if table_id not in self.pack.oracle_tables:
            available = sorted(self.pack.oracle_tables.keys())
            raise KeyError(
                f"Oracle table '{table_id}' not found in pack '{self.pack.id}'. "
                f"Available: {available}"
            )
        return self.pack.oracle_tables[table_id]

    def _oracle_roll(self, table_id: str) -> int:
        """Roll 2D6 on the oracle stream via the command funnel.

        Going through the funnel preserves determinism, audit, and
        checkpoint guarantees (AE14).
        """
        cmd = OracleRollCommand(table_id=table_id)
        event = self.engine.apply(cmd)
        return event.changes["roll_total"]

    @staticmethod
    def _narrate_result(check_result: SceneCheckResult, scaffold: SceneScaffold) -> str:
        """Template narration for a scene check result."""
        quality = check_result.quality
        skill = check_result.skill
        if quality == OutcomeQuality.STRONG_HIT.value:
            return f"Your {skill} check succeeds brilliantly in the {scaffold.focus} scene."
        elif quality == OutcomeQuality.WEAK_HIT.value:
            return (
                f"Your {skill} check succeeds, but with a complication "
                f"in the {scaffold.focus} scene."
            )
        else:
            return (
                f"Your {skill} check fails in the {scaffold.focus} scene. "
                f"The situation does not go your way."
            )


class _LogNarrationCommand(Command):
    """Internal command to append narration to the narrative log."""

    command_type: ClassVar[str] = "log_narration"
    text: str

    def validate(self, state: GameState) -> None:
        if not self.text or not self.text.strip():
            raise ValueError("Narration text must be non-empty")

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        state.narrative_log.append(self.text.strip())
        return Event(
            kind=EventKind.STATE_CHANGE,
            command_type=self.command_type,
            description="Narration logged",
            changes={"text": self.text},
        )
