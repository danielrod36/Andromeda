"""Tests for guided retry: steering, badge, retry cap, AE5 (U15, R17).

Covers:
- AE5: state and event log are byte-identical across a regeneration.
- Steering text appears in the prompt sent to the model.
- Retry cap: fourth retry is refused.
- Template-mode sessions: no retry affordance (error event).
- Badge block renders "outcome unchanged".
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

#: Origin header required by SameOriginGuard for POST requests.
_ORIGIN = {"Origin": "http://127.0.0.1"}


def _get_client(saves_dir: Path) -> TestClient:
    from src.web.app import create_app
    from src.web.routes import adventure as adv_module
    from src.web.routes import lifepath as life_module
    from src.web.routes import menu as menu_module
    from src.web.routes import stream as stream_module

    saves_dir.mkdir(parents=True, exist_ok=True)
    menu_module.DEFAULT_SAVES_DIR = saves_dir
    life_module.DEFAULT_SAVES_DIR = saves_dir
    adv_module.DEFAULT_SAVES_DIR = saves_dir
    stream_module.DEFAULT_SAVES_DIR = saves_dir
    return TestClient(create_app(), base_url="http://127.0.0.1")


def _create_save(saves_dir: Path, name: str = "Hero") -> Path:
    from src.engine.persistence import save
    from src.engine.state import CampaignConfig, GameState

    state = GameState.new(seed=42)
    state.campaign = CampaignConfig(theme_pack="scifi")
    state.character.name = name
    state.character.career = "navy"
    state.character.alive = True
    state.narrative_log.append("mustered_out=true")
    path = saves_dir / f"{name}.json"
    save(state, path)
    return path


def _data_lines(text: str) -> list[dict]:
    """Extract SSE data payloads from response text."""
    return [
        json.loads(line.removeprefix("data: "))
        for line in text.split("\n")
        if line.startswith("data: ")
    ]


class TestRetryEndpoint:
    """POST /stream/{name}/retry SSE endpoint (U15)."""

    def test_retry_emits_badge_and_blocks(self, tmp_path: Path):
        """Retry stream includes badge + narration blocks + done."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.post(
                "/stream/Hero/retry",
                data={"steering_text": "Make it darker", "attempt": "1"},
                headers=_ORIGIN,
            )
        assert response.status_code == 200
        lines = _data_lines(response.text)
        assert len(lines) >= 3  # badge + at least 1 block + done.

        # First data should be the badge.
        assert lines[0]["type"] == "badge"
        assert "unchanged" in lines[0]["content"].lower()

        # Last should be done.
        assert lines[-1]["type"] == "done"

    def test_retry_includes_steering_in_content(self, tmp_path: Path):
        """Steering text appears in the streamed content (template mode)."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.post(
                "/stream/Hero/retry",
                data={"steering_text": "Focus on the tension", "attempt": "1"},
                headers=_ORIGIN,
            )
        assert "Focus on the tension" in response.text

    def test_retry_cap_blocks_fourth(self, tmp_path: Path):
        """Fourth retry (attempt=4) is refused with error."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.post(
                "/stream/Hero/retry",
                data={"steering_text": "try again", "attempt": "4"},
                headers=_ORIGIN,
            )
        lines = _data_lines(response.text)
        assert lines[0]["type"] == "error"
        assert "limit" in lines[0]["content"].lower()

    def test_retry_cap_allows_third(self, tmp_path: Path):
        """Third retry (attempt=3) is the last allowed."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.post(
                "/stream/Hero/retry",
                data={"steering_text": "one more", "attempt": "3"},
                headers=_ORIGIN,
            )
        lines = _data_lines(response.text)
        assert lines[-1]["type"] == "done"

    def test_nonexistent_save_error(self, tmp_path: Path):
        """Nonexistent save produces an error event."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.post(
                "/stream/Nobody/retry",
                data={"steering_text": "x", "attempt": "1"},
                headers=_ORIGIN,
            )
        assert "error" in response.text or "not found" in response.text.lower()

    def test_empty_steering_text_works(self, tmp_path: Path):
        """Empty steering text is accepted (player can re-narrate without direction)."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.post(
                "/stream/Hero/retry",
                data={"steering_text": "", "attempt": "1"},
                headers=_ORIGIN,
            )
        lines = _data_lines(response.text)
        assert lines[-1]["type"] == "done"


class TestAE5StateIntegrity:
    """AE5: state and event log are byte-identical across regeneration (U15)."""

    def test_state_unchanged_after_retry(self, tmp_path: Path):
        """The save file is not modified by a retry request."""
        saves_dir = tmp_path / "saves"
        save_path = _create_save(saves_dir)

        before = save_path.read_bytes()

        with _get_client(saves_dir) as client:
            client.post(
                "/stream/Hero/retry",
                data={"steering_text": "Make it epic", "attempt": "1"},
                headers=_ORIGIN,
            )

        after = save_path.read_bytes()
        assert before == after


class TestSteeredPrompt:
    """Steering text appears in the prompt sent to the model (U15)."""

    def test_steered_prompt_contains_steering_text(self):
        from src.llm.prompts import build_steered_scene_prompt
        from src.llm.state_view import CuratedView

        view = MagicMock(spec=CuratedView)
        view.model_dump.return_value = {"character_name": "Hero"}
        scaffold = MagicMock()
        scaffold.focus = "Combat"
        scaffold.focus_description = "A fight"
        scaffold.situation = "Under fire"
        scaffold.npc_hint = None

        prompt = build_steered_scene_prompt(
            view, scaffold, ["You hit the target"], "Make it feel desperate"
        )

        assert "Make it feel desperate" in prompt
        assert "Steering Direction" in prompt
        assert "You hit the target" in prompt


class TestBadgeBlock:
    """Badge block type for UI metadata (U15)."""

    def test_badge_block_format(self):
        from src.game.narration import build_badge_block

        block = build_badge_block("Test badge")
        sse = block.to_sse()
        assert sse.startswith("data: ")
        data = json.loads(sse.removeprefix("data: ").strip())
        assert data["type"] == "badge"
        assert data["content"] == "Test badge"

    def test_badge_block_in_valid_types(self):
        from src.game.narration import NarrationBlock

        block = NarrationBlock(type="badge", content="x")
        assert block.type == "badge"


class TestRetryCap:
    """MAX_RETRIES_PER_BEAT constant (U15)."""

    def test_cap_is_three(self):
        from src.game.narration import MAX_RETRIES_PER_BEAT

        assert MAX_RETRIES_PER_BEAT == 3


class TestNarrateSceneSteered:
    """Adapter narrate_scene_steered method (U15)."""

    def test_template_mode_returns_template(self):
        """Without LLM, steered narration returns template source."""
        from src.llm.adapter import LLMAdapter

        adapter = LLMAdapter()
        scaffold = MagicMock()
        scaffold.focus = "Test"
        scaffold.focus_description = "desc"
        scaffold.situation = "sit"
        scaffold.npc_hint = None

        import asyncio

        result = asyncio.run(
            adapter.narrate_scene_steered(
                scaffold,
                ["fact 1"],
                MagicMock(),
                "steering direction",
            )
        )
        assert result.source == "template"

    def test_llm_mode_produces_prose(self):
        """With a test model, steered narration produces LLM prose."""
        from pydantic_ai.models.test import TestModel

        from src.llm.adapter import LLMAdapter

        test_model = TestModel(custom_output_args={"prose": "A darker take on the scene."})
        adapter = LLMAdapter(test_model=test_model)

        scaffold = MagicMock()
        scaffold.focus = "Test"
        scaffold.focus_description = "desc"
        scaffold.situation = "sit"
        scaffold.npc_hint = None

        view = MagicMock()
        view.model_dump.return_value = {}

        import asyncio

        result = asyncio.run(
            adapter.narrate_scene_steered(
                scaffold,
                ["fact 1"],
                view,
                "darker tone",
            )
        )
        assert result.source == "llm"
        assert "darker take" in result.prose
