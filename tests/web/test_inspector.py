"""Tests for tool-call pills and the curated-view inspector (U16, R18, AE13).

Covers:
- Pill extraction: register_fact tool call produces a pill with summary and seq.
- Pill extraction: ratify_fact uses the correct ``fact_name`` changes key.
- Pill extraction: set_flag with key="narration" is labeled as "Added log entry".
- Pill extraction: non-tool events are skipped.
- Pill extraction: empty key fallback (no dangling colon).
- Recent pills: sequence-boundary filtering.
- Inspector route: renders curated view JSON, AE13 guard passes.
- Inspector: no prohibited fields in the rendered payload.
- Inspector: AE13 guard failure hides the view (no leak).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.engine.audit import Event, EventKind
from src.engine.state import GameState


def _make_event(
    command_type: str,
    changes: dict,
    seq: int = 0,
    kind: EventKind = EventKind.STATE_CHANGE,
) -> Event:
    return Event(
        seq=seq,
        kind=kind,
        command_type=command_type,
        description="test",
        changes=changes,
    )


# ---------------------------------------------------------------------------
# Pill extraction tests.
# ---------------------------------------------------------------------------


class TestPillExtraction:
    """Tool-call pills from the event log (U16, R18)."""

    def test_register_fact_produces_pill(self):
        from src.game.pills import extract_pills

        events = [
            _make_event(
                "register_fact",
                {"name": "Station Alpha", "description": "a hub"},
                seq=5,
            ),
        ]
        pills = extract_pills(events)
        assert len(pills) == 1
        assert "Registered fact" in pills[0].tool_name
        assert pills[0].summary == "Station Alpha"
        assert pills[0].seq == 5

    def test_ratify_fact_produces_pill(self):
        """ratify_fact events carry fact_name (not name) in changes."""
        from src.game.pills import extract_pills

        events = [
            _make_event(
                "ratify_fact",
                {"fact_name": "Captain Vex", "stats_description": "a smuggler"},
                seq=3,
            ),
        ]
        pills = extract_pills(events)
        assert len(pills) == 1
        assert "Ratified" in pills[0].tool_name
        assert pills[0].summary == "Captain Vex"

    def test_set_flag_produces_pill(self):
        from src.game.pills import extract_pills

        events = [
            _make_event("set_flag", {"key": "mood", "value": "tense"}, seq=1),
        ]
        pills = extract_pills(events)
        assert len(pills) == 1
        assert "mood=tense" in pills[0].summary

    def test_narration_key_labeled_as_log_entry(self):
        """add_narrative_log_entry tool uses SetFlagCommand(key='narration').

        The resulting set_flag event must be labeled 'Added log entry',
        not 'Set narrative flag'.
        """
        from src.game.pills import extract_pills

        events = [
            _make_event(
                "set_flag",
                {"key": "narration", "value": "The captain drew her sidearm."},
                seq=7,
            ),
        ]
        pills = extract_pills(events)
        assert len(pills) == 1
        assert pills[0].tool_name == "Added log entry"
        assert "The captain drew her sidearm." in pills[0].summary

    def test_set_flag_empty_key_no_dangling_colon(self):
        """Empty key in set_flag does not produce a dangling colon in label."""
        from src.game.pills import extract_pills

        events = [
            _make_event("set_flag", {"key": "", "value": ""}, seq=1),
        ]
        pills = extract_pills(events)
        assert len(pills) == 1
        assert not pills[0].label.endswith(": ")

    def test_non_tool_events_skipped(self):
        from src.game.pills import extract_pills

        events = [
            _make_event("scene_check", {"skill": "Gun Combat"}, seq=0),
            _make_event("oracle_roll", {"table_id": "t"}, seq=1),
            _make_event("gain_skill", {"skill_id": "Pilot"}, seq=2),
        ]
        pills = extract_pills(events)
        assert len(pills) == 0

    def test_mixed_events(self):
        from src.game.pills import extract_pills

        events = [
            _make_event("scene_check", {}, seq=0),
            _make_event("register_fact", {"name": "Fact A"}, seq=1),
            _make_event("oracle_roll", {}, seq=2),
            _make_event("register_fact", {"name": "Fact B"}, seq=3),
        ]
        pills = extract_pills(events)
        assert len(pills) == 2
        assert pills[0].summary == "Fact A"
        assert pills[1].summary == "Fact B"
        assert pills[0].seq == 1
        assert pills[1].seq == 3

    def test_empty_log(self):
        from src.game.pills import extract_pills

        assert extract_pills([]) == []

    def test_pill_label_property(self):
        from src.game.pills import ToolPill

        pill = ToolPill(tool_name="Registered fact", summary="Station Alpha", seq=5)
        assert "Registered fact" in pill.label
        assert "Station Alpha" in pill.label


class TestRecentPills:
    """Sequence-boundary filtering for pills (U16)."""

    def test_since_seq(self):
        from src.game.pills import extract_recent_pills

        events = [
            _make_event("register_fact", {"name": "A"}, seq=1),
            _make_event("register_fact", {"name": "B"}, seq=2),
            _make_event("register_fact", {"name": "C"}, seq=3),
        ]
        pills = extract_recent_pills(events, since_seq=1)
        assert len(pills) == 2
        assert pills[0].summary == "B"
        assert pills[1].summary == "C"


# ---------------------------------------------------------------------------
# Inspector route tests.
# ---------------------------------------------------------------------------


def _get_client(saves_dir: Path) -> TestClient:
    from src.web.app import create_app
    from src.web.routes import adventure as adv_module
    from src.web.routes import inspector as insp_module
    from src.web.routes import lifepath as life_module
    from src.web.routes import menu as menu_module
    from src.web.routes import stream as stream_module

    saves_dir.mkdir(parents=True, exist_ok=True)
    menu_module.DEFAULT_SAVES_DIR = saves_dir
    life_module.DEFAULT_SAVES_DIR = saves_dir
    adv_module.DEFAULT_SAVES_DIR = saves_dir
    stream_module.DEFAULT_SAVES_DIR = saves_dir
    insp_module.DEFAULT_SAVES_DIR = saves_dir
    return TestClient(create_app(), base_url="http://127.0.0.1")


def _create_save(saves_dir: Path, name: str = "Hero") -> Path:
    from src.engine.persistence import save
    from src.engine.state import CampaignConfig, GameState

    state = GameState.new(seed=42)
    state.campaign = CampaignConfig(theme_pack="scifi")
    state.character.name = name
    state.character.career = "navy"
    state.character.characteristics = {"STR": 7, "DEX": 9, "END": 6, "INT": 8, "EDU": 10, "SOC": 5}
    state.character.skills = {"Gun Combat": 1}
    state.character.alive = True
    state.narrative_log.append("mustered_out=true")
    state.open_threads = ["Debt to Vaska"]
    path = saves_dir / f"{name}.json"
    save(state, path)
    return path


class TestInspectorRoute:
    """GET /inspector/{save_name} renders curated view (U16, R18)."""

    def test_inspector_renders(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/inspector/Hero")
        assert response.status_code == 200
        assert "Hero" in response.text
        assert "navy" in response.text

    def test_inspector_shows_curated_fields(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/inspector/Hero")
        # Character sheet fields appear.
        assert "character_sheet" in response.text
        assert "Gun Combat" in response.text
        # Open threads appear.
        assert "Debt to Vaska" in response.text

    def test_inspector_no_prohibited_fields(self, tmp_path: Path):
        """AE13: prohibited keys must not appear in the rendered payload."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/inspector/Hero")
        prohibited = [
            '"rng"',
            '"events"',
            '"save_version"',
            '"seed"',
            '"ndice"',
            '"sides"',
        ]
        for key in prohibited:
            assert key not in response.text, f"Prohibited key {key} in inspector"

    def test_inspector_no_guard_error(self, tmp_path: Path):
        """AE13 guard passes on a clean state."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/inspector/Hero")
        assert "AE13 Violation" not in response.text

    def test_inspector_guard_failure_hides_view(self, tmp_path: Path):
        """When AE13 guard fails, the view JSON must not be rendered."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with (
            _get_client(saves_dir) as client,
            patch(
                "src.web.routes.inspector.assert_no_prohibited_fields",
                side_effect=ValueError("simulated leak"),
            ),
        ):
            response = client.get("/inspector/Hero")
        assert response.status_code == 200
        assert "AE13 Violation" in response.text
        assert "simulated leak" in response.text
        # The view JSON must NOT be rendered when the guard fails.
        assert "character_sheet" not in response.text

    def test_inspector_nonexistent_save(self, tmp_path: Path):
        """Nonexistent save redirects to saves page."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/inspector/Nobody", follow_redirects=False)
        assert response.status_code == 303


class TestCuratedViewIntegrity:
    """The curated view is faithful to what the LLM receives (U16, AE13)."""

    def test_view_has_no_prohibited_keys(self):
        from src.llm.state_view import assert_no_prohibited_fields, build_curated_view

        state = GameState.new(seed=1)
        view = build_curated_view(state)
        # Should not raise.
        assert_no_prohibited_fields(view)

    def test_view_contains_character_sheet(self):
        from src.llm.state_view import build_curated_view

        state = GameState.new(seed=1)
        state.character.name = "Test"
        view = build_curated_view(state)
        data = view.model_dump()
        assert "character_sheet" in data
        assert data["character_sheet"]["name"] == "Test"

    def test_view_excludes_events(self):
        from src.llm.state_view import build_curated_view

        state = GameState.new(seed=1)
        state.events.append(
            Event(
                kind=EventKind.ROLL,
                command_type="test",
                description="roll",
                changes={},
            )
        )
        view = build_curated_view(state)
        raw = json.dumps(view.model_dump())
        assert '"events"' not in raw
        assert '"roll"' not in raw
        assert '"rolls"' not in raw
