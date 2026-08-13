"""Contract tests for AdventureSession (M0.3).

Mirrors tests/game/test_chargen_session.py's shape: create → view → choose →
serialize → restore, with determinism and validation guarantees locked in.
"""

from __future__ import annotations

import pytest

from src.engine.commands import Engine
from src.engine.dice import ForcedRoller
from src.engine.state import CampaignConfig, GameState
from src.game.adventure_session import CONTRACT_VERSION, AdventureSession

# 4 mission hook tables + 2 scene oracle tables + generous scene checks.
_QUEUE = [
    [3, 4],
    [5, 5],
    [3, 3],
    [4, 4],  # hook
    [5, 5],
    [4, 4],  # scene oracle
    [6, 6],  # scene check 1
    [5, 5],
    [4, 4],  # scene oracle 2
    [5, 5],  # scene check 2
    [5, 5],
    [4, 4],  # scene oracle 3
    [5, 5],  # scene check 3
]


def _make_session(queue: list | None = None, death_mode: str = "narrative") -> AdventureSession:
    state = GameState.new(seed=42)
    state.campaign = CampaignConfig(
        resolution_profile="narrative",
        death_mode=death_mode,
        theme_pack="scifi",
    )
    state.character.name = "TestHero"
    state.character.characteristics = {
        "STR": 7,
        "DEX": 9,
        "END": 6,
        "INT": 8,
        "EDU": 10,
        "SOC": 5,
    }
    state.character.skills = {"Gun Combat": 1, "Persuade": 0, "Stealth": 2}
    state.character.career = "navy"
    state.character.terms = 2
    state.narrative_log.append("mustered_out=true")
    engine = Engine(state, roller=ForcedRoller(queue or list(_QUEUE)))
    return AdventureSession.wrap(engine)


class TestViewAndChoice:
    def test_initial_view_is_hook_offered(self):
        session = _make_session()
        result_view = session.current_view()
        assert result_view.phase == "hook_offered"

    def test_choose_accepts_mission(self):
        session = _make_session()
        session.current_view()  # generate the hook
        result = session.choose("accept_mission")
        assert result.phase == "scene_active"
        assert result.contract_version == CONTRACT_VERSION
        assert result.view["choices"]  # serialized choices present

    def test_choose_rejects_unknown_option(self):
        session = _make_session()
        session.current_view()
        with pytest.raises(ValueError, match="Invalid option"):
            session.choose("not_a_real_option")

    def test_choose_rejects_dimmed_option(self):
        """push_for_ending is dimmed before min_scenes — not choosable (B4 at the contract layer)."""
        session = _make_session()
        session.current_view()
        session.choose("accept_mission")
        with pytest.raises(ValueError, match="Invalid option"):
            session.choose("push_for_ending")

    def test_submit_freetext_rejected_outside_scene(self):
        session = _make_session()
        session.current_view()  # hook phase
        with pytest.raises(ValueError, match="active scene"):
            session.submit_freetext("I look around")

    def test_submit_freetext_rejects_empty(self):
        session = _make_session()
        with pytest.raises(ValueError, match="non-empty"):
            session.submit_freetext("   ")


class TestSerializeRestore:
    def test_round_trip_preserves_state_byte_for_byte(self):
        session = _make_session()
        session.current_view()
        session.choose("accept_mission")
        before = session.engine.state.model_dump_json()

        restored = AdventureSession.restore(session.serialize())

        assert restored.engine.state.model_dump_json() == before
        assert restored.current_view().phase == "scene_active"

    def test_restore_rejects_newer_contract_version(self):
        session = _make_session()
        envelope = session.serialize().replace(
            f'"contract_version": {CONTRACT_VERSION}',
            f'"contract_version": {CONTRACT_VERSION + 1}',
            1,
        )
        with pytest.raises(ValueError, match="contract_version"):
            AdventureSession.restore(envelope)

    def test_checkpoint_snapshot_rides_the_envelope(self):
        session = _make_session(death_mode="checkpoint")
        session.current_view()
        session.choose("accept_mission")  # scene start takes the snapshot
        assert session.checkpoint_mgr.has_snapshot

        restored = AdventureSession.restore(session.serialize())

        assert restored.checkpoint_mgr.has_snapshot

    def test_restore_without_checkpoint_has_none(self):
        session = _make_session(death_mode="narrative")
        session.current_view()
        restored = AdventureSession.restore(session.serialize())
        assert not restored.checkpoint_mgr.has_snapshot
