"""Headless adventure flow controller (U8).

Wraps the scene engine, mission manager, and death strategies into a
UI-agnostic controller that emits view models. Mirrors the TUI's
adventure screen semantics — all mutations stay inside ``Engine.apply``.

The controller never caches GameState — it reads through ``engine.state``
every call so ``swap_state`` (rewind) is always reflected.

Because the adapter's classify surface is synchronous, controller entry
points that call it are documented as blocking and must run in a
threadpool at the web layer (KTD-9).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.engine.commands import Engine
from src.engine.death import DefeatContext, get_death_strategy
from src.engine.mission import Mission, MissionEnding, MissionEngine, MissionHook
from src.engine.odds import compute_check_odds, format_odds_line
from src.engine.scene import (
    SceneCheckResult,
    SceneEngine,
    SceneOption,
    SceneResult,
    SetPendingFreetextCommand,
)
from src.engine.skills import skill_display_name
from src.engine.state import GameState, Injury
from src.game.views import ChoiceOption
from src.rulesets.base import OutcomeQuality
from src.themepacks.base import LoadedThemePack

logger = logging.getLogger(__name__)


@dataclass
class AdventureView:
    """View model for the adventure screen (U8).

    Encapsulates the current adventure state: hook, scene options with
    odds, receipts, and defeat interstitials. Shells render this without
    inspecting GameState directly.
    """

    phase: str = "hook_offered"
    prompt: str = ""
    choices: list[ChoiceOption] = field(default_factory=list)
    receipts: list[str] = field(default_factory=list)
    narration: str = ""
    scaffold_text: str = ""
    scene_options: list[SceneOption] = field(default_factory=list)
    odds_lines: list[str] = field(default_factory=list)
    defeat: str | None = None
    mission_ending: str | None = None


class AdventureController:
    """Headless adventure controller (U8).

    Owns the adventure flow: hooks → scenes → checks → consequences →
    missions → defeat. All mutations route through ``Engine.apply``.

    The controller holds transient state (current hook, current scene,
    current mission) as instance attributes. These are rebuilt from
    GameState on resume via ``_reconstruct_if_needed``.
    """

    def __init__(self, engine: Engine, pack: LoadedThemePack) -> None:
        self._engine = engine
        self._pack = pack
        self._mission_engine = MissionEngine(engine, pack)
        self._scene_engine = SceneEngine(engine, pack)

        # Transient state — rebuilt from GameState on resume.
        self._current_hook: MissionHook | None = None
        self._current_scene: SceneResult | None = None
        self._current_mission: Mission | None = None
        self._pending_freetext: SceneOption | None = None
        self._freetext_draft: str | None = None

        self._reconstruct_if_needed()

    @property
    def engine(self) -> Engine:
        return self._engine

    @property
    def state(self) -> GameState:
        return self._engine.state

    @property
    def pack(self) -> LoadedThemePack:
        return self._pack

    # ------------------------------------------------------------------
    # Reconstruction (AE8-safe resume).
    # ------------------------------------------------------------------

    def _reconstruct_if_needed(self) -> None:
        """Rebuild transient state from GameState on construction/resume."""
        state = self._engine.state
        if state.active_mission is not None:
            self._current_mission = Mission.from_dict(state.active_mission)

    # ------------------------------------------------------------------
    # Phase determination.
    # ------------------------------------------------------------------

    def determine_phase(self) -> str:
        """Determine the current adventure phase from engine state."""
        state = self._engine.state

        # Dead character → game_over (for web routing; memorial in U12).
        if not state.character.alive:
            return "game_over"

        # Pending free-text interpretation (U3).
        if state.pending_freetext is not None:
            return "freetext_pending"

        # No active mission: offer a hook.
        if state.active_mission is None:
            return "hook_offered"

        return "scene_active"

    # ------------------------------------------------------------------
    # View assembly.
    # ------------------------------------------------------------------

    def get_view(self) -> AdventureView:
        """Build an AdventureView for the current phase."""
        phase = self.determine_phase()

        if phase == "hook_offered":
            return self._build_hook_view()
        if phase == "scene_active":
            return self._build_scene_view()
        if phase == "freetext_pending":
            return self._build_freetext_pending_view()
        if phase == "game_over":
            return AdventureView(phase="game_over", prompt="The character is dead.")

        return AdventureView(phase=phase)

    def _build_hook_view(self) -> AdventureView:
        """Build the hook-offered view."""
        if self._current_hook is None:
            self._current_hook = self._mission_engine.generate_hook()

        hook = self._current_hook
        return AdventureView(
            phase="hook_offered",
            prompt=f"Patron: {hook.patron}\nObjective: {hook.objective}\nComplication: {hook.complication}\nReward: {hook.reward}",
            choices=[
                ChoiceOption(label="Accept Mission", option_id="accept_mission"),
                ChoiceOption(label="Refuse — Look for Another Job", option_id="refuse_mission"),
            ],
        )

    def _build_scene_view(self) -> AdventureView:
        """Build the scene-active view with options and pre-commit odds."""
        if self._current_scene is None:
            self._current_scene = self._scene_engine.run_scene()

        scaffold = self._current_scene.scaffold
        state = self._engine.state
        profile = state.campaign.resolution_profile

        odds_lines = []
        choices = []
        for i, opt in enumerate(self._current_scene.options):
            odds = compute_check_odds(
                state.character,
                skill=opt.skill,
                characteristic=opt.characteristic,
                difficulty=opt.difficulty,
                profile=profile,
            )
            odds_line = format_odds_line(odds)
            odds_lines.append(odds_line)
            choices.append(
                ChoiceOption(
                    label=f"{i + 1}. {opt.label} ({skill_display_name(self._pack, opt.skill)}, {opt.difficulty})",
                    option_id=f"option:{i}",
                    description=odds_line,
                )
            )

        # Mission gate: ending push only after min_scenes.
        mission = state.active_mission or {}
        scenes_done = int(mission.get("scenes_completed", 0))
        min_scenes = int(mission.get("min_scenes", 3))
        if scenes_done >= min_scenes:
            choices.append(ChoiceOption(label="Push for the ending", option_id="push_for_ending"))
        choices.append(ChoiceOption(label="Abandon the mission", option_id="abandon_mission"))

        scaffold_text = f"Focus: {scaffold.focus} — {scaffold.focus_description}\nSituation: {scaffold.situation}"
        if scaffold.npc_hint:
            scaffold_text += f"\nNPC: {scaffold.npc_hint}"

        return AdventureView(
            phase="scene_active",
            prompt="Choose your action:",
            choices=choices,
            scaffold_text=scaffold_text,
            scene_options=self._current_scene.options,
            odds_lines=odds_lines,
        )

    def _build_freetext_pending_view(self) -> AdventureView:
        """Build the freetext-pending view (U3 restore)."""
        payload = self._engine.state.pending_freetext
        if payload is None:
            return self._build_scene_view()

        check_data = payload["check"]
        check = SceneOption(
            label=check_data["label"],
            skill=check_data["skill"],
            characteristic=check_data["characteristic"],
            difficulty=check_data["difficulty"],
            description=check_data.get("description", ""),
            life_threatening=check_data.get("life_threatening", False),
        )
        self._pending_freetext = check
        self._freetext_draft = payload["text"]

        return AdventureView(
            phase="freetext_pending",
            prompt=f"Interpreted as: {check.label} ({skill_display_name(self._pack, check.skill)}, {check.difficulty})",
            choices=[
                ChoiceOption(label="Accept — Proceed with this check", option_id="accept_freetext"),
                ChoiceOption(
                    label="Reject — Rephrase or pick an option", option_id="reject_freetext"
                ),
            ],
        )

    # ------------------------------------------------------------------
    # Choice application.
    # ------------------------------------------------------------------

    def apply_choice(self, option_id: str) -> AdventureView:
        """Apply a player's choice and return the updated view."""
        if option_id == "accept_mission":
            return self._do_accept_mission()
        if option_id == "refuse_mission":
            return self._do_refuse_mission()
        if option_id == "push_for_ending":
            return self._do_push_for_ending()
        if option_id == "abandon_mission":
            return self._do_abandon_mission()
        if option_id == "accept_freetext":
            return self._do_accept_freetext()
        if option_id == "reject_freetext":
            return self._do_reject_freetext()
        if option_id.startswith("option:"):
            idx = int(option_id.split(":", 1)[1])
            return self._do_resolve_option(idx)

        # Unknown — return current view.
        return self.get_view()

    def _do_accept_mission(self) -> AdventureView:
        # Ensure a hook exists (get_view generates it lazily; apply_choice
        # may be called without a prior get_view).
        if self._current_hook is None:
            self._current_hook = self._mission_engine.generate_hook()
        self._current_mission = self._mission_engine.accept_mission(self._current_hook)
        self._current_hook = None
        self._current_scene = None
        return self.get_view()

    def _do_refuse_mission(self) -> AdventureView:
        self._current_hook = self._mission_engine.refuse_mission()
        return self.get_view()

    def _do_resolve_option(self, option_index: int) -> AdventureView:
        # Generate a fresh scene if the previous one was consumed.
        if self._current_scene is None:
            self._current_scene = self._scene_engine.run_scene()
        option = self._current_scene.options[option_index]
        scaffold = self._current_scene.scaffold
        check_result = self._scene_engine.resolve_scene(scaffold, option)

        receipts = [self._mechanics_line(check_result)]
        consequences = self._scene_engine.apply_consequences(check_result, scaffold)
        receipts.extend(f"→ {c}" for c in consequences)

        # Defeat check.
        defeat = self._check_defeat(check_result, option, consequences)
        if defeat is not None:
            return defeat

        self._current_scene = None
        return AdventureView(
            phase="scene_active",
            prompt="Choose your action:",
            receipts=receipts,
        )

    def _do_push_for_ending(self) -> AdventureView:
        if self._current_scene is None:
            self._current_scene = self._scene_engine.run_scene()
        option = self._current_scene.options[0]
        scaffold = self._current_scene.scaffold

        check_result = self._scene_engine.resolve_scene(scaffold, option)
        receipts = [self._mechanics_line(check_result)]

        if check_result.quality in (OutcomeQuality.STRONG_HIT.value, OutcomeQuality.WEAK_HIT.value):
            ending = MissionEnding.SUCCESS
        else:
            ending = MissionEnding.FAILURE

        consequences: list[str] = []
        mission = self._current_mission
        if ending == MissionEnding.SUCCESS and mission.success_text:
            consequences.append(mission.success_text)
        elif mission.failure_text:
            consequences.append(mission.failure_text)

        scene_consequences = self._scene_engine.apply_consequences(check_result, scaffold)
        consequences.extend(scene_consequences)

        # Defeat check.
        defeat = self._check_defeat(check_result, option, scene_consequences)
        if defeat is not None:
            return defeat

        self._mission_engine.resolve_mission(mission, ending, consequences)

        receipts.append(f"Mission resolved: {ending.value}")
        receipts.extend(f"→ {c}" for c in consequences)

        self._current_scene = None
        self._current_hook = None

        return AdventureView(
            phase="hook_offered",
            prompt="Mission resolved. A new opportunity awaits.",
            receipts=receipts,
            mission_ending=ending.value,
        )

    def _do_abandon_mission(self) -> AdventureView:
        consequences: list[str] = []
        mission = self._current_mission
        if mission.abandonment_text:
            consequences.append(mission.abandonment_text)

        self._mission_engine.resolve_mission(mission, MissionEnding.ABANDONMENT, consequences)

        self._current_scene = None
        self._current_hook = None

        return AdventureView(
            phase="hook_offered",
            prompt="Mission abandoned. Looking for the next opportunity...",
            receipts=[f"→ {c}" for c in consequences],
            mission_ending=MissionEnding.ABANDONMENT.value,
        )

    # ------------------------------------------------------------------
    # Free-text classification (blocking — KTD-9 threadpool at web layer).
    # ------------------------------------------------------------------

    def classify_freetext(self, text: str) -> AdventureView:
        """Classify free-text input (U8, blocking — KTD-9).

        Routes through the SceneEngine's classify_freetext with an optional
        LLM classifier. On success, stores the pending state via
        SetPendingFreetextCommand (U3) and returns the interpretation view.
        On failure, returns the scene view with an error message.
        """
        if self._current_scene is None:
            return self.get_view()

        scaffold = self._current_scene.scaffold
        classification = self._scene_engine.classify_freetext(text, scaffold)

        if classification is None:
            return AdventureView(
                phase="scene_active",
                prompt=f"Could not interpret '{text}'. Try rephrasing or select an option.",
                receipts=[],
            )

        check = classification.interpreted_check
        # U3: persist the pending state.
        payload = {
            "text": text,
            "check": {
                "label": check.label,
                "skill": check.skill,
                "characteristic": check.characteristic,
                "difficulty": check.difficulty,
                "description": check.description,
                "life_threatening": check.life_threatening,
            },
            "scaffold": {
                "focus": scaffold.focus,
                "focus_description": scaffold.focus_description,
                "situation": scaffold.situation,
                "npc_hint": scaffold.npc_hint or "",
            },
            "options": [
                {
                    "label": opt.label,
                    "skill": opt.skill,
                    "characteristic": opt.characteristic,
                    "difficulty": opt.difficulty,
                    "description": opt.description,
                    "life_threatening": opt.life_threatening,
                }
                for opt in self._current_scene.options
            ],
        }
        self._engine.apply(SetPendingFreetextCommand(payload=payload))

        self._pending_freetext = check
        self._freetext_draft = text

        return AdventureView(
            phase="freetext_pending",
            prompt=f"Interpreted as: {check.label} ({skill_display_name(self._pack, check.skill)}, {check.difficulty})",
            choices=[
                ChoiceOption(label="Accept — Proceed with this check", option_id="accept_freetext"),
                ChoiceOption(
                    label="Reject — Rephrase or pick an option", option_id="reject_freetext"
                ),
            ],
        )

    def _do_accept_freetext(self) -> AdventureView:
        """Accept the pending free-text check and resolve it."""
        option = self._pending_freetext
        if option is None:
            return self.get_view()

        scaffold = self._current_scene.scaffold if self._current_scene else None
        if scaffold is None:
            return self.get_view()

        check_result = self._scene_engine.resolve_scene(
            scaffold, option, clear_pending_freetext=True
        )
        receipts = [self._mechanics_line(check_result)]
        consequences = self._scene_engine.apply_consequences(check_result, scaffold)
        receipts.extend(f"→ {c}" for c in consequences)

        self._pending_freetext = None
        self._freetext_draft = None

        # Defeat check.
        defeat = self._check_defeat(check_result, option, consequences)
        if defeat is not None:
            return defeat

        self._current_scene = None
        return AdventureView(
            phase="scene_active",
            prompt="Choose your action:",
            receipts=receipts,
        )

    def _do_reject_freetext(self) -> AdventureView:
        """Reject the pending free-text check."""
        self._engine.apply(SetPendingFreetextCommand(payload=None))
        self._pending_freetext = None
        self._freetext_draft = None
        return self.get_view()

    # ------------------------------------------------------------------
    # Defeat handling.
    # ------------------------------------------------------------------

    def _check_defeat(
        self,
        check_result: SceneCheckResult,
        option: SceneOption,
        consequences: list[str],
    ) -> AdventureView | None:
        """Check for catastrophic outcomes and invoke the death strategy.

        Returns an AdventureView with the defeat interstitial if defeat
        was triggered; None if the adventure continues.
        """
        is_defeat = False
        reason = ""

        # MISS on a life-threatening check.
        if check_result.quality == OutcomeQuality.MISS.value and getattr(
            option, "life_threatening", False
        ):
            is_defeat = True
            reason = f"a failed life-threatening {skill_display_name(self._pack, check_result.skill)} check"

        # Severe injury.
        if not is_defeat:
            state = self._engine.state
            has_severe = any(
                isinstance(e, Injury) and e.severity == "severe" for e in state.entities
            )
            if (
                has_severe
                and check_result.quality == OutcomeQuality.MISS.value
                and any("severe" in c.lower() or "serious" in c.lower() for c in consequences)
            ):
                is_defeat = True
                reason = f"accumulated severe injuries during {skill_display_name(self._pack, check_result.skill)}"

        if not is_defeat:
            return None

        return self._handle_defeat(reason)

    def _handle_defeat(self, reason: str) -> AdventureView:
        """Invoke the death strategy and return the defeat view."""
        from src.engine.checkpoint import CheckpointManager

        state = self._engine.state
        death_mode = state.campaign.death_mode

        checkpoint_mgr = CheckpointManager()
        strategy = get_death_strategy(
            death_mode,
            checkpoint=checkpoint_mgr,
            engine=self._engine,
        )
        context = DefeatContext(
            reason=reason,
            scene_label=getattr(
                self._current_scene.scaffold if self._current_scene else None,
                "focus",
                "unknown",
            ),
        )
        result = strategy.handle_defeat(state, context)

        self._current_scene = None

        if result.restored_state is not None:
            self._engine.swap_state(result.restored_state)

        if not result.play_continues:
            return AdventureView(
                phase="game_over",
                prompt=f"DEFEAT ({death_mode}): {result.message}",
                defeat=death_mode,
            )

        return AdventureView(
            phase="scene_active",
            prompt=f"DEFEAT ({death_mode}): {result.message}. Play continues.",
            defeat=death_mode,
        )

    # ------------------------------------------------------------------
    # Helpers.
    # ------------------------------------------------------------------

    def _mechanics_line(self, result: SceneCheckResult) -> str:
        """Build the inline mechanics line from a check result."""
        dice = ", ".join(str(d) for d in result.dice)
        raw = result.raw_roll
        total = raw + result.total_dm
        profile = self._engine.state.campaign.resolution_profile
        if profile == "classic":
            tier = "Success" if result.success else "Failure"
        else:
            tier = {
                "strong_hit": "Strong hit",
                "weak_hit": "Weak hit",
                "miss": "Miss",
            }[result.quality]
        trained_note = "" if result.trained else " (untrained)"
        return (
            f"2D6 [{dice}] = {raw}  DM {result.total_dm:+d} → {total} "
            f"vs 8 — {tier} (Effect {result.effect:+d}){trained_note}"
        )
