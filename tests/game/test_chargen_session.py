"""P6 — ChargenSession headless API (contract v1)."""

from __future__ import annotations

import asyncio

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


class TestChargenSessionAdvisor:
    """suggest() and propose() wire through advisor/translator."""

    def test_suggest_with_heuristic_advisor(self):
        """HeuristicAdvisor picks the highest-odds option and records advice."""
        from src.llm.advisor import HeuristicAdvisor, SuggestionRecord

        advisor = HeuristicAdvisor()
        session = ChargenSession.create(
            seed=42, pack_id="scifi", death_mode="narrative", advisor=advisor
        )
        record = asyncio.run(session.suggest())
        assert isinstance(record, SuggestionRecord)
        assert record.selected_option_id  # non-empty
        assert record.rationale  # non-empty
        # Advice recorded in event log
        advice_events = [
            e for e in session._engine.state.events if e.command_type == "record_advice"
        ]
        assert len(advice_events) >= 1

    def test_suggest_without_advisor_raises(self):
        """Without an advisor injected, suggest() raises informative error."""
        session = ChargenSession.create(seed=42, pack_id="scifi")
        with pytest.raises(RuntimeError, match="advisor"):
            asyncio.run(session.suggest())

    def test_propose_with_stub_translator(self):
        """propose() records the translation via record_proposal."""

        class StubTranslator:
            async def propose(self, text, choice, rules_summary):
                from src.llm.translator import TranslationRecord

                return TranslationRecord(
                    choice_id=choice.choice_id,
                    text=text,
                    selected_option_id=choice.options[0].option_id,
                    rationale="stub",
                    context_hash="stub",
                    validation="passed",
                )

        session = ChargenSession.create(
            seed=42,
            pack_id="scifi",
            death_mode="narrative",
            translator=StubTranslator(),
        )
        record = asyncio.run(session.propose("I want to be a Navy pilot"))
        assert record.validation == "passed"
        proposal_events = [
            e for e in session._engine.state.events if e.command_type == "record_proposal"
        ]
        assert len(proposal_events) >= 1
