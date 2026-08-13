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
