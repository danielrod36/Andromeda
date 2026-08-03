"""Tests for the SSE streaming narration endpoint (U10)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient


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


class TestSSEStream:
    """U10: the SSE endpoint streams typed blocks then done."""

    def test_stream_returns_event_stream(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/stream/Hero/narration")
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

    def test_stream_emits_blocks_and_done(self, tmp_path: Path):
        """The stream contains at least one block and a terminal done event."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/stream/Hero/narration")
        text = response.text

        # SSE lines start with "data: "
        data_lines = [line for line in text.split("\n") if line.startswith("data: ")]
        assert len(data_lines) >= 2  # At least one block + done.

        # Last data line should be the done event.
        last_data = json.loads(data_lines[-1].removeprefix("data: "))
        assert last_data["type"] == "done"

    def test_stream_blocks_have_valid_types(self, tmp_path: Path):
        """Each block has a valid type and content."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/stream/Hero/narration")
        text = response.text
        valid_types = {"narration", "receipt", "change", "divider", "pill", "done", "error"}

        for line in text.split("\n"):
            if line.startswith("data: "):
                data = json.loads(line.removeprefix("data: "))
                assert data["type"] in valid_types
                assert "content" in data

    def test_stream_includes_character_name(self, tmp_path: Path):
        """The narration content includes the character name."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir, name="Ace")
        with _get_client(saves_dir) as client:
            response = client.get("/stream/Ace/narration")
        assert "Ace" in response.text

    def test_nonexistent_save_emits_error(self, tmp_path: Path):
        """A nonexistent save produces an error event."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/stream/Nobody/narration")
        text = response.text
        assert "error" in text or "not found" in text.lower()

    def test_no_llm_session_delivers_template_blocks(self, tmp_path: Path):
        """Without an LLM configured, template blocks are emitted through the same endpoint (AE3)."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/stream/Hero/narration")
        # Template mode still produces valid SSE blocks and a done event.
        assert response.status_code == 200
        data_lines = [line for line in response.text.split("\n") if line.startswith("data: ")]
        assert len(data_lines) >= 2
        last = json.loads(data_lines[-1].removeprefix("data: "))
        assert last["type"] == "done"


class TestNarrationBlocks:
    """U10: NarrationBlock serialization and assembly."""

    def test_block_to_sse_format(self):
        from src.game.narration import NarrationBlock

        block = NarrationBlock(type="narration", content="The starport hums.")
        sse = block.to_sse()
        assert sse.startswith("data: ")
        assert sse.endswith("\n\n")
        data = json.loads(sse.removeprefix("data: ").strip())
        assert data["type"] == "narration"
        assert data["content"] == "The starport hums."

    def test_build_template_blocks(self):
        from src.game.narration import build_template_blocks

        blocks = build_template_blocks("Scene text", ["consequence 1"], ["receipt 1", "receipt 2"])
        assert len(blocks) == 4  # 1 narration + 2 receipts + 1 change
        assert blocks[0].type == "narration"
        assert blocks[1].type == "receipt"
        assert blocks[3].type == "change"

    def test_done_block(self):
        from src.game.narration import build_done_block

        block = build_done_block()
        assert block.type == "done"
        assert block.content == ""

    def test_error_block(self):
        from src.game.narration import build_error_block

        block = build_error_block("something broke")
        assert block.type == "error"
        assert "broke" in block.content
