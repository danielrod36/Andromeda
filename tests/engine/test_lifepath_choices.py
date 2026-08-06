"""Tests for the engine-owned chargen choice surface (P2)."""

from __future__ import annotations

import pytest

from src.engine.lifepath_choices import (
    ChoicePointView,
    choice_assign_characteristics,
    choice_background_skills,
    choice_roll_characteristics,
)
from src.engine.state import CampaignConfig, CareerTermRecord, GameState
from src.rulesets.cepheus import CepheusRuleSet
from src.themepacks.base import get_pack


@pytest.fixture
def pack():
    return get_pack("scifi")


@pytest.fixture
def ruleset():
    return CepheusRuleSet()


def _make_state() -> GameState:
    state = GameState.new(seed=42)
    state.campaign = CampaignConfig(death_mode="narrative")
    state.character.characteristics = {s: 9 for s in ("STR", "DEX", "END", "INT", "EDU", "SOC")}
    return state


def test_roll_characteristics_choice_point(pack, ruleset):
    state = _make_state()
    state.character.characteristics = {}
    cp = choice_roll_characteristics(state, pack, ruleset)
    assert cp.phase == "roll_characteristics"
    assert [o.option_id for o in cp.options] == ["roll_pool"]
    assert cp.allows_advisor is True and cp.allows_freetext is False


def test_assign_characteristics_full_matrix_and_reroll_dimming(pack, ruleset):
    state = _make_state()
    char = state.character
    char.characteristics = {"STR": 7, "DEX": 6, "END": 5, "INT": 4}
    char.unassigned_rolls = [9, 8]
    cp = choice_assign_characteristics(state, pack, ruleset)
    ids = {o.option_id for o in cp.options}
    assert ids == {"assign:0:EDU", "assign:0:SOC", "assign:1:EDU", "assign:1:SOC", "reroll_pool"}
    reroll = next(o for o in cp.options if o.option_id == "reroll_pool")
    assert reroll.dimmed is False and reroll.requirement is None
    char.pool_rerolled = True
    cp = choice_assign_characteristics(state, pack, ruleset)
    reroll = next(o for o in cp.options if o.option_id == "reroll_pool")
    assert reroll.dimmed is True and reroll.requirement == "Pool reroll already used"


def test_background_skills_all_listed_freetext_enabled(pack, ruleset):
    state = _make_state()
    state.character.background_picks_remaining = 3
    cp = choice_background_skills(state, pack, ruleset)
    assert len(cp.options) == len(pack.background_skills) == 12
    assert cp.allows_freetext is True and cp.freetext_hint
    assert all(o.option_id.startswith("bg_skill:") for o in cp.options)
    assert next(o for o in cp.options if o.option_id == "bg_skill:mechanic").label == "Mechanic"


def test_background_skills_computes_picks_before_phase_start(pack, ruleset):
    state = _make_state()  # background_picks_remaining == -1; EDU 9 -> DM +1 -> 4 picks
    assert choice_background_skills(state, pack, ruleset).prompt == (
        "Pick 4 background skills (level 0)."
    )
