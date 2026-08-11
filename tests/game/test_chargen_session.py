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

    def test_suggest_returns_none_when_advisor_has_nothing(self):
        """suggest() returns None (not crash) when the advisor returns None.

        Both Advisor (LLM failure / no model) and HeuristicAdvisor (all
        options dimmed) can return None by contract. ChargenSession must
        propagate that gracefully rather than crash in record_advice.
        """

        class EmptyAdvisor:
            async def suggest(self, choice, rules_summary):
                return None

        session = ChargenSession.create(
            seed=42, pack_id="scifi", death_mode="narrative", advisor=EmptyAdvisor()
        )
        record = asyncio.run(session.suggest())
        assert record is None
        # No advice event should have been recorded.
        advice_events = [
            e for e in session._engine.state.events if e.command_type == "record_advice"
        ]
        assert len(advice_events) == 0

    def test_choose_with_advisor_origin_surfaces_in_events(self):
        """choose(origin='advisor') stamps origin on SetFlagCommand events (ADR A10).

        Drives several steps — the first few (roll_pool, assign) use runner
        commands without SetFlagCommand, but term-phase transitions (career
        change, survival, skills, etc.) route through _set_term_phase which
        passes origin to SetFlagCommand.
        """
        session = ChargenSession.create(seed=42, pack_id="scifi", death_mode="narrative")
        for _ in range(50):
            choice = session.current_choice()
            if choice.phase == "complete":
                break
            pickable = [o for o in choice.options if not o.dimmed]
            if pickable:
                session.choose(pickable[0].option_id, origin="advisor")
            elif choice.options:
                session.choose(choice.options[0].option_id, origin="advisor")
            else:
                break
        flagged = [e for e in session._engine.state.events if e.changes.get("origin") == "advisor"]
        assert len(flagged) >= 1, "advisor origin should surface in SetFlagCommand events"

    def test_choose_default_origin_is_byte_identical(self):
        """Player-origin choices must NOT add origin to events (backward compat)."""
        session_default = ChargenSession.create(seed=42, pack_id="scifi")
        session_default.choose("roll_pool")
        for e in session_default._engine.state.events:
            assert "origin" not in e.changes, (
                "player-origin events must not carry origin (byte-identical)"
            )


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
        """A v4 save envelope restores to current (migration runs)."""
        session = ChargenSession.create(seed=42)
        data = session.serialize()
        envelope = json.loads(data)
        envelope["state"]["save_version"] = 4
        data = json.dumps(envelope)
        restored = ChargenSession.restore(data)
        # v4 walks through v5 → v6 (C3); the pin tracks the current version.
        from src.engine.persistence import CURRENT_SAVE_VERSION

        assert restored._engine.state.save_version == CURRENT_SAVE_VERSION

    def test_restore_rejects_future_save_version(self):
        """A save version newer than CURRENT_SAVE_VERSION is rejected."""
        session = ChargenSession.create(seed=42)
        data = session.serialize()
        envelope = json.loads(data)
        envelope["state"]["save_version"] = 999
        data = json.dumps(envelope)
        with pytest.raises(ValueError, match="newer than supported"):
            ChargenSession.restore(data)

    def test_restore_rejects_missing_state_field(self):
        """Restore raises descriptive ValueError when 'state' key is absent."""
        data = json.dumps({"contract_version": 1, "save_version": 5})
        with pytest.raises(ValueError, match="state"):
            ChargenSession.restore(data)


class TestChargenParityAllDeathModes:
    """Full lifepaths in all three death modes via the session API.

    Re-expresses TUI assertions from tests/tui/test_lifepath_phases.py
    headlessly.
    """

    @pytest.mark.parametrize("death_mode", ["narrative", "ironman", "checkpoint"])
    def test_full_lifepath_completes(self, death_mode):
        """A complete lifepath runs end-to-end in every death mode."""
        session = ChargenSession.create(seed=42, pack_id="scifi", death_mode=death_mode)
        # Auto-pick first available option until complete or 200 steps (safety valve)
        for _ in range(200):
            choice = session.current_choice()
            if choice.phase == "complete":
                break
            pickable = [o for o in choice.options if not o.dimmed]
            if pickable:
                session.choose(pickable[0].option_id)
            elif choice.options:
                session.choose(choice.options[0].option_id)
            else:
                break
        assert session._controller.determine_phase() == "complete"

    def test_reenlist_shows_continue_and_muster(self):
        """Re-enlistment offers both continue and muster-out (TUI:215)."""
        session = ChargenSession.create(seed=44, pack_id="scifi", death_mode="narrative")
        for _ in range(200):
            choice = session.current_choice()
            if choice.phase == "re_enlist":
                option_ids = {o.option_id for o in choice.options}
                assert "reenlist_continue" in option_ids
                assert "reenlist_muster" in option_ids
                return
            pickable = [o for o in choice.options if not o.dimmed]
            if pickable:
                session.choose(pickable[0].option_id)
            elif choice.options:
                session.choose(choice.options[0].option_id)
            else:
                break
        pytest.fail("Did not reach re_enlist phase")


