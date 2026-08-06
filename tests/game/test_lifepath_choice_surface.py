"""Controller list-parity and pool-reroll tests (P2.T7/T8, W4)."""

from __future__ import annotations

import pytest

from src.engine.commands import Engine
from src.engine.dice import ForcedRoller
from src.engine.state import CampaignConfig, GameState
from src.game.lifepath import LifepathController
from src.themepacks.cepheus_scifi import load_scifi_pack


def _make_controller(queue: list[list[int]]) -> LifepathController:
    state = GameState.new(seed=42)
    state.campaign = CampaignConfig(death_mode="narrative")
    engine = Engine(state, roller=ForcedRoller(queue))
    return LifepathController(engine, load_scifi_pack())


def test_choose_career_lists_all_25_careers_sorted():
    controller = _make_controller([])
    char = controller.engine.state.character
    char.characteristics = dict.fromkeys(("STR", "DEX", "END", "INT", "EDU", "SOC"), 9)
    char.background_picks_remaining = 0  # background phase done
    view = controller.get_phase_view()
    assert view.phase == "choose_career"
    assert len(view.choices) == 25
    labels = [c.label for c in view.choices]
    assert labels == sorted(labels)
    navy = next(c for c in view.choices if c.option_id == "career:navy")
    assert "INT 6+" in navy.description


def test_choose_background_skill_lists_all_pack_skills():
    controller = _make_controller([])
    controller.engine.state.character.characteristics = dict.fromkeys(
        ("STR", "DEX", "END", "INT", "EDU", "SOC"), 9
    )
    view = controller.get_phase_view()
    assert view.phase == "choose_background_skills"
    assert len(view.choices) == 12 > 6


def test_pool_reroll_flow_via_controller():
    first_pool = [[1, 2], [3, 4], [5, 6], [2, 3], [4, 5], [6, 1]]  # 3,7,11,5,9,7
    second_pool = [[6, 6], [5, 5], [4, 4], [3, 3], [2, 2], [1, 1]]  # 12,10,8,6,4,2
    controller = _make_controller(first_pool + second_pool)
    view = controller.apply_choice("roll_pool")
    char = controller.engine.state.character
    assert view.phase == "assign_characteristics"
    assert char.unassigned_rolls == [3, 7, 11, 5, 9, 7]
    assert not next(c for c in view.choices if c.option_id == "reroll_pool").dimmed
    view = controller.apply_choice("reroll_pool")
    assert char.pool_rerolled is True
    assert char.unassigned_rolls == [12, 10, 8, 6, 4, 2]
    reroll = next(c for c in view.choices if c.option_id == "reroll_pool")
    assert reroll.dimmed and reroll.requirement == "Pool reroll already used"


def test_pool_reroll_rejected_after_use():
    controller = _make_controller([[3, 3]] * 6 + [[4, 4]] * 6 + [[5, 5]] * 6)
    controller.apply_choice("roll_pool")
    controller.apply_choice("reroll_pool")
    with pytest.raises(ValueError, match="Pool reroll already used"):
        controller.apply_choice("reroll_pool")
