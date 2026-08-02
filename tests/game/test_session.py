"""Tests for GameSession — session lifecycle, action gate, stale-write (U5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.engine.commands import Engine
from src.engine.state import CampaignConfig, GameState
from src.game.session import GameSession, StaleWriteError


def _make_state(seed: int = 42) -> GameState:
    """Create a minimal GameState for testing."""
    state = GameState.new(seed=seed)
    state.campaign = CampaignConfig()
    state.character.name = "TestHero"
    return state


class TestGameSessionCore:
    """U5: GameSession core properties — never caches state."""

    def test_state_property_reads_from_engine(self, tmp_path: Path):
        """state property returns the engine's current state, not a cached copy."""
        state = _make_state()
        engine = Engine(state)
        session = GameSession(tmp_path / "save.json", engine=engine)

        assert session.state is engine.state

        # Mutate the engine state — session.state should reflect it.
        engine.state.character.name = "Changed"
        assert session.state.character.name == "Changed"

    def test_adapter_is_none_without_settings(self, tmp_path: Path):
        """No adapter when settings are not provided."""
        state = _make_state()
        engine = Engine(state)
        session = GameSession(tmp_path / "save.json", engine=engine)
        assert session.adapter is None

    def test_engine_property_returns_engine(self, tmp_path: Path):
        state = _make_state()
        engine = Engine(state)
        session = GameSession(tmp_path / "save.json", engine=engine)
        assert session.engine is engine


class TestActionGate:
    """U5 rule 3: per-session action serialization."""

    def test_begin_action_succeeds_when_idle(self, tmp_path: Path):
        state = _make_state()
        engine = Engine(state)
        session = GameSession(tmp_path / "save.json", engine=engine)

        assert session.begin_action() is True
        assert session.action_in_flight is True

    def test_begin_action_rejects_concurrent(self, tmp_path: Path):
        state = _make_state()
        engine = Engine(state)
        session = GameSession(tmp_path / "save.json", engine=engine)

        assert session.begin_action() is True
        assert session.begin_action() is False  # Second attempt rejected.

    def test_end_action_re_enables(self, tmp_path: Path):
        state = _make_state()
        engine = Engine(state)
        session = GameSession(tmp_path / "save.json", engine=engine)

        session.begin_action()
        session.end_action()
        assert session.action_in_flight is False
        assert session.begin_action() is True  # Can begin again.


class TestSaveAndStaleWrite:
    """U5 rules 2+4: autosave with stale-write detection."""

    def test_save_writes_main_document(self, tmp_path: Path):
        state = _make_state()
        engine = Engine(state)
        save_path = tmp_path / "save.json"
        session = GameSession(save_path, engine=engine)

        session.save()
        assert save_path.exists()

        # The saved file should load correctly.
        from src.engine.persistence import load

        loaded = load(save_path)
        assert loaded.character.name == "TestHero"

    def test_stale_write_detected(self, tmp_path: Path):
        """When another session writes to the same path, the first detects the conflict."""
        state_a = _make_state(seed=1)
        state_a.character.name = "Alpha"
        engine_a = Engine(state_a)
        save_path = tmp_path / "save.json"
        session_a = GameSession(save_path, engine=engine_a)
        session_a.save()

        # Session B writes to the same path.
        state_b = _make_state(seed=2)
        state_b.character.name = "Beta"
        engine_b = Engine(state_b)
        session_b = GameSession(save_path, engine=engine_b)
        session_b.save()

        # Session A tries to save again — should detect stale write.
        with pytest.raises(StaleWriteError):
            session_a.save()

    def test_checkpoint_sidecar_path(self, tmp_path: Path):
        """Sidecar path is derived from the main save path."""
        state = _make_state()
        engine = Engine(state)
        save_path = tmp_path / "campaign.json"
        session = GameSession(save_path, engine=engine)

        assert session.checkpoint_sidecar_path == tmp_path / "campaign.checkpoint.json"

    def test_checkpoint_mode_writes_sidecar(self, tmp_path: Path):
        """Checkpoint death mode writes a sidecar alongside the main save."""
        state = _make_state()
        state.campaign = CampaignConfig(death_mode="checkpoint")
        engine = Engine(state)
        save_path = tmp_path / "save.json"
        session = GameSession(save_path, engine=engine)

        session.save()
        assert save_path.exists()
        assert session.checkpoint_sidecar_path.exists()

    def test_checkpoint_mode_double_save_no_false_positive(self, tmp_path: Path):
        """Two consecutive saves in checkpoint mode must not raise StaleWriteError.

        Regression: the stale-write hash was captured after the main write but
        before the sidecar write, so the second save saw the sidecar as an
        external modification. The hash is now captured after all writes.
        """
        state = _make_state()
        state.campaign = CampaignConfig(death_mode="checkpoint")
        engine = Engine(state)
        save_path = tmp_path / "save.json"
        session = GameSession(save_path, engine=engine)

        session.save()
        session.state.character.name = "Changed"
        session.save()  # Must not raise.

    def test_checkpoint_mode_stale_write_still_detected(self, tmp_path: Path):
        """Stale-write detection still works in checkpoint mode."""
        state_a = _make_state(seed=1)
        state_a.campaign = CampaignConfig(death_mode="checkpoint")
        state_a.character.name = "Alpha"
        engine_a = Engine(state_a)
        save_path = tmp_path / "save.json"
        session_a = GameSession(save_path, engine=engine_a)
        session_a.save()

        # Session B writes to the same path.
        state_b = _make_state(seed=2)
        state_b.campaign = CampaignConfig(death_mode="checkpoint")
        state_b.character.name = "Beta"
        engine_b = Engine(state_b)
        session_b = GameSession(save_path, engine=engine_b)
        session_b.save()

        # Session A tries to save again — should detect stale write.
        with pytest.raises(StaleWriteError):
            session_a.save()


class TestSaveLoadRoundTrip:
    """U5: session loads from a saved file."""

    def test_load_from_existing_save(self, tmp_path: Path):
        """GameSession loads engine state from a save file on construction."""
        state = _make_state()
        state.character.name = "Persisted"
        save_path = tmp_path / "save.json"

        # Save via the engine directly.
        from src.engine.persistence import save

        save(state, save_path)

        # Construct a session from the save path (no engine provided).
        session = GameSession(save_path)
        assert session.state.character.name == "Persisted"
