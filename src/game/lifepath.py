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
from src.game.views import PhaseView
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
                return term_phase
            # Unknown term_phase falls through to a fresh term start.
        return "run_survival"

    # ------------------------------------------------------------------
    # Phase view assembly — minimal for U5; enriched in U7 (web screens).
    # ------------------------------------------------------------------

    def get_phase_view(self) -> PhaseView:
        """Build a PhaseView for the current phase.

        This is a minimal implementation that returns the phase identifier
        and prompt. Full choice/odds/receipt assembly is added in U7 (web
        lifepath screens) when templates consume this layer.
        """
        phase = self.determine_phase()
        prompts = {
            "roll_characteristics": "Roll your characteristic pool.",
            "assign_characteristics": "Assign each rolled value to a characteristic.",
            "choose_background_skills": "Pick your background skills.",
            "choose_career": "Choose a career to qualify for.",
            "run_survival": "Rolling survival...",
            "complete": "Lifepath complete.",
        }
        return PhaseView(
            phase=phase,
            prompt=prompts.get(phase, phase.replace("_", " ").title()),
        )
