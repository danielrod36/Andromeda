"""Tests for the story-so-far recap assembly (U11, R13).

Covers:
- Template recap from chapter summaries, recent events, and open threads.
- 5-line cap enforcement.
- New campaign with no history → empty recap.
- LLM polish path: valid prose ships; invalid (mechanical claims) falls back.
- build_recap with no adapter returns template floor.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.engine.audit import Event, EventKind
from src.engine.state import CampaignConfig, GameState
from src.game.recap import (
    MAX_RECAP_LINES,
    RecapResult,
    _cap_lines,
    build_recap,
    build_template_recap,
)


def _make_state(
    *,
    name: str = "Hero",
    career: str = "navy",
    terms: int = 2,
    summaries: list[str] | None = None,
    events: list[Event] | None = None,
    threads: list[str] | None = None,
) -> GameState:
    """Create a state with enough history for a recap."""
    state = GameState.new(seed=42)
    state.campaign = CampaignConfig(theme_pack="scifi")
    state.character.name = name
    state.character.career = career
    state.character.terms = terms
    state.character.alive = True
    state.narrative_log.append("mustered_out=true")
    state.chapter_summaries = summaries or []
    state.events = events or []
    state.open_threads = threads or []
    return state


class TestTemplateRecap:
    """Deterministic template recap assembly (U11)."""

    def test_empty_state_no_history(self):
        """New campaign with no history renders no recap."""
        state = GameState.new(seed=1)
        lines = build_template_recap(state)
        assert lines == []

    def test_mid_lifepath_name_only(self):
        """Character exists but no career → name line only."""
        state = GameState.new(seed=1)
        state.character.name = "Ace"
        lines = build_template_recap(state)
        assert len(lines) == 1
        assert "Ace" in lines[0]

    def test_character_anchor_line(self):
        """Recap starts with the character's identity."""
        state = _make_state(name="Vala", career="scout", terms=3)
        lines = build_template_recap(state)
        assert lines[0] == "Vala — scout, 3 terms served"

    def test_includes_chapter_summaries(self):
        """Chapter summaries appear in the recap."""
        state = _make_state(
            summaries=[
                "The crew delivered the cargo and earned a contact.",
                "A salvage job went sideways but they escaped with the data.",
            ],
        )
        lines = build_template_recap(state)
        joined = " ".join(lines)
        assert "delivered the cargo" in joined
        assert "salvage job" in joined

    def test_includes_recent_events(self):
        """Recent state-change events appear in the recap."""
        events = [
            Event(
                kind=EventKind.STATE_CHANGE,
                command_type="scene_check",
                description="You gained the trust of the station commander.",
                changes={},
            ),
            Event(
                kind=EventKind.STATE_CHANGE,
                command_type="register_fact",
                description="A new lead pointed to the outer rim.",
                changes={},
            ),
        ]
        state = _make_state(events=events)
        lines = build_template_recap(state)
        joined = " ".join(lines)
        assert "trust of the station commander" in joined
        assert "outer rim" in joined

    def test_includes_open_threads(self):
        """Open threads appear at the end."""
        state = _make_state(threads=["Debt to Vaska", "Missing sister"])
        lines = build_template_recap(state)
        joined = " ".join(lines)
        assert "Debt to Vaska" in joined
        assert "Missing sister" in joined

    def test_five_line_cap(self):
        """Recap never exceeds MAX_RECAP_LINES."""
        events = [
            Event(
                kind=EventKind.STATE_CHANGE,
                command_type=f"cmd_{i}",
                description=f"Event number {i} happened.",
                changes={},
            )
            for i in range(20)
        ]
        summaries = [f"Mission {i} summary." for i in range(10)]
        threads = [f"Thread {i}" for i in range(10)]
        state = _make_state(summaries=summaries, events=events, threads=threads)
        lines = build_template_recap(state)
        assert len(lines) <= MAX_RECAP_LINES

    def test_excludes_noisy_internal_events(self):
        """Internal events (flag sets, RNG snapshots) don't pollute the recap."""
        events = [
            Event(
                kind=EventKind.STATE_CHANGE,
                command_type="set_flag",
                description="term_phase=assignment",
                changes={},
            ),
            Event(
                kind=EventKind.STATE_CHANGE,
                command_type="set_rng_snapshot",
                description="RNG snapshot saved",
                changes={},
            ),
            Event(
                kind=EventKind.STATE_CHANGE,
                command_type="scene_check",
                description="You found the hidden cache.",
                changes={},
            ),
        ]
        state = _make_state(events=events)
        lines = build_template_recap(state)
        joined = " ".join(lines)
        assert "term_phase" not in joined
        assert "RNG snapshot" not in joined
        assert "hidden cache" in joined

    def test_no_duplicate_lines(self):
        """Identical lines don't appear twice."""
        events = [
            Event(
                kind=EventKind.STATE_CHANGE,
                command_type="scene_check",
                description="You found the hidden cache.",
                changes={},
            ),
            Event(
                kind=EventKind.STATE_CHANGE,
                command_type="register_fact",
                description="You found the hidden cache.",
                changes={},
            ),
        ]
        state = _make_state(events=events)
        lines = build_template_recap(state)
        count = sum(1 for line in lines if "hidden cache" in line)
        assert count == 1


