"""Headless adventure flow controller (U8).

Wraps the scene engine, mission manager, and death strategies into a
UI-agnostic controller that emits view models. Mirrors the TUI's
adventure screen semantics — all mutations stay inside ``Engine.apply``.

The controller never caches GameState — it reads through ``engine.state``
every call so ``swap_state`` (rewind) is always reflected.

Resume: ``_reconstruct_if_needed`` rebuilds the in-memory ``_current_hook``
and ``_current_mission`` from ``state.pending_hook`` and
``state.active_mission``. Scene options are *not* persisted across save/load
(mid-decision saves inside a scene regenerate the scene on resume, matching
the TUI's behavior); the hook and free-text interpretation paths are
persisted because they are the prominent decision points and regenerating
either would silently advance the oracle stream.

Because the adapter's classify surface is synchronous, controller entry
points that call it are documented as blocking and must run in a
threadpool at the web layer (KTD-9).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.engine.checkpoint import CheckpointManager
from src.engine.commands import Engine
from src.engine.death import DefeatContext, get_death_strategy
from src.engine.mission import (
    Mission,
    MissionEnding,
    MissionEngine,
    MissionHook,
    SetMissionStateCommand,
    SetPendingHookCommand,
)
from src.engine.odds import compute_check_odds, format_odds_line
from src.engine.scene import (
    SceneCheckResult,
    SceneEngine,
    SceneOption,
    SceneResult,
    SceneScaffold,
    SetPendingFreetextCommand,
)
from src.engine.skills import skill_display_name
from src.engine.state import GameState, Injury
from src.game.change_lines import ChangeLine
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
    change_lines: list[ChangeLine] = field(default_factory=list)


class AdventureController:
    """Headless adventure controller (U8).

    Owns the adventure flow: hooks → scenes → checks → consequences →
    missions → defeat. All mutations route through ``Engine.apply``.

    The controller holds transient state (current hook, current scene,
    current mission) as instance attributes. The hook and mission are
    rebuilt from ``GameState`` on resume via ``_reconstruct_if_needed``;
    the current scene is intentionally not persisted (mid-scene saves
    regenerate, matching the TUI).

    The controller owns a long-lived :class:`CheckpointManager` so the
    scene-start snapshot survives across the adventure loop. Shells that
    persist saves to disk are responsible for calling
    ``checkpoint_mgr.save_snapshot`` / ``load_snapshot`` alongside the
    main save (mirroring the TUI's app-level save).
    """

    def __init__(
        self,
        engine: Engine,
        pack: LoadedThemePack,
        *,
        checkpoint_mgr: CheckpointManager | None = None,
    ) -> None:
        self._engine = engine
        self._pack = pack
        self._mission_engine = MissionEngine(engine, pack)
        self._scene_engine = SceneEngine(engine, pack)
        # When a checkpoint_mgr is injected (e.g. from a GameSession), the
        # controller shares the session's manager so scene-start snapshots
        # persist to disk through session.save(). Otherwise the controller
        # owns its own (standalone / TUI usage).
        self._checkpoint_mgr = checkpoint_mgr or CheckpointManager()

        # Transient state — rebuilt from GameState on resume.
        self._current_hook: MissionHook | None = None
        self._current_scene: SceneResult | None = None
        self._current_mission: Mission | None = None
        self._pending_freetext: SceneOption | None = None
        self._freetext_draft: str | None = None
        #: Event-log index before the current action — used to derive
        #: change-lines for just the events that this action produced (U14).
        self._action_start_seq: int = 0

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

    @property
    def checkpoint_mgr(self) -> CheckpointManager:
        """The controller's long-lived checkpoint manager (for shells)."""
        return self._checkpoint_mgr

    @property
    def action_start_seq(self) -> int:
        """Event-log index before the current action (U16, for pill scoping)."""
        return self._action_start_seq

    # ------------------------------------------------------------------
    # Change-lines helper (U14).
    # ------------------------------------------------------------------

    def _collect_change_lines(self) -> list[ChangeLine]:
        """Derive change-lines from events produced during the current action.

        Called after an action's mutations to populate the view's
        ``change_lines`` field. Reads events with ``seq >=
        _action_start_seq`` — the events this action appended.
        """
        from src.game.change_lines import derive_recent_change_lines

        return derive_recent_change_lines(
            self._engine.state.events,
            since_seq=self._action_start_seq - 1,
        )

    # ------------------------------------------------------------------
    # Reconstruction (AE8-safe resume).
    # ------------------------------------------------------------------

    def _reconstruct_if_needed(self) -> None:
        """Rebuild transient state from GameState on construction/resume.

        Restores ``_current_mission`` from ``state.active_mission``,
        ``_current_hook`` from ``state.pending_hook``, and the pending
        free-text scene from ``state.pending_freetext`` — all so resume
        doesn't regenerate either (which would consume oracle rolls) and
        so ``_do_accept_freetext`` can resolve on a freshly constructed
        controller (U9 web request lifecycle).
        """
        state = self._engine.state
        if state.active_mission is not None:
            self._current_mission = Mission.from_dict(state.active_mission)
        if state.pending_hook is not None:
            self._current_hook = _hook_from_dict(state.pending_hook)
        if state.pending_freetext is not None:
            self._restore_pending_freetext(state.pending_freetext)

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
        """Build an AdventureView for the current phase.

        .. note::

            This method has side effects on first call in a phase: it lazily
            generates the hook or scene via ``Engine.apply`` (oracle rolls).
            ``_build_hook_view`` persists the hook; ``_build_scene_view``
            runs the scene engine. Subsequent calls in the same phase are
            pure reads (the transient state is cached). Treat this as a
            refresh, not a pure query.
        """
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
        """Build the hook-offered view, persisting the hook for resume."""
        if self._current_hook is None:
            self._current_hook = self._mission_engine.generate_hook()
            # Persist so resume restores the hook without regenerating
            # (regeneration would consume oracle rolls).
            self._engine.apply(SetPendingHookCommand(payload=_hook_to_dict(self._current_hook)))

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
        self._ensure_current_scene()

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
        # U14: dimmed-not-hidden — the option always shows, but is greyed
        # out with the requirement until the gate is met.
        mission = state.active_mission or {}
        scenes_done = int(mission.get("scenes_completed", 0))
        min_scenes = int(mission.get("min_scenes", 3))
        if scenes_done >= min_scenes:
            choices.append(ChoiceOption(label="Push for the ending", option_id="push_for_ending"))
        else:
            remaining = min_scenes - scenes_done
            choices.append(
                ChoiceOption(
                    label="Push for the ending",
                    option_id="push_for_ending",
                    dimmed=True,
                    requirement=f"Requires {remaining} more scene{'s' if remaining != 1 else ''}",
                )
            )
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
        """Build the freetext-pending view (U3 restore).

        ``_pending_freetext`` and ``_current_scene`` are already restored
        from ``state.pending_freetext`` by ``_reconstruct_if_needed`` (or
        set in-memory by ``classify_freetext``).  This method just builds
        the view model.
        """
        check = self._pending_freetext
        if check is None:
            return self._build_scene_view()

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
        # U14: snapshot event count to derive change-lines from this action.
        self._action_start_seq = len(self._engine.state.events)
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
        # The hook is no longer pending — clear it from canonical state.
        self._engine.apply(SetPendingHookCommand(payload=None))
        return self.get_view()

    def _do_refuse_mission(self) -> AdventureView:
        self._current_hook = self._mission_engine.refuse_mission()
        # Persist the newly generated hook so resume doesn't re-roll oracle.
        self._engine.apply(SetPendingHookCommand(payload=_hook_to_dict(self._current_hook)))
        return self.get_view()

    def _do_resolve_option(self, option_index: int) -> AdventureView:
        self._ensure_current_scene()
        if not 0 <= option_index < len(self._current_scene.options):
            logger.warning(
                "option_index %d out of range (0-%d)",
                option_index,
                len(self._current_scene.options) - 1,
            )
            return self.get_view()
        option = self._current_scene.options[option_index]
        scaffold = self._current_scene.scaffold
        check_result = self._scene_engine.resolve_scene(scaffold, option)

        receipts = [self._mechanics_line(check_result)]
        consequences = self._scene_engine.apply_consequences(check_result, scaffold)
        receipts.extend(f"→ {c}" for c in consequences)

        # Advance the mission's progress gate before the defeat check: the
        # scene happened regardless of outcome. In checkpoint mode a defeat
        # rewinds state (undoing this increment); in narrative mode play
        # continues and the scene counts; in ironman mode the character is
        # dead and the count is moot.
        self._record_scene_progress()

        # Defeat check.
        defeat = self._check_defeat(check_result, option, consequences)
        if defeat is not None:
            return defeat

        self._current_scene = None
        return AdventureView(
            phase="scene_active",
            prompt="Choose your action:",
            receipts=receipts,
            change_lines=self._collect_change_lines(),
        )

    def _do_push_for_ending(self) -> AdventureView:
        if self._current_mission is None:
            # Defensive: push_for_ending should only be offered with an active
            # mission. Return the current view rather than crashing.
            logger.warning("push_for_ending called with no active mission")
            return self.get_view()
        self._ensure_current_scene()
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
        # The hook from the resolved mission is gone; clear canonical state.
        self._engine.apply(SetPendingHookCommand(payload=None))

        return AdventureView(
            phase="hook_offered",
            prompt="Mission resolved. A new opportunity awaits.",
            receipts=receipts,
            mission_ending=ending.value,
            change_lines=self._collect_change_lines(),
        )

    def _do_abandon_mission(self) -> AdventureView:
        consequences: list[str] = []
        mission = self._current_mission
        if mission is not None and mission.abandonment_text:
            consequences.append(mission.abandonment_text)
        if mission is None:
            logger.warning("abandon_mission called with no active mission")
            return self.get_view()

        self._mission_engine.resolve_mission(mission, MissionEnding.ABANDONMENT, consequences)

        self._current_scene = None
        self._current_hook = None
        self._engine.apply(SetPendingHookCommand(payload=None))

        return AdventureView(
            phase="hook_offered",
            prompt="Mission abandoned. Looking for the next opportunity...",
            receipts=[f"→ {c}" for c in consequences],
            mission_ending=MissionEnding.ABANDONMENT.value,
            change_lines=self._collect_change_lines(),
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
        self._ensure_current_scene()

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

        # Advance the mission's progress gate before the defeat check (see
        # _do_resolve_option for rationale).
        self._record_scene_progress()

        # Defeat check.
        defeat = self._check_defeat(check_result, option, consequences)
        if defeat is not None:
            return defeat

        self._current_scene = None
        return AdventureView(
            phase="scene_active",
            prompt="Choose your action:",
            receipts=receipts,
            change_lines=self._collect_change_lines(),
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
        state = self._engine.state
        death_mode = state.campaign.death_mode

        strategy = get_death_strategy(
            death_mode,
            checkpoint=self._checkpoint_mgr,
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
            # Re-sync all transient state from the restored canonical state.
            # Without this, ``_current_mission`` is stale (pointing at the
            # pre-rewind mission with wrong ``scenes_completed``), which
            # would crash ``_do_push_for_ending`` / ``_do_abandon_mission``
            # with AttributeError on ``mission.success_text`` etc.
            self._reconstruct_if_needed()

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
            }.get(result.quality, result.quality)
        trained_note = "" if result.trained else " (untrained)"
        return (
            f"2D6 [{dice}] = {raw}  DM {result.total_dm:+d} → {total} "
            f"vs 8 — {tier} (Effect {result.effect:+d}){trained_note}"
        )

    def _ensure_current_scene(self) -> None:
        """Generate a fresh scene if the previous one was consumed.

        Takes a checkpoint snapshot at scene start when the campaign uses
        checkpoint death mode (AE3). Mirrors the TUI's scene-start behavior
        so ``restore()`` has a snapshot to rewind to on defeat.
        """
        if self._current_scene is not None:
            return
        state = self._engine.state
        if state.campaign.death_mode == "checkpoint":
            self._checkpoint_mgr.take_snapshot(state)
        self._current_scene = self._scene_engine.run_scene()

    def _restore_pending_freetext(self, payload: dict) -> None:
        """Reconstruct ``_current_scene`` and ``_pending_freetext`` from a
        serialized ``state.pending_freetext`` payload.

        Mirrors the TUI's ``_restore_pending_freetext`` (TUI-6).  Called
        from ``_reconstruct_if_needed`` on construction/resume so that
        ``_do_accept_freetext`` can resolve the check on a freshly loaded
        controller (U9 web request lifecycle).
        """
        check_data = payload["check"]
        self._pending_freetext = SceneOption(
            label=check_data["label"],
            skill=check_data["skill"],
            characteristic=check_data["characteristic"],
            difficulty=check_data["difficulty"],
            description=check_data.get("description", ""),
            life_threatening=check_data.get("life_threatening", False),
        )
        self._freetext_draft = payload["text"]

        scaffold_data = payload["scaffold"]
        scaffold = SceneScaffold(
            focus=scaffold_data["focus"],
            focus_description=scaffold_data["focus_description"],
            situation=scaffold_data["situation"],
            npc_hint=scaffold_data.get("npc_hint") or None,
        )
        options = [
            SceneOption(
                label=o["label"],
                skill=o["skill"],
                characteristic=o["characteristic"],
                difficulty=o["difficulty"],
                description=o.get("description", ""),
                life_threatening=o.get("life_threatening", False),
            )
            for o in payload.get("options", [])
        ]
        self._current_scene = SceneResult(scaffold=scaffold, options=options)

    def _record_scene_progress(self) -> None:
        """Increment ``scenes_completed`` on the active mission (Task 19).

        Routing the updated mission dict through ``SetMissionStateCommand``
        keeps the progress gate (``push_for_ending`` availability and
        ``ResolveMissionCommand.validate``) in sync with canonical state.
        Without this, the gate never opens.
        """
        mission = self._current_mission
        if mission is None:
            return
        mission.scenes_played += 1
        mission.scenes_completed = mission.scenes_played
        self._engine.apply(SetMissionStateCommand(mission_data=mission.to_dict()))


# ----------------------------------------------------------------------
# Hook serialization helpers (U8 — pending_hook persistence).
# ----------------------------------------------------------------------


def _hook_to_dict(hook: MissionHook) -> dict:
    """Serialize a :class:`MissionHook` for ``state.pending_hook``."""
    return {
        "patron": hook.patron,
        "objective": hook.objective,
        "complication": hook.complication,
        "reward": hook.reward,
        "description": hook.description,
    }


def _hook_from_dict(data: dict) -> MissionHook:
    """Reconstruct a :class:`MissionHook` from its serialized form."""
    return MissionHook(
        patron=data.get("patron", ""),
        objective=data.get("objective", ""),
        complication=data.get("complication", ""),
        reward=data.get("reward", ""),
        description=data.get("description", ""),
    )
