"""Tests for the engine-owned chargen choice surface (P2)."""

from __future__ import annotations

import pytest

from src.engine.lifepath_choices import (
    ChoicePointView,
    choice_assign_characteristics,
    choice_background_skills,
    choice_career,
    choice_qualification_fallback,
    choice_roll_characteristics,
)
from src.engine.state import AgingSlot, CampaignConfig, CareerTermRecord, GameState
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
    state.character.characteristics = dict.fromkeys(("STR", "DEX", "END", "INT", "EDU", "SOC"), 9)
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


def test_choose_career_lists_all_careers_sorted_with_previews(pack, ruleset):
    cp = choice_career(_make_state(), pack, ruleset)
    assert len(cp.options) == 25
    labels = [o.label for o in cp.options]
    assert labels == sorted(labels)
    navy = next(o for o in cp.options if o.option_id == "career:navy")
    assert navy.preview == ["2D6+1 vs INT 6+ to qualify"]
    assert navy.odds_line == "DM +1 vs 6+ · 83% Favorable"
    assert cp.allows_freetext and cp.freetext_hint


def test_choose_career_career_change_dm_and_left_career_dimming(pack, ruleset):
    state = _make_state()
    state.character.career_history = [
        CareerTermRecord(career_id="navy", terms=1, final_rank=2, ended_by="muster_out"),
        CareerTermRecord(career_id="drifter", terms=1, final_rank=0, ended_by="mishap"),
    ]
    cp = choice_career(state, pack, ruleset)
    navy = next(o for o in cp.options if o.option_id == "career:navy")
    assert navy.dimmed and navy.requirement and navy.odds_line is None
    drifter = next(o for o in cp.options if o.option_id == "career:drifter")
    assert not drifter.dimmed  # drifter may always be re-entered (B17)
    marines = next(o for o in cp.options if o.option_id == "career:marines")
    q = pack.careers["marines"].qualification
    assert marines.preview == [f"2D6-3 vs {q.characteristic} {q.target}+ to qualify"]


def test_qualification_fallback_options_and_draft_dimming(pack, ruleset):
    state = _make_state()
    cp = choice_qualification_fallback(state, pack, ruleset)
    assert [o.option_id for o in cp.options] == [
        "fallback_retry",
        "fallback_draft",
        "fallback_drifter",
    ]
    assert cp.options[2].preview == ["2D6+1 vs SOC 2+ to qualify"]
    state.character.drafted = True
    cp = choice_qualification_fallback(state, pack, ruleset)
    draft = next(o for o in cp.options if o.option_id == "fallback_draft")
    assert draft.dimmed and draft.requirement == "Already drafted"


# ---------------------------------------------------------------------------
# T4: Term-choice builders
# ---------------------------------------------------------------------------


def test_survival_odds_include_natural_two_auto_fail(pack, ruleset):
    state = _make_state()
    state.character.career = "navy"
    from src.engine.lifepath_choices import choice_survival

    opt = choice_survival(state, pack, ruleset).options[0]
    assert opt.option_id == "begin_term"
    assert opt.preview[0] == "2D6+1 vs INT 5+ to survive"
    assert opt.odds_line == "DM +1 vs 5+ · 92% Straightforward"


def test_advancement_previews_next_rank_title(pack, ruleset):
    state = _make_state()
    state.character.career, state.character.terms, state.character.rank = "navy", 1, 1
    from src.engine.lifepath_choices import choice_advancement

    attempt = choice_advancement(state, pack, ruleset).options[0]
    assert attempt.preview == [
        "2D6+1 vs EDU 6+",
        "success promotes to rank 2 ('Lieutenant') and grants an extra skill roll",
    ]
    assert attempt.odds_line == "DM +1 vs 6+ · 83% Favorable"


def test_choose_skills_gates_advanced_education(pack, ruleset):
    state = _make_state()
    state.character.career = "navy"
    state.character.characteristics["EDU"] = 7
    from src.engine.lifepath_choices import choice_skills

    cp = choice_skills(state, pack, ruleset)
    assert [o.option_id for o in cp.options] == [
        "skill_table:Personal Development",
        "skill_table:Service Skills",
        "skill_table:Specialist Skills",
        "skill_table:Advanced Education",
    ]
    ae = cp.options[-1]
    assert ae.dimmed and ae.requirement == "Requires EDU 8+"
    state.character.characteristics["EDU"] = 9
    assert not choice_skills(state, pack, ruleset).options[-1].dimmed


# ---------------------------------------------------------------------------
# T5: Aging, mishap, crisis builders
# ---------------------------------------------------------------------------


def test_aging_reduction_previews_crisis(pack, ruleset):
    state = _make_state()
    state.character.characteristics["STR"] = 2
    state.character.pending_aging = [AgingSlot(group="physical", points=2)]
    from src.engine.lifepath_choices import choice_aging_reduction

    cp = choice_aging_reduction(state, pack, ruleset)
    assert [o.option_id for o in cp.options] == [
        "aging_stat:STR",
        "aging_stat:DEX",
        "aging_stat:END",
    ]
    assert cp.options[0].preview == ["STR 2 → 0 — crisis at 0!"]
    assert cp.options[1].preview == ["DEX 9 → 7"]


