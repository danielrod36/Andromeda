"""Tests for LLM tool definitions — tool-call validation (R3, test scenario 4).

Tools must:
- Mutate state only through the command funnel (Engine.apply).
- Reject invalid arguments with clear errors.
- Never alter dice or mechanical outcomes directly.
"""

from __future__ import annotations

import pytest

from src.engine.commands import Engine
from src.engine.state import GameState
from src.llm.tools import TOOL_REGISTRY, ToolDeps, add_narrative_log_entry, set_narrative_flag

# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


class FakeRunContext:
    """Minimal RunContext stand-in for unit-testing tools without an agent."""

    def __init__(self, deps: ToolDeps):
        self.deps = deps


@pytest.fixture
def deps() -> ToolDeps:
    state = GameState.new(seed=99)
    engine = Engine(state)
    return ToolDeps(engine=engine, state=state)


@pytest.fixture
def ctx(deps: ToolDeps) -> FakeRunContext:
    return FakeRunContext(deps)


# ---------------------------------------------------------------------------
# Tool registry tests.
# ---------------------------------------------------------------------------


class TestToolRegistry:
    def test_registry_has_expected_tools(self):
        assert "set_narrative_flag" in TOOL_REGISTRY
        assert "add_narrative_log_entry" in TOOL_REGISTRY

    def test_all_tools_are_callable(self):
        for name, func in TOOL_REGISTRY.items():
            assert callable(func), f"Tool {name} is not callable"


# ---------------------------------------------------------------------------
# set_narrative_flag tests.
# ---------------------------------------------------------------------------


class TestSetNarrativeFlag:
    @pytest.mark.asyncio
    async def test_sets_flag_through_funnel(self, ctx, deps):
        result = await set_narrative_flag(ctx, "met_npc", "captain_vex")
        assert "met_npc=captain_vex" in result
        # Verify it went through the funnel (event appended).
        assert len(deps.state.events) == 1
        assert deps.state.events[0].command_type == "set_flag"
        # Verify the flag is in the narrative log.
        assert "met_npc=captain_vex" in deps.state.narrative_log

    @pytest.mark.asyncio
    async def test_rejects_empty_key(self, ctx):
        with pytest.raises(ValueError, match="snake_case"):
            await set_narrative_flag(ctx, "", "value")

    @pytest.mark.asyncio
    async def test_rejects_whitespace_key(self, ctx):
        with pytest.raises(ValueError, match="snake_case"):
            await set_narrative_flag(ctx, "   ", "value")

    @pytest.mark.asyncio
    async def test_rejects_uppercase_key(self, ctx):
        with pytest.raises(ValueError, match="snake_case"):
            await set_narrative_flag(ctx, "MetNPC", "value")

    @pytest.mark.asyncio
    async def test_rejects_special_chars_in_key(self, ctx, deps):
        with pytest.raises(ValueError, match="snake_case"):
            await set_narrative_flag(ctx, "met;drop table", "value")

    @pytest.mark.asyncio
    async def test_multiple_flags_appended(self, ctx, deps):
        await set_narrative_flag(ctx, "flag_a", "1")
        await set_narrative_flag(ctx, "flag_b", "2")
        assert len(deps.state.events) == 2
        assert len(deps.state.narrative_log) == 2


# ---------------------------------------------------------------------------
# add_narrative_log_entry tests.
# ---------------------------------------------------------------------------


class TestAddNarrativeLogEntry:
    @pytest.mark.asyncio
    async def test_adds_entry_through_funnel(self, ctx, deps):
        result = await add_narrative_log_entry(ctx, "A daring escape!")
        assert "added" in result.lower()
        assert len(deps.state.events) == 1
        assert "A daring escape!" in deps.state.narrative_log[0]

    @pytest.mark.asyncio
    async def test_rejects_empty_entry(self, ctx):
        with pytest.raises(ValueError, match="non-empty"):
            await add_narrative_log_entry(ctx, "")

    @pytest.mark.asyncio
    async def test_rejects_whitespace_entry(self, ctx):
        with pytest.raises(ValueError, match="non-empty"):
            await add_narrative_log_entry(ctx, "   ")

    @pytest.mark.asyncio
    async def test_strips_whitespace(self, ctx, deps):
        await add_narrative_log_entry(ctx, "  padded entry  ")
        assert deps.state.narrative_log[0] == "narration=padded entry"


# ---------------------------------------------------------------------------
# Command funnel integration.
# ---------------------------------------------------------------------------


class TestToolsUseCommandFunnel:
    """Tools must mutate state only through Engine.apply() — never directly."""

    @pytest.mark.asyncio
    async def test_tool_does_not_bypass_funnel(self, ctx, deps):
        """After a tool call, the event log must have exactly one entry."""
        initial_events = len(deps.state.events)
        await set_narrative_flag(ctx, "test", "val")
        assert len(deps.state.events) == initial_events + 1
        # The event must be the correct type.
        assert deps.state.events[-1].command_type == "set_flag"

    @pytest.mark.asyncio
    async def test_tool_does_not_alter_dice(self, ctx, deps):
        """Tools must never modify RNG state."""
        rng_before = deps.state.rng.snapshot()
        await set_narrative_flag(ctx, "test", "val")
        rng_after = deps.state.rng.snapshot()
        # RNG snapshots should be identical (no dice rolled).
        for stream in rng_before:
            assert rng_before[stream].internalstate == rng_after[stream].internalstate, (
                f"RNG stream '{stream}' was modified by a tool call"
            )
