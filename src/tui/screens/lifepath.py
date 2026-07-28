"""Lifepath mini-game screen — three-panel layout (R16, AE8).

Three panels: character sheet sidebar, scrolling narrative log, choice menu.
Phase state machine is fully reconstructable from GameState, enabling
quit-and-resume with identical state (AE8).

Phase flow:
    roll_characteristics -> choose_career -> run_term -> mustering_out -> complete

Each step applies engine commands through the LifepathRunner funnel, narrates
the result, updates the character sheet, and auto-saves.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Footer, Label, OptionList

from src.engine.commands import SetFlagCommand
from src.tui.widgets.character_sheet import CharacterSheetWidget
from src.tui.widgets.choice_menu import ChoiceMenuWidget
from src.tui.widgets.narrative_log import NarrativeLogWidget


class LifepathScreen(Screen):
    """Three-panel lifepath screen.

    Layout::

        +-----------+-------------------+
        | Character | Narrative Log     |
        | Sheet     |                   |
        |           +-------------------+
        |           | Status            |
        +-----------+-------------------+
        | Choice Menu                    |
        +--------------------------------+

    Tab/Shift-Tab cycles focus between panels. Number keys 1-9 select
    choices when the OptionList has focus. PageUp/PageDown and Home/End
    scroll the narrative log.
    """

    CSS = """
    LifepathScreen {
        layout: vertical;
    }
    #main-area {
        height: 1fr;
    }
    #char-sheet {
        width: 28;
        height: 100%;
    }
    #content-area {
        width: 1fr;
        height: 100%;
    }
    #narrative-log {
        height: 1fr;
    }
    #status-bar {
        height: 1;
        background: $boost;
        color: $text-muted;
        padding: 0 1;
    }
    #choice-menu {
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

    #: always_update ensures choices refresh even when phase string is unchanged.
    phase = reactive("init", always_update=True)

    def compose(self) -> ComposeResult:
        with Horizontal(id="main-area"):
            yield CharacterSheetWidget(id="char-sheet")
            with Vertical(id="content-area"):
                yield NarrativeLogWidget(id="narrative-log")
                yield Label(
                    "[dim]Template narration — no LLM connected[/dim]",
                    id="status-bar",
                )
        yield ChoiceMenuWidget(id="choice-menu")
        yield Footer()

    def on_mount(self) -> None:
        """Initialize: show character sheet, resume context, set phase."""
        self._update_character_sheet()
        self._show_resume_context()
        self.phase = self._determine_phase()
        # Focus the choice menu's OptionList for immediate interaction.
        self.query_one(ChoiceMenuWidget).option_list.focus()

    # ------------------------------------------------------------------
    # Phase determination — fully reconstructable from GameState (AE8).
    # ------------------------------------------------------------------

    def _determine_phase(self) -> str:
        """Determine the current lifepath phase from engine state."""
        state = self.app.engine.state
        char = state.character

        # No characteristics rolled yet.
        if len(char.characteristics) < 6:
            return "roll_characteristics"

        # Characteristics rolled but no career chosen.
        if not char.career:
            return "choose_career"

        # Character is dead (ironman death during lifepath).
        if not char.alive:
            return "complete"

        # Mustering out already completed (flag set via the funnel).
        if "mustered_out=true" in state.narrative_log:
            return "complete"

        # Check for mishap in the most recent survival event.
        surv_events = [
            e
            for e in state.events
            if e.command_type == "lifepath_survival"
        ]
        if surv_events and surv_events[-1].changes.get("mishap"):
            return "mustering_out"

        # All target terms completed.
        if char.terms >= self.app.target_terms:
            return "mustering_out"

        # Still in the term loop.
        return "run_term"

    def _show_resume_context(self) -> None:
        """Show a summary of existing state (useful on resume from save)."""
        state = self.app.engine.state
        char = state.character

        self._narrate(f"=== Campaign: {self.app.campaign_name} ===")

        if char.name:
            self._narrate(f"Character: {char.name}")

        if char.characteristics:
            chars = ", ".join(
                f"{k} {v}" for k, v in char.characteristics.items()
            )
            self._narrate(f"Characteristics: {chars}.")

        if char.career:
            self._narrate(
                f"Career: {char.career.title()}, Rank: {char.rank}, "
                f"Terms: {char.terms}, Age: {char.age}."
            )

        if char.skills:
            skills = ", ".join(
                f"{s.replace('_', ' ').title()}-{v}"
                for s, v in sorted(char.skills.items())
            )
            self._narrate(f"Skills: {skills}.")

        if not char.alive:
            self._narrate("[red]This character has died.[/red]")

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

        if self.phase == "roll_characteristics":
            cm.set_choices(
                "Begin character generation:",
                [("Roll Characteristics (2D6 x6)", "roll_chars")],
            )
        elif self.phase == "choose_career":
            careers = sorted(
                self.app.pack.careers.values(), key=lambda c: c.name
            )
            choices = [(c.name, f"career:{c.id}") for c in careers]
            cm.set_choices("Choose your career:", choices)
        elif self.phase == "run_term":
            next_term = self.app.engine.state.character.terms + 1
            cm.set_choices(
                f"Term {next_term} of {self.app.target_terms}:",
                [(f"Run Term {next_term}", "run_term")],
            )
        elif self.phase == "mustering_out":
            cm.set_choices(
                "Your service is ending:",
                [("Muster Out (collect benefits)", "muster_out")],
            )
        elif self.phase == "complete":
            state = self.app.engine.state
            label = "Character generation complete:"
            if not state.character.alive:
                label = "Character generation complete (deceased):"
            cm.set_choices(
                label,
                [("Finish — Return to Main Menu", "finish")],
            )

    # ------------------------------------------------------------------
    # Event handlers.
    # ------------------------------------------------------------------

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        """Dispatch choice selection to the appropriate step handler."""
        option_id = event.option.id
        if option_id is None:
            return

        if option_id == "roll_chars":
            self._do_roll_characteristics()
        elif option_id == "run_term":
            self._do_run_term()
        elif option_id == "muster_out":
            self._do_muster_out()
        elif option_id == "finish":
            self._do_finish()
        elif option_id.startswith("career:"):
            career_id = option_id.split(":", 1)[1]
            self._do_choose_career(career_id)

    # ------------------------------------------------------------------
    # Lifepath step methods.
    # ------------------------------------------------------------------

    def _do_roll_characteristics(self) -> None:
        """Roll the six characteristics via the engine funnel."""
        self._narrate("Rolling characteristics...")
        chars = self.app.runner.roll_characteristics()
        char_line = ", ".join(f"{k} {v}" for k, v in chars.items())
        self._narrate(f"Characteristics: {char_line}.")
        self._post_step()
        self.phase = self._determine_phase()

    def _do_choose_career(self, career_id: str) -> None:
        """Attempt qualification for the selected career."""
        career_name = self.app.pack.careers[career_id].name
        self._narrate(f"Attempting qualification for {career_name}...")
        qual = self.app.runner.qualify(career_id)
        self._narrate(self.app.narrator.narrate_qualification(qual))

        if not qual.success:
            # Drifter fallback (matches LifepathRunner.run_lifepath behavior).
            if (
                career_id != "drifter"
                and "drifter" in self.app.pack.careers
            ):
                self._narrate("Falling back to the drifter career...")
                qual2 = self.app.runner.qualify("drifter")
                self._narrate(
                    self.app.narrator.narrate_qualification(qual2)
                )

        self._post_step()
        self.phase = self._determine_phase()

    def _do_run_term(self) -> None:
        """Run one 4-year term: survival, advancement, skills, aging."""
        state = self.app.engine.state
        career_id = state.character.career
        term_number = state.character.terms + 1

        self._narrate(f"-- Term {term_number} begins --")
        term_result = self.app.runner.run_term(career_id, term_number)
        self._narrate(self.app.narrator.narrate_term(term_result))

        if term_result.died:
            self._narrate(
                "[red]Your character did not survive character generation.[/red]"
            )

        self._post_step()
        self.phase = self._determine_phase()

    def _do_muster_out(self) -> None:
        """Collect mustering-out benefits."""
        state = self.app.engine.state
        career_id = state.character.career

        self._narrate("Mustering out of service...")
        mo_result = self.app.runner.muster_out(career_id)
        self._narrate(self.app.narrator.narrate_mustering_out(mo_result))

        # Mark mustering out as complete via the funnel so save/resume
        # can distinguish "needs mustering out" from "already done".
        self.app.engine.apply(
            SetFlagCommand(key="mustered_out", value="true")
        )

        self._post_step()
        self.phase = "complete"

    def _do_finish(self) -> None:
        """Return to the main menu."""
        self._narrate("Campaign saved. Returning to main menu...")
        self.app.save_game()
        self.app.return_to_main_menu()

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
    # Scroll actions for the narrative log.
    # ------------------------------------------------------------------

    def action_scroll_log_up(self) -> None:
        """Scroll the narrative log up by one page."""
        self.query_one(NarrativeLogWidget).scroll_page_up()

    def action_scroll_log_down(self) -> None:
        """Scroll the narrative log down by one page."""
        self.query_one(NarrativeLogWidget).scroll_page_down()

    def action_scroll_log_home(self) -> None:
        """Scroll to the top of the narrative log."""
        self.query_one(NarrativeLogWidget).scroll_home()

    def action_scroll_log_end(self) -> None:
        """Scroll to the bottom of the narrative log."""
        self.query_one(NarrativeLogWidget).scroll_end()

    # ------------------------------------------------------------------
    # Focus delegation (Screen lacks action_focus_next; App has it).
    # ------------------------------------------------------------------

    def action_focus_next(self) -> None:
        """Delegate Tab to the app's focus-next action."""
        self.app.action_focus_next()

    def action_focus_previous(self) -> None:
        """Delegate Shift-Tab to the app's focus-previous action."""
        self.app.action_focus_previous()
