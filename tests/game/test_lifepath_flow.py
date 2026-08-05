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
        """The term_phase= flag is read byte-identically to the TUI (KTD-3).

        The controller must be constructed AFTER the flag is in place so the
        U2 reconstruction runs against the persisted state (same lifecycle as
        a web session resume).
        """
        engine = _make_engine()
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
        engine.apply(SetFlagCommand(key="term_phase", value="re_enlist"))
        controller = LifepathController(engine, load_scifi_pack())
        phase = controller.determine_phase()
        assert phase == "re_enlist"

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

    def test_choose_aging_reduction_advances_when_pending_empty(self):
        """choose_aging_reduction auto-advances to re_enlist when pending_aging is empty.

        Parity with the TUI (lines 327-329): all aging slots consumed → re_enlist.
        """
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
        engine.apply(SetFlagCommand(key="term_phase", value="choose_aging_reduction"))
        # pending_aging defaults to empty list.
        assert controller.determine_phase() == "re_enlist"

    def test_choose_aging_reduction_stays_when_pending_present(self):
        """choose_aging_reduction stays when pending_aging still has slots."""
        from src.engine.state import AgingSlot

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
        engine.apply(SetFlagCommand(key="term_phase", value="choose_aging_reduction"))
        engine.state.character.pending_aging = [AgingSlot(group="physical", points=1)]
        assert controller.determine_phase() == "choose_aging_reduction"


class TestPhaseView:
    """U5: PhaseView assembly."""

    def test_get_phase_view_returns_current_phase(self):
        """get_phase_view returns a PhaseView for the current phase."""
        engine = _make_engine()
        controller = LifepathController(engine, load_scifi_pack())
        view = controller.get_phase_view()
        assert view.phase == "roll_characteristics"
        assert len(view.prompt) > 0


def _make_mid_lifepath_engine(seed: int = 42) -> Engine:
    """Engine with characteristics, background skills, and career set.

    After this, ``determine_phase`` returns ``run_survival``.
    """
    engine = _make_engine(seed=seed)
    char = engine.state.character
    char.characteristics = {
        "STR": 7,
        "DEX": 8,
        "END": 6,
        "INT": 10,
        "EDU": 9,
        "SOC": 5,
    }
    char.career = "navy"
    char.alive = True
    char.background_picks_remaining = 0
    return engine


class TestTermLoop:
    """U7: the term sub-phase machine runs survival → advancement → re-enlist."""

    def test_get_phase_view_for_run_survival_is_read_only(self):
        """get_phase_view() for run_survival must NOT execute mutations (U7)."""
        engine = _make_mid_lifepath_engine()
        controller = LifepathController(engine, load_scifi_pack())
        view = controller.get_phase_view()
        assert view.phase == "run_survival"
        assert "Begin Term" in view.choices[0].label
        # No term_phase flag should have been set just by viewing.
        assert controller.get_latest_term_phase(engine.state) is None

    def test_begin_term_runs_survival_then_advances(self):
        """U2: begin_term starts the interactive term flow (not _auto_advance).

        Survival runs immediately; commission/advancement/skills are now
        separate interactive clicks. The view should show survival receipt
        and land on the next sub-phase (choose_commission for navy).
        """
        engine = _make_mid_lifepath_engine()
        controller = LifepathController(engine, load_scifi_pack())
        view = controller.apply_choice("begin_term")
        # Survival ran — receipt present.
        assert any("Survival" in r for r in view.receipts)
        assert controller._current_term_result is not None
        # Navy is a hierarchy career with commission → lands on choose_commission.
        assert view.phase == "choose_commission"
        # No advancement yet — that's a separate click now.
        event_types = [e.command_type for e in engine.state.events]
        assert "lifepath_advancement" not in event_types

    def test_re_enlist_view_not_overridden_by_term_phases_fallback(self):
        """get_phase_view() for re_enlist returns choices, not a generic prompt."""
        engine = _make_mid_lifepath_engine()
        controller = LifepathController(engine, load_scifi_pack())
        # Fast-forward to re_enlist by setting the flag.
        engine.apply(SetFlagCommand(key="term_phase", value="re_enlist"))
        view = controller.get_phase_view()
        assert view.phase == "re_enlist"
        option_ids = [c.option_id for c in view.choices]
        assert "reenlist_continue" in option_ids
        assert "reenlist_muster" in option_ids

    def test_reenlist_continue_starts_new_term(self):
        """Choosing re-enlist transitions back to run_survival."""
        engine = _make_mid_lifepath_engine()
        controller = LifepathController(engine, load_scifi_pack())
        engine.apply(SetFlagCommand(key="term_phase", value="re_enlist"))
        controller.apply_choice("reenlist_continue")
        assert controller.determine_phase() == "run_survival"

    def test_reenlist_muster_transitions_to_mustering_out(self):
        """Choosing muster out transitions to muster_out_allocate (U3 interactive).

        With terms > 0 the character has benefit rolls; the mustering_out
        phase computes the plan and advances to muster_out_allocate.
        """
        engine = _make_mid_lifepath_engine()
        controller = LifepathController(engine, load_scifi_pack())
        # Give the character a term so benefit_rolls_for > 0.
        engine.state.character.terms = 1
        engine.apply(SetFlagCommand(key="term_phase", value="re_enlist"))
        controller.apply_choice("reenlist_muster")
        assert controller.determine_phase() == "muster_out_allocate"


class TestBackgroundSkillMutation:
    """U7: background skill picks go through Engine.apply, not direct writes."""

    def test_bg_skill_choice_uses_engine_funnel(self):
        """Picking a background skill applies GainSkillCommand via the funnel."""
        engine = _make_engine()
        char = engine.state.character
        char.characteristics = {
            "STR": 7,
            "DEX": 8,
            "END": 6,
            "INT": 10,
            "EDU": 9,
            "SOC": 5,
        }
        char.background_picks_remaining = -1  # uninitialized sentinel
        controller = LifepathController(engine, load_scifi_pack())
        # Pick a skill that exists in the scifi pack's background list.
        pack = load_scifi_pack()
        skill = pack.background_skills[0]
        controller.apply_choice(f"bg_skill:{skill}")
        # Skill should be at level 0 in character's skills.
        assert char.skills.get(skill) == 0
        # background_picks_remaining should be > 0 (decremented from 3 + EDU DM).
        assert char.background_picks_remaining > 0
        # Events should prove it went through the funnel (not a direct write).
        event_types = [e.command_type for e in engine.state.events]
        assert "lifepath_gain_skill" in event_types
        assert "lifepath_decrement_background_picks" in event_types
