"""Tests for chapter summary: generation, validation, and context replacement.

Covers AE16 (after two completed missions, LLM context contains two chapter
summaries and no raw event history; validation failure triggers regeneration
up to retry limit), R19 (summary validated against canonical state).
"""

from __future__ import annotations

from src.engine.audit import Event, EventKind
from src.engine.state import CampaignConfig, GameState, NarrativeFact
from src.engine.summary import (
    ChapterSummarizer,
    SummaryValidator,
    get_llm_context_summaries,
    has_raw_history_been_summarized,
)

# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def make_state():
    state = GameState.new(seed=42)
    state.campaign = CampaignConfig()
    return state


def make_check_event(quality="strong_hit", effect=2, skill="Persuade"):
    """Create a fake scene_check event for summary input."""
    return Event(
        kind=EventKind.ROLL,
        command_type="scene_check",
        description=f"Scene check ({skill})",
        changes={
            "skill": skill,
            "quality": quality,
            "effect": effect,
        },
    )


def make_fact_event(name="Dock Officer Vex"):
    """Create a fake register_fact event."""
    return Event(
        kind=EventKind.STATE_CHANGE,
        command_type="register_fact",
        description=f"Registered: {name}",
        changes={"name": name, "description": "An NPC."},
    )


# ---------------------------------------------------------------------------
# Summary validator (R19).
# ---------------------------------------------------------------------------


class TestSummaryValidator:
    """Summary validation against canonical state."""

    def test_valid_summary_passes(self):
        """A clean summary with no mechanical claims passes validation."""
        state = make_state()
        state.entities.append(NarrativeFact(name="Vex", description="An NPC."))
        validator = SummaryValidator()

        result = validator.validate(
            "The crew met Vex at the station and negotiated a deal.",
            state,
        )
        assert result.valid is True

    def test_mechanical_dice_notation_rejected(self):
        """Dice notation (e.g., 2d6) is rejected."""
        state = make_state()
        validator = SummaryValidator()

        result = validator.validate("The crew rolled 2d6 and succeeded.", state)
        assert result.valid is False
        assert any("Mechanical" in e for e in result.errors)

    def test_mechanical_dm_rejected(self):
        """DM references are rejected."""
        state = make_state()
        validator = SummaryValidator()

        result = validator.validate("With a +2 DM, the check succeeded.", state)
        assert result.valid is False

    def test_mechanical_stat_abbreviations_rejected(self):
        """Raw stat abbreviations (STR, DEX, etc.) are rejected."""
        state = make_state()
        validator = SummaryValidator()

        result = validator.validate("The character's STR was impressive.", state)
        assert result.valid is False

    def test_mechanical_roll_reference_rejected(self):
        """The word 'roll' is rejected."""
        state = make_state()
        validator = SummaryValidator()

        result = validator.validate("The crew made a roll and won.", state)
        assert result.valid is False

    def test_mechanical_vs_target_rejected(self):
        """'vs 8' style references are rejected."""
        state = make_state()
        validator = SummaryValidator()

        result = validator.validate("The result was vs 8 and they passed.", state)
        assert result.valid is False

    def test_effect_value_rejected(self):
        """Effect values (e.g., effect +3) are rejected."""
        state = make_state()
        validator = SummaryValidator()

        result = validator.validate("The check had effect +3.", state)
        assert result.valid is False


# ---------------------------------------------------------------------------
# Chapter summarizer (AE16).
# ---------------------------------------------------------------------------


class TestChapterSummarizer:
    """Chapter summary generation and regeneration on validation failure."""

    def test_template_summary_generated(self):
        """Template summary is generated from events."""
        state = make_state()
        events = [
            make_check_event("strong_hit", 3, "Persuade"),
            make_check_event("weak_hit", 1, "Stealth"),
            make_check_event("miss", -2, "Gun Combat"),
            make_fact_event("Vex"),
        ]
        summarizer = ChapterSummarizer()

        result = summarizer.summarize_mission(events, state, "Rescue the hostage from Vex.")

        assert len(result.summary) > 0
        assert "Rescue the hostage" in result.summary
        assert result.valid is True

    def test_summary_does_not_contain_mechanical_claims(self):
        """Template summary has no dice/modifiers/stat abbreviations."""
        state = make_state()
        events = [make_check_event("strong_hit", 3, "Persuade")]
        summarizer = ChapterSummarizer()

        result = summarizer.summarize_mission(events, state, "A simple mission.")

        # Validate the template output.
        validator = SummaryValidator()
        validation = validator.validate(result.summary, state)
        assert validation.valid is True

    def test_llm_summary_validated_on_success(self):
        """LLM-generated summary passes validation when clean."""
        state = make_state()
        events = [make_check_event("strong_hit", 3, "Persuade")]
        summarizer = ChapterSummarizer()

        # LLM generator that returns a clean summary.
        def good_generator(events, desc, attempt):
            return "The crew succeeded in their mission."

        result = summarizer.summarize_mission(
            events,
            state,
            "Test mission.",
            llm_generator=good_generator,
        )

        assert result.valid is True
        assert result.retries_used == 0

    def test_llm_summary_rejected_then_regenerated(self):
        """Invalid LLM summary triggers regeneration (AE16)."""
        state = make_state()
        events = [make_check_event("strong_hit", 3, "Persuade")]
        summarizer = ChapterSummarizer(max_retries=3)

        call_count = [0]

        def generator(events, desc, attempt):
            call_count[0] += 1
            if attempt == 0:
                return "They rolled 2d6 and won."  # Invalid: mechanical.
            return "The crew completed the mission successfully."  # Valid.

        result = summarizer.summarize_mission(
            events,
            state,
            "Test mission.",
            llm_generator=generator,
        )

        assert result.valid is True
        assert result.retries_used == 1
        assert call_count[0] == 2  # First attempt failed, second succeeded.

    def test_all_retries_exhausted_ships_best_available(self):
        """Validation failure after all retries ships best-available with flag."""
        state = make_state()
        events = [make_check_event()]
        summarizer = ChapterSummarizer(max_retries=2)

        def always_bad_generator(events, desc, attempt):
            return f"They rolled 2d6 on attempt {attempt}."  # Always invalid.

        result = summarizer.summarize_mission(
            events,
            state,
            "Test mission.",
            llm_generator=always_bad_generator,
        )

        assert result.valid is False
        assert result.retries_used == 2
        assert result.best_available is True
        assert len(result.validation_errors) > 0

    def test_retry_limit_respected(self):
        """Summarizer respects the max_retries limit."""
        state = make_state()
        events = [make_check_event()]
        summarizer = ChapterSummarizer(max_retries=3)

        call_count = [0]

        def always_bad(events, desc, attempt):
            call_count[0] += 1
            return "They rolled dice."  # Always invalid.

        summarizer.summarize_mission(
            events,
            state,
            "Test.",
            llm_generator=always_bad,
        )

        # Should have been called max_retries times for generation + validation,
        # plus one final template generation.
        assert call_count[0] == 3


