"""P6 — ChargenSession headless API (contract v1)."""

from __future__ import annotations

import asyncio
import json

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


class TestChargenSessionSerialize:
    """serialize/restore round-trips with byte-identical RNG continuation."""

    def test_round_trip_mid_lifepath(self):
        """Save mid-lifepath, restore — same phase."""
        session = ChargenSession.create(seed=99, pack_id="scifi", death_mode="narrative")
        session.choose("roll_pool")
        # Assign all six characteristics by auto-picking the first valid option
        for _ in range(6):
            choice = session.current_choice()
            first_assign = next(
                (o.option_id for o in choice.options if o.option_id.startswith("assign:")), None
            )
            if first_assign:
                session.choose(first_assign)
        data = session.serialize()
        assert json.loads(data)["contract_version"] == CONTRACT_VERSION

        restored = ChargenSession.restore(data)
        assert restored.current_choice().phase == session.current_choice().phase

    def test_rng_byte_identical_after_restore(self):
        """RNG stream continues identently after serialize+restore (A2)."""
        session = ChargenSession.create(seed=77, pack_id="scifi")
        session.choose("roll_pool")
        session.choose("assign:0:STR")

        data = session.serialize()
        restored = ChargenSession.restore(data)

        orig_rng = session._engine.state.rng
        rest_rng = restored._engine.state.rng
        assert orig_rng.lifepath == rest_rng.lifepath
        assert orig_rng.oracle == rest_rng.oracle

    def test_restore_rejects_newer_contract(self):
        """Restore raises on a contract version from the future."""
        data = json.dumps({"contract_version": 999, "save_version": 5, "state": {}})
        with pytest.raises(ValueError, match="contract"):
            ChargenSession.restore(data)

    def test_restore_runs_save_migrations(self):
        """A v4 save envelope restores to v5 (migration runs)."""
        session = ChargenSession.create(seed=42)
        data = session.serialize()
        envelope = json.loads(data)
        envelope["state"]["save_version"] = 4
        data = json.dumps(envelope)
        restored = ChargenSession.restore(data)
        assert restored._engine.state.save_version == 5
