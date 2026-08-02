"""Tests for LifepathController — headless phase determination (U5).

KTD-3 parity: the same flag-reading logic the TUI uses must work headlessly
so saves round-trip across shells.
"""

from __future__ import annotations

from src.engine.commands import Engine, SetFlagCommand
from src.engine.state import CampaignConfig, GameState
from src.game.lifepath import LifepathController
from src.themepacks.cepheus_scifi import load_scifi_pack


def _make_engine(seed: int = 42) -> Engine:
    state = GameState.new(seed=seed)
    state.campaign = CampaignConfig(resolution_profile="classic")
    state.character.name = "TestHero"
    return Engine(state)


class TestPhaseDetermination:
    """U5: headless phase determination matches the TUI's flag-reading logic."""

    def test_fresh_state_starts_at_roll_characteristics(self):
        """A character with no characteristics starts at roll_characteristics."""
        engine = _make_engine()
        pack = load_scifi_pack()
        controller = LifepathController(engine, pack)
        assert controller.determine_phase() == "roll_characteristics"

    def test_term_phase_flag_read_from_narrative_log(self):
        """The term_phase= flag is read byte-identically to the TUI (KTD-3)."""
        engine = _make_engine()
        pack = load_scifi_pack()
        controller = LifepathController(engine, pack)

        # Simulate a mid-lifepath save with a term_phase flag.
        engine.apply(SetFlagCommand(key="term_phase", value="choose_skills"))
        phase = controller.determine_phase()
        # With a career set and term_phase=choose_skills, phase should be choose_skills.
        # (Need to set career first for the flag to take precedence.)
        engine.state.character.career = "navy"
        engine.state.character.characteristics = {
            "STR": 7,
            "DEX": 8,
            "END": 6,
            "INT": 10,
            "EDU": 9,
            "SOC": 5,
        }
        engine.state.character.alive = True
        phase = controller.determine_phase()
        assert phase == "choose_skills"

    def test_mustered_out_flag_leads_to_complete(self):
        """mustered_out=true in narrative_log → phase is 'complete'."""
        engine = _make_engine()
        pack = load_scifi_pack()
        controller = LifepathController(engine, pack)

        engine.state.character.career = "navy"
        engine.state.character.characteristics = {
            "STR": 7,
            "DEX": 8,
            "END": 6,
            "INT": 10,
            "EDU": 9,
            "SOC": 5,
        }
        engine.state.character.alive = True
        engine.apply(SetFlagCommand(key="mustered_out", value="true"))
        assert controller.determine_phase() == "complete"

    def test_dead_character_is_complete(self):
        """A dead character (ironman) is in the complete phase."""
        engine = _make_engine()
        pack = load_scifi_pack()
        controller = LifepathController(engine, pack)

        engine.state.character.career = "navy"
        engine.state.character.characteristics = {
            "STR": 7,
            "DEX": 8,
            "END": 6,
            "INT": 10,
            "EDU": 9,
            "SOC": 5,
        }
        engine.state.character.alive = False
        assert controller.determine_phase() == "complete"

    def test_get_latest_term_phase_returns_most_recent(self):
        """The most recent term_phase flag wins (KTD-3 parity)."""
        engine = _make_engine()

        engine.apply(SetFlagCommand(key="term_phase", value="run_survival"))
        engine.apply(SetFlagCommand(key="term_phase", value="choose_skills"))

        result = LifepathController.get_latest_term_phase(engine.state)
        assert result == "choose_skills"

    def test_get_latest_term_phase_returns_none_when_absent(self):
        """No term_phase flag in the log returns None."""
        engine = _make_engine()
        result = LifepathController.get_latest_term_phase(engine.state)
        assert result is None


class TestPhaseView:
    """U5: PhaseView assembly."""

    def test_get_phase_view_returns_current_phase(self):
        """get_phase_view returns a PhaseView for the current phase."""
        engine = _make_engine()
        controller = LifepathController(engine, load_scifi_pack())
        view = controller.get_phase_view()
        assert view.phase == "roll_characteristics"
        assert len(view.prompt) > 0
