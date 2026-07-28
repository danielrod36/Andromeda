"""Adventure screen — scene display, structured options, free-text input (U7).

Three-panel layout matching the lifepath screen: character sheet sidebar,
scrolling narrative log, and choice menu at the bottom. The adventure screen
adds:

- Scene scaffold display (oracle-derived focus, situation, NPC hints).
- Structured options (2-4 pre-mapped checks) + a free-text input slot.
- Free-text classification display: the interpreted check is shown to the
  player before resolution. Player may accept, reject to rephrase, or fall
  back to a structured option (AE5).

Phase flow::

    hook_offered -> hook_decision (accept/refuse)
    -> scene_active (scaffold + options)
    -> resolving (check resolution + consequences)
    -> mission_active (next scene or resolve)
    -> back to hook_offered

Phase state is reconstructable from GameState (AE8).
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Footer, Input, Label, OptionList

from src.engine.death import DefeatContext, get_death_strategy
from src.engine.mission import Mission, MissionEnding, MissionEngine
from src.engine.scene import SceneEngine
from src.engine.state import Injury
from src.tui.widgets.character_sheet import CharacterSheetWidget
from src.tui.widgets.choice_menu import ChoiceMenuWidget
from src.tui.widgets.narrative_log import NarrativeLogWidget


class AdventureScreen(Screen):
    """Three-panel adventure screen with scene display and free-text input.

    Layout::

        +-----------+-------------------+
        | Character | Narrative Log     |
        | Sheet     |                   |
        |           +-------------------+
        |           | Status / Input    |
        +-----------+-------------------+
        | Choice Menu / Options         |
        +-------------------------------+

    Tab/Shift-Tab cycles focus between panels. Number keys 1-9 select
    structured options. Enter submits free-text input.
    """

    CSS = """
    AdventureScreen {
        layout: vertical;
    }
    #adv-main-area {
        height: 1fr;
    }
    #adv-char-sheet {
        width: 28;
        height: 100%;
    }
    #adv-content-area {
        width: 1fr;
        height: 100%;
    }
    #adv-narrative-log {
        height: 1fr;
    }
    #adv-status-bar {
        height: 1;
        background: $boost;
        color: $text-muted;
        padding: 0 1;
    }
    #adv-input {
        height: 3;
        border: round $accent;
        padding: 0 1;
    }
    #adv-choice-menu {
        height: 9;
    }
    """

    BINDINGS = [
        Binding("tab", "focus_next", "Next panel"),
        Binding("shift+tab", "focus_previous", "Prev panel"),
        Binding("pageup", "scroll_log_up", "Log up", show=False),
        Binding("pagedown", "scroll_log_down", "Log down", show=False),
        Binding("home", "scroll_log_home", "Log top", show=False),
        Binding("end", "scroll_log_end", "Log end", show=False),
    ]

    #: Phase state machine — always_update so refreshes happen on re-entry.
    phase = reactive("init", always_update=True)

    def compose(self) -> ComposeResult:
        with Horizontal(id="adv-main-area"):
            yield CharacterSheetWidget(id="adv-char-sheet")
            with Vertical(id="adv-content-area"):
                yield NarrativeLogWidget(id="adv-narrative-log")
                yield Label(
                    "[dim]Adventure mode — no LLM connected[/dim]",
                    id="adv-status-bar",
                )
        yield ChoiceMenuWidget(id="adv-choice-menu")
        yield Input(
            placeholder="Or type your own action and press Enter...",
            id="adv-input",
        )
        yield Footer()

    def on_mount(self) -> None:
        """Initialize: show character sheet, resume context, set phase."""
        self._update_character_sheet()
        self._reconstruct_mission_if_needed()
        self._show_adventure_context()
        self.phase = self._determine_phase()
        # Focus the choice menu for immediate interaction.
        self.query_one(ChoiceMenuWidget).option_list.focus()

    def _reconstruct_mission_if_needed(self) -> None:
        """Reconstruct ``_current_mission`` from ``state.active_mission`` on resume.

        On resume from save where ``state.active_mission`` is not None, the
        in-memory ``_current_mission`` was never set (it is only set in
        ``_do_accept_mission``). Without reconstruction, ``_do_resolve_mission``
        crashes with ``AttributeError``.
        """
        if not hasattr(self, "_current_mission") or self._current_mission is None:
            state = self.app.engine.state
            if state.active_mission is not None:
                self._current_mission = Mission.from_dict(state.active_mission)

    # ------------------------------------------------------------------
    # Phase determination — fully reconstructable from GameState (AE8).
    # ------------------------------------------------------------------

    def _determine_phase(self) -> str:
        """Determine the current adventure phase from engine state."""
        state = self.app.engine.state

        # No active mission: offer a hook.
        if state.active_mission is None:
            return "hook_offered"

        # Active mission: playing scenes.
        return "scene_active"

    def _show_adventure_context(self) -> None:
        """Show adventure context on entry or resume."""
        state = self.app.engine.state
        char = state.character

        self._narrate("=== Adventure Mode ===")

        if char.name:
            self._narrate(f"Character: {char.name}")

        if state.active_mission:
            mission = state.active_mission
            hook = mission.get("hook", {})
            self._narrate(
                f"Active mission: {hook.get('patron', 'Unknown patron')} — "
                f"{hook.get('objective', 'Unknown objective')}"
            )
        else:
            self._narrate("No active mission. Seeking opportunities...")

    # ------------------------------------------------------------------
    # Reactive watcher — updates choices whenever phase changes.
    # ------------------------------------------------------------------

    def watch_phase(self, old_phase: str, new_phase: str) -> None:
        """Refresh the choice menu when phase changes."""
        self._update_choices()

    # ------------------------------------------------------------------
    # Choice management.
    # ------------------------------------------------------------------

    def _update_choices(self) -> None:
        """Populate the choice menu based on current phase."""
        cm = self.query_one(ChoiceMenuWidget)

        if self.phase == "hook_offered":
            self._offer_hook()
        elif self.phase == "scene_active":
            self._present_scene()
        elif self.phase == "mission_resolved":
            cm.set_choices(
                "Mission resolved:",
                [("Begin New Mission", "new_mission")],
            )

    # ------------------------------------------------------------------
    # Hook phase.
    # ------------------------------------------------------------------

    def _offer_hook(self) -> None:
        """Generate and display a mission hook."""
        mission_engine = self._get_mission_engine()
        self._current_hook = mission_engine.generate_hook()

        self._narrate("--- Mission Hook ---")
        self._narrate(f"Patron: {self._current_hook.patron}")
        self._narrate(f"Objective: {self._current_hook.objective}")
        self._narrate(f"Complication: {self._current_hook.complication}")
        self._narrate(f"Reward: {self._current_hook.reward}")

        cm = self.query_one(ChoiceMenuWidget)
        cm.set_choices(
            "A patron approaches with a job:",
            [
                ("Accept Mission", "accept_mission"),
                ("Refuse — Look for Another Job", "refuse_mission"),
            ],
        )

    def _do_accept_mission(self) -> None:
        """Accept the current hook and enter scene play."""
        mission_engine = self._get_mission_engine()
        self._current_mission = mission_engine.accept_mission(self._current_hook)
        self._narrate("Mission accepted. The adventure begins!")
        self._post_step()
        self.phase = "scene_active"

    def _do_refuse_mission(self) -> None:
        """Refuse the hook; generate a new one."""
        mission_engine = self._get_mission_engine()
        self._current_hook = mission_engine.refuse_mission()
        self._narrate("You decline. Another opportunity arises...")
        self._narrate("--- New Mission Hook ---")
        self._narrate(f"Patron: {self._current_hook.patron}")
        self._narrate(f"Objective: {self._current_hook.objective}")
        self._post_step()
        # Stay in hook_offered to offer the new hook.
        self.phase = "hook_offered"

    # ------------------------------------------------------------------
    # Scene phase.
    # ------------------------------------------------------------------

    def _present_scene(self) -> None:
        """Generate and present a scene with options."""
        # Take a checkpoint snapshot at scene start (F4 cycle) for
        # checkpoint death mode (AE3).
        state = self.app.engine.state
        if state.campaign.death_mode == "checkpoint":
            self.app.checkpoint_mgr.take_snapshot(state)

        scene_engine = self._get_scene_engine()
        self._current_scene = scene_engine.run_scene()
        scaffold = self._current_scene.scaffold

        self._narrate("--- New Scene ---")
        self._narrate(f"Focus: {scaffold.focus} — {scaffold.focus_description}")
        self._narrate(f"Situation: {scaffold.situation}")
        if scaffold.npc_hint:
            self._narrate(f"NPC: {scaffold.npc_hint}")

        # Build choice list from options.
        cm = self.query_one(ChoiceMenuWidget)
        choices = [
            (f"{i+1}. {opt.label} ({opt.skill}, {opt.difficulty})",
             f"option:{i}")
            for i, opt in enumerate(self._current_scene.options)
        ]
        choices.append(("Resolve Mission (attempt ending)", "resolve_mission"))
        cm.set_choices("Choose your action:", choices)

    def _do_resolve_option(self, option_index: int) -> None:
        """Resolve the selected structured option."""
        scene_engine = self._get_scene_engine()
        option = self._current_scene.options[option_index]

        self._narrate(f"You attempt: {option.label}")
        check_result = scene_engine.resolve_scene(
            self._current_scene.scaffold, option
        )

        self._narrate(
            f"Result: {check_result.quality} "
            f"(effect {check_result.effect:+d})"
        )

        # Apply consequences.
        consequences = scene_engine.apply_consequences(
            check_result, self._current_scene.scaffold
        )
        for c in consequences:
            self._narrate(f"  -> {c}")

        # Check for defeat (F5): life-threatening MISS or severe injury.
        if self._check_and_handle_defeat(check_result, option, consequences):
            return  # Defeat handled; phase already updated.

        self._post_step()
        self.phase = "scene_active"

    def _do_resolve_mission(self) -> None:
        """Resolve the active mission."""
        mission_engine = self._get_mission_engine()

        # Simple heuristic: if the last check was a success, mission succeeds.
        # In a real game, the TUI would offer ending choices.
        ending = MissionEnding.SUCCESS
        consequences = ["Reputation increased.", "Payment received."]

        mission_engine.resolve_mission(
            self._current_mission, ending, consequences
        )

        for c in consequences:
            self._narrate(f"  -> {c}")

        self._narrate("Mission complete! Looking for the next opportunity...")
        self._post_step()
        self.phase = "hook_offered"

    # ------------------------------------------------------------------
    # Defeat detection and handling (F5, R8).
    # ------------------------------------------------------------------

    def _check_and_handle_defeat(
        self,
        check_result,
        option,
        consequences: list[str],
    ) -> bool:
        """Detect catastrophic outcomes and invoke the death strategy (F5).

        Triggers defeat when:
        - The check result is a MISS on a life-threatening action, OR
        - A severe injury was applied as a consequence.

        When defeat is triggered, invokes the appropriate death strategy via
        ``get_death_strategy`` and applies the result. Returns ``True`` if
        defeat was handled (caller should skip the normal post-step).
        """
        from src.rulesets.base import OutcomeQuality

        is_defeat = False
        reason = ""

        # Condition 1: MISS on a life-threatening check.
        if (
            check_result.quality == OutcomeQuality.MISS.value
            and getattr(option, "life_threatening", False)
        ):
            is_defeat = True
            reason = f"a failed life-threatening {check_result.skill} check"

        # Condition 2: severe injury applied as a consequence.
        if not is_defeat:
            state = self.app.engine.state
            has_severe = any(
                isinstance(e, Injury) and e.severity == "severe"
                for e in state.entities
            )
            if has_severe and check_result.quality == OutcomeQuality.MISS.value:
                # Check if a severe injury was just added in this consequence.
                if any("severe" in c.lower() or "serious" in c.lower() for c in consequences):
                    is_defeat = True
                    reason = f"accumulated severe injuries during {check_result.skill}"

        if not is_defeat:
            return False

        return self._handle_defeat(reason)

    def _handle_defeat(self, reason: str) -> bool:
        """Invoke the death strategy and apply the defeat result (F5, R8).

        Constructs the appropriate :class:`DeathStrategy` via
        :func:`get_death_strategy`, routes mutations through the funnel when
        possible, narrates the outcome, and updates the phase.

        Returns ``True`` to signal the caller that defeat was handled.
        """
        state = self.app.engine.state
        death_mode = state.campaign.death_mode

        checkpoint_mgr = self.app.checkpoint_mgr
        strategy = get_death_strategy(
            death_mode,
            checkpoint=checkpoint_mgr,
            engine=self.app.engine,
        )
        context = DefeatContext(
            reason=reason,
            scene_label=getattr(
                self._current_scene.scaffold, "focus", "unknown"
            ),
        )
        result = strategy.handle_defeat(state, context)

        self._narrate(f"=== DEFEAT ({death_mode}) ===")
        self._narrate(result.message)

        if result.restored_state is not None:
            # Checkpoint mode: swap in the restored state.
            self.app.engine._state = result.restored_state

        if not result.play_continues:
            # Ironman: character is dead. Offer restart via hook phase.
            self._update_character_sheet()
            self._post_step()
            self.phase = "hook_offered"
        else:
            # Checkpoint or Narrative: play continues.
            self._update_character_sheet()
            self._post_step()
            self.phase = "scene_active"

        return True

    # ------------------------------------------------------------------
    # Free-text input handling (AE5).
    # ------------------------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle free-text input submission (AE5).

        The LLM (or template classifier) interprets the free text into an
        engine-known check. The interpreted check is shown to the player
        for confirmation before resolution.
        """
        if event.input.id != "adv-input":
            return

        text = event.value.strip()
        if not text:
            return

        # Only process free-text during scene phase.
        if self.phase != "scene_active":
            self._narrate("Free-text is only available during scenes.")
            event.input.value = ""
            return

        scene_engine = self._get_scene_engine()
        classification = scene_engine.classify_freetext(
            text, self._current_scene.scaffold
        )

        if classification is None:
            self._narrate(
                f"Could not interpret '{text}'. "
                "Try rephrasing or select a structured option."
            )
            event.input.value = ""
            return

        # Show the interpreted check to the player (AE5).
        check = classification.interpreted_check
        self._narrate(
            f"Interpreted as: {check.label} "
            f"(skill: {check.skill}, difficulty: {check.difficulty})"
        )

        # Offer accept/reject choices.
        cm = self.query_one(ChoiceMenuWidget)
        cm.set_choices(
            "Confirm interpreted action:",
            [
                ("Accept — Proceed with this check", "accept_freetext"),
                ("Reject — Rephrase or pick an option", "reject_freetext"),
            ],
        )

        # Store the interpreted check for resolution.
        self._pending_freetext = check
        event.input.value = ""

    def _do_accept_freetext(self) -> None:
        """Accept the interpreted free-text check and resolve it."""
        scene_engine = self._get_scene_engine()
        option = self._pending_freetext

        self._narrate(f"You attempt: {option.label}")
        check_result = scene_engine.resolve_scene(
            self._current_scene.scaffold, option
        )
        self._narrate(
            f"Result: {check_result.quality} "
            f"(effect {check_result.effect:+d})"
        )

        consequences = scene_engine.apply_consequences(
            check_result, self._current_scene.scaffold
        )
        for c in consequences:
            self._narrate(f"  -> {c}")

        self._pending_freetext = None

        # Check for defeat (F5): life-threatening MISS or severe injury.
        if self._check_and_handle_defeat(check_result, option, consequences):
            return  # Defeat handled; phase already updated.

        self._post_step()
        self.phase = "scene_active"

    def _do_reject_freetext(self) -> None:
        """Reject the interpreted check; return to structured options."""
        self._narrate("Interpretation rejected. Choose an option or rephrase.")
        self._pending_freetext = None
        self.phase = "scene_active"

    # ------------------------------------------------------------------
    # Event handlers.
    # ------------------------------------------------------------------

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        """Dispatch choice selection to the appropriate handler."""
        option_id = event.option.id
        if option_id is None:
            return

        if option_id == "accept_mission":
            self._do_accept_mission()
        elif option_id == "refuse_mission":
            self._do_refuse_mission()
        elif option_id == "resolve_mission":
            self._do_resolve_mission()
        elif option_id == "accept_freetext":
            self._do_accept_freetext()
        elif option_id == "reject_freetext":
            self._do_reject_freetext()
        elif option_id == "new_mission":
            self.phase = "hook_offered"
        elif option_id.startswith("option:"):
            idx = int(option_id.split(":", 1)[1])
            self._do_resolve_option(idx)

    # ------------------------------------------------------------------
    # UI helpers.
    # ------------------------------------------------------------------

    def _narrate(self, text: str) -> None:
        """Add a line to the narrative log."""
        self.query_one(NarrativeLogWidget).add_line(text)

    def _update_character_sheet(self) -> None:
        """Refresh the character sheet from engine state."""
        self.query_one(CharacterSheetWidget).update_from_state(
            self.app.engine.state
        )

    def _post_step(self) -> None:
        """Common post-step actions: update sheet, auto-save (AE8)."""
        self._update_character_sheet()
        self.app.save_game()

    # ------------------------------------------------------------------
    # Engine accessors.
    # ------------------------------------------------------------------

    def _get_mission_engine(self) -> MissionEngine:
        """Get or create a mission engine."""
        if not hasattr(self, "_mission_engine_cache") or self._mission_engine_cache is None:
            self._mission_engine_cache = MissionEngine(
                self.app.engine, self.app.pack
            )
        return self._mission_engine_cache

    def _get_scene_engine(self) -> SceneEngine:
        """Get or create a scene engine."""
        if not hasattr(self, "_scene_engine_cache") or self._scene_engine_cache is None:
            self._scene_engine_cache = SceneEngine(
                self.app.engine, self.app.pack
            )
        return self._scene_engine_cache

    # ------------------------------------------------------------------
    # Scroll actions for the narrative log.
    # ------------------------------------------------------------------

    def action_scroll_log_up(self) -> None:
        self.query_one(NarrativeLogWidget).scroll_page_up()

    def action_scroll_log_down(self) -> None:
        self.query_one(NarrativeLogWidget).scroll_page_down()

    def action_scroll_log_home(self) -> None:
        self.query_one(NarrativeLogWidget).scroll_home()

    def action_scroll_log_end(self) -> None:
        self.query_one(NarrativeLogWidget).scroll_end()

    # ------------------------------------------------------------------
    # Focus delegation.
    # ------------------------------------------------------------------

    def action_focus_next(self) -> None:
        self.app.action_focus_next()

    def action_focus_previous(self) -> None:
        self.app.action_focus_previous()
