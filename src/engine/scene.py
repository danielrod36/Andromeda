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

import re
from dataclasses import dataclass, field
from typing import ClassVar

from src.engine.audit import Event, EventKind
from src.engine.commands import Command, Engine
from src.engine.dice import RollResult, Roller
from src.engine.lifepath import lookup_table_result
from src.engine.state import GameState, Injury, NarrativeFact
from src.rulesets.base import CheckOutcome, OutcomeQuality, SkillTableEntry
from src.rulesets.cepheus import CepheusRuleSet
from src.rulesets.profiles import (
    ClassicProfile,
    NarrativeProfile,
    ResolutionProfile,
)
from src.themepacks.base import LoadedThemePack


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

    def resolve(self, state: GameState, roller: Roller) -> RollResult:
        return roller.roll("combat", ndice=2, sides=6)

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        assert roll is not None
        ruleset = CepheusRuleSet()

        char_value = state.character.characteristics.get(self.characteristic, 7)
        char_dm = ruleset.characteristic_dm(char_value)
        skill_level = state.character.skills.get(self.skill, 0)
        difficulty_dm = ruleset.difficulty_modifier(self.difficulty)
        total_dm = char_dm + skill_level + difficulty_dm

        # Resolve via the appropriate profile strategy.
        profile_obj: ResolutionProfile
        if self.profile == "classic":
            profile_obj = ClassicProfile()
        else:
            profile_obj = NarrativeProfile()
        outcome = profile_obj.resolve(roll.total, total_dm)

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
                "char_dm": char_dm,
                "skill_level": skill_level,
                "difficulty_dm": difficulty_dm,
                "total_dm": total_dm,
                "success": outcome.success,
                "effect": outcome.effect,
                "quality": outcome.quality.value,
                "description": outcome.description,
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

    def validate(self, state: GameState) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("Fact name must be non-empty")

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        fact = NarrativeFact(
            name=self.name.strip(),
            description=self.description,
        )
        state.entities.append(fact)
        return Event(
            kind=EventKind.STATE_CHANGE,
            command_type=self.command_type,
            description=f"Registered narrative fact: {self.name}",
            changes={"name": self.name, "description": self.description},
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

    def validate(self, state: GameState) -> None:
        if not self.fact_name or not self.fact_name.strip():
            raise ValueError("Fact name must be non-empty")

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        fact = next(
            (
                e for e in state.entities
                if isinstance(e, NarrativeFact) and e.name == self.fact_name
            ),
            None,
        )
        if fact is None:
            raise ValueError(
                f"Cannot ratify fact {self.fact_name!r}: not found in entities"
            )
        fact.description = (
            f"{fact.description} {self.stats_description}"
        ).strip()
        return Event(
            kind=EventKind.STATE_CHANGE,
            command_type=self.command_type,
            description=(
                f"Ratified narrative fact as NPC: {self.fact_name}"
            ),
            changes={
                "fact_name": self.fact_name,
                "stats_description": self.stats_description,
            },
        )


# ---------------------------------------------------------------------------
# Data structures (transient — not serialized).
# ---------------------------------------------------------------------------


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
# Focus-to-option mapping (derives structured options from scaffold).
# ---------------------------------------------------------------------------

#: Each tuple is (keyword, list of option templates).
#: The keyword is matched against the scene_focus oracle result to determine
#: which set of options to present. Each template provides a label, skill,
#: characteristic, difficulty, and life_threatening flag for the pre-mapped check.
_FOCUS_OPTION_MAP: list[tuple[str, list[tuple[str, str, str, str, bool]]]] = [
    (
        "combat",
        [
            ("Engage in combat", "Gun Combat", "DEX", "average", True),
            ("Use stealth to gain advantage", "Stealth", "DEX", "difficult", False),
            ("Intimidate them into backing down", "Streetwise", "SOC", "average", False),
        ],
    ),
    (
        "social",
        [
            ("Persuade them to cooperate", "Persuade", "SOC", "average", False),
            ("Deceive them with a cover story", "Deception", "SOC", "difficult", False),
            ("Negotiate a mutually beneficial deal", "Broker", "INT", "average", False),
        ],
    ),
    (
        "exploration",
        [
            ("Investigate the area thoroughly", "Investigate", "INT", "average", False),
            ("Scan with ship sensors", "Sensors", "EDU", "average", False),
            ("Navigate difficult terrain", "Survival", "END", "difficult", True),
        ],
    ),
    (
        "technical",
        [
            ("Repair or modify the system", "Mechanic", "EDU", "average", False),
            ("Hack into the computer", "Computers", "INT", "difficult", False),
            ("Apply engineering expertise", "Engineer", "EDU", "average", False),
        ],
    ),
    (
        "political",
        [
            ("Use diplomacy to resolve the situation", "Diplomat", "SOC", "average", False),
            ("Leverage administrative connections", "Admin", "SOC", "difficult", False),
            ("Research the political background", "Research", "EDU", "average", False),
        ],
    ),
    (
        "plot twist",
        [
            ("Adapt quickly to the new situation", "Leadership", "SOC", "difficult", False),
            ("Investigate the unexpected development", "Investigate", "INT", "average", False),
            ("Negotiate from a position of strength", "Persuade", "SOC", "average", False),
        ],
    ),
]


#: Keyword-based free-text classifier (v0.3b template fallback, AE5).
#: Maps common verbs/actions to skill + characteristic + difficulty.
_FREETEXT_KEYWORD_MAP: list[tuple[str, str, str, str, str]] = [
    ("bribe", "Broker", "SOC", "average", "Bribe the target"),
    ("pay off", "Broker", "SOC", "average", "Bribe the target"),
    ("fight", "Gun Combat", "DEX", "average", "Fight the target"),
    ("attack", "Gun Combat", "DEX", "average", "Attack the target"),
    ("shoot", "Gun Combat", "DEX", "average", "Shoot at the target"),
    ("sneak", "Stealth", "DEX", "difficult", "Sneak past"),
    ("hide", "Stealth", "DEX", "average", "Hide from view"),
    ("hack", "Computers", "INT", "difficult", "Hack the system"),
    ("repair", "Mechanic", "EDU", "average", "Repair the system"),
    ("persuade", "Persuade", "SOC", "average", "Persuade the target"),
    ("convince", "Persuade", "SOC", "average", "Convince the target"),
    ("lie", "Deception", "SOC", "difficult", "Deceive the target"),
    ("deceive", "Deception", "SOC", "difficult", "Deceive the target"),
    ("negotiate", "Broker", "INT", "average", "Negotiate a deal"),
    ("intimidate", "Streetwise", "SOC", "difficult", "Intimidate the target"),
    ("threaten", "Streetwise", "SOC", "difficult", "Threaten the target"),
    ("investigate", "Investigate", "INT", "average", "Investigate the situation"),
    ("search", "Investigate", "INT", "average", "Search the area"),
    ("scan", "Sensors", "EDU", "average", "Scan with sensors"),
    ("pilot", "Pilot", "DEX", "average", "Pilot the vehicle"),
    ("fly", "Pilot", "DEX", "average", "Fly the vehicle"),
    ("drive", "Drive", "DEX", "average", "Drive the vehicle"),
    ("heal", "Medic", "EDU", "average", "Provide medical aid"),
    ("medicine", "Medic", "EDU", "average", "Provide medical aid"),
    ("climb", "Athletics", "STR", "difficult", "Climb the obstacle"),
    ("run", "Athletics", "END", "average", "Run to safety"),
    ("escape", "Athletics", "END", "difficult", "Escape the situation"),
    ("flee", "Athletics", "END", "average", "Flee from danger"),
    ("research", "Research", "EDU", "average", "Research the topic"),
    ("inspect", "Investigate", "INT", "average", "Inspect the target"),
]


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
    # Option generation (R12, R13).
    # ------------------------------------------------------------------

    def generate_options(self, scaffold: SceneScaffold) -> list[SceneOption]:
        """Derive 2-4 structured options from the scaffold + theme-pack data.

        Each option pre-maps to an engine-known check (skill + difficulty)
        before display to the player. The player always has the additional
        free-text slot (handled by the TUI, not this method).
        """
        focus_lower = scaffold.focus.lower()
        templates = self._match_focus_options(focus_lower)

        options: list[SceneOption] = []
        for label, skill, char, diff, life_threatening in templates:
            options.append(
                SceneOption(
                    label=label,
                    skill=skill,
                    characteristic=char,
                    difficulty=diff,
                    description=f"{skill} check ({diff}) using {char}",
                    life_threatening=life_threatening,
                )
            )

        # Ensure at least 2 options.
        if len(options) < 2:
            options.append(
                SceneOption(
                    label="Take direct action",
                    skill="Gun Combat",
                    characteristic="DEX",
                    difficulty="average",
                    description="Direct confrontation",
                    life_threatening=True,
                )
            )

        return options[:4]  # Cap at 4.

    # ------------------------------------------------------------------
    # Check resolution (R13, R15).
    # ------------------------------------------------------------------

    def resolve_scene(
        self,
        scaffold: SceneScaffold,
        option: SceneOption,
    ) -> SceneCheckResult:
        """Resolve a scene check through the command funnel.

        Rolls 2D6 on the combat stream, applies the active resolution
        profile, and returns the outcome. The check is recorded in the
        event log via SceneCheckCommand.
        """
        cmd = SceneCheckCommand(
            skill=option.skill,
            characteristic=option.characteristic,
            difficulty=option.difficulty,
            profile=self.engine.state.campaign.resolution_profile,
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
        )

    # ------------------------------------------------------------------
    # Free-text classification (R14, AE5).
    # ------------------------------------------------------------------

    def classify_freetext(
        self, text: str, scaffold: SceneScaffold
    ) -> FreeTextClassification | None:
        """Classify free-text input into an engine-known check (AE5).

        Uses keyword matching as the template fallback. The LLM adapter
        can override this with a smarter classification.

        Returns ``None`` if no interpretation could be derived.
        """
        text_lower = text.lower().strip()

        for keyword, skill, char, diff, label in _FREETEXT_KEYWORD_MAP:
            if keyword in text_lower:
                option = SceneOption(
                    label=f"[Free-text] {label}",
                    skill=skill,
                    characteristic=char,
                    difficulty=diff,
                    description=f"Interpreted from: '{text}'",
                )
                return FreeTextClassification(
                    original_text=text,
                    interpreted_check=option,
                )

        return None

    # ------------------------------------------------------------------
    # Consequence application (R15).
    # ------------------------------------------------------------------

    def apply_consequences(
        self,
        check_result: SceneCheckResult,
        scaffold: SceneScaffold,
    ) -> list[str]:
        """Apply consequences based on the check outcome via the funnel.

        Misses and weak hits may produce injuries or complications.
        Strong hits may register advantages as narrative facts.
        Returns a list of human-readable consequence descriptions.
        """
        consequences: list[str] = []
        quality = check_result.quality

        if quality == OutcomeQuality.MISS.value:
            # Failure: possible injury on severe misses.
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
            else:
                consequences.append("The attempt failed with minor consequences.")

        elif quality == OutcomeQuality.WEAK_HIT.value:
            # Weak hit: success with a cost.
            consequences.append("Success with a complication.")

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
        self.engine.apply(
            _LogNarrationCommand(
                text=self._narrate_result(check_result, scaffold)
            )
        )

        return consequences

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
    def _match_focus_options(
        focus_lower: str,
    ) -> list[tuple[str, str, str, str]]:
        """Match a focus string against the option templates."""
        for keyword, templates in _FOCUS_OPTION_MAP:
            if keyword in focus_lower:
                return templates
        # Default to social options if no match.
        return _FOCUS_OPTION_MAP[1][1]

    @staticmethod
    def _narrate_result(
        check_result: SceneCheckResult, scaffold: SceneScaffold
    ) -> str:
        """Template narration for a scene check result."""
        quality = check_result.quality
        skill = check_result.skill
        if quality == OutcomeQuality.STRONG_HIT.value:
            return (
                f"Your {skill} check succeeds brilliantly in the "
                f"{scaffold.focus} scene."
            )
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
            description=f"Narration logged",
            changes={"text": self.text},
        )
