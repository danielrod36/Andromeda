"""Headless lifepath flow controller (U5).

Ports the phase machine from the TUI's ``LifepathScreen`` into a testable,
UI-agnostic controller. The engine's ``LifepathRunner`` already owns the
mechanical step methods; this controller owns the phase *decision* logic —
which step to run next based on GameState flags — and returns ``PhaseView``
models that shells render without inspecting state directly.

KTD-3 parity: phase flags (``term_phase=...``, ``mustered_out=true``,
``reenlist_outcome=...``) are read and written byte-identical to the TUI's
``SetFlagCommand`` convention so TUI-written saves reconstruct identically
in ``src/game/`` and vice versa.

The ``choose_skills`` exhaustion auto-advance is deferred to U7: it
requires reconstructing ``_current_term_result`` from the event log
(~80 lines of event-scanning in the TUI's ``_reconstruct_term_state``),
which is delivered alongside the web lifepath screens that consume it.
"""

from __future__ import annotations

import logging

from src.engine.commands import Engine, SetFlagCommand
from src.engine.lifepath import LifepathRunner
from src.engine.state import GameState
from src.game.views import ChoiceOption, PhaseView
from src.themepacks.base import LoadedThemePack

logger = logging.getLogger(__name__)

#: Phases that belong to the term sub-state-machine (same set as the TUI).
TERM_PHASES = frozenset(
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


class LifepathController:
    """Headless lifepath phase controller (U5).

    Wraps the engine and theme pack, providing:

    - ``determine_phase()`` — reads state flags to determine the current phase
    - ``get_phase_view()`` — builds a :class:`PhaseView` for the current phase
    - ``apply_choice()`` — routes a choice to the appropriate step handler

    The controller never caches GameState — it reads through ``engine.state``
    every call so ``swap_state`` (rewind) is always reflected.
    """

    def __init__(self, engine: Engine, pack: LoadedThemePack) -> None:
        self._engine = engine
        self._pack = pack
        self._runner = LifepathRunner(engine, pack)
        self._current_term_result = None

    @property
    def engine(self) -> Engine:
        return self._engine

    @property
    def pack(self) -> LoadedThemePack:
        return self._pack

    @property
    def runner(self) -> LifepathRunner:
        return self._runner

    # ------------------------------------------------------------------
    # Phase flag helpers (KTD-3 byte-identical parity with the TUI).
    # ------------------------------------------------------------------

    @staticmethod
    def get_latest_term_phase(state: GameState) -> str | None:
        """Return the most recent ``term_phase=`` flag from the narrative log.

        This is the exact same logic the TUI uses — scanning
        ``state.narrative_log`` for ``term_phase=`` entries. KTD-3 requires
        byte-identical flag handling so saves round-trip across shells.
        """
        for entry in reversed(state.narrative_log):
            if entry.startswith("term_phase="):
                return entry.split("=", 1)[1]
        return None

    def _set_term_phase(self, phase: str) -> None:
        """Persist a ``term_phase`` flag via the command funnel (AE8-safe)."""
        self._engine.apply(SetFlagCommand(key="term_phase", value=phase))

    @staticmethod
    def _get_reenlist_outcome(state: GameState) -> str | None:
        """Return ``reenlist_outcome`` set after the most recent ``re_enlist``.

        Scans the narrative log backward: if a ``reenlist_outcome=`` entry
        appears before (i.e. later in the log than) the most recent
        ``term_phase=re_enlist``, the player has already chosen.
        """
        for i in range(len(state.narrative_log) - 1, -1, -1):
            entry = state.narrative_log[i]
            if entry == "term_phase=re_enlist":
                return None
            if entry.startswith("reenlist_outcome="):
                return entry.split("=", 1)[1]
        return None

    # ------------------------------------------------------------------
    # Phase determination — headless port of the TUI's _determine_phase.
    # ------------------------------------------------------------------

    def determine_phase(self) -> str:
        """Determine the current lifepath phase from engine state.

        Reads the same flags and character fields the TUI does. This is the
        canonical phase resolver for both shells — the TUI keeps its own copy
        frozen (KTD-3 byte-parity) until OQ1 is decided.

        Parity note: ``choose_aging_reduction`` auto-advances to ``re_enlist``
        when ``pending_aging`` is empty (ported from the TUI). The
        ``choose_skills`` exhaustion check is deferred to U7 (see module
        docstring).
        """
        state = self._engine.state
        char = state.character

        # Characteristics not fully assigned yet.
        if len(char.characteristics) < 6:
            return "assign_characteristics" if char.unassigned_rolls else "roll_characteristics"

        # No career chosen yet.
        if not char.career:
            term_phase = self.get_latest_term_phase(state)
            if term_phase == "mustering_out":
                return "mustering_out"
            if term_phase == "muster_out_allocate":
                return "muster_out_allocate"
            if term_phase == "choose_qualification_fallback":
                return "choose_qualification_fallback"
            if term_phase == "choose_career_change":
                return "choose_career_change"
            # Background skills phase.
            # Two checks for KTD-3 parity with the TUI: -1 is the "uninitialized"
            # sentinel (first entry, needs setup); >0 means picks remain mid-phase.
            # 0 falls through to choose_career (phase complete).
            if not char.career_history:
                if char.background_picks_remaining == -1:
                    return "choose_background_skills"
                if char.background_picks_remaining > 0:
                    return "choose_background_skills"
            return "choose_career"

        # Character is dead (ironman death during lifepath).
        if not char.alive:
            return "complete"

        # Mustering out completed.
        if "mustered_out=true" in state.narrative_log:
            return "complete"

        # Check the persisted term_phase flag.
        term_phase = self.get_latest_term_phase(state)
        if term_phase:
            if term_phase == "run_advancement":
                term_phase = "choose_advancement"
            if term_phase == "mustering_out":
                return "mustering_out"
            if term_phase == "muster_out_allocate":
                return "muster_out_allocate"
            if term_phase in TERM_PHASES:
                # All pending aging slots consumed — advance to re_enlist.
                if term_phase == "choose_aging_reduction" and not char.pending_aging:
                    return "re_enlist"
                # Player already chose at the re_enlist prompt — advance.
                if term_phase == "re_enlist":
                    outcome = self._get_reenlist_outcome(state)
                    if outcome == "continued":
                        return "run_survival"
                    if outcome == "mustered":
                        return "mustering_out"
                return term_phase
            # Unknown term_phase falls through to a fresh term start.
        return "run_survival"

    # ------------------------------------------------------------------
    # Phase view assembly — minimal for U5; enriched in U7 (web screens).
    # ------------------------------------------------------------------

    def get_phase_view(self) -> PhaseView:
        """Build a PhaseView for the current phase (U7 enrichment).

        Returns choices, receipts, and prompts for each phase. The web
        shell renders these via Jinja templates; the TUI keeps its own
        rendering frozen (KTD-3/KTD-8).
        """
        phase = self.determine_phase()
        state = self._engine.state
        char = state.character

        if phase == "roll_characteristics":
            return PhaseView(
                phase=phase,
                prompt="Roll six 2D6 values for your characteristics.",
                choices=[ChoiceOption(label="Roll Pool", option_id="roll_pool")],
            )

        if phase == "assign_characteristics":
            pool = char.unassigned_rolls
            assigned = set(char.characteristics.keys())
            stats = ["STR", "DEX", "END", "INT", "EDU", "SOC"]
            unassigned_stats = [s for s in stats if s not in assigned]
            choices = []
            for i, val in enumerate(pool):
                stat = unassigned_stats[i] if i < len(unassigned_stats) else f"slot_{i}"
                choices.append(
                    ChoiceOption(
                        label=f"Assign {val} to {stat}",
                        option_id=f"assign:{i}:{stat}",
                    )
                )
            return PhaseView(
                phase=phase,
                prompt=f"Assign pool values: {list(pool)}",
                choices=choices,
                drawer_pinned=True,
            )

        if phase == "choose_background_skills":
            picks_left = (
                char.background_picks_remaining if char.background_picks_remaining > 0 else 3
            )
            bg_skills = (
                list(self._pack.background_skills[:6]) if self._pack.background_skills else []
            )
            choices = [
                ChoiceOption(label=f"{s} (level 0)", option_id=f"bg_skill:{s}")
                for s in bg_skills[:6]
            ]
            return PhaseView(
                phase=phase,
                prompt=f"Pick {picks_left} background skills (level 0).",
                choices=choices,
                drawer_pinned=True,
            )

        if phase == "choose_career":
            careers = list(self._pack.careers.values())[:8]
            choices = [
                ChoiceOption(
                    label=f"{c.name}",
                    option_id=f"career:{c.id}",
                    description=c.description[:80] + "..."
                    if len(c.description) > 80
                    else c.description,
                )
                for c in careers
            ]
            return PhaseView(
                phase=phase,
                prompt="Choose a career to qualify for.",
                choices=choices,
            )

        if phase == "run_survival":
            return PhaseView(
                phase=phase,
                prompt=f"Term {char.terms + 1} — Ready to begin.",
                choices=[ChoiceOption(label="Begin Term", option_id="auto_term")],
            )

        if phase == "complete":
            return PhaseView(
                phase="complete",
                prompt=f"Lifepath complete. Character: {char.name}, Career: {char.career}, Terms: {char.terms}.",
                choices=[ChoiceOption(label="Begin Adventure", option_id="begin_adventure")]
                if char.alive and "mustered_out=true" in state.narrative_log
                else [],
            )

        if phase == "re_enlist":
            return PhaseView(
                phase="re_enlist",
                prompt="Re-enlist for another term or muster out?",
                choices=[
                    ChoiceOption(label="Re-enlist", option_id="reenlist_continue"),
                    ChoiceOption(label="Muster Out", option_id="reenlist_muster"),
                ],
            )

        if phase in ("mustering_out", "muster_out_allocate"):
            return PhaseView(
                phase=phase,
                prompt="Mustering out...",
                choices=[ChoiceOption(label="Continue", option_id="auto_advance")],
            )

        # Fallback: auto-advance term phases that don't need explicit UI.
        if phase in TERM_PHASES:
            return PhaseView(
                phase=phase,
                prompt=f"Processing: {phase.replace('_', ' ')}...",
                choices=[ChoiceOption(label="Continue", option_id="auto_advance")],
            )

        return PhaseView(
            phase=phase,
            prompt=phase.replace("_", " ").title(),
        )

    # ------------------------------------------------------------------
    # Choice application — routes a choice to the appropriate step (U7).
    # ------------------------------------------------------------------

    def apply_choice(self, option_id: str) -> PhaseView:
        """Apply a player's choice and return the next PhaseView (U7).

        Routes the ``option_id`` to the appropriate LifepathRunner method.
        Sets term_phase flags via SetFlagCommand (KTD-3 byte-identical).
        After applying, returns the updated PhaseView.
        """
        if option_id == "roll_pool":
            self._runner.roll_pool()
            return self.get_phase_view()

        if option_id.startswith("assign:"):
            parts = option_id.split(":", 2)
            pool_index = int(parts[1])
            stat_name = parts[2] if len(parts) > 2 else ""
            self._runner.assign_characteristic(stat_name, pool_index)
            return self.get_phase_view()

        if option_id.startswith("bg_skill:"):
            skill = option_id.split(":", 1)[1]
            self._runner.start_background_phase()
            self._runner.pick_background_skill(skill)
            return self.get_phase_view()

        if option_id.startswith("career:"):
            career_id = option_id.split(":", 1)[1]
            qual = self._runner.qualify(career_id)
            if qual.success:
                self._runner.run_basic_training(career_id)
            return self.get_phase_view()

        if option_id == "auto_term" or option_id == "auto_advance":
            return self._auto_advance_term()

        if option_id == "begin_adventure":
            return self.get_phase_view()

        if option_id == "reenlist_continue":
            self._engine.apply(SetFlagCommand(key="reenlist_outcome", value="continued"))
            self._current_term_result = None
            return self.get_phase_view()

        if option_id == "reenlist_muster":
            self._engine.apply(SetFlagCommand(key="reenlist_outcome", value="mustered"))
            self._set_term_phase("mustering_out")
            return self.get_phase_view()

        # Unknown choice — return current view unchanged.
        return self.get_phase_view()

    def _auto_advance_term(self) -> PhaseView:
        """Auto-resolve the current term sub-phase and advance (U7).

        For the web MVP, the full term (survival → advancement → aging)
        runs in a single pass inside the ``run_survival`` handler. This
        is deliberate: ``_current_term_result`` is an in-memory attribute
        that doesn't persist across HTTP requests, so all mechanical
        steps that depend on it must execute while it's still set. The
        player faces an explicit choice only at re-enlist.
        """
        phase = self.determine_phase()
        char = self._engine.state.character
        career_id = char.career

        if phase == "run_survival":
            term_number = char.terms + 1
            result = self._runner.start_term(career_id, term_number)
            self._current_term_result = result
            self._runner.run_survival_step(career_id, result)
            receipts = [f"Survival: {'passed' if result.survival_success else 'failed'}"]
            if not result.survival_success and result.died:
                return PhaseView(
                    phase="complete",
                    prompt="The character did not survive.",
                    receipts=receipts,
                )
            # Run advancement and aging while _current_term_result is in
            # memory — the web shell reconstructs the controller per
            # request, so these can't be deferred to separate clicks.
            self._runner.run_advancement_step(career_id, result)
            aging_checked = self._runner.run_aging_step(result)
            if aging_checked:
                outcome = "passed" if result.aging_success else "reduction"
                receipts.append(f"Aging roll: {result.aging_raw} ({outcome})")
            if not char.alive:
                return PhaseView(
                    phase="complete",
                    prompt="The character died.",
                    receipts=receipts,
                )
            self._set_term_phase("re_enlist")
            return PhaseView(
                phase="re_enlist",
                prompt=f"Term {term_number} complete.",
                receipts=receipts,
                choices=[
                    ChoiceOption(label="Re-enlist", option_id="reenlist_continue"),
                    ChoiceOption(label="Muster Out", option_id="reenlist_muster"),
                ],
            )

        if phase == "re_enlist":
            return self.get_phase_view()

        if phase == "mustering_out" or phase == "muster_out_allocate":
            self._runner.muster_out(career_id)
            self._engine.apply(SetFlagCommand(key="mustered_out", value="true"))
            return self.get_phase_view()

        if phase in TERM_PHASES:
            # Legacy mid-term phases (TUI-originated saves or older
            # versions).  _current_term_result can't be reconstructed
            # without event-log scanning, so fast-forward to re_enlist
            # rather than dead-ending in an infinite loop.
            self._set_term_phase("re_enlist")
            return self.get_phase_view()

        # Default: just re-determine phase.
        return self.get_phase_view()
