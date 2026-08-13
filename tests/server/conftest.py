"""Server test fixtures (M0.6)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.server.app import create_app


@pytest.fixture()
def client(tmp_path):
    app = create_app(saves_dir=tmp_path / "saves", settings_dir=tmp_path / "settings")
    with TestClient(app) as test_client:
        yield test_client


def write_save(saves_dir, name: str, *, death_mode: str = "narrative", seed: int = 42):
    """Write a mustered-out, adventure-ready save document (M0.6 tests)."""
    from src.engine.persistence import save
    from src.engine.state import CampaignConfig, GameState

    state = GameState.new(seed=seed)
    state.campaign = CampaignConfig(
        resolution_profile="narrative", death_mode=death_mode, theme_pack="scifi"
    )
    state.character.name = "TestHero"
    state.character.characteristics = {
        "STR": 7,
        "DEX": 9,
        "END": 6,
        "INT": 8,
        "EDU": 10,
        "SOC": 5,
    }
    state.character.skills = {"Gun Combat": 1, "Persuade": 0}
    state.character.career = "navy"
    state.character.terms = 2
    state.narrative_log.append("mustered_out=true")
    saves_dir.mkdir(parents=True, exist_ok=True)
    return save(state, saves_dir / f"{name}.json")
