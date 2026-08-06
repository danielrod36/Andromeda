"""Lifepath mini-game screen — three-panel layout (R16, AE8).

Three panels: character sheet sidebar, scrolling narrative log, choice menu.
Phase state machine is fully reconstructable from GameState, enabling
quit-and-resume with identical state (AE8).

Interactive phase flow (per CE SRD rules)::

    roll_characteristics   (pool empty — player rolls six 2D6 values)
        -> assign_characteristics  (player assigns each value, one optional reroll)
        -> choose_career
        -> run_survival     (auto-roll, show result)
        -> choose_commission (Attempt / Decline — hierarchy careers, rank 0 only)
        -> choose_advancement (Attempt / Decline — hierarchy careers with advancement)
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

import asyncio
from contextlib import suppress
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.dom import NoMatches
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Footer, Label, OptionList

from src.engine.commands import SetFlagCommand
from src.engine.lifepath import (
    ApplyAgingReductionCommand,
    EndCareerCommand,
    InjuryRollCommand,
    MishapRollCommand,
    ResolveInjuryCrisisCommand,
    TermResult,
)
from src.rulesets.base import CareerData
from src.rulesets.cepheus import CepheusRuleSet
from src.tui.widgets.character_sheet import CharacterSheetWidget
from src.tui.widgets.choice_menu import ChoiceMenuWidget
from src.tui.widgets.narrative_log import NarrativeLogWidget


def career_choice_description(career: CareerData) -> str:
    """Build the choose-career menu description for one career.

    Shows the qualification and survival targets followed by the **full**
    career description — never truncated. Theme-pack YAML descriptions are
    complete and well-authored; truncating them here cut careers mid-word.
    """
    qual = career.qualification
    surv = career.survival
    return (
        f"Qualify: {qual.characteristic} target {qual.target}. "
        f"Survival: {surv.characteristic} target {surv.target}. "
        f"{career.description.strip()}"
    )


# Phases that belong to the term sub-state-machine.
_TERM_PHASES = frozenset(
    {
        "run_survival",
        "choose_commission",
        "choose_advancement",
        "choose_skills",
        "run_aging",
        "choose_aging_reduction",
        "re_enlist",
        "mishap_roll",
        "choose_injury_stat",
        "choose_crisis_resolution",
    }
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
    /* U1/TUI-5: dimmed inputs while a worker is in flight. */
    LifepathScreen.busy #choice-menu { opacity: 0.5; }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("tab", "focus_next", "Next panel"),
        Binding("shift+tab", "focus_previous", "Prev panel"),
        Binding("c", "toggle_sheet", "Char sheet"),
        Binding("escape", "cancel_generation", "Cancel", show=True),
        Binding("pageup", "scroll_log_up", "Log up", show=False),
        Binding("pagedown", "scroll_log_down", "Log down", show=False),
        Binding("home", "scroll_log_home", "Log top", show=False),
        Binding("end", "scroll_log_end", "Log end", show=False),
    ]

    #: always_update ensures choices refresh even when phase string is unchanged.
    phase = reactive("init", always_update=True)
    #: True while a narration worker is in flight — input locked (U1/TUI-5).
    _busy = reactive(False)
    #: Current LLM attempt number for the generating indicator (U1/TUI-5).
    _narration_attempt = reactive(0)
    #: Active worker reference for Esc cancellation (U1/TUI-5).
    _active_worker = None
    _mounted = False

    def __init__(self) -> None:
        super().__init__()
        # Current term's partial result — rebuilt from events on resume.
        self._current_term_result: TermResult | None = None
        # How many skill table picks the player still has.
        self._skill_rolls_remaining: int = 0
        # Characteristic pool submenu: which char the player is choosing a
        # pool value for (None = characteristic-list step). Not serialized —
        # on resume the player re-selects; the pool itself is in state.
        self._assigning_char: str | None = None
        # Tracks whether a crisis resolution should return to the aging loop
        # (True) rather than completing the term (False, the injury default).
        self._aging_active: bool = False
        # Muster-out plan (Task 12): cached MusteringOutResult for the
        # per-roll allocation phase. Reconstructed from state on resume.
        self._muster_plan = None
        self._benefit_rolls_remaining: int = 0

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
        # Rebuild term-level instance state BEFORE phase determination:
        # _determine_phase consults _skill_rolls_remaining (choose_skills
        # exhaustion check), which is only reconstructed here. Determining
        # the phase first would read the initial 0 and skip a resumed
        # player's remaining skill picks (AE8).
        if self._get_latest_term_phase() in _TERM_PHASES:
            self._reconstruct_term_state()
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

    def _get_latest_term_phase(self) -> str | None:
        """Return the most recent ``term_phase=`` flag from the narrative log."""
        for entry in reversed(self.app.engine.state.narrative_log):
            if entry.startswith("term_phase="):
                return entry.split("=", 1)[1]
        return None

    def _set_term_phase(self, phase: str) -> None:
        """Persist a ``term_phase`` flag via the command funnel (AE8-safe)."""
        self.app.engine.apply(SetFlagCommand(key="term_phase", value=phase))

    def _determine_phase(self) -> str:
        """Determine the current lifepath phase from engine state."""
        state = self.app.engine.state
        char = state.character

        # Characteristics not fully assigned yet: a non-empty pool means the
        # player is mid-assignment (or hasn't started assigning); an empty
        # pool means they still need to roll (Task 4 pool flow).
        if len(char.characteristics) < 6:
            return "assign_characteristics" if char.unassigned_rolls else "roll_characteristics"

        # Background skills phase (B10): 3 + EDU DM picks at level 0 from
        # pack.background_skills. Runs once after characteristics are assigned
        # and before career selection. Once a career is chosen the player is
        # past this phase. Resume-safe via background_picks_remaining (Task 9).
        if not char.career:
            # Post-background term_phase flags take precedence over the
            # background gate: these are only ever set after background skills
            # have completed, so a character with one of these flags is never
            # sent back to choose_background_skills (even if a test fixture
            # left background_picks_remaining at its -1 default). EndCareerCommand
            # clears career, so mustering_out / career-change are reachable here.
            term_phase = self._get_latest_term_phase()
            if term_phase == "mustering_out":
                return "mustering_out"
            if term_phase == "muster_out_allocate":
                return "muster_out_allocate"
            if term_phase == "choose_qualification_fallback":
                return "choose_qualification_fallback"
            if term_phase == "choose_career_change":
                return "choose_career_change"
            # Background skills phase (B10): runs once after characteristics,
            # before the first career. Once any career has been started
            # (career_history non-empty), background is done and this gate is
            # skipped — so career-change/muster-out flows reach choose_career.
            if not char.career_history:
                if char.background_picks_remaining == -1:
                    return "choose_background_skills"
                if char.background_picks_remaining > 0:
                    return "choose_background_skills"
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
            # Backward compat: old saves persisted "run_advancement" (forced).
            # Treat as the new choosable advancement phase.
            if term_phase == "run_advancement":
                term_phase = "choose_advancement"
            if term_phase == "mustering_out":
                return "mustering_out"
            if term_phase == "muster_out_allocate":
                return "muster_out_allocate"
            if term_phase in _TERM_PHASES:
                # During skill selection, check if rolls are exhausted.
                if term_phase == "choose_skills":
                    remaining = self._compute_skill_rolls_remaining()
                    if remaining <= 0:
                        # All skill rolls done — advance to aging or re_enlist.
                        if char.age >= 34:
                            return "run_aging"
                        return "re_enlist"
                if term_phase == "choose_aging_reduction" and not char.pending_aging:
                    # All pending slots consumed — advance to re_enlist.
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
        surv_events = [e for e in state.events if e.command_type == "lifepath_survival"]
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
        saw_aging = False
        for event in state.events[surv_idx + 1 :]:
            if event.command_type == "lifepath_commission":
                cc = event.changes
                result.commission_raw = cc.get("raw_roll", 0)
                result.commission_dm = cc.get("char_dm", 0)
                result.commission_total = cc.get("adjusted_total", 0)
                result.commission_target = cc.get("target", 0)
                result.commission_success = cc.get("success", False)
            elif event.command_type == "lifepath_advancement":
                ac = event.changes
                result.advancement_raw = ac.get("raw_roll", 0)
                result.advancement_dm = ac.get("char_dm", 0)
                result.advancement_total = ac.get("adjusted_total", 0)
                result.advancement_success = ac.get("success", False)
                result.rank_after = ac.get("new_rank", char.rank)
            elif event.command_type == "lifepath_skill_roll":
                from src.engine.lifepath import SkillGain

                sec = event.changes
                result.skill_gains.append(
                    SkillGain(
                        table_name=sec.get("table_name", ""),
                        roll=sec.get("roll_total", 0),
                        result_text=sec.get("result_text", ""),
                        gain_type=sec.get("gain_type", "skill"),
                        gain_name=sec.get("gain_name", ""),
                    )
                )
            elif event.command_type == "lifepath_aging":
                saw_aging = True
                agc = event.changes
                result.aging_raw = agc.get("raw_roll", 0)
                result.aging_success = agc.get("success", True)
                # Graduated table (B4): slots aggregated by group for narration.
                slots = agc.get("slots", [])
                reductions: dict[str, int] = {}
                for slot in slots:
                    g = slot.get("group", "physical")
                    reductions[g] = reductions.get(g, 0) + slot.get("points", 0)
                result.aging_reductions = reductions

        self._current_term_result = result

        # Rebuild skill rolls remaining.
        phase = self._get_latest_term_phase()
        if phase == "choose_skills":
            total = self.app.runner.compute_num_skill_rolls(result)
            self._skill_rolls_remaining = total - len(result.skill_gains)

        # Rebuild the aging-active flag: if the current term had an aging roll,
        # crisis resolution should return to the aging loop (or finalise the
        # term through the aging path) rather than the injury path.
        self._aging_active = saw_aging

    def _show_resume_context(self) -> None:
        """Show a summary of existing state (useful on resume from save)."""
        state = self.app.engine.state
        char = state.character

        self._narrate_separator(f"Campaign: {self.app.campaign_name}")

        if char.name:
            self._narrate(f"[bold]{char.name}[/bold]")

        if char.characteristics:
            chars = ", ".join(f"{k} {v}" for k, v in char.characteristics.items())
            self._narrate(f"[dim]Characteristics:[/dim] {chars}")

        if char.career:
            self._narrate(
                f"[dim]Career:[/dim] {char.career.title()}, Rank {char.rank}, "
                f"{char.terms} terms, Age {char.age}"
            )

        if char.skills:
            skills = ", ".join(
                f"{s.replace('_', ' ').title()}-{v}" for s, v in sorted(char.skills.items())
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

    def watch__busy(self, busy: bool) -> None:
        """Toggle dimmed visual state when busy flag changes (U1/TUI-5)."""
        if busy:
            self.add_class("busy")
        else:
            self.remove_class("busy")
            self._narration_attempt = 0

    def watch__narration_attempt(self, attempt: int) -> None:
        """Update the status bar with the attempt counter (U1/TUI-5)."""
        if self._busy and attempt > 0:
            bar = self.query_one("#status-bar", Label)
            bar.update(f"[yellow]Generating narration… attempt {attempt}[/yellow]")

    def action_cancel_generation(self) -> None:
        """Cancel an in-flight narration worker (U1/TUI-5).

        Esc aborts the active LLM call. The worker's exception handler
        supplies template fallback prose. The engine outcome was already
        locked before narration started, so cancellation never alters
        mechanics.
        """
        if self._active_worker is not None and self._active_worker.is_running:
            self._active_worker.cancel()

    # ------------------------------------------------------------------
    # Choice management.
    # ------------------------------------------------------------------

    def _update_choices(self) -> None:
        """Populate the choice menu based on current phase."""
        cm = self.query_one(ChoiceMenuWidget)

        if self.phase == "roll_characteristics":
            cm.set_choices(
                "Begin character generation:",
                [("Roll Characteristics (2D6 x6)", "roll_pool")],
                descriptions=[
                    (
                        "Rolls six 2D6 values into a pool. You then assign each "
                        "value to STR, DEX, END, INT, EDU, or SOC — your choice."
                    )
                ],
            )
        elif self.phase == "assign_characteristics":
            self._populate_assign_choices(cm)
        elif self.phase == "choose_background_skills":
            self._populate_background_skill_choices(cm)
        elif self.phase == "choose_career":
            careers = sorted(self.app.pack.careers.values(), key=lambda c: c.name)
            choices = []
            descs = []
            for c in careers:
                choices.append((c.name, f"career:{c.id}"))
                descs.append(career_choice_description(c))
            cm.set_choices("Choose your career:", choices, descriptions=descs)
        elif self.phase == "choose_qualification_fallback":
            self._populate_qualification_fallback_choices(cm)
        elif self.phase == "choose_career_change":
            self._populate_career_change_choices(cm)
        elif self.phase == "run_survival":
            state = self.app.engine.state
            next_term = state.character.terms + 1
            career = self.app.pack.careers.get(state.character.career)
            career_name = career.name if career else state.character.career
            surv_char = career.survival.characteristic if career else "?"
            surv_target = career.survival.target if career else "?"
            cm.set_choices(
                f"Term {next_term} — Survival Check ({career_name}):",
                [(f"Roll Survival (2D6 vs {surv_target}, {surv_char})", "roll_survival")],
                descriptions=[
                    (
                        f"Roll 2D6 + {surv_char} DM vs target {surv_target}. "
                        f"Failure means death (ironman) or mishap (narrative)."
                    )
                ],
            )
        elif self.phase == "choose_commission":
            state = self.app.engine.state
            career = self.app.pack.careers.get(state.character.career)
            comm_char = career.commission.characteristic if career and career.commission else "?"
            comm_target = career.commission.target if career and career.commission else "?"
            cm.set_choices(
                f"Term {state.character.terms} — Commission Check (Rank 0):",
                [
                    (f"Attempt Commission (2D6 vs {comm_target}, {comm_char})", "roll_commission"),
                    ("Decline Commission", "decline_commission"),
                ],
                descriptions=[
                    (
                        f"Roll 2D6 + {comm_char} DM vs target {comm_target}. "
                        f"Success grants rank 1 and an extra skill roll."
                    ),
                    "Skip the commission roll this term.",
                ],
            )
        elif self.phase == "choose_advancement":
            state = self.app.engine.state
            career = self.app.pack.careers.get(state.character.career)
            adv_char = career.advancement.characteristic if career and career.advancement else "?"
            adv_target = career.advancement.target if career and career.advancement else "?"
            cm.set_choices(
                f"Term {state.character.terms} — Advancement Check:",
                [
                    (f"Attempt Advancement (2D6 vs {adv_target}, {adv_char})", "roll_advancement"),
                    ("Decline Advancement", "decline_advancement"),
                ],
                descriptions=[
                    (
                        f"Roll 2D6 + {adv_char} DM vs target {adv_target}. "
                        f"Success grants a promotion and an extra skill roll."
                    ),
                    "Skip the advancement roll this term.",
                ],
            )
        elif self.phase == "choose_skills":
            state = self.app.engine.state
            career = self.app.pack.careers.get(state.character.career)
            remaining = self._skill_rolls_remaining
            edu = state.character.characteristics.get("EDU", 0)
            choices = []
            descs = []
            for table in career.skill_tables:
                # B7: Advanced Education requires EDU 8+; hide when below.
                if table.name == "Advanced Education" and edu < 8:
                    continue
                # Build a short preview of table contents.
                skills = [e.result for e in table.entries.entries]
                preview = ", ".join(skills[:4])
                if len(skills) > 4:
                    preview += ", ..."
                choices.append((f"{table.name} ({remaining} left)", f"skill_table:{table.name}"))
                descs.append(f"Possible: {preview}")
            cm.set_choices(
                f"Choose skill tables ({remaining} roll{'s' if remaining != 1 else ''} remaining):",
                choices,
                descriptions=descs,
            )
        elif self.phase == "run_aging":
            state = self.app.engine.state
            terms = state.character.terms
            cm.set_choices(
                "Aging Check (age 34+):",
                [(f"Roll Aging (2D6 - terms={terms})", "roll_aging")],
                descriptions=[
                    (
                        f"Roll 2D6 minus terms served ({terms}). "
                        "Adjusted roll below 1 produces physical (and at deep "
                        "negatives, mental) reductions you distribute among "
                        "your characteristics."
                    )
                ],
            )
        elif self.phase == "choose_aging_reduction":
            self._populate_aging_reduction_choices(cm)
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
        elif self.phase == "mishap_roll":
            cm.set_choices(
                "Roll on the career mishap table:",
                [("Roll Mishap (1D6)", "roll_mishap")],
                descriptions=[
                    (
                        "Roll 1D6 on the career mishap table. Entries 1 and 6 "
                        "chain to the injury table."
                    )
                ],
            )
        elif self.phase == "choose_injury_stat":
            chars = self.app.engine.state.character.characteristics
            cm.set_choices(
                "Choose which physical characteristic takes the injury:",
                [
                    (f"STR ({chars.get('STR', 0)})", "injury_stat:STR"),
                    (f"DEX ({chars.get('DEX', 0)})", "injury_stat:DEX"),
                    (f"END ({chars.get('END', 0)})", "injury_stat:END"),
                ],
                descriptions=[
                    f"STR is currently {chars.get('STR', 0)}.",
                    f"DEX is currently {chars.get('DEX', 0)}.",
                    f"END is currently {chars.get('END', 0)}.",
                ],
            )
        elif self.phase == "choose_crisis_resolution":
            state = self.app.engine.state
            crisis_stat = self._find_stat_at_zero() or "a characteristic"
            can_afford = state.character.credits >= 10_000
            pay_label = (
                f"Pay Cr10,000 (have Cr{state.character.credits:,})"
                if can_afford
                else f"Pay Cr10,000 (have Cr{state.character.credits:,} — cannot afford)"
            )
            cm.set_choices(
                f"Injury crisis: {crisis_stat} reached 0. Choose your response:",
                [
                    (pay_label, "crisis_pay"),
                    ("Accept lasting scar", "crisis_scar"),
                ],
                descriptions=[
                    f"Pay for medical care. {crisis_stat} stabilises at 1.",
                    f"{crisis_stat} stabilises at 1 with a permanent severe Injury.",
                ],
            )
            if not can_afford:
                with suppress(NoMatches):
                    cm.option_list.disable_option("crisis_pay")
        elif self.phase == "mustering_out":
            cm.set_choices(
                "Your service is ending:",
                [("Begin Mustering Out", "muster_out")],
                descriptions=["Allocate benefit rolls between cash and material tables."],
            )
        elif self.phase == "muster_out_allocate":
            self._populate_muster_allocate_choices(cm)
        elif self.phase == "complete":
            state = self.app.engine.state
            label = "Character generation complete:"
            if not state.character.alive:
                label = "Character generation complete (deceased):"
            choices = []
            descs = []
            # A living, mustered-out character may enter the adventure loop.
            if state.character.alive and "mustered_out=true" in state.narrative_log:
                choices.append(("Begin Adventure", "begin_adventure"))
                descs.append(
                    "Enter the adventure loop: mission hooks, scenes, and "
                    "free-text actions with this character."
                )
            # Ironman death offers an immediate restart (AE2).
            if not state.character.alive and state.campaign.death_mode == "ironman":
                choices.append(("Begin a new lifepath", "begin_new_lifepath"))
                descs.append(
                    "Discard this dead character and start a fresh lifepath "
                    "with the same campaign settings."
                )
            choices.append(("Finish — Return to Main Menu", "finish"))
            descs.append("Save the character and return to the main menu.")
            cm.set_choices(label, choices, descriptions=descs)

    # ------------------------------------------------------------------
    # Event handlers.
    # ------------------------------------------------------------------

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Dispatch choice selection to the appropriate step handler."""
        if self._busy:
            return  # Input locked during narration (U1/TUI-5).
        option_id = event.option.id
        if option_id is None:
            return

        if option_id == "roll_pool":
            self._do_roll_pool()
        elif option_id == "reroll_pool":
            self._do_reroll_pool()
        elif option_id == "assign_back":
            self._assigning_char = None
            # Force a choice refresh (phase string is unchanged).
            self.phase = self._determine_phase()
        elif option_id and option_id.startswith("assign_char:"):
            self._assigning_char = option_id.split(":", 1)[1]
            self.phase = self._determine_phase()
        elif option_id and option_id.startswith("assign_value:"):
            idx = int(option_id.split(":", 1)[1])
            self._do_assign_characteristic(idx)
        elif option_id == "roll_survival":
            self._do_survival_roll()
        elif option_id == "roll_commission":
            self._do_commission_roll()
        elif option_id == "decline_commission":
            self._decline_commission()
        elif option_id == "decline_advancement":
            self._decline_advancement()
        elif option_id == "roll_advancement":
            self._do_advancement_roll()
        elif option_id == "roll_aging":
            self._do_aging_roll()
        elif option_id == "muster_out":
            self._do_muster_out()
        elif option_id == "claim_cash":
            self._do_claim_benefit("cash")
        elif option_id == "claim_material":
            self._do_claim_benefit("material")
        elif option_id == "finish":
            self._do_finish()
        elif option_id == "begin_adventure":
            self._do_begin_adventure()
        elif option_id == "begin_new_lifepath":
            self._do_begin_new_lifepath()
        elif option_id == "re_enlist_continue":
            self._do_re_enlist_continue()
        elif option_id == "re_enlist_muster_out":
            self._do_re_enlist_muster_out()
        elif option_id.startswith("career:"):
            career_id = option_id.split(":", 1)[1]
            self._do_choose_career(career_id)
        elif option_id == "fallback_retry":
            self._do_fallback_retry()
        elif option_id == "fallback_draft":
            self._do_fallback_draft()
        elif option_id == "fallback_drifter":
            self._do_fallback_drifter()
        elif option_id == "career_change_new":
            self._do_career_change_new()
        elif option_id == "career_change_muster":
            self._do_career_change_muster()
        elif option_id.startswith("skill_table:"):
            table_name = option_id.split(":", 1)[1]
            self._do_skill_table_choice(table_name)
        elif option_id == "roll_mishap":
            self._do_mishap_roll()
        elif option_id and option_id.startswith("injury_stat:"):
            stat = option_id.split(":", 1)[1]
            self._do_choose_injury_stat(stat)
        elif option_id == "crisis_pay":
            self._do_choose_crisis_resolution(pay=True)
        elif option_id == "crisis_scar":
            self._do_choose_crisis_resolution(pay=False)
        elif option_id and option_id.startswith("aging_stat:"):
            stat = option_id.split(":", 1)[1]
            self._do_choose_aging_reduction(stat)
        elif option_id and option_id.startswith("background_skill:"):
            skill_id = option_id.split(":", 1)[1]
            self._do_pick_background_skill(skill_id)

    # ------------------------------------------------------------------
    # Lifepath step methods.
    # ------------------------------------------------------------------

    def _do_roll_pool(self) -> None:
        """Roll the six-value characteristic pool via the engine funnel."""
        self._narrate_section("Characteristic Pool Rolls")
        pool = self.app.runner.roll_pool()

        self._narrate(f"  Rolled: {pool}")
        self._narrate("[dim]Assign each value to a characteristic — your choice.[/dim]")
        self._narrate("")

        self._post_step()
        self.phase = self._determine_phase()

    def _do_assign_characteristic(self, pool_index: int) -> None:
        """Assign one pool value to the selected characteristic (Task 4)."""
        char_name = self._assigning_char
        if char_name is None:
            return
        state = self.app.engine.state
        # Guard against a stale submenu after a reroll changed indices.
        if pool_index >= len(state.character.unassigned_rolls):
            self._assigning_char = None
            self.phase = self._determine_phase()
            return
        value = state.character.unassigned_rolls[pool_index]
        self.app.runner.assign_characteristic(char_name, pool_index)

        dm = CepheusRuleSet().characteristic_dm(value)
        dm_str = f"DM {'+' if dm >= 0 else ''}{dm}" if dm else "DM +0"
        tier = "strong" if value >= 9 else ("weak" if value <= 5 else "average")
        self._narrate(f"  [bold]{char_name}[/bold]: {value} ({dm_str}, {tier})")

        # Return to the characteristic-list step for the next pick.
        self._assigning_char = None

        state = self.app.engine.state
        if len(state.character.characteristics) >= 6:
            # All six assigned — show a summary and advance.
            self._narrate("")
            chars = state.character.characteristics
            self._narrate(
                "[green]All characteristics assigned.[/green] "
                f"{', '.join(f'{k} {v}' for k, v in chars.items())}"
            )
            self._narrate("")

        self._post_step()
        self.phase = self._determine_phase()

    def _do_reroll_pool(self) -> None:
        """Discard the pool and re-roll all six values (once, pre-assignment)."""
        old = list(self.app.engine.state.character.unassigned_rolls)
        self._narrate(f"[yellow]Rerolling pool (discarding {old})...[/yellow]")
        self.app.runner.reroll_pool()
        new = self.app.engine.state.character.unassigned_rolls
        self._narrate(f"  New pool: {list(new)}")

        # Reroll resets to the characteristic-list step.
        self._assigning_char = None
        self._post_step()
        self.phase = self._determine_phase()

    def _do_choose_career(self, career_id: str) -> None:
        """Attempt qualification for the selected career.

        On success, triggers basic training (B11): the first career's first
        term grants ALL Service Skills at level 0; later careers would prompt
        the player to choose one Service skill (handled by the
        ``choose_basic_training_skill`` phase). The first-career path is the
        common case during initial chargen.

        On failure, routes to the ``choose_qualification_fallback`` phase
        (F2 / "always more player choice") so the player chooses: a different
        career, the draft (once), or the Drifter career. The previous silent
        auto-drifter fallback was removed (Task 10).
        """
        career_name = self.app.pack.careers[career_id].name
        self._narrate_section(f"Qualification: {career_name}")
        qual = self.app.runner.qualify(career_id)

        # Show the roll. QualificationResult exposes ``raw_roll`` (the dice)
        # and ``adjusted_total`` (dice + DM); there is no ``roll_total``.
        self._narrate_roll(
            "Qualification",
            f"2D6({qual.raw_roll})",
            qual.raw_roll,
            qual.adjusted_total - qual.raw_roll,
            qual.target,
            qual.success,
        )

        # Narrate — LLM or template.
        self._narrate_step(
            "qualification",
            qual,
            lambda: self.app.narrator.narrate_qualification(qual),
        )

        if not qual.success:
            # Route to the explicit fallback choice — never auto-enter drifter.
            self._set_term_phase("choose_qualification_fallback")
            self._post_step()
            self.phase = self._determine_phase()
            return

        # Basic training (B11): first career → all Service Skills at level 0.
        # The runner is a no-op when basic_training_done is already True, so
        # re-entry after save/resume is safe.
        self._run_basic_training_for_career(career_id)

        self._post_step()
        self.phase = self._determine_phase()

    def _run_basic_training_for_career(self, career_id: str) -> None:
        """Trigger basic training on first-term career entry (B11).

        For the first career (empty ``career_history``) the runner grants all
        Service Skills at level 0 automatically. For later careers the player
        would choose one Service skill — that path is not yet wired in the TUI
        because the initial chargen flow only enters one career; the engine
        API (``run_basic_training(career_id, chosen_skill=...)``) supports it
        for future use.
        """
        state = self.app.engine.state
        if state.character.basic_training_done:
            return
        if not state.character.career_history:
            # First career: grant all Service Skills at level 0 (no choice).
            career = self.app.pack.careers.get(career_id)
            if career is None:
                return
            self._narrate_section("Basic Training")
            self.app.runner.run_basic_training(career_id)
            service = next(
                (t for t in career.skill_tables if t.name == "Service Skills"),
                None,
            )
            if service is not None:
                granted = [
                    e.result for e in service.entries.entries if not e.result.startswith("+")
                ]
                listed = ", ".join(s.replace("_", " ").title() for s in granted)
                self._narrate(f"  [green]Service Skills granted (level 0):[/green] {listed}")
            self._narrate("")

    # ------------------------------------------------------------------
    # Qualification-fallback choice (Task 10 — F2 / player agency).
    # ------------------------------------------------------------------

    def _populate_qualification_fallback_choices(self, cm: ChoiceMenuWidget) -> None:
        """Populate the choose_qualification_fallback menu (F2).

        Three explicit paths — never silent:
          1. Choose a different career (returns to ``choose_career``).
          2. Submit to the draft (hidden if already drafted or pack has no
             draft table).
          3. Enter the Drifter career (only if the pack defines one).
        """
        char = self.app.engine.state.character
        pack = self.app.pack

        prompt = "Qualification failed. Choose your path:"
        choices: list[tuple[str, str]] = [
            ("Choose a different career", "fallback_retry"),
        ]
        descs: list[str] = [
            "Return to the career list and attempt a different qualification.",
        ]

        if not char.drafted and pack.draft_table:
            choices.append(("Submit to the draft (1D6)", "fallback_draft"))
            descs.append(
                "Roll 1D6 on the pack's 6-entry draft table. Your career is "
                "set by the roll; you can only be drafted once."
            )

        if "drifter" in pack.careers:
            choices.append(("Enter the Drifter career", "fallback_drifter"))
            descs.append(
                "Attempt drifter qualification (SOC target 2 — almost always "
                "succeeds). The drifter has no ranks or commission."
            )

        cm.set_choices(prompt, choices, descriptions=descs)

    def _do_fallback_retry(self) -> None:
        """Player chose 'different career' — clear the fallback flag and
        return to ``choose_career``.

        Overwrites the persisted ``term_phase`` flag with a sentinel so that
        resume doesn't land back in the fallback phase.
        """
        self._set_term_phase("choose_career")
        self._post_step()
        self.phase = self._determine_phase()

    def _do_fallback_draft(self) -> None:
        """Player chose 'submit to the draft' — apply DraftCommand + basic
        training, then route to ``run_survival``.

        ``DraftCommand`` rejects a re-draft (``character.drafted`` already
        True); the menu hides the option in that case, but the engine
        invariant is the command's ``validate``.
        """
        self._narrate_section("The Draft")
        try:
            career_id = self.app.runner.run_draft()
        except ValueError as exc:
            self._narrate(f"[red]Draft unavailable: {exc}[/red]")
            self._post_step()
            self.phase = self._determine_phase()
            return
        career_name = self.app.pack.careers[career_id].name
        self._narrate(f"  [green]Drafted into: {career_name}.[/green]")
        self._run_basic_training_for_career(career_id)
        self._post_step()
        self.phase = self._determine_phase()

    def _do_fallback_drifter(self) -> None:
        """Player chose 'enter the drifter career' — attempt drifter qual.

        On success, basic training runs and the term begins. On failure (very
        unlikely with SOC 2+ target) the player is routed back to the
        fallback choice.
        """
        self._narrate_section("Qualification: Drifter")
        qual = self.app.runner.qualify("drifter")
        self._narrate_roll(
            "Qualification",
            f"2D6({qual.raw_roll})",
            qual.raw_roll,
            qual.adjusted_total - qual.raw_roll,
            qual.target,
            qual.success,
        )
        self._narrate_step(
            "qualification",
            qual,
            lambda: self.app.narrator.narrate_qualification(qual),
        )
        if qual.success:
            self._run_basic_training_for_career("drifter")
            self._post_step()
            self.phase = self._determine_phase()
        else:
            # Drifter qual failed (rare) — keep the fallback phase active so
            # the player can pick retry or draft instead.
            self._post_step()
            self.phase = self._determine_phase()

    # ------------------------------------------------------------------
    # Career-change choice (Task 11 — B17 / player agency).
    # ------------------------------------------------------------------

    def _end_career_then_choose_or_muster(self, ended_by: str) -> None:
        """Record the just-ended career, then offer a new career (B17) when
        the character is under mandatory retirement, else go to mustering out.

        ``terms`` is the total across all careers and drives the 7-term cap.
        """
        state = self.app.engine.state
        if state.character.career:
            self.app.engine.apply(EndCareerCommand(ended_by=ended_by))
        if state.character.terms < 7:
            self._set_term_phase("choose_career_change")
        else:
            self._set_term_phase("mustering_out")
        self._post_step()
        self.phase = self._determine_phase()

    def _end_career_then_muster_out(self, ended_by: str) -> None:
        """Record the just-ended career and go straight to mustering out
        (no career-change offer — e.g. mandatory retirement)."""
        state = self.app.engine.state
        if state.character.career:
            self.app.engine.apply(EndCareerCommand(ended_by=ended_by))
        self._set_term_phase("mustering_out")
        self._post_step()
        self.phase = self._determine_phase()

    def _populate_career_change_choices(self, cm: ChoiceMenuWidget) -> None:
        """Offer mustering out or attempting a new career (B17)."""
        history = self.app.engine.state.character.career_history
        dm = -2 * len(history)
        cm.set_choices(
            "Your career has ended. What next?",
            [
                ("Try a new career", "career_change_new"),
                ("Muster out (end character creation)", "career_change_muster"),
            ],
            descriptions=[
                (
                    f"Return to the career list. Qualification is at DM {dm:+d} "
                    f"({len(history)} previous career(s)). You cannot re-enter a "
                    f"career you have already left, except the Drifter."
                ),
                "End character creation and roll mustering-out benefits.",
            ],
        )

    def _do_career_change_new(self) -> None:
        """Player chose to try a new career — return to ``choose_career``."""
        self._set_term_phase("choose_career")
        self._post_step()
        self.phase = self._determine_phase()

    def _do_career_change_muster(self) -> None:
        """Player chose to muster out — go to ``mustering_out``."""
        self._set_term_phase("mustering_out")
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
            self._narrate("[yellow]A serious mishap ends your career.[/yellow]")
            # Enter the interactive mishap flow (resume-safe via term_phase).
            # The player rolls the mishap, chooses an injury stat if needed,
            # and decides crisis resolution — no auto-resolution.
            self._set_term_phase("mishap_roll")
            self._post_step()
            self.phase = self._determine_phase()
            return

        self._narrate("[green]Survived.[/green]")
        self._narrate(
            f"[dim]Age {result.age_before} -> {result.age_after}, Term {term_number}[/dim]"
        )

        # Route to the next term phase: commission (if available), then
        # advancement (if the career has it), else straight to skill rolls.
        self._advance_after_survival(career_id)
        self._post_step()
        self.phase = self._determine_phase()

    # ------------------------------------------------------------------
    # Mishap / injury / crisis interactive handlers (B13 — player agency).
    # ------------------------------------------------------------------

    def _find_stat_at_zero(self) -> str | None:
        """Return the first characteristic at or below 0, or None.

        Scans all six characteristics, physical-first (STR, DEX, END, then
        INT, EDU, SOC), so that both aging crises (which can drive a mental
        stat to 0 via the graduated table's ``mental`` slot) and injury
        crises (physical-only) are detected. Injury only ever reduces
        physical characteristics, so a physical stat at 0 is always found
        before any mental stat is considered — injury behavior is unchanged.
        """
        chars = self.app.engine.state.character.characteristics
        for stat in ("STR", "DEX", "END", "INT", "EDU", "SOC"):
            if chars.get(stat, 0) <= 0:
                return stat
        return None

    def _do_mishap_roll(self) -> None:
        """Roll the career mishap table (step 1 of the interactive mishap flow).

        Applies :class:`MishapRollCommand` via the funnel, shows the result,
        and transitions to ``choose_injury_stat`` if the entry chains to
        injury (roll 1 or 6) and the pack has an injury table. Otherwise
        completes the term narration.
        """
        result = self._current_term_result
        if result is None:
            return

        state = self.app.engine.state
        career_id = state.character.career
        career = self.app.pack.careers.get(career_id)
        if career is None or career.mishap_table is None:
            self._complete_term_narration(result)
            return

        event = self.app.engine.apply(
            MishapRollCommand(career_id=career_id, entries=career.mishap_table.entries)
        )
        mc = event.changes
        self._narrate(f"  Mishap (roll {mc['roll_total']}): {mc['result_text']}")

        if mc["injury"] and self.app.pack.injury_table is not None:
            self._narrate("[yellow]The mishap results in physical injury.[/yellow]")
            self._set_term_phase("choose_injury_stat")
            self._post_step()
            self.phase = self._determine_phase()
        else:
            self._complete_term_narration(result)

    def _do_choose_injury_stat(self, stat: str) -> None:
        """Apply the injury roll with the player's chosen stat (step 2).

        Applies :class:`InjuryRollCommand` via the funnel, shows the
        reduction, then either transitions to ``choose_crisis_resolution``
        (stat at 0, non-ironman), auto-resolves death (ironman), or
        completes the term narration.
        """
        result = self._current_term_result
        if result is None:
            return

        state = self.app.engine.state
        injury_table = self.app.pack.injury_table
        if injury_table is None:
            self._complete_term_narration(result)
            return

        event = self.app.engine.apply(
            InjuryRollCommand(entries=injury_table.entries, chosen_stat=stat)
        )
        ic = event.changes
        reductions = ic["reductions"]
        rstr = ", ".join(f"{s} -{a}" for s, a in reductions.items())
        self._narrate(f"  [red]Injury: {rstr}[/red]")

        crisis_stat = self._find_stat_at_zero()
        if crisis_stat:
            if state.campaign.death_mode == "ironman":
                # Ironman: crisis is mandatory death (no player choice).
                self.app.engine.apply(ResolveInjuryCrisisCommand(stat=crisis_stat, pay=False))
                self._narrate(
                    f"[bold red]Injury crisis! {crisis_stat} reached 0. "
                    f"Ironman rule: the character dies.[/bold red]"
                )
                result.died = True
                self._complete_term_narration(result)
            else:
                self._narrate(f"[bold red]Injury crisis! {crisis_stat} reached 0.[/bold red]")
                self._set_term_phase("choose_crisis_resolution")
                self._post_step()
                self.phase = self._determine_phase()
        else:
            self._complete_term_narration(result)

    def _do_choose_crisis_resolution(self, pay: bool) -> None:
        """Apply the player's crisis resolution choice (step 3).

        Applies :class:`ResolveInjuryCrisisCommand` via the funnel, narrates
        the outcome. Returns to the aging-reduction loop when ``_aging_active``
        is set and pending slots remain; otherwise completes the term.
        """
        result = self._current_term_result
        if result is None:
            return

        crisis_stat = self._find_stat_at_zero()
        if not crisis_stat:
            self._after_crisis_resolution(result)
            return

        event = self.app.engine.apply(ResolveInjuryCrisisCommand(stat=crisis_stat, pay=pay))
        outcome = event.changes["outcome"]
        if outcome == "paid_cr10000":
            self._narrate(f"[green]Paid Cr10,000 — {crisis_stat} stabilised at 1.[/green]")
        elif outcome == "death":
            self._narrate(f"[bold red]{crisis_stat} crisis: the character has died.[/bold red]")
            result.died = True
        elif outcome == "scarred":
            self._narrate(f"[yellow]{crisis_stat} stabilised at 1 with a lasting scar.[/yellow]")

        self._after_crisis_resolution(result)

    def _after_crisis_resolution(self, result: TermResult) -> None:
        """Transition after a crisis is resolved.

        If the aging loop is active and slots remain, return to it; if the
        aging loop is active but empty, finalise the term. Otherwise (injury
        crisis path) complete the term narration as before.
        """
        if result.died:
            self._aging_active = False
            self._complete_term_narration(result)
            return
        if self._aging_active:
            if self.app.engine.state.character.pending_aging:
                self._set_term_phase("choose_aging_reduction")
                self._post_step()
                self.phase = self._determine_phase()
            else:
                self._aging_active = False
                career_id = self.app.engine.state.character.career
                self.app.runner.finalize_term(career_id, result)
                self._complete_term_narration(result)
        else:
            self._complete_term_narration(result)

    def _advance_after_survival(self, career_id: str) -> None:
        """Route to the next term phase after a successful survival check.

        Order: commission (if available at rank 0), then advancement (if the
        career has it), else straight to skill rolls (B8/B9).
        """
        if self.app.runner.commission_available(career_id):
            self._set_term_phase("choose_commission")
            return
        if self.app.runner.advancement_available(career_id):
            self._set_term_phase("choose_advancement")
            return
        # Non-hierarchy (or no advancement) -> straight to skills.
        self._enter_choose_skills()

    def _do_commission_roll(self) -> None:
        """Roll commission for the current term (player chose Attempt)."""
        state = self.app.engine.state
        career_id = state.character.career
        result = self._current_term_result
        if result is None:
            return

        career = self.app.pack.careers[career_id]
        self.app.runner.run_commission_step(career_id, result)

        if result.commission_success:
            self._narrate_roll(
                "Commission",
                f"2D6({result.commission_raw})",
                result.commission_raw,
                result.commission_dm,
                result.commission_target,
                True,
            )
            rank_title = ""
            if career.ranks:
                matching = [r for r in career.ranks if r.rank == state.character.rank]
                if matching:
                    rank_title = matching[0].title
            commissioned_to = f" ({rank_title})" if rank_title else ""
            self._narrate(f"[green]Commissioned{commissioned_to} (Rank 1).[/green]")
        else:
            self._narrate_roll(
                "Commission",
                f"2D6({result.commission_raw})",
                result.commission_raw,
                result.commission_dm,
                result.commission_target,
                False,
            )
            self._narrate("[yellow]Passed over for commission.[/yellow]")

        self._advance_after_commission(career_id)

    def _decline_commission(self) -> None:
        """Skip the commission roll (player chose Decline)."""
        state = self.app.engine.state
        career_id = state.character.career
        self._narrate("[dim]Commission declined.[/dim]")
        self._advance_after_commission(career_id)

    def _advance_after_commission(self, career_id: str) -> None:
        """Route to advancement (if available) or skill rolls after commission."""
        if self.app.runner.advancement_available(career_id):
            self._set_term_phase("choose_advancement")
        else:
            self._enter_choose_skills()
        self._post_step()
        self.phase = self._determine_phase()

    def _decline_advancement(self) -> None:
        """Skip the advancement roll (player chose Decline)."""
        self._narrate("[dim]Advancement declined.[/dim]")
        self._enter_choose_skills()

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

        self._enter_choose_skills()

    def _enter_choose_skills(self) -> None:
        """Compute skill rolls and transition to the choose_skills phase.

        The count reflects commission/advancement outcomes (B8/B9): 2 for
        non-hierarchy careers, else 1; +1 commission success, +1 advancement
        success. The rank>=3 bonus has no SRD basis and was removed (N2).
        """
        result = self._current_term_result
        if result is None:
            return
        num_rolls = self.app.runner.compute_num_skill_rolls(result)
        self._skill_rolls_remaining = num_rolls
        career = self.app.pack.careers.get(result.career_id)
        base = 1 if (career and career.has_hierarchy) else 2
        parts = [f"base {base}"]
        if result.commission_success:
            parts.append("+ commission")
        if result.advancement_success:
            parts.append("+ advancement")
        self._narrate(f"[dim]Skill rolls available: {num_rolls} ({' '.join(parts)})[/dim]")

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

        gain = self.app.runner.run_skill_roll_step(career_id, result, table_name)
        self._skill_rolls_remaining -= 1

        # Display the skill roll result.
        if gain.gain_type == "skill":
            skill_display = gain.gain_name.replace("_", " ").title()
            self._narrate(
                f"  [bold]{table_name}[/bold] (roll {gain.roll}): [cyan]{skill_display}[/cyan] +1"
            )
        else:
            self._narrate(
                f"  [bold]{table_name}[/bold] (roll {gain.roll}): [cyan]+1 {gain.gain_name}[/cyan]"
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
                # Advance the UI too: without this the choice menu keeps
                # showing skill tables with "0 left" and the player is
                # soft-locked out of the aging roll.
                self._post_step()
                self.phase = self._determine_phase()
            else:
                # No aging needed — finalize and narrate the term.
                self.app.runner.finalize_term(career_id, result)
                self._complete_term_narration(result)

    def _do_aging_roll(self) -> None:
        """Roll the graduated aging check (2D6 - terms, B4).

        On a no-effect roll (adjusted >= 1) the term finalises immediately.
        Otherwise the player enters ``choose_aging_reduction`` to assign each
        pending slot to a characteristic of the matching group.
        """
        state = self.app.engine.state
        career_id = state.character.career
        result = self._current_term_result
        if result is None:
            return

        terms = state.character.terms
        self.app.runner.run_aging_step(result)

        adjusted = result.aging_raw - terms
        self._narrate_roll(
            "Aging",
            f"2D6({result.aging_raw}) - terms({terms})",
            result.aging_raw,
            -terms,
            1,  # conceptual threshold: adjusted >= 1 means no effect
            result.aging_success,
            tier=f"adjusted {adjusted}",
        )

        if result.aging_success:
            self._narrate("[green]No aging effects.[/green]")
            self.app.runner.finalize_term(career_id, result)
            self._complete_term_narration(result)
        else:
            parts = [f"{grp} -{amt}" for grp, amt in result.aging_reductions.items()]
            self._narrate(
                f"[yellow]Aging effects pending: {', '.join(parts)}. "
                f"Choose which characteristics take the reductions.[/yellow]"
            )
            self._aging_active = True
            self._set_term_phase("choose_aging_reduction")
            self._post_step()
            self.phase = self._determine_phase()

    def _populate_aging_reduction_choices(self, cm: ChoiceMenuWidget) -> None:
        """Populate the choose_aging_reduction submenu (B4 player agency).

        Shows the first pending slot's group and points, offering each
        characteristic in that group as a choice. The player picks where the
        reduction goes; the loop continues until pending_aging is empty.
        """
        from src.engine.lifepath import _PHYSICAL_CHARACTERISTICS

        char = self.app.engine.state.character
        pending = char.pending_aging
        if not pending:
            return
        slot = pending[0]
        group = slot.group
        points = slot.points
        stats = list(_PHYSICAL_CHARACTERISTICS) if group == "physical" else ["INT", "EDU", "SOC"]
        prompt = (
            f"Aging reduction ({group} -{points}). "
            f"Choose a characteristic ({len(pending)} slot(s) left):"
        )
        choices = []
        descs = []
        for s in stats:
            val = char.characteristics.get(s, 0)
            choices.append((f"{s} ({val})", f"aging_stat:{s}"))
            descs.append(
                f"{s} is currently {val}. "
                f"Reducing by {points}{' — crisis at 0!' if val - points <= 0 else ''}."
            )
        cm.set_choices(prompt, choices, descriptions=descs)

    def _do_choose_aging_reduction(self, stat: str) -> None:
        """Apply one pending aging slot to the player's chosen characteristic.

        Consumes from the first matching-group slot, narrates the reduction,
        and either routes to crisis resolution (stat at 0), continues the
        aging loop (more slots), or finalises the term (all slots consumed).
        """
        state = self.app.engine.state
        career_id = state.character.career
        result = self._current_term_result
        if result is None or not state.character.pending_aging:
            return

        slot = state.character.pending_aging[0]
        event = self.app.engine.apply(
            ApplyAgingReductionCommand(characteristic=stat, points=slot.points)
        )
        new_val = event.changes["new_value"]
        self._narrate(f"  [red]Aging: {stat} -{slot.points} (now {new_val})[/red]")

        if event.changes.get("crisis"):
            if state.campaign.death_mode == "ironman":
                self.app.engine.apply(ResolveInjuryCrisisCommand(stat=stat, pay=False))
                self._narrate(
                    f"[bold red]Aging crisis! {stat} reached 0. "
                    f"Ironman rule: the character dies.[/bold red]"
                )
                if result is not None:
                    result.died = True
                self._aging_active = False
                self._complete_term_narration(result)
            else:
                self._narrate(f"[bold red]Aging crisis! {stat} reached 0.[/bold red]")
                self._set_term_phase("choose_crisis_resolution")
                self._post_step()
                self.phase = self._determine_phase()
            return

        # No crisis — check for remaining slots.
        if state.character.pending_aging:
            self._post_step()
            self.phase = self._determine_phase()
        else:
            self._aging_active = False
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
            self._narrate_paragraph(self.app.narrator.narrate_term(result))
            self.phase = self._determine_phase()
            return

        if result.mishap:
            # Narrate, then go to mustering_out.
            self._narrate_step(
                "term",
                result,
                lambda: self.app.narrator.narrate_term(result),
                on_complete=lambda: self._transition_after_term(result),
            )
            return

        # Normal term completion.
        self._narrate_step(
            "term",
            result,
            lambda: self.app.narrator.narrate_term(result),
            on_complete=lambda: self._transition_after_term(result),
        )

    def _transition_after_term(self, result: TermResult) -> None:
        """Set the appropriate phase after term narration completes.

        For normal (non-death, non-mishap) term completion, runs the SRD
        re-enlistment roll (B12) and honors forced outcomes:
        ``must_continue`` auto-advances to the next term; ``must_leave``/
        ``must_retire`` route to mustering out; ``may_continue`` falls through
        to the player-driven Continue/Muster Out choice in ``re_enlist``.
        """
        if result.died:
            self.phase = self._determine_phase()
        elif result.mishap:
            # Career ended early via mishap — offer a new career if the
            # character is still short of mandatory retirement (B17).
            self._end_career_then_choose_or_muster(ended_by="mishap")
        else:
            self._set_term_phase("re_enlist")
            career_id = self.app.engine.state.character.career
            outcome = self._resolve_reenlistment(career_id)
            if outcome == "must_continue":
                self._narrate(
                    "[bold green]A natural 12 — you must re-enlist for another term![/bold green]"
                )
                self._current_term_result = None
                self._skill_rolls_remaining = 0
                self._set_term_phase("run_survival")
            elif outcome in ("must_leave", "must_retire"):
                if outcome == "must_retire":
                    self._narrate(
                        "[bold yellow]Mandatory retirement (7+ terms) — "
                        "time to muster out.[/bold yellow]"
                    )
                    # 7+ total terms: no career change allowed (B17).
                    self._end_career_then_muster_out(ended_by="muster_out")
                else:
                    self._narrate(
                        "[bold yellow]The career releases you — time to muster out.[/bold yellow]"
                    )
                    self._end_career_then_choose_or_muster(ended_by="muster_out")
            # else: may_continue — re_enlist phase shows the Continue/Muster
            # Out choice to the player.
            self._post_step()
            self.phase = self._determine_phase()

    def _get_reenlistment_outcome(self) -> str | None:
        """Return the persisted re-enlistment outcome for the current term.

        Looks for a ``reenlist_outcome=`` flag that was set AFTER the most
        recent ``term_phase=re_enlist`` flag, so stale outcomes from prior
        terms never suppress a fresh roll. Returns ``None`` when no outcome
        has been persisted for the current term yet (resume-safety).
        """
        log = self.app.engine.state.narrative_log
        reenlist_idx = None
        for i in range(len(log) - 1, -1, -1):
            if log[i] == "term_phase=re_enlist":
                reenlist_idx = i
                break
        if reenlist_idx is None:
            return None
        for entry in log[reenlist_idx + 1 :]:
            if entry.startswith("reenlist_outcome="):
                return entry.split("=", 1)[1]
        return None

    def _resolve_reenlistment(self, career_id: str) -> str:
        """Run the re-enlistment roll once per term; honor the persisted flag.

        On first entry the SRD re-enlistment roll (B12) is applied through the
        runner, narrated, and its outcome persisted via the funnel so a
        save/resume cycle doesn't re-roll. On resume the persisted outcome is
        returned directly.
        """
        outcome = self._get_reenlistment_outcome()
        if outcome is not None:
            return outcome

        state = self.app.engine.state
        career = self.app.pack.careers.get(career_id)
        career_name = career.name if career else career_id
        target = career.re_enlistment if career else None

        self._narrate_section(f"Re-enlistment ({career_name})")
        outcome = self.app.runner.run_reenlistment_step(career_id)

        # Narrate the result from the event the command just appended.
        reenlist_event = state.events[-1]
        if reenlist_event.roll is not None:
            raw = sum(reenlist_event.roll.rolls)
            if raw == 12:
                self._narrate(
                    f"  Re-enlistment roll: 2D6={raw} — natural 12! "
                    f"You [bold green]must[/bold green] continue."
                )
            elif outcome == "must_leave":
                self._narrate(
                    f"  Re-enlistment roll: 2D6={raw} vs target {target} — "
                    f"[bold red]must leave[/bold red] the career."
                )
            else:
                self._narrate(
                    f"  Re-enlistment roll: 2D6={raw} vs target {target} — "
                    f"you may continue or muster out."
                )
        elif outcome == "must_retire":
            self._narrate("  7+ terms served — [bold red]mandatory retirement[/bold red].")
        else:
            self._narrate(f"  Re-enlistment: {outcome}.")

        # Persist via the funnel so resume doesn't re-roll (B12 resume-safety).
        self.app.engine.apply(SetFlagCommand(key="reenlist_outcome", value=outcome))
        return outcome

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

    def _get_muster_career_id(self) -> str:
        """Return the career id for mustering out (current or last in history)."""
        state = self.app.engine.state
        if state.character.career:
            return state.character.career
        if state.character.career_history:
            return state.character.career_history[-1].career_id
        return ""

    def _do_muster_out(self) -> None:
        """Begin mustering out: compute the plan and enter per-roll allocation."""
        career_id = self._get_muster_career_id()
        if not career_id:
            self._finish_mustering_out()
            return

        self._narrate_section("Mustering Out")
        plan = self.app.runner.muster_out(career_id)
        self._muster_plan = plan

        # Reconstruct cash rolls taken from events (resume safety).
        self.app.runner._cash_rolls_taken = self.app.runner._count_cash_benefit_events()

        cash_taken = self.app.runner._cash_rolls_taken
        material_taken = sum(
            1
            for e in self.app.engine.state.events
            if e.command_type == "lifepath_benefit" and e.changes.get("benefit_type") == "material"
        )
        self._benefit_rolls_remaining = plan.total_rolls - cash_taken - material_taken

        if plan.total_rolls == 0:
            self._narrate("[dim]No benefit rolls available (0 terms).[/dim]")
            self._finish_mustering_out()
            return

        self._narrate(
            f"  [dim]{plan.total_rolls} benefit roll"
            f"{'s' if plan.total_rolls != 1 else ''} available "
            f"(terms {plan.terms_served}, rank {plan.final_rank}).[/dim]"
        )
        if plan.material_dm:
            self._narrate(
                f"  [dim]Material table DM +{plan.material_dm} (rank {plan.final_rank}).[/dim]"
            )

        self._set_term_phase("muster_out_allocate")
        self._post_step()
        self.phase = self._determine_phase()

    def _populate_muster_allocate_choices(self, cm: ChoiceMenuWidget) -> None:
        """Populate the muster_out_allocate submenu (Task 12 per-roll choice).

        Shows remaining rolls and cash count; offers Cash (max 3 total) or
        Material per roll. Cash is disabled when 3 have been taken.
        """
        plan = self._muster_plan
        if plan is None:
            career_id = self._get_muster_career_id()
            plan = self.app.runner.muster_out(career_id)
            self._muster_plan = plan
            self.app.runner._cash_rolls_taken = self.app.runner._count_cash_benefit_events()
            material_taken = sum(
                1
                for e in self.app.engine.state.events
                if e.command_type == "lifepath_benefit"
                and e.changes.get("benefit_type") == "material"
            )
            self._benefit_rolls_remaining = (
                plan.total_rolls - self.app.runner._cash_rolls_taken - material_taken
            )

        remaining = self._benefit_rolls_remaining
        cash_taken = self.app.runner._cash_rolls_taken
        career_id = self._get_muster_career_id()
        career = self.app.pack.careers.get(career_id)

        if remaining <= 0:
            # All rolls exhausted — finish.
            self._finish_mustering_out()
            return

        choices: list[tuple[str, str]] = []
        descs: list[str] = []

        if career and career.mustering_out_cash and cash_taken < 3:
            choices.append((f"Cash table ({cash_taken}/3 taken)", "claim_cash"))
            descs.append(
                f"Roll on the cash benefits table. {3 - cash_taken} cash roll(s) remaining."
            )
        elif career and career.mustering_out_cash:
            choices.append(("Cash table (3/3 — full)", "claim_cash"))
            descs.append("Cash rolls exhausted (3/3 taken).")

        if career and career.mustering_out_material:
            choices.append(("Material table", "claim_material"))
            descs.append("Roll on the material benefits table for gear, passages, or perks.")

        if not choices:
            self._finish_mustering_out()
            return

        cm.set_choices(
            f"Allocate benefit roll ({remaining} remaining):",
            choices,
            descriptions=descs,
        )
        # Disable cash when at cap.
        if cash_taken >= 3:
            with suppress(NoMatches):
                cm.option_list.disable_option("claim_cash")

    def _do_claim_benefit(self, table: str) -> None:
        """Roll one benefit on the chosen table and narrate the result."""
        career_id = self._get_muster_career_id()
        plan = self._muster_plan
        if plan is None:
            plan = self.app.runner.muster_out(career_id)
            self._muster_plan = plan

        dm = 0 if table == "cash" else plan.material_dm
        try:
            result_text = self.app.runner.claim_benefit(career_id, table=table, dm=dm)
        except ValueError as exc:
            self._narrate(f"[red]{exc}[/red]")
            self._post_step()
            self.phase = self._determine_phase()
            return

        # Show the result.
        label = "Cash" if table == "cash" else "Material"
        self._narrate(f"  [bold]{label}[/bold]: [cyan]{result_text}[/cyan]")
        if table == "cash":
            self._narrate(f"  [dim]Credits: {self.app.engine.state.character.credits:,} Cr[/dim]")

        self._benefit_rolls_remaining -= 1
        self._post_step()

        if self._benefit_rolls_remaining <= 0:
            # All rolls done — narrate summary and finish.
            self._narrate_muster_summary()
        else:
            self.phase = self._determine_phase()

    def _narrate_muster_summary(self) -> None:
        """Narrate the mustering-out summary and finish."""
        state = self.app.engine.state
        char = state.character
        plan = self._muster_plan

        # Build a MusteringOutResult with collected benefits for narration.
        if plan is not None:
            cash_events = [
                e
                for e in state.events
                if e.command_type == "lifepath_benefit" and e.changes.get("benefit_type") == "cash"
            ]
            material_events = [
                e
                for e in state.events
                if e.command_type == "lifepath_benefit"
                and e.changes.get("benefit_type") == "material"
            ]
            plan.cash_benefits = [e.changes["result_text"] for e in cash_events]
            plan.material_benefits = [e.changes["result_text"] for e in material_events]

        self._narrate(
            f"  [green]Mustering out complete. "
            f"Total credits: {char.credits:,} Cr, "
            f"Inventory: {len(char.inventory)} item(s).[/green]"
        )
        self._narrate("")

        # Narrate — LLM or template.
        self._narrate_step(
            "mustering_out",
            plan,
            lambda: self.app.narrator.narrate_mustering_out(plan) if plan else "",
            on_complete=self._finish_mustering_out,
        )

    def _finish_mustering_out(self) -> None:
        """Complete mustering out after narration."""
        # Mark mustering out as complete via the funnel so save/resume
        # can distinguish "needs mustering out" from "already done".
        self.app.engine.apply(SetFlagCommand(key="mustered_out", value="true"))

        self._post_step()
        self.phase = "complete"

    def _do_finish(self) -> None:
        """Return to the main menu."""
        # Generate full lifepath summary if LLM is configured.
        self._narrate_step(
            "lifepath_summary",
            None,
            lambda: "",
            on_complete=self._do_finish_actual,
        )

    def _do_finish_actual(self) -> None:
        """Actually save and return after any narration."""
        self._narrate("Campaign saved. Returning to main menu...")
        self.app.save_game()
        self.app.return_to_main_menu()

    def _do_begin_adventure(self) -> None:
        """Enter the adventure loop with the mustered-out character."""
        self._narrate("Campaign saved. Beginning the adventure...")
        self.app.start_adventure()

    def _do_begin_new_lifepath(self) -> None:
        """Ironman death restart (AE2): discard the dead character and start a
        fresh lifepath with the same campaign configuration."""
        self._narrate(
            "[bold yellow]Beginning a new lifepath with the same campaign settings...[/bold yellow]"
        )
        self.app.restart_lifepath()

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
        self._busy = True  # U1/TUI-5: input lock.
        self._narration_attempt = 0
        self._narrate("[dim]Generating narration...[/dim]")

        self._active_worker = self.run_worker(
            self._narrate_with_llm(narration_type, result_obj, template_fn, on_complete)
        )

    async def _narrate_with_llm(
        self,
        narration_type: str,
        result_obj,
        template_fn,
        on_complete=None,
    ) -> None:
        """Worker: fetch LLM narration, display it, then call on_complete.

        U1/TUI-5: passes an ``on_attempt`` callback so the generating
        indicator reflects the current attempt number. The busy flag is
        cleared in the ``finally`` block.
        """
        # Guard against the screen being disposed while the worker runs.
        if not self._mounted or self.app.engine is None:
            self._busy = False
            self._active_worker = None
            if on_complete:
                on_complete()
            return
        try:
            adapter = self.app.create_llm_adapter()
            # Task 24: None-check — if the adapter is not configured (e.g.
            # settings changed at runtime), fall back to template immediately.
            if adapter is None:
                prose = template_fn()
                if prose:
                    self._narrate_paragraph(prose)
                if on_complete:
                    on_complete()
                return
            state = self.app.engine.state
            engine = self.app.engine

            def attempt_cb(k: int) -> None:
                self._narration_attempt = k

            if narration_type == "qualification":
                nar = await adapter.narrate_qualification(
                    state, engine, result_obj, on_attempt=attempt_cb
                )
            elif narration_type == "term":
                nar = await adapter.narrate_term(state, engine, result_obj, on_attempt=attempt_cb)
            elif narration_type == "mustering_out":
                nar = await adapter.narrate_mustering_out(
                    state, engine, result_obj, on_attempt=attempt_cb
                )
            elif narration_type == "lifepath_summary":
                # Build a LifepathResult from the event log for the summary.
                lifepath = self._build_lifepath_result_for_summary()
                if lifepath:
                    nar = await adapter.narrate_lifepath(
                        state, engine, lifepath, on_attempt=attempt_cb
                    )
                else:
                    nar = None
            else:
                nar = None

            if nar and nar.prose:
                self._narrate_paragraph(nar.prose)
                if nar.llm_failed:
                    self._narrate("[dim](LLM failed — template fallback)[/dim]")
                    self._update_status_bar(nar.failure_kind)
                else:
                    self._update_status_bar()
            else:
                prose = template_fn()
                if prose:
                    self._narrate_paragraph(prose)

        except asyncio.CancelledError:
            # U1/TUI-5: Esc pressed — show template fallback prose.
            prose = template_fn()
            if prose:
                self._narrate_paragraph(prose)
            self._update_status_bar()
        except Exception:
            # Fall back to template on any error.
            prose = template_fn()
            if prose:
                self._narrate_paragraph(prose)
            self._update_status_bar()
        finally:
            self._busy = False
            self._active_worker = None
            if on_complete:
                on_complete()

    def _build_lifepath_result_for_summary(self):
        """Build a LifepathResult from the current state for summary narration."""
        from src.engine.lifepath import LifepathResult

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

    def _populate_assign_choices(self, cm: ChoiceMenuWidget) -> None:
        """Populate the assign_characteristics submenu (Task 4).

        Two-step flow driven by ``self._assigning_char``:

        * None  — characteristic-list step: each unassigned characteristic is
          a choice, plus a "Reroll pool (once)" option when the reroll is
          still available (omitted once ``pool_rerolled`` is set — the brief's
          "disabled when pool_rerolled" is realised as "not offered", since a
          terminal OptionList has no disabled state).
        * set   — pool-value step: each remaining pool value is a choice for
          the selected characteristic, plus a "Back" option.
        """
        from src.engine.lifepath import _CHARACTERISTICS

        char = self.app.engine.state.character
        pool = char.unassigned_rolls

        # Step 2: a characteristic is selected — show pool values.
        if self._assigning_char is not None:
            prompt = f"Assign pool value to {self._assigning_char} (pool: {pool}):"
            choices: list[tuple[str, str]] = [
                (f"Assign {val} to {self._assigning_char}", f"assign_value:{idx}")
                for idx, val in enumerate(pool)
            ]
            descs = [f"Pool slot {idx}: 2D6={value}." for idx, value in enumerate(pool)]
            choices.append(("Back to characteristic list", "assign_back"))
            descs.append("Return to the list of unassigned characteristics without assigning.")
            cm.set_choices(prompt, choices, descriptions=descs)
            return

        # Step 1: list unassigned characteristics + reroll (disabled once used).
        assigned_summary = (
            ", ".join(f"{k} {v}" for k, v in char.characteristics.items()) or "none yet"
        )
        prompt = f"Assign characteristic rolls (pool: {pool}; assigned: {assigned_summary}):"
        choices = []
        descs = []
        for c in _CHARACTERISTICS:
            if c in char.characteristics:
                continue
            choices.append((f"Assign {c}", f"assign_char:{c}"))
            descs.append(f"Choose a pool value for {c}.")
        # Always show the reroll option; disable it once it can't be used
        # (already spent, or any assignment has begun). The brief specifies a
        # "disabled" reroll option when pool_rerolled is True; the engine also
        # rejects reroll after the first assignment, so we disable then too.
        reroll_used = char.pool_rerolled or bool(char.characteristics)
        label = "Reroll pool (already used)" if reroll_used else "Reroll pool (once)"
        choices.append((label, "reroll_pool"))
        descs.append(
            "Discard the current pool and re-roll all six values. "
            "Only available before any assignment and only once."
        )
        cm.set_choices(prompt, choices, descriptions=descs)
        if reroll_used:
            with suppress(NoMatches):
                cm.option_list.disable_option("reroll_pool")

    # ------------------------------------------------------------------
    # Background skills phase (Task 9 — B10).
    # ------------------------------------------------------------------

    def _populate_background_skill_choices(self, cm: ChoiceMenuWidget) -> None:
        """Populate the choose_background_skills submenu (B10).

        Offers every pack background skill the player hasn't already picked.
        The pick count is set once via ``start_background_phase`` (computed as
        3 + EDU DM, min 0); each selection decrements
        ``background_picks_remaining``. When the count reaches zero the phase
        auto-advances to ``choose_career``.
        """
        char = self.app.engine.state.character
        # Lazily compute picks on first entry (when -1).
        if char.background_picks_remaining == -1:
            picks = self.app.runner.start_background_phase()
            self._narrate_section("Background Skills")
            edu = char.characteristics.get("EDU", 7)
            self._narrate(
                f"  [dim]EDU {edu} -> {picks} background skill "
                f"pick{'s' if picks != 1 else ''} at level 0.[/dim]"
            )
        remaining = char.background_picks_remaining
        if remaining <= 0:
            # No picks to make — advance immediately via phase determination.
            self._narrate("[dim]No background skill picks available.[/dim]")
            self._narrate("")
            self._post_step()
            self.phase = self._determine_phase()
            return
        pack_skills = self.app.pack.background_skills
        already = set(char.skills.keys())
        prompt = f"Choose background skills ({remaining} pick{'s' if remaining != 1 else ''} left):"
        choices: list[tuple[str, str]] = []
        descs: list[str] = []
        for sid in pack_skills:
            if sid in already:
                continue
            skill = self.app.pack.skills.get(sid)
            label = skill.name if skill else sid
            choices.append((f"{label} (level 0)", f"background_skill:{sid}"))
            descs.append(skill.description if skill else "")
        cm.set_choices(prompt, choices, descriptions=descs)

    def _do_pick_background_skill(self, skill_id: str) -> None:
        """Apply one background-skill pick and refresh choices (B10)."""
        skill = self.app.pack.skills.get(skill_id)
        label = skill.name if skill else skill_id
        self.app.runner.pick_background_skill(skill_id)
        self._narrate(f"  [bold]Background skill:[/bold] [cyan]{label}[/cyan] (level 0)")
        state = self.app.engine.state
        if state.character.background_picks_remaining > 0:
            self._post_step()
            self.phase = self._determine_phase()
        else:
            self._narrate("[green]Background skills complete.[/green]")
            self._narrate("")
            self._post_step()
            self.phase = self._determine_phase()

    # ------------------------------------------------------------------
    # UI helpers.
    # ------------------------------------------------------------------

    def _narrate(self, text: str) -> None:
        """Add a line to the narrative log."""
        self.query_one(NarrativeLogWidget).add_line(text)

    def _update_status_bar(self, failure_kind: str | None = None) -> None:
        """Update the status bar to reflect LLM connection state (Task 24).

        On narration failure, shows the degraded-mode surface matching the
        failure kind, using the same strings as the adventure screen.
        """
        bar = self.query_one("#status-bar", Label)
        if failure_kind == "provider_error":
            bar.update("[yellow]connection lost — template narration[/yellow]")
            return
        if failure_kind == "retry_exhausted":
            bar.update("[yellow]narration unavailable — showing mechanical outcomes[/yellow]")
            return
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

    def _narrate_roll(
        self, label: str, dice: str, total: int, dm: int, target: int, success: bool, tier: str = ""
    ) -> None:
        """Add a formatted dice roll result."""
        self.query_one(NarrativeLogWidget).add_roll(label, dice, total, dm, target, success, tier)

    def _narrate_paragraph(self, text: str) -> None:
        """Add a paragraph with a blank line after."""
        self.query_one(NarrativeLogWidget).add_paragraph(text)

    def _update_character_sheet(self) -> None:
        """Refresh the character sheet from engine state."""
        # Screen not yet mounted or being disposed.
        with suppress(NoMatches):
            self.query_one(CharacterSheetWidget).update_from_state(self.app.engine.state)

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
