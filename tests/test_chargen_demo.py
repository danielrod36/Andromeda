"""P6.T4 — demo harness smoke test."""

from __future__ import annotations


class TestChargenDemo:
    """The demo harness runs to completion headlessly."""

    def test_demo_smoke(self, monkeypatch, capsys):
        """Drive the demo with scripted inputs through a full lifepath."""
        from scripts.chargen_demo import run_demo

        # Script: always pick first option
        inputs = iter(["0"] * 200)
        monkeypatch.setattr("builtins.input", lambda *_: next(inputs))
        run_demo(seed=42, death_mode="narrative")
        captured = capsys.readouterr()
        assert "complete" in captured.out.lower() or "character" in captured.out.lower()
