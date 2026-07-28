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

from src.engine.mission import MissionEnding, MissionEngine
from src.engine.scene import SceneEngine
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
        self._show_adventure_context()
        self.phase = self._determine_phase()
        # Focus the choice menu for immediate interaction.
        self.query_one(ChoiceMenuWidget).option_list.focus()

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