def test_crisis_resolution_dims_pay_when_broke(pack, ruleset):
    state = _make_state()
    state.character.characteristics["STR"] = 0
    state.character.credits = 5_000
    from src.engine.lifepath_choices import choice_crisis_resolution

    cp = choice_crisis_resolution(state, pack, ruleset)
    pay, scar = cp.options
    assert pay.dimmed and pay.requirement == "Requires Cr10,000"
    assert "Crisis: STR" in cp.prompt and scar.option_id == "crisis_scar"
    state.character.credits = 10_000
    assert not choice_crisis_resolution(state, pack, ruleset).options[0].dimmed


def test_crisis_resolution_ironman_shows_death_label(pack, ruleset):
    """Ironman decline = death label; non-ironman = scar label (P1.T8 parity)."""
    state = _make_state()
    state.character.characteristics["STR"] = 0
    state.campaign = CampaignConfig(death_mode="ironman")
    from src.engine.lifepath_choices import choice_crisis_resolution

    cp = choice_crisis_resolution(state, pack, ruleset)
    decline = cp.options[1]
    assert decline.label == "Accept death"
    assert "fatal" in decline.preview[0].lower()

    # Non-ironman shows scar label
    state.campaign = CampaignConfig(death_mode="narrative")
    decline = choice_crisis_resolution(state, pack, ruleset).options[1]
    assert decline.label == "Accept lasting scar"


def test_mishap_previews_full_table(pack, ruleset):
    state = _make_state()
    state.character.career = "navy"
    from src.engine.lifepath_choices import choice_mishap

    preview = choice_mishap(state, pack, ruleset).options[0].preview
    assert len(preview) == 7  # six entries + injury-chain note
    assert preview[0].startswith("1: Injured in action")
    assert preview[-1] == "1 and 6 chain to the injury table"


# ---------------------------------------------------------------------------
# T6: Re-enlist, muster, dispatcher, stubs
# ---------------------------------------------------------------------------


def _rich_state() -> GameState:
    state = _make_state()
    char = state.character
    char.career, char.terms, char.rank, char.age, char.credits = "navy", 2, 1, 30, 20_000
    char.unassigned_rolls = [9, 8]
    char.background_picks_remaining = 3
    char.pending_aging = [AgingSlot(group="physical", points=2)]
    return state


def test_re_enlist_previews_aging_and_forced_outcomes(pack, ruleset):
    from src.engine.lifepath_choices import choice_re_enlist

    cp = choice_re_enlist(_rich_state(), pack, ruleset)  # age 30 -> age_after 34
    cont = next(o for o in cp.options if o.option_id == "reenlist_continue")
    assert "aging check will apply" in cont.preview[0]
    assert "re-enlistment 2D6 vs 5" in cont.preview[1]
    muster = next(o for o in cp.options if o.option_id == "reenlist_muster")
    assert muster.preview == ["leave service and collect mustering-out benefits"]


def test_muster_out_allocate_counts_and_cash_cap(pack, ruleset):
    from src.engine.audit import Event, EventKind
    from src.engine.lifepath_choices import choice_muster_out_allocate

    state = _rich_state()
    state.character.rank = 5  # total rolls 2+2=4, material DM +1
    cp = choice_muster_out_allocate(state, pack, ruleset)
    assert cp.prompt == "Allocate benefit roll (4 remaining of 4)."
    assert not next(o for o in cp.options if o.option_id == "claim_cash").dimmed
    assert next(o for o in cp.options if o.option_id == "claim_material").preview[-1] == (
        "material DM +1 (rank 5+)"
    )
    for _ in range(3):
        state.events.append(
            Event(
                kind=EventKind.ROLL,
                command_type="lifepath_benefit",
                description="cash",
                changes={"benefit_type": "cash"},
            )
        )
    cp = choice_muster_out_allocate(state, pack, ruleset)
    cash = next(o for o in cp.options if o.option_id == "claim_cash")
    assert cash.dimmed and cash.requirement == "Cash rolls exhausted"
    assert cp.prompt == "Allocate benefit roll (1 remaining of 4)."


def test_dispatcher_covers_every_controller_phase(pack, ruleset):
    from src.engine.lifepath_choices import ALL_PHASES, choice_point_for_phase

    state = _rich_state()
    assert len(ALL_PHASES) == 20  # 19 original + choose_basic_training_skill (Part 1 T7)
    for phase in ALL_PHASES:
        cp = choice_point_for_phase(phase, state, pack, ruleset)
        assert isinstance(cp, ChoicePointView) and cp.phase == phase


def test_dispatcher_rejects_unknown_phase(pack, ruleset):
    from src.engine.lifepath_choices import choice_point_for_phase

    with pytest.raises(ValueError, match="No choice-point builder"):
        choice_point_for_phase("scene_active", _rich_state(), pack, ruleset)


def test_p3_stubs_raise_not_implemented(pack, ruleset):
    from src.engine.lifepath_choices import choice_muster_out_per_career, choice_specialization

    with pytest.raises(NotImplementedError, match="P3"):
        choice_specialization(_rich_state(), pack, ruleset)
    with pytest.raises(NotImplementedError, match="P3"):
        choice_muster_out_per_career(_rich_state(), pack, ruleset)