class TestCapLines:
    """The 5-line cap helper (U11)."""

    def test_multiline_split(self):
        text = "Line one.\nLine two.\nLine three.\nLine four.\nLine five.\nLine six."
        lines = _cap_lines(text, cap=5)
        assert len(lines) == 5
        assert lines[0] == "Line one."
        assert lines[4] == "Line five."

    def test_single_paragraph_sentence_split(self):
        text = "First sentence. Second sentence. Third sentence. Fourth. Fifth. Sixth."
        lines = _cap_lines(text, cap=5)
        assert len(lines) == 5
        assert lines[0] == "First sentence."

    def test_whitespace_lines_dropped(self):
        text = "Real line.\n\n\n  \nAnother line."
        lines = _cap_lines(text, cap=5)
        assert len(lines) == 2


class TestBuildRecap:
    """build_recap with and without adapter (U11)."""

    def test_no_adapter_returns_template(self):
        state = _make_state(summaries=["The mission succeeded."])
        result = build_recap(state)
        assert result.source == "template"
        assert result.llm_failed is False
        assert len(result.lines) >= 1

    def test_no_llm_configured_returns_template(self):
        adapter = MagicMock()
        adapter.llm_configured = False
        state = _make_state(summaries=["The mission succeeded."])
        result = build_recap(state, adapter=adapter)
        assert result.source == "template"

    def test_empty_history_returns_empty(self):
        state = GameState.new(seed=1)
        result = build_recap(state)
        assert result.lines == []
        assert result.source == "template"

    def test_llm_valid_prose_ships(self):
        """Valid LLM prose passes validation and ships."""
        from src.llm.adapter import LLMAdapter

        adapter = LLMAdapter()  # No model — llm_configured=False.
        # Manually set _scene_agent and flag to simulate configured.
        adapter._scene_agent = MagicMock()
        adapter._test_model = MagicMock()  # Forces llm_configured=True path.

        mock_result = MagicMock()
        mock_result.output.prose = (
            "You rose through the Navy ranks. "
            "A smuggling ring tested your resolve. "
            "Now, a new mission calls."
        )
        with patch.object(adapter, "_run_agent_sync_retry", return_value=mock_result):
            state = _make_state(
                summaries=["The crew delivered the cargo."],
                events=[
                    Event(
                        kind=EventKind.STATE_CHANGE,
                        command_type="scene_check",
                        description="You secured the station.",
                        changes={},
                    ),
                ],
            )
            result = build_recap(state, adapter=adapter)
        assert result.source == "llm"
        assert len(result.lines) <= MAX_RECAP_LINES

    def test_llm_mechanical_claims_fall_back(self):
        """LLM output with dice notation is rejected → template floor."""
        from src.llm.adapter import LLMAdapter

        adapter = LLMAdapter()
        adapter._scene_agent = MagicMock()
        adapter._test_model = MagicMock()

        mock_result = MagicMock()
        mock_result.output.prose = "You rolled 2d6 and beat the target number."
        with patch.object(adapter, "_run_agent_sync_retry", return_value=mock_result):
            state = _make_state(
                summaries=["The crew delivered the cargo."],
            )
            result = build_recap(state, adapter=adapter)
        assert result.source == "template"
        assert result.llm_failed is True

    def test_llm_exception_falls_back(self):
        """Provider error → template floor, llm_failed=True."""
        from src.llm.adapter import LLMAdapter

        adapter = LLMAdapter()
        adapter._scene_agent = MagicMock()
        adapter._test_model = MagicMock()

        with patch.object(
            adapter, "_run_agent_sync_retry", side_effect=RuntimeError("network down")
        ):
            state = _make_state(summaries=["The crew survived."])
            result = build_recap(state, adapter=adapter)
        assert result.source == "template"
        assert result.llm_failed is True

    def test_recap_result_dataclass(self):
        """RecapResult has the right shape."""
        r = RecapResult(lines=["a", "b"], source="llm")
        assert r.lines == ["a", "b"]
        assert r.source == "llm"
        assert r.llm_failed is False

    def test_covers_most_recent_mission(self):
        """Template recap covers the most recent mission (scenario from plan)."""
        state = _make_state(
            summaries=[
                "First mission: delivered cargo to Vega.",
                "Second mission: rescued the diplomat from rebels.",
            ],
            threads=["The diplomat owes you a favor"],
        )
        lines = build_template_recap(state)
        joined = " ".join(lines)
        # Most recent summary should be included.
        assert "rescued the diplomat" in joined
        # Open thread should be included.
        assert "owes you a favor" in joined
        assert len(lines) <= MAX_RECAP_LINES