# ---------------------------------------------------------------------------
# AE16: Chapter summaries replace raw event history.
# ---------------------------------------------------------------------------


class TestChapterSummaryReplacement:
    """After missions complete, summaries replace raw events in LLM context."""

    def test_summary_stored_in_state(self):
        """Chapter summary is stored in GameState.chapter_summaries."""
        state = make_state()
        events = [make_check_event("strong_hit", 3, "Persuade")]
        summarizer = ChapterSummarizer()

        result = summarizer.summarize_mission(events, state, "Mission 1.")
        state.chapter_summaries.append(result.summary)

        assert len(state.chapter_summaries) == 1
        assert result.summary in state.chapter_summaries

    def test_two_missions_produce_two_summaries(self):
        """After two completed missions, context has two summaries (AE16)."""
        state = make_state()
        summarizer = ChapterSummarizer()

        # Mission 1.
        events1 = [make_check_event("strong_hit", 3, "Persuade")]
        r1 = summarizer.summarize_mission(events1, state, "Mission 1.")
        state.chapter_summaries.append(r1.summary)

        # Mission 2.
        events2 = [make_check_event("weak_hit", 1, "Stealth")]
        r2 = summarizer.summarize_mission(events2, state, "Mission 2.")
        state.chapter_summaries.append(r2.summary)

        assert len(state.chapter_summaries) == 2

        # LLM context should use summaries, not raw events.
        context = get_llm_context_summaries(state)
        assert len(context) == 2
        assert r1.summary in context
        assert r2.summary in context

    def test_has_raw_history_been_summarized_flag(self):
        """The flag correctly indicates when summaries exist."""
        state = make_state()
        assert has_raw_history_been_summarized(state) is False

        state.chapter_summaries.append("A summary.")
        assert has_raw_history_been_summarized(state) is True

    def test_summaries_appear_in_curated_view(self):
        """Chapter summaries appear in the curated view (R19)."""
        from src.llm.state_view import build_curated_view

        state = make_state()
        state.chapter_summaries.append("Mission 1 summary.")
        state.chapter_summaries.append("Mission 2 summary.")

        view = build_curated_view(state)

        assert len(view.chapter_summaries) == 2
        assert "Mission 1 summary." in view.chapter_summaries

    def test_raw_events_not_in_curated_view(self):
        """Raw event details are not in the curated view (R19)."""
        from src.llm.state_view import build_curated_view

        state = make_state()
        state.chapter_summaries.append("A clean summary.")

        # Add some events to state.
        state.events.append(make_check_event())

        view = build_curated_view(state)
        import json

        raw = json.dumps(view.model_dump())

        # Raw event data should not be present.
        assert "command_type" not in raw
        assert "scene_check" not in raw


# ---------------------------------------------------------------------------
# Integration: validation failure triggers regeneration.
# ---------------------------------------------------------------------------


class TestValidationRegeneration:
    """Validation failure triggers regeneration up to retry limit (AE16)."""

    def test_regeneration_eventually_succeeds(self):
        """Summary succeeds on third attempt after two failures."""
        state = make_state()
        events = [make_check_event()]
        summarizer = ChapterSummarizer(max_retries=5)

        def generator(events, desc, attempt):
            if attempt < 2:
                return "They made a roll with a DM."  # Invalid.
            return "The crew completed their objective."  # Valid.

        result = summarizer.summarize_mission(
            events,
            state,
            "Test.",
            llm_generator=generator,
        )

        assert result.valid is True
        assert result.retries_used == 2

    def test_regeneration_with_different_errors(self):
        """Different validation errors across attempts."""
        state = make_state()
        events = [make_check_event()]
        summarizer = ChapterSummarizer(max_retries=4)

        attempts = []

        def generator(events, desc, attempt):
            attempts.append(attempt)
            if attempt == 0:
                return "They rolled 2d6."  # Dice notation.
            elif attempt == 1:
                return "Their STR was high."  # Stat abbreviation.
            return "Success through determination."  # Valid.

        result = summarizer.summarize_mission(
            events,
            state,
            "Test.",
            llm_generator=generator,
        )

        assert result.valid is True
        assert result.retries_used == 2
        assert len(attempts) == 3