class TestBackgroundSkillExclusion:
    """C1 — owned background skills are never offered twice."""

    def test_background_skill_duplicate_rejected(self):
        session = ChargenSession.create(seed=42, pack_id="scifi", death_mode="narrative")
        session.choose("roll_pool")
        for _ in range(6):
            choice = session.current_choice()
            assert choice.phase == "assign_characteristics"
            first = next(o for o in choice.options if o.option_id.startswith("assign:"))
            session.choose(first.option_id)
        choice = session.current_choice()
        assert choice.phase == "choose_background_skills"
        first_skill = next(o for o in choice.options if o.option_id.startswith("bg_skill:"))
        session.choose(first_skill.option_id)
        choice = session.current_choice()
        if choice.phase == "choose_background_skills":
            # Same skill must not be offered again; choosing it is invalid.
            assert first_skill.option_id not in {o.option_id for o in choice.options}
            with pytest.raises(ValueError, match="Invalid option"):
                session.choose(first_skill.option_id)


class TestCascadeRealPack:
    """C4 — real scifi pack exercises cascades end-to-end."""

    def test_scifi_cascade_end_to_end(self):
        """Play navy preferring Service Skills; a cascade prompt must appear (C4)."""
        session = ChargenSession.create(seed=42, pack_id="scifi", death_mode="narrative")
        saw_specialization = False
        for _ in range(200):
            choice = session.current_choice()
            if choice.phase == "complete":
                break
            if choice.phase == "choose_specialization":
                saw_specialization = True
                pick = choice.options[0]
                session.choose(pick.option_id)
                skill_id = pick.option_id.removeprefix("spec:")
                assert skill_id in session._engine.state.character.skills
                continue
            # C6: after a career's muster, choose_career_change offers a new
            # career or finish. This test only needs ONE career to exercise
            # cascades — pick finish to terminate.
            if choice.phase == "choose_career_change":
                finish = next(
                    (o for o in choice.options if o.option_id == "career_change_finish"),
                    None,
                )
                if finish is not None:
                    session.choose(finish.option_id)
                    continue
            pick = next(
                (o for o in choice.options if o.option_id == "career:navy"),
                next(
                    (
                        o
                        for o in choice.options
                        if not o.dimmed and o.option_id == "skill_table:Service Skills"
                    ),
                    next(
                        (
                            o
                            for o in choice.options
                            if not o.dimmed and o.option_id == "reenlist_continue"
                        ),
                        next((o for o in choice.options if not o.dimmed), choice.options[0]),
                    ),
                ),
            )
            session.choose(pick.option_id)
        assert saw_specialization, "no cascade slot hit in a full navy lifepath — investigate"


class TestPerCareerMusterSession:
    """C6 — per-career muster-out at the contract surface."""

    def test_two_career_muster_out_per_career(self):
        """Two careers muster separately; history/muster tracking consistent (C6/G4)."""
        session = ChargenSession.create(seed=42, pack_id="scifi", death_mode="narrative")
        # Drive two careers in sequence. The career pick is gated on what's
        # already in career_history (not on a pick counter) so a failed
        # qualification + retry doesn't double-count.
        for _ in range(300):
            choice = session.current_choice()
            if choice.phase == "complete":
                break
            ids = {o.option_id for o in choice.options}
            history = session._engine.state.character.career_history
            history_ids = [r.career_id for r in history]
            if choice.phase == "choose_career":
                # First career navy; second career army.
                target = "navy" if not history_ids else "army"
                if f"career:{target}" in ids and target not in history_ids:
                    session.choose(f"career:{target}")
                    continue
            if choice.phase == "re_enlist" and "reenlist_muster" in ids:
                session.choose("reenlist_muster")
                continue
            if choice.phase == "choose_career_change":
                if len(history_ids) < 2 and "career_change_new" in ids:
                    session.choose("career_change_new")
                elif "career_change_finish" in ids:
                    session.choose("career_change_finish")
                else:  # pre-C6 id
                    session.choose("career_change_muster")
                continue
            pick = next((o for o in choice.options if not o.dimmed), None)
            if pick is None:
                break
            session.choose(pick.option_id)
        ch = session._engine.state.character
        history = ch.career_history
        assert [r.career_id for r in history] == ["navy", "army"], (
            f"expected [navy, army], got {[r.career_id for r in history]}"
        )
        # Per-career terms sum to lifetime terms:
        assert sum(r.terms_in_career for r in history) == ch.terms
        # Each career mustered separately, in order:
        assert ch.mustered_careers == ["navy", "army"]
