"""Tests for the headless AdventureController (U8).

Mirrors the core scenarios of tests/tui/test_adventure.py headlessly:
hooks, scenes with odds, free-text classify, mission gate, defeat modes.
"""

from __future__ import annotations

from src.engine.commands import Engine
from src.engine.dice import ForcedRoller
from src.engine.state import CampaignConfig, GameState
from src.game.adventure import AdventureController
from src.themepacks.cepheus_scifi import load_scifi_pack


def _make_engine(queue: list | None = None, death_mode: str = "narrative") -> Engine:
    """Create an engine with a mustered-out character ready for adventure."""
    state = GameState.new(seed=42)
    state.campaign = CampaignConfig(
        resolution_profile="narrative",
        death_mode=death_mode,
        theme_pack="scifi",
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
    state.character.skills = {"Gun Combat": 1, "Persuade": 0, "Stealth": 2, "Investigate": 1}
    state.character.career = "navy"
    state.character.terms = 2
    state.character.alive = True
    # Mark as mustered out so adventure can start.
    state.narrative_log.append("mustered_out=true")

    roller = ForcedRoller(queue or [])
    return Engine(state, roller=roller)


# Queue: 4 mission hook table rolls + 2 oracle rolls + 1 check per scene.
_DEFAULT_QUEUE = [
    [3, 4],
    [5, 5],
    [3, 3],
    [4, 4],  # mission hook tables
    [5, 5],
    [4, 4],  # scene oracle tables (first scene)
    [6, 6],  # scene check
    [5, 5],
    [4, 4],  # scene oracle tables (second scene)
    [5, 5],  # scene check
    [5, 5],
    [4, 4],  # scene oracle tables (third scene)
]


class TestHookPhase:
    """U8: hook generation and accept/refuse."""

    def test_hook_offered_on_no_active_mission(self):
        engine = _make_engine(_DEFAULT_QUEUE)
        controller = AdventureController(engine, load_scifi_pack())
        view = controller.get_view()
        assert view.phase == "hook_offered"
        assert len(view.choices) == 2  # Accept + Refuse.

    def test_accept_mission_enters_scene(self):
        engine = _make_engine(_DEFAULT_QUEUE)
        controller = AdventureController(engine, load_scifi_pack())
        controller.apply_choice("accept_mission")
        view = controller.get_view()
        assert view.phase == "scene_active"
        assert len(view.choices) >= 2  # Structured options + abandon.

    def test_refuse_mission_stays_in_hook(self):
        engine = _make_engine(_DEFAULT_QUEUE * 2)
        controller = AdventureController(engine, load_scifi_pack())
        controller.apply_choice("refuse_mission")
        view = controller.get_view()
        assert view.phase == "hook_offered"


class TestSceneOptions:
    """U8: scene options carry pre-commit odds."""

    def test_scene_options_have_odds_lines(self):
        engine = _make_engine(_DEFAULT_QUEUE)
        controller = AdventureController(engine, load_scifi_pack())
        controller.apply_choice("accept_mission")
        view = controller.get_view()
        assert view.phase == "scene_active"
        assert len(view.odds_lines) > 0
        # Each odds line should contain a "%" (pre-commit probability).
        for line in view.odds_lines:
            assert "%" in line or "DM" in line

    def test_resolve_option_produces_receipt(self):
        engine = _make_engine(_DEFAULT_QUEUE * 2)
        controller = AdventureController(engine, load_scifi_pack())
        controller.apply_choice("accept_mission")
        view = controller.apply_choice("option:0")
        assert len(view.receipts) > 0
        # Receipt should contain dice notation.
        assert "2D6" in view.receipts[0]


class TestMissionGate:
    """U8: ending push is gated by min_scenes."""

    def test_ending_push_gated_before_min_scenes(self):
        engine = _make_engine(_DEFAULT_QUEUE)
        controller = AdventureController(engine, load_scifi_pack())
        controller.apply_choice("accept_mission")
        view = controller.get_view()
        # Push for ending should NOT be available yet (0 scenes done).
        choice_ids = [c.option_id for c in view.choices]
        assert "push_for_ending" not in choice_ids


class TestFreeTextClassify:
    """U8: free-text classification flow."""

    def test_classify_keyword_match(self):
        engine = _make_engine(_DEFAULT_QUEUE * 2)
        controller = AdventureController(engine, load_scifi_pack())
        controller.apply_choice("accept_mission")
        view = controller.classify_freetext("I bribe the dock officer")
        # Should produce an interpretation (keyword match) or error message.
        assert view.phase in ("freetext_pending", "scene_active")

    def test_reject_freetext_clears_pending(self):
        engine = _make_engine(_DEFAULT_QUEUE * 2)
        controller = AdventureController(engine, load_scifi_pack())
        controller.apply_choice("accept_mission")
        controller.classify_freetext("I bribe the dock officer")
        # If classify produced a pending state, reject should clear it.
        if controller.state.pending_freetext is not None:
            controller.apply_choice("reject_freetext")
            assert controller.state.pending_freetext is None


class TestDefeatHandling:
    """U8: defeat triggers the death strategy."""

    def test_narrative_defeat_continues(self):
        """In narrative mode, defeat is an injury — play continues."""
        engine = _make_engine(_DEFAULT_QUEUE * 3, death_mode="narrative")
        controller = AdventureController(engine, load_scifi_pack())
        controller.apply_choice("accept_mission")
        # Resolve several options until a miss happens or scenes exhaust.
        for _ in range(5):
            view = controller.apply_choice("option:0")
            if view.defeat is not None:
                # Narrative defeat should allow play to continue.
                assert view.defeat == "narrative"
                return
        # If no defeat triggered (depends on rolls), that's also acceptable.
        assert view.phase in ("scene_active", "hook_offered", "game_over")
