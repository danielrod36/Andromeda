"""Tests for tool-call pill provenance and scoping (U7, R13, AE3).

Covers:
- LLM tool calls produce events with ``origin="llm"`` in changes.
- Engine-originated events do NOT carry origin (no pills for them).
- AE3: template-mode play renders zero pills even when scenes register facts.
- Action POST renders pills; fresh GET renders none.
- Pill links are htmx-only (no ``href`` fallback).
- Old saves (events without origin) yield no pills.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.engine.audit import Event, EventKind
from src.game.pills import extract_pills, extract_recent_pills

# ---------------------------------------------------------------------------
# Unit-level pill extraction tests.
# ---------------------------------------------------------------------------


def _make_event(
    command_type: str,
    changes: dict,
    seq: int = 0,
) -> Event:
    """Build a minimal STATE_CHANGE event for pill testing."""
    return Event(
        seq=seq,
        kind=EventKind.STATE_CHANGE,
        command_type=command_type,
        description=f"test {command_type}",
        changes=changes,
    )


class TestPillProvenance:
    """Pills appear only for events with ``changes["origin"] == "llm"``."""

    def test_llm_register_fact_produces_pill(self):
        """RegisterFactCommand with origin='llm' yields a pill."""
        event = _make_event(
            "register_fact",
            {"name": "Bartender", "description": "Knows the docks", "origin": "llm"},
            seq=5,
        )
        pills = extract_pills([event])
        assert len(pills) == 1
        assert pills[0].tool_name == "Registered fact"
        assert pills[0].summary == "Bartender"
        assert pills[0].seq == 5

    def test_llm_set_flag_produces_pill(self):
        """SetFlagCommand with origin='llm' yields a pill."""
        event = _make_event(
            "set_flag",
            {"key": "met_npc", "value": "captain_vex", "origin": "llm"},
            seq=3,
        )
        pills = extract_pills([event])
        assert len(pills) == 1
        assert pills[0].tool_name == "Set narrative flag"
        assert "met_npc=captain_vex" in pills[0].summary

    def test_llm_narration_entry_produces_pill(self):
        """add_narrative_log_entry (SetFlagCommand key='narration') yields an 'Added log entry' pill."""
        event = _make_event(
            "set_flag",
            {"key": "narration", "value": "A daring escape!", "origin": "llm"},
            seq=7,
        )
        pills = extract_pills([event])
        assert len(pills) == 1
        assert pills[0].tool_name == "Added log entry"
        assert pills[0].summary == "A daring escape!"

    def test_engine_register_fact_no_pill(self):
        """Engine-originated RegisterFactCommand (no origin) yields no pill (R13)."""
        event = _make_event(
            "register_fact",
            {"name": "Advantage from scene", "description": "A lasting advantage."},
            seq=1,
        )
        pills = extract_pills([event])
        assert pills == []

    def test_engine_set_flag_no_pill(self):
        """Engine-originated SetFlagCommand (no origin) yields no pill."""
        event = _make_event(
            "set_flag",
            {"key": "mustered_out", "value": "true"},
            seq=2,
        )
        pills = extract_pills([event])
        assert pills == []

    def test_engine_ratify_fact_no_pill(self):
        """Engine-originated RatifyFactCommand (no origin) yields no pill."""
        event = _make_event(
            "ratify_fact",
            {"fact_name": "Bartender", "stats_description": "[NPC stats...]"},
            seq=4,
        )
        pills = extract_pills([event])
        assert pills == []

    def test_old_save_events_no_pill(self):
        """Events from old saves (no origin key at all) produce no pills — no migration."""
        old_events = [
            _make_event("register_fact", {"name": "Old NPC", "description": "..."}, seq=0),
            _make_event("set_flag", {"key": "old_flag", "value": "1"}, seq=1),
            _make_event("ratify_fact", {"fact_name": "Old NPC", "stats_description": "..."}, seq=2),
        ]
        assert extract_pills(old_events) == []

    def test_mixed_events_only_llm_pills(self):
        """In a mixed log, only events with origin='llm' produce pills."""
        events = [
            _make_event("register_fact", {"name": "Engine fact"}, seq=0),
            _make_event("register_fact", {"name": "LLM fact", "origin": "llm"}, seq=1),
            _make_event("set_flag", {"key": "engine_flag", "value": "x"}, seq=2),
            _make_event("set_flag", {"key": "llm_flag", "value": "y", "origin": "llm"}, seq=3),
        ]
        pills = extract_pills(events)
        assert len(pills) == 2
        assert pills[0].seq == 1
        assert pills[1].seq == 3


class TestExtractRecentPills:
    """extract_recent_pills filters by seq and provenance."""

    def test_only_recent_llm_events(self):
        events = [
            _make_event("set_flag", {"key": "old", "value": "x", "origin": "llm"}, seq=1),
            _make_event("set_flag", {"key": "new", "value": "y", "origin": "llm"}, seq=5),
        ]
        pills = extract_recent_pills(events, since_seq=3)
        assert len(pills) == 1
        assert pills[0].seq == 5

    def test_recent_engine_events_filtered_out(self):
        events = [
            _make_event("register_fact", {"name": "engine fact"}, seq=5),
            _make_event("set_flag", {"key": "llm", "value": "x", "origin": "llm"}, seq=6),
        ]
        pills = extract_recent_pills(events, since_seq=3)
        assert len(pills) == 1
        assert pills[0].seq == 6


# ---------------------------------------------------------------------------
# Integration: LLM tools stamp origin into events.
# ---------------------------------------------------------------------------


class TestLLMToolOriginStamp:
    """LLM tool wrappers produce events with origin='llm' in changes."""

    @pytest.mark.asyncio
    async def test_set_narrative_flag_stamps_origin(self):
        from src.engine.commands import Engine
        from src.engine.state import GameState
        from src.llm.tools import ToolDeps, set_narrative_flag

        state = GameState.new(seed=1)
        engine = Engine(state)
        deps = ToolDeps(engine=engine, state=state)

        class FakeCtx:
            pass

        ctx = FakeCtx()
        ctx.deps = deps

        await set_narrative_flag(ctx, "met_npc", "vex")
        assert state.events[-1].changes.get("origin") == "llm"

    @pytest.mark.asyncio
    async def test_add_narrative_log_entry_stamps_origin(self):
        from src.engine.commands import Engine
        from src.engine.state import GameState
        from src.llm.tools import ToolDeps, add_narrative_log_entry

        state = GameState.new(seed=2)
        engine = Engine(state)
        deps = ToolDeps(engine=engine, state=state)

        class FakeCtx:
            pass

        ctx = FakeCtx()
        ctx.deps = deps

        await add_narrative_log_entry(ctx, "A bold move!")
        assert state.events[-1].changes.get("origin") == "llm"

    @pytest.mark.asyncio
    async def test_register_fact_stamps_origin(self):
        from src.engine.commands import Engine
        from src.engine.state import GameState
        from src.llm.tools import ToolDeps, register_fact

        state = GameState.new(seed=3)
        engine = Engine(state)
        deps = ToolDeps(engine=engine, state=state)

        class FakeCtx:
            pass

        ctx = FakeCtx()
        ctx.deps = deps

        await register_fact(ctx, name="Bartender", description="A friendly face")
        assert state.events[-1].changes.get("origin") == "llm"


# ---------------------------------------------------------------------------
# Integration: engine-originated events never carry origin.
# ---------------------------------------------------------------------------


class TestEngineEventsNoOrigin:
    """Engine-originated commands never stamp origin into changes."""

    def test_engine_register_fact_no_origin(self):
        from src.engine.commands import Engine
        from src.engine.scene import RegisterFactCommand
        from src.engine.state import GameState

        state = GameState.new(seed=10)
        engine = Engine(state)
        engine.apply(RegisterFactCommand(name="Advantage", description="A bonus."))
        assert "origin" not in state.events[-1].changes

    def test_engine_set_flag_no_origin(self):
        from src.engine.commands import Engine, SetFlagCommand
        from src.engine.state import GameState

        state = GameState.new(seed=11)
        engine = Engine(state)
        engine.apply(SetFlagCommand(key="test", value="val"))
        assert "origin" not in state.events[-1].changes

    def test_engine_ratify_fact_no_origin(self):
        from src.engine.commands import Engine
        from src.engine.scene import RatifyFactCommand, RegisterFactCommand
        from src.engine.state import GameState

        state = GameState.new(seed=12)
        engine = Engine(state)
        engine.apply(RegisterFactCommand(name="NPC", description="Someone."))
        engine.apply(RatifyFactCommand(fact_name="NPC", stats_description="[NPC stats]"))
        # The ratify event should not have origin.
        assert "origin" not in state.events[-1].changes


# ---------------------------------------------------------------------------
# Web integration: pill scoping in adventure route responses.
# ---------------------------------------------------------------------------


def _get_client(saves_dir: Path) -> TestClient:
    from src.web.app import create_app
    from src.web.routes import adventure as adv_module
    from src.web.routes import lifepath as life_module
    from src.web.routes import menu as menu_module

    saves_dir.mkdir(parents=True, exist_ok=True)
    menu_module.DEFAULT_SAVES_DIR = saves_dir
    life_module.DEFAULT_SAVES_DIR = saves_dir
    adv_module.DEFAULT_SAVES_DIR = saves_dir
    return TestClient(create_app(), base_url="http://127.0.0.1")


def _create_adventure_save(saves_dir: Path, name: str = "Hero") -> Path:
    from src.engine.persistence import save
    from src.engine.state import CampaignConfig, GameState

    state = GameState.new(seed=42)
    state.campaign = CampaignConfig(
        theme_pack="scifi", resolution_profile="narrative", death_mode="narrative"
    )
    state.character.name = name
    state.character.characteristics = {
        "STR": 7,
        "DEX": 9,
        "END": 6,
        "INT": 8,
        "EDU": 10,
        "SOC": 5,
    }
    state.character.skills = {"Gun Combat": 1, "Persuade": 0, "Stealth": 2}
    state.character.career = "navy"
    state.character.terms = 2
    state.character.alive = True
    state.narrative_log.append("mustered_out=true")
    path = saves_dir / f"{name}.json"
    save(state, path)
    return path


_ORIGIN = {"Origin": "http://127.0.0.1"}


class TestAdventurePillScoping:
    """Pills appear only in action POST responses, not in fresh GET (U7, R13)."""

    def test_fresh_get_renders_no_pills(self, tmp_path):
        """A fresh GET to the adventure screen renders zero pills, even if
        engine-originated RegisterFactCommand events exist in the log (AE3)."""
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        client = _get_client(saves_dir)

        resp = client.get("/adventure/Hero", headers=_ORIGIN)
        assert resp.status_code == 200
        body = resp.text
        # No pill markup in a fresh GET.
        assert 'class="pills"' not in body
        assert 'class="pill-link"' not in body

    def test_action_post_no_pills_in_template_mode(self, tmp_path):
        """An action POST in template mode (no LLM events) renders no pills (AE3)."""
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        client = _get_client(saves_dir)

        # GET first to populate the session registry.
        client.get("/adventure/Hero", headers=_ORIGIN)

        # POST an action — no LLM configured, so no origin='llm' events.
        resp = client.post(
            "/adventure/Hero/action",
            data={"choice": "accept_mission"},
            headers=_ORIGIN,
        )
        assert resp.status_code == 200
        assert 'class="pill-link"' not in resp.text

    def test_pill_link_template_is_htmx_only(self):
        """Pill links use hx-get with no href fallback (U7) — template-level check."""
        from pathlib import Path

        template = (
            Path(__file__).resolve().parent.parent.parent
            / "src"
            / "web"
            / "templates"
            / "partials"
            / "pills.html"
        ).read_text()
        assert "hx-get" in template
        assert 'hx-target=".drawer-content"' in template
        # The template must not contain an href attribute on the pill link.
        assert "href=" not in template
