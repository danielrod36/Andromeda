"""P6.T1 — ChargenSession headless API (contract v1)."""

from __future__ import annotations

import pytest

from src.engine.lifepath_choices import ChoicePointView
from src.game.chargen import CONTRACT_VERSION, ChargenSession, StepResult


class TestChargenSessionCore:
    """Create a session, read the first choice, make a selection."""

    def test_contract_version(self):
        assert CONTRACT_VERSION == 1

    def test_create_and_first_choice(self):
        """New session starts at roll_characteristics phase."""
        session = ChargenSession.create(seed=42, pack_id="scifi", death_mode="narrative")
        choice = session.current_choice()
        assert isinstance(choice, ChoicePointView)
        assert choice.phase == "roll_characteristics"
        assert len(choice.options) > 0

    def test_choose_returns_step_result(self):
        """Selecting an option returns a StepResult with the next view."""
        session = ChargenSession.create(seed=42, pack_id="scifi", death_mode="narrative")
        result = session.choose("roll_pool")
        assert isinstance(result, StepResult)
        assert result.view is not None
        assert result.view.phase != "roll_characteristics"  # advanced

    def test_invalid_option_raises(self):
        session = ChargenSession.create(seed=42, pack_id="scifi", death_mode="narrative")
        with pytest.raises(ValueError):
            session.choose("nonexistent_option")
