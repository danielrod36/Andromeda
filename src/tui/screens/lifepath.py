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
from src.rulesets.cepheus import CepheusRuleSet
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
    LifepathScreen.narrow #char-sheet { display: none; }
    LifepathScreen.narrow.show-sheet #char-sheet { display: block; width: 100%; height: 40%; }
    LifepathScreen.narrow.show-sheet #content-area { height: 1fr; }
    LifepathScreen.narrow.show-sheet #main-area { layout: vertical; }
    LifepathScreen.short #choice-menu { height: 6; }
    LifepathScreen.short #status-bar { height: 1; }
    """

    BINDINGS = [
        Binding("tab", "focus_next", "Next panel"),
        Binding("shift+tab", "focus_previous", "Prev panel"),
        Binding("c", "toggle_sheet", "Char sheet"),
        Binding("pageup", "scroll_log_up", "Log up", show=False),
        Binding("pagedown", "scroll_log_down", "Log down", show=False),
        Binding("home", "scroll_log_home", "Log top", show=False),
        Binding("end", "scroll_log_end", "Log end", show=False),
    ]

    #: always_update ensures choices refresh even when phase string is unchanged.
    phase = reactive("init", always_update=True)
    _mounted = False

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
        self._update_status_bar()
        self._show_resume_context()
        self.phase = self._determine_phase()
        # Focus the choice menu's OptionList for immediate interaction.
        self.query_one(ChoiceMenuWidget).option_list.focus()
        self._mounted = True
        self.call_after_refresh(self._apply_responsive_layout)

    def on_resize(self, event) -> None:
        """Re-evaluate layout when terminal is resized."""
        if self._mounted:
            self._apply_responsive_layout()

    def _apply_responsive_layout(self) -> None:
        """Toggle CSS classes based on terminal dimensions."""
        w, h = self.size.width, self.size.height
        if w < 100:
            self.add_class("narrow")
        else:
            self.remove_class("narrow")
            self.remove_class("show-sheet")
        if h < 24:
            self.add_class("short")
        else:
            self.remove_class("short")

    def action_toggle_sheet(self) -> None:
        """Toggle the character sheet on narrow terminals."""
        if self.has_class("narrow"):
            self.toggle_class("show-sheet")

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

        self._narrate_separator(f"Campaign: {self.app.campaign_name}")

        if char.name:
            self._narrate(f"[bold]{char.name}[/bold]")

        if char.characteristics:
            chars = ", ".join(
                f"{k} {v}" for k, v in char.characteristics.items()
            )
            self._narrate(f"[dim]Characteristics:[/dim] {chars}")

        if char.career:
            self._narrate(
                f"[dim]Career:[/dim] {char.career.title()}, Rank {char.rank}, "
                f"{char.terms} terms, Age {char.age}"
            )

        if char.skills:
            skills = ", ".join(
                f"{s.replace('_', ' ').title()}-{v}"
                for s, v in sorted(char.skills.items())
            )
            self._narrate(f"[dim]Skills:[/dim] {skills}")

        if not char.alive:
            self._narrate("[bold red]This character has died.[/bold red]")
        self._narrate("")

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
                descriptions=["Rolls STR, DEX, END, INT, EDU, SOC — each 2D6. These define your character's core aptitudes."],
            )
        elif self.phase == "choose_career":
            careers = sorted(
                self.app.pack.careers.values(), key=lambda c: c.name
            )
            choices = []
            descs = []
            for c in careers:
                choices.append((c.name, f"career:{c.id}"))
                qual = c.qualification
                surv = c.survival
                desc = (
                    f"Qualify: {qual.characteristic} target {qual.target}. "
                    f"Survival: {surv.characteristic} target {surv.target}. "
                    f"{c.description.strip()[:80]}"
                )
                descs.append(desc)
            cm.set_choices("Choose your career:", choices, descriptions=descs)
        elif self.phase == "run_term":
            next_term = self.app.engine.state.character.terms + 1
            career = self.app.engine.state.character.career.title()
            age_after = self.app.engine.state.character.age + 4
            aging_note = " Aging check applies." if age_after >= 34 else ""
            cm.set_choices(
                f"Term {next_term} of {self.app.target_terms} ({career}):",
                [(f"Run Term {next_term}", "run_term")],
                descriptions=[
                    f"4 years of service. Survival, advancement, and skill rolls.{aging_note}"
                ],
            )
        elif self.phase == "mustering_out":
            cm.set_choices(
                "Your service is ending:",
                [("Muster Out (collect benefits)", "muster_out")],
                descriptions=["Roll for cash and material benefits based on terms served and rank achieved."],
            )
        elif self.phase == "complete":
            state = self.app.engine.state
            label = "Character generation complete:"
            if not state.character.alive:
                label = "Character generation complete (deceased):"
            cm.set_choices(
                label,
                [("Finish — Return to Main Menu", "finish")],
                descriptions=["Save the character and return to the main menu."],
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
        self._narrate_section("Characteristic Rolls")
        chars = self.app.runner.roll_characteristics()

        # Show each roll individually with DM info.
        state = self.app.engine.state
        for stat, val in chars.items():
            dm = CepheusRuleSet().characteristic_dm(val)
            dm_str = f"DM {'+' if dm >= 0 else ''}{dm}" if dm else "DM +0"
            tier = "strong" if val >= 9 else ("weak" if val <= 5 else "average")
            self._narrate(f"  [bold]{stat}[/bold]: {val} ({dm_str}, {tier})")
        self._narrate("")

        self._post_step()
        self.phase = self._determine_phase()

    def _do_choose_career(self, career_id: str) -> None:
        """Attempt qualification for the selected career."""
        career_name = self.app.pack.careers[career_id].name
        self._narrate_section(f"Qualification: {career_name}")
        qual = self.app.runner.qualify(career_id)

        # Show the roll.
        if hasattr(qual, 'roll_total') and qual.roll_total:
            self._narrate_roll(
                "Qualification", f"2D6({qual.roll_total})",
                qual.roll_total, qual.adjusted_total - qual.roll_total,
                qual.target, qual.success,
            )
        self._narrate_paragraph(self.app.narrator.narrate_qualification(qual))

        if not qual.success:
            if (
                career_id != "drifter"
                and "drifter" in self.app.pack.careers
            ):
                self._narrate("[dim]Falling back to the drifter career...[/dim]")
                qual2 = self.app.runner.qualify("drifter")
                self._narrate_paragraph(
                    self.app.narrator.narrate_qualification(qual2)
                )

        self._post_step()
        self.phase = self._determine_phase()

    def _do_run_term(self) -> None:
        """Run one 4-year term: survival, advancement, skills, aging."""
        state = self.app.engine.state
        career_id = state.character.career
        term_number = state.character.terms + 1

        self._narrate_section(f"Term {term_number}")
        term_result = self.app.runner.run_term(career_id, term_number)

        # Show survival roll.
        if hasattr(term_result, 'survival_total') and term_result.survival_total:
            self._narrate_roll(
                "Survival", f"2D6({term_result.survival_total})",
                term_result.survival_total, 0,
                term_result.survival_target,
                not term_result.died and not term_result.mishap,
                "MISHAP" if term_result.mishap else "",
            )

        self._narrate_paragraph(self.app.narrator.narrate_term(term_result))

        if term_result.died:
            self._narrate(
                "[bold red]Your character did not survive character generation.[/bold red]"
            )

        self._post_step()
        self.phase = self._determine_phase()

    def _do_muster_out(self) -> None:
        """Collect mustering-out benefits."""
        state = self.app.engine.state
        career_id = state.character.career

        self._narrate_section("Mustering Out")
        mo_result = self.app.runner.muster_out(career_id)
        self._narrate_paragraph(self.app.narrator.narrate_mustering_out(mo_result))

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

    def _update_status_bar(self) -> None:
        """Update the status bar to reflect LLM connection state."""
        bar = self.query_one("#status-bar", Label)
        if self.app.llm_settings.is_configured:
            provider = self.app.llm_settings.provider
            model = self.app.llm_settings.model
            bar.update(f"[green]LLM: {provider}/{model}[/green]")
        else:
            bar.update("[dim]Template narration — configure LLM in Settings[/dim]")

    def _narrate_section(self, title: str) -> None:
        """Add a section header to the log."""
        self.query_one(NarrativeLogWidget).add_section(title)

    def _narrate_separator(self, label: str = "") -> None:
        """Add a separator line."""
        self.query_one(NarrativeLogWidget).add_separator(label)

    def _narrate_roll(self, label: str, dice: str, total: int,
                      dm: int, target: int, success: bool, tier: str = "") -> None:
        """Add a formatted dice roll result."""
        self.query_one(NarrativeLogWidget).add_roll(
            label, dice, total, dm, target, success, tier
        )

    def _narrate_paragraph(self, text: str) -> None:
        """Add a paragraph with a blank line after."""
        self.query_one(NarrativeLogWidget).add_paragraph(text)

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
