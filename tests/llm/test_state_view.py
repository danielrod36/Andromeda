"""Tests for the curated state view (AE13).

Verifies that the curated view:
- Contains all required fields (character sheet, active mission, scene NPCs,
  recent log, open threads).
- Excludes prohibited fields (raw dice, audit log details, RNG state,
  off-scene NPC stats, internal engine fields).
"""
from __future__ import annotations

import json

from src.engine.audit import Event, EventKind
from src.engine.dice import RollResult
from src.engine.state import Character, CampaignConfig, GameState
from src.llm.state_view import (
    PROHIBITED_KEYS,
    CharacterSheet,
    CuratedView,
    NpcSummary,
    assert_no_prohibited_fields,
    build_curated_view,
)


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


def make_state_with_events() -> GameState:
    """Build a GameState with events containing raw dice data.

    The curated view must exclude all of this audit/dice detail.
    """
    state = GameState.new(seed=42)
    state.character = Character(
        name="Jax",
        characteristics={"STR": 7, "DEX": 8, "END": 6, "INT": 10, "EDU": 9, "SOC": 5},
        skills={"Pilot": 2, "Gunner": 1},
        age=26,
        terms=2,
        career="navy",
        rank=3,
    )
    state.narrative_log = [
        "You enlisted in the Navy.",
        "You completed your first tour.",
        "You were promoted to Lieutenant.",
        "You survived a border skirmish.",
        "You mastered the ship's guns.",
    ]
    # Add events with raw dice data — these must NOT appear in the view.
    state.events.append(
        Event(
            seq=0,
            kind=EventKind.ROLL,
            command_type="lifepath_survival",
            description="Survival: 2D6=11 vs 6 -> success",
            roll=RollResult(
                stream="lifepath",
                ndice=2,
                sides=6,
                modifiers=1,
                rolls=[5, 6],
                total=12,
            ),
        )
    )
    return state


# ---------------------------------------------------------------------------
# Required-field tests.
# ---------------------------------------------------------------------------


class TestCuratedViewRequiredFields:
    """AE13: curated view contains all required fields."""

    def test_has_character_sheet(self):
        state = make_state_with_events()
        view = build_curated_view(state)
        assert isinstance(view.character_sheet, CharacterSheet)
        assert view.character_sheet.name == "Jax"
        assert view.character_sheet.career == "navy"
        assert view.character_sheet.rank == 3
        assert view.character_sheet.skills == {"Pilot": 2, "Gunner": 1}

    def test_has_active_mission(self):
        state = make_state_with_events()
        view = build_curated_view(state, active_mission="Deliver cargo to Vega")
        assert view.active_mission == "Deliver cargo to Vega"

    def test_active_mission_none_by_default(self):
        state = make_state_with_events()
        view = build_curated_view(state)
        assert view.active_mission is None  # v0.2: no missions yet

    def test_has_scene_npcs(self):
        state = make_state_with_events()
        npcs = [
            NpcSummary(name="Captain Vex", disposition="friendly"),
            NpcSummary(name="Agent Cole", disposition="suspicious"),
        ]
        view = build_curated_view(state, scene_npcs=npcs)
        assert len(view.scene_npcs) == 2
        assert view.scene_npcs[0].name == "Captain Vex"

    def test_scene_npcs_empty_by_default(self):
        state = make_state_with_events()
        view = build_curated_view(state)
        assert view.scene_npcs == []  # v0.2: no scene NPCs yet

    def test_has_recent_log(self):
        state = make_state_with_events()
        view = build_curated_view(state)
        assert len(view.recent_log) == 3
        # Should be the last 3 entries.
        assert view.recent_log[0] == "You were promoted to Lieutenant."
        assert view.recent_log[-1] == "You mastered the ship's guns."

    def test_recent_log_capped_at_3(self):
        state = make_state_with_events()
        view = build_curated_view(state, recent_log_count=3)
        assert len(view.recent_log) == 3

    def test_recent_log_handles_fewer_entries(self):
        state = GameState.new(seed=1)
        state.narrative_log = ["Only one entry."]
        view = build_curated_view(state)
        assert len(view.recent_log) == 1

    def test_has_open_threads(self):
        state = make_state_with_events()
        view = build_curated_view(state, open_threads=["Find the missing ship"])
        assert view.open_threads == ["Find the missing ship"]

    def test_open_threads_empty_by_default(self):
        state = make_state_with_events()
        view = build_curated_view(state)
        assert view.open_threads == []  # v0.2: no threads yet


# ---------------------------------------------------------------------------
# Prohibited-field tests.
# ---------------------------------------------------------------------------


class TestCuratedViewExcludesProhibited:
    """AE13: curated view excludes prohibited fields."""

    def test_no_raw_dice_data_in_serialization(self):
        """The serialized view must not contain die pips, roll values, etc."""
        state = make_state_with_events()
        view = build_curated_view(state)
        raw = json.dumps(view.model_dump())

        # Prohibited keys should not appear as JSON keys.
        for key in PROHIBITED_KEYS:
            assert f'"{key}"' not in raw, (
                f"Prohibited key '{key}' found in curated view serialization"
            )

    def test_no_event_objects(self):
        """Events (raw audit log) must not appear in the view."""
        state = make_state_with_events()
        view = build_curated_view(state)
        raw = json.dumps(view.model_dump())
        assert "lifepath_survival" not in raw
        assert "command_type" not in raw
        assert "EventKind" not in raw

    def test_no_rng_state(self):
        """RNG state must not appear in the view."""
        state = make_state_with_events()
        view = build_curated_view(state)
        raw = json.dumps(view.model_dump())
        assert "rng" not in raw
        assert "seed" not in raw
        assert "save_version" not in raw

    def test_no_off_scene_npc_stats(self):
        """The view only includes scene NPCs, not all NPCs."""
        state = make_state_with_events()
        # Only scene NPCs are passed — off-scene stats are never included.
        view = build_curated_view(
            state,
            scene_npcs=[NpcSummary(name="Visible NPC")],
        )
        raw = json.dumps(view.model_dump())
        # Only the passed NPC appears.
        assert "Visible NPC" in raw
        # No characteristic/stats of any NPC.
        for npc in view.scene_npcs:
            assert not hasattr(npc, "characteristics")

    def test_assert_no_prohibited_fields_passes(self):
        """The runtime guard should pass for a clean view."""
        state = make_state_with_events()
        view = build_curated_view(state)
        assert_no_prohibited_fields(view)  # Should not raise.

    def test_character_sheet_excludes_alive_flag(self):
        """The 'alive' internal flag should not be in the character sheet."""
        state = make_state_with_events()
        view = build_curated_view(state)
        raw = json.dumps(view.model_dump())
        assert '"alive"' not in raw

    def test_model_dump_does_not_include_full_state(self):
        """The view must not accidentally embed the full GameState."""
        state = make_state_with_events()
        view = build_curated_view(state)
        dumped = view.model_dump()
        # Should only have the CuratedView top-level keys.
        assert set(dumped.keys()) == {
            "character_sheet",
            "active_mission",
            "scene_npcs",
            "recent_log",
            "open_threads",
        }
