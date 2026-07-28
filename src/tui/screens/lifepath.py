"""Lifepath mini-game screen — three-panel layout (R16, AE8).

Three panels: character sheet sidebar, scrolling narrative log, choice menu.
Phase state machine is fully reconstructable from GameState, enabling
quit-and-resume with identical state (AE8).

Interactive phase flow (per CE SRD rules)::

    roll_characteristics
        -> choose_career
        -> run_survival     (auto-roll, show result)
        -> run_advancement  (auto-roll, show result)
        -> choose_skills    (player picks skill tables, one roll each)
        -> run_aging        (auto-roll if age >= 34)
        -> re_enlist        (continue or muster out)
        -> [loop back to run_survival or go to mustering_out]
    mustering_out
        -> complete

Each step applies engine commands through the LifepathRunner funnel, narrates
the result, updates the character sheet, and auto-saves.

LLM narration is wired for qualification, term completion, mustering out,
and the full lifepath summary. When the LLM is configured, narration is
fetched asynchronously via ``run_worker``; otherwise the template
``Narrator`` is used synchronously.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.dom import NoMatches
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Footer, Label, OptionList

from src.engine.commands import SetFlagCommand
from src.engine.lifepath import TermResult
from src.rulesets.cepheus import CepheusRuleSet
from src.tui.widgets.character_sheet import CharacterSheetWidget
from src.tui.widgets.choice_menu import ChoiceMenuWidget
from src.tui.widgets.narrative_log import NarrativeLogWidget


# Phases that belong to the term sub-state-machine.
_TERM_PHASES = frozenset(
    {"run_survival", "run_advancement", "choose_skills", "run_aging", "re_enlist"}
)


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

    def __init__(self) -> None:
        super().__init__()
        # Current term's partial result — rebuilt from events on resume.
        self._current_term_result: TermResult | None = None
        # How many skill table picks the player still has.
        self._skill_rolls_remaining: int = 0

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
        # Rebuild term-level instance state if resuming mid-term.
        if self.phase in _TERM_PHASES:
            self._reconstruct_term_state()
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

    def _get_latest_term_phase(self) -> str | None:
        """Return the most recent ``term_phase=`` flag from the narrative log."""
        for entry in reversed(self.app.engine.state.narrative_log):
            if entry.startswith("term_phase="):
                return entry.split("=", 1)[1]
        return None

    def _set_term_phase(self, phase: str) -> None:
        """Persist a ``term_phase`` flag via the command funnel (AE8-safe)."""
        self.app.engine.apply(
            SetFlagCommand(key="term_phase", value=phase)
        )

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

        # Check the persisted term_phase flag (tracks sub-step of current term).
        term_phase = self._get_latest_term_phase()
        if term_phase:
            if term_phase == "mustering_out":
                return "mustering_out"
            if term_phase in _TERM_PHASES:
                # During skill selection, check if rolls are exhausted.
                if term_phase == "choose_skills":
                    remaining = self._compute_skill_rolls_remaining()
                    if remaining <= 0:
                        # All skill rolls done — advance to aging or re_enlist.
                        if char.age >= 34:
                            return "run_aging"
                        return "re_enlist"
                return term_phase

        # No term_phase flag — start a new term (first term or after continue).
        return "run_survival"

    def _reconstruct_term_state(self) -> None:
        """Rebuild ``_current_term_result`` from events on save/resume."""
        state = self.app.engine.state
        char = state.character
        career_id = char.career
        if not career_id:
            return

        # Find the survival event for the current term (the most recent one).
        surv_events = [
            e for e in state.events
            if e.command_type == "lifepath_survival"
        ]
        if not surv_events:
            return

        last_surv = surv_events[-1]
        sc = last_surv.changes

        result = TermResult(
            term_number=char.terms,
            career_id=career_id,
            career_name=self.app.pack.careers[career_id].name,
            age_before=char.age - 4,
            age_after=char.age,
            rank_before=char.rank,
            survival_target=sc.get("target", 0),
            advancement_target=self.app.pack.careers[career_id].advancement.target,
        )
        result.survival_raw = sc.get("raw_roll", 0)
        result.survival_dm = sc.get("char_dm", 0)
        result.survival_total = sc.get("adjusted_total", 0)
        result.survival_success = sc.get("success", True)
        result.died = sc.get("died", False)
        result.mishap = sc.get("mishap", False)
        result.rank_after = char.rank

        # Find events after the survival event index.
        surv_idx = state.events.index(last_surv)
        for event in state.events[surv_idx + 1:]:
            if event.command_type == "lifepath_advancement":
                ac = event.changes
                result.advancement_raw = ac.get("raw_roll", 0)
                result.advancement_dm = ac.get("char_dm", 0)
                result.advancement_total = ac.get("adjusted_total", 0)
                result.advancement_success = ac.get("success", False)
                result.rank_after = ac.get("new_rank", char.rank)
            elif event.command_type == "lifepath_skill_roll":
                from src.engine.lifepath import SkillGain
                sec = event.changes
                result.skill_gains.append(SkillGain(
                    table_name=sec.get("table_name", ""),
                    roll=sec.get("roll_total", 0),
                    result_text=sec.get("result_text", ""),
                    gain_type=sec.get("gain_type", "skill"),
                    gain_name=sec.get("gain_name", ""),
                ))
            elif event.command_type == "lifepath_aging":
                agc = event.changes
                result.aging_raw = agc.get("raw_roll", 0)
                result.aging_success = agc.get("success", True)
                result.aging_reductions = agc.get("reductions", {})

        self._current_term_result = result

        # Rebuild skill rolls remaining.
        phase = self._get_latest_term_phase()
        if phase == "choose_skills":
            total = self.app.runner.compute_num_skill_rolls(result)
            self._skill_rolls_remaining = total - len(result.skill_gains)

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
        elif self.phase == "run_survival":
            state = self.app.engine.state
            next_term = state.character.terms + 1
            career = self.app.pack.careers.get(
                state.character.career
            )
            career_name = career.name if career else state.character.career
            surv_char = career.survival.characteristic if career else "?"
            surv_target = career.survival.target if career else "?"
            cm.set_choices(
                f"Term {next_term} — Survival Check ({career_name}):",
                [(f"Roll Survival (2D6 vs {surv_target}, {surv_char})", "roll_survival")],
                descriptions=[
                    f"Roll 2D6 + {surv_char} DM vs target {surv_target}. "
                    f"Failure means death (ironman) or mishap (narrative)."
                ],
            )
        elif self.phase == "run_advancement":
            state = self.app.engine.state
            career = self.app.pack.careers.get(state.character.career)
            adv_char = career.advancement.characteristic if career else "?"
            adv_target = career.advancement.target if career else "?"
            cm.set_choices(
                f"Term {state.character.terms} — Advancement Check:",
                [(f"Roll Advancement (2D6 vs {adv_target}, {adv_char})", "roll_advancement")],
                descriptions=[
                    f"Roll 2D6 + {adv_char} DM vs target {adv_target}. "
                    f"Success grants a promotion and an extra skill roll."
                ],
            )
        elif self.phase == "choose_skills":
            state = self.app.engine.state
            career = self.app.pack.careers.get(state.character.career)
            remaining = self._skill_rolls_remaining
            choices = []
            descs = []
            for table in career.skill_tables:
                # Build a short preview of table contents.
                skills = [e.result for e in table.entries.entries]
                preview = ", ".join(skills[:4])
                if len(skills) > 4:
                    preview += ", ..."
                choices.append(
                    (f"{table.name} ({remaining} left)", f"skill_table:{table.name}")
                )
                descs.append(f"Possible: {preview}")
            cm.set_choices(
                f"Choose skill tables ({remaining} roll{'s' if remaining != 1 else ''} remaining):",
                choices,
                descriptions=descs,
            )
        elif self.phase == "run_aging":
            cm.set_choices(
                "Aging Check (age 34+):",
                [("Roll Aging (2D6 vs 8)", "roll_aging")],
                descriptions=[
                    "Roll 2D6 vs target 8. Failure reduces physical characteristics. "
                    "Natural 2 reduces ALL characteristics."
                ],
            )
        elif self.phase == "re_enlist":
            state = self.app.engine.state
            char = state.character
            career = self.app.pack.careers.get(char.career)
            career_name = career.name if career else char.career
            age_after = char.age + 4
            aging_note = " Aging check will apply." if age_after >= 34 else ""
            cm.set_choices(
                f"Term {char.terms} complete ({career_name}, Rank {char.rank}, Age {char.age}). Re-enlist?",
                [
                    (f"Continue for another term (Age {age_after})", "re_enlist_continue"),
                    ("Muster Out and Finish Character", "re_enlist_muster_out"),
                ],
                descriptions=[
                    f"Serve another 4-year term.{aging_note}",
                    "Leave service and collect mustering-out benefits.",
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
        elif option_id == "roll_survival":
            self._do_survival_roll()
        elif option_id == "roll_advancement":
            self._do_advancement_roll()
        elif option_id == "roll_aging":
            self._do_aging_roll()
        elif option_id == "muster_out":
            self._do_muster_out()
        elif option_id == "finish":
            self._do_finish()
        elif option_id == "re_enlist_continue":
            self._do_re_enlist_continue()
        elif option_id == "re_enlist_muster_out":
            self._do_re_enlist_muster_out()
        elif option_id.startswith("career:"):
            career_id = option_id.split(":", 1)[1]
            self._do_choose_career(career_id)
        elif option_id.startswith("skill_table:"):
            table_name = option_id.split(":", 1)[1]
            self._do_skill_table_choice(table_name)

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

        # Narrate — LLM or template.
        self._narrate_step(
            "qualification", qual,
            lambda: self.app.narrator.narrate_qualification(qual),
        )

        if not qual.success:
            if (
                career_id != "drifter"
                and "drifter" in self.app.pack.careers
            ):
                self._narrate("[dim]Falling back to the drifter career...[/dim]")
                qual2 = self.app.runner.qualify("drifter")
                self._narrate_step(
                    "qualification", qual2,
                    lambda: self.app.narrator.narrate_qualification(qual2),
                )

        self._post_step()
        self.phase = self._determine_phase()

    # ------------------------------------------------------------------
    # Term sub-step handlers.
    # ------------------------------------------------------------------

    def _do_survival_roll(self) -> None:
        """Roll survival for the current term."""
        state = self.app.engine.state
        career_id = state.character.career
        term_number = state.character.terms + 1
        career = self.app.pack.careers[career_id]

        self._narrate_section(f"Term {term_number} — {career.name}")

        # Start the term and roll survival.
        result = self.app.runner.start_term(career_id, term_number)
        self.app.runner.run_survival_step(career_id, result)
        self._current_term_result = result

        # Show the detailed survival roll.
        self._narrate_roll(
            "Survival",
            f"2D6({result.survival_raw})",
            result.survival_raw,
            result.survival_dm,
            result.survival_target,
            result.survival_success,
            "MISHAP" if result.mishap else ("DEATH" if result.died else ""),
        )
        self._narrate(
            f"  [dim]{career.survival.characteristic} "
            f"{state.character.characteristics.get(career.survival.characteristic, 0)}"
            f" -> DM {'+' if result.survival_dm >= 0 else ''}{result.survival_dm}[/dim]"
        )

        if result.died:
            self._narrate(
                "[bold red]Your character did not survive character generation.[/bold red]"
            )
            self._complete_term_narration(result)
            return

        if result.mishap:
            self._narrate(
                "[yellow]A serious mishap ends your career.[/yellow]"
            )
            self._complete_term_narration(result)
            return

        self._narrate("[green]Survived.[/green]")
        self._narrate(
            f"[dim]Age {result.age_before} -> {result.age_after}, "
            f"Term {term_number}[/dim]"
        )

        # Advance to the advancement phase.
        self._set_term_phase("run_advancement")
        self._post_step()
        self.phase = self._determine_phase()

    def _do_advancement_roll(self) -> None:
        """Roll advancement for the current term."""
        state = self.app.engine.state
        career_id = state.character.career
        result = self._current_term_result
        if result is None:
            return

        career = self.app.pack.careers[career_id]
        self.app.runner.run_advancement_step(career_id, result)

        # Show the detailed advancement roll.
        self._narrate_roll(
            "Advancement",
            f"2D6({result.advancement_raw})",
            result.advancement_raw,
            result.advancement_dm,
            result.advancement_target,
            result.advancement_success,
        )
        self._narrate(
            f"  [dim]{career.advancement.characteristic} "
            f"{state.character.characteristics.get(career.advancement.characteristic, 0)}"
            f" -> DM {'+' if result.advancement_dm >= 0 else ''}{result.advancement_dm}[/dim]"
        )

        if result.advancement_success:
            rank_title = ""
            if career.ranks:
                matching = [r for r in career.ranks if r.rank == state.character.rank]
                if matching:
                    rank_title = matching[0].title
            promoted_to = f" to {rank_title}" if rank_title else ""
            self._narrate(f"[green]Promoted{promoted_to} (Rank {result.rank_after}).[/green]")
        else:
            self._narrate("[yellow]Passed over for advancement.[/yellow]")

        # Determine number of skill rolls and enter choose_skills.
        num_rolls = self.app.runner.compute_num_skill_rolls(result)
        self._skill_rolls_remaining = num_rolls
        self._narrate(
            f"[dim]Skill rolls available: {num_rolls} "
            f"(base 1{'+ advancement' if result.advancement_success else ''}"
            f"{'+ rank 3+' if state.character.rank >= 3 else ''})[/dim]"
        )

        self._set_term_phase("choose_skills")
        self._post_step()
        self.phase = self._determine_phase()

    def _do_skill_table_choice(self, table_name: str) -> None:
        """Roll on the player's chosen skill table."""
        state = self.app.engine.state
        career_id = state.character.career
        result = self._current_term_result
        if result is None or self._skill_rolls_remaining <= 0:
            return

        gain = self.app.runner.run_skill_roll_step(
            career_id, result, table_name
        )
        self._skill_rolls_remaining -= 1

        # Display the skill roll result.
        if gain.gain_type == "skill":
            skill_display = gain.gain_name.replace("_", " ").title()
            self._narrate(
                f"  [bold]{table_name}[/bold] "
                f"(roll {gain.roll}): [cyan]{skill_display}[/cyan] +1"
            )
        else:
            self._narrate(
                f"  [bold]{table_name}[/bold] "
                f"(roll {gain.roll}): [cyan]+1 {gain.gain_name}[/cyan]"
            )

        if self._skill_rolls_remaining > 0:
            # Still more picks — refresh choices with updated count.
            self._post_step()
            self.phase = self._determine_phase()
        else:
            # All skill rolls done — advance to aging or re_enlist.
            state = self.app.engine.state
            if state.character.age >= 34:
                self._set_term_phase("run_aging")
            else:
                # No aging needed — finalize and narrate the term.
                self.app.runner.finalize_term(career_id, result)
                self._complete_term_narration(result)

    def _do_aging_roll(self) -> None:
        """Roll the aging check."""
        state = self.app.engine.state
        career_id = state.character.career
        result = self._current_term_result
        if result is None:
            return

        self.app.runner.run_aging_step(result)

        self._narrate_roll(
            "Aging",
            f"2D6({result.aging_raw})",
            result.aging_raw,
            0,
            8,
            result.aging_success,
        )

        if result.aging_success:
            self._narrate("[green]No aging effects.[/green]")
        else:
            parts = [
                f"{stat} -{amt}"
                for stat, amt in result.aging_reductions.items()
            ]
            self._narrate(
                f"[yellow]Aging effects: {', '.join(parts)}[/yellow]"
            )

        # Finalize the term and narrate.
        self.app.runner.finalize_term(career_id, result)
        self._complete_term_narration(result)

    def _complete_term_narration(self, result: TermResult) -> None:
        """Narrate the completed term and transition to the next phase.

        If the LLM is configured, narration runs asynchronously via a
        worker; otherwise the template narrator is used synchronously.
        """
        self._post_step()

        # Death or mishap goes to mustering_out/complete after narration.
        if result.died:
            self._narrate_paragraph(
                self.app.narrator.narrate_term(result)
            )
            self.phase = self._determine_phase()
            return

        if result.mishap:
            # Narrate, then go to mustering_out.
            self._narrate_step(
                "term", result,
                lambda: self.app.narrator.narrate_term(result),
                on_complete=lambda: self._transition_after_term(result),
            )
            return

        # Normal term completion.
        self._narrate_step(
            "term", result,
            lambda: self.app.narrator.narrate_term(result),
            on_complete=lambda: self._transition_after_term(result),
        )

    def _transition_after_term(self, result: TermResult) -> None:
        """Set the appropriate phase after term narration completes."""
        if result.died:
            self.phase = self._determine_phase()
        elif result.mishap:
            self._set_term_phase("mustering_out")
            self.phase = self._determine_phase()
        else:
            self._set_term_phase("re_enlist")
            self._post_step()
            self.phase = self._determine_phase()

    def _do_re_enlist_continue(self) -> None:
        """Player chooses to continue for another term."""
        self._current_term_result = None
        self._skill_rolls_remaining = 0
        self._set_term_phase("run_survival")
        self._post_step()
        self.phase = self._determine_phase()

    def _do_re_enlist_muster_out(self) -> None:
        """Player chooses to muster out."""
        self._set_term_phase("mustering_out")
        self._post_step()
        self.phase = self._determine_phase()

    def _do_muster_out(self) -> None:
        """Collect mustering-out benefits."""
        state = self.app.engine.state
        career_id = state.character.career

        self._narrate_section("Mustering Out")
        mo_result = self.app.runner.muster_out(career_id)

        # Show each benefit roll.
        for i, benefit in enumerate(mo_result.cash_benefits):
            roll = mo_result.cash_rolls[i] if i < len(mo_result.cash_rolls) else "?"
            self._narrate(f"  [bold]Cash[/bold] (roll {roll}): [cyan]{benefit}[/cyan]")
        for i, benefit in enumerate(mo_result.material_benefits):
            roll = mo_result.material_rolls[i] if i < len(mo_result.material_rolls) else "?"
            self._narrate(f"  [bold]Material[/bold] (roll {roll}): [cyan]{benefit}[/cyan]")

        # Narrate — LLM or template.
        self._narrate_step(
            "mustering_out", mo_result,
            lambda: self.app.narrator.narrate_mustering_out(mo_result),
            on_complete=self._finish_mustering_out,
        )

    def _finish_mustering_out(self) -> None:
        """Complete mustering out after narration."""
        # Mark mustering out as complete via the funnel so save/resume
        # can distinguish "needs mustering out" from "already done".
        self.app.engine.apply(
            SetFlagCommand(key="mustered_out", value="true")
        )

        self._post_step()
        self.phase = "complete"

    def _do_finish(self) -> None:
        """Return to the main menu."""
        # Generate full lifepath summary if LLM is configured.
        self._narrate_step(
            "lifepath_summary", None,
            lambda: "",
            on_complete=self._do_finish_actual,
        )

    def _do_finish_actual(self) -> None:
        """Actually save and return after any narration."""
        self._narrate("Campaign saved. Returning to main menu...")
        self.app.save_game()
        self.app.return_to_main_menu()

    # ------------------------------------------------------------------
    # LLM narration plumbing.
    # ------------------------------------------------------------------

    def _narrate_step(
        self,
        narration_type: str,
        result_obj,
        template_fn,
        on_complete=None,
    ) -> None:
        """Dispatch narration to LLM (async worker) or template (sync).

        Args:
            narration_type: "qualification", "term", "mustering_out",
                or "lifepath_summary".
            result_obj: The mechanical result object (QualificationResult,
                TermResult, MusteringOutResult, or None for summary).
            template_fn: Zero-arg callable that returns template prose.
            on_complete: Optional zero-arg callable invoked after the
                narration has been displayed (phase transitions go here).
        """
        if not self.app.llm_settings.is_configured:
            # Template narration — synchronous.
            prose = template_fn()
            if prose:
                self._narrate_paragraph(prose)
            if on_complete:
                on_complete()
            return

        # LLM narration — async via worker.
        cm = self.query_one(ChoiceMenuWidget)
        cm.clear_choices()
        self._narrate("[dim]Generating narration...[/dim]")

        self.run_worker(
            self._narrate_with_llm(narration_type, result_obj, template_fn, on_complete)
        )

    async def _narrate_with_llm(
        self,
        narration_type: str,
        result_obj,
        template_fn,
        on_complete=None,
    ) -> None:
        """Worker: fetch LLM narration, display it, then call on_complete."""
        # Guard against the screen being disposed while the worker runs.
        if not self._mounted or self.app.engine is None:
            if on_complete:
                on_complete()
            return
        try:
            adapter = self.app.create_llm_adapter()
            state = self.app.engine.state
            engine = self.app.engine

            if narration_type == "qualification":
                nar = await adapter.narrate_qualification(state, engine, result_obj)
            elif narration_type == "term":
                nar = await adapter.narrate_term(state, engine, result_obj)
            elif narration_type == "mustering_out":
                nar = await adapter.narrate_mustering_out(state, engine, result_obj)
            elif narration_type == "lifepath_summary":
                # Build a LifepathResult from the event log for the summary.
                from src.engine.lifepath import LifepathResult
                lifepath = self._build_lifepath_result_for_summary()
                if lifepath:
                    nar = await adapter.narrate_lifepath(state, engine, lifepath)
                else:
                    nar = None
            else:
                nar = None

            if nar and nar.prose:
                self._narrate_paragraph(nar.prose)
                if nar.llm_failed:
                    self._narrate("[dim](LLM failed — template fallback)[/dim]")
            else:
                prose = template_fn()
                if prose:
                    self._narrate_paragraph(prose)

        except Exception:
            # Fall back to template on any error.
            prose = template_fn()
            if prose:
                self._narrate_paragraph(prose)
        finally:
            if on_complete:
                on_complete()

    def _build_lifepath_result_for_summary(self):
        """Build a LifepathResult from the current state for summary narration."""
        from src.engine.lifepath import LifepathResult, MusteringOutResult

        state = self.app.engine.state
        char = state.character

        # We don't have the full TermResult history, so build a minimal
        # LifepathResult for the template fallback.
        result = LifepathResult(
            characteristics=dict(char.characteristics),
            character_alive=char.alive,
            career_id=char.career,
        )
        return result

    def _compute_skill_rolls_remaining(self) -> int:
        """Compute remaining skill rolls from instance state."""
        return self._skill_rolls_remaining

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
        try:
            self.query_one(CharacterSheetWidget).update_from_state(
                self.app.engine.state
            )
        except NoMatches:
            pass  # Screen not yet mounted or being disposed.

    def _post_step(self) -> None:
        """Common post-step actions: update sheet, auto-save (AE8)."""
        self._update_character_sheet()
        if self.app.engine is not None:
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
