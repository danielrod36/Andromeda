"""Engine-owned choice surface for chargen (P2, A5).

Pure builders enumerate every legal lifepath decision as a ChoicePointView
with deterministic mechanical previews and odds. No mutation, no dice — the
funnel stays the sole mutation path. Part 6 maps controller phases to these
builders; Parts 4–5 select among the enumerated candidates (A3).
"""

from __future__ import annotations

from pydantic import BaseModel

from src.engine.state import GameState
from src.rulesets.base import CareerData, RuleSet
from src.themepacks.base import LoadedThemePack

_PHYSICAL = ("STR", "DEX", "END")
_MENTAL = ("INT", "EDU", "SOC")
_ALL = _PHYSICAL + _MENTAL


class ChoiceOptionView(BaseModel):
    """One selectable option with deterministic mechanical preview (P2.T2)."""

    option_id: str
    label: str
    description: str = ""
    preview: list[str] = []
    odds_line: str | None = None
    dimmed: bool = False
    requirement: str | None = None


class ChoicePointView(BaseModel):
    """A full decision point: prompt + enumerated legal options (P2.T2)."""

    choice_id: str
    phase: str
    prompt: str
    options: list[ChoiceOptionView]
    allows_advisor: bool = True
    allows_freetext: bool = False
    freetext_hint: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_odds_line(dm: int, target: int, *, min_raw: int = 2) -> str:
    """Odds line for a lifepath 2D6 check (P2.T2).

    ``format_odds_line`` hardcodes the scene-check 'vs 8' (odds.py:186), so
    lifepath targets are formatted here from odds.py's distribution and
    bands. ``min_raw=3`` models the natural-2 survival auto-fail (N1).
    """
    from src.engine.odds import _p_2d6_at_least, band_label

    p = _p_2d6_at_least(max(min_raw, target - dm))
    return f"DM {dm:+d} vs {target}+ · {round(p * 100)}% {band_label(p)}"


def _career(state: GameState, pack: LoadedThemePack) -> CareerData:
    return pack.careers[state.character.career]


def _char_dm(ruleset: RuleSet, state: GameState, characteristic: str) -> int:
    return ruleset.characteristic_dm(state.character.characteristics.get(characteristic, 7))


def _qual_dm(state: GameState, ruleset: RuleSet, career: CareerData) -> int:
    """Characteristic DM + career-change DM -2 per prior career (B17)."""
    return _char_dm(ruleset, state, career.qualification.characteristic) - 2 * len(
        state.character.career_history
    )


# ---------------------------------------------------------------------------
# Phase builders — characteristics & background (P2.T2)
# ---------------------------------------------------------------------------


def choice_roll_characteristics(
    state: GameState, pack: LoadedThemePack, ruleset: RuleSet
) -> ChoicePointView:
    """Initial pool roll (P2.T2)."""
    return ChoicePointView(
        choice_id="roll_characteristics",
        phase="roll_characteristics",
        prompt="Roll six 2D6 values for your characteristics.",
        options=[
            ChoiceOptionView(
                option_id="roll_pool",
                label="Roll Pool",
                preview=["roll six 2D6 values into a pool",
                         "assign each value to a characteristic afterwards"],
            )
        ],
    )


def choice_assign_characteristics(
    state: GameState, pack: LoadedThemePack, ruleset: RuleSet
) -> ChoicePointView:
    """Full assignment matrix + once-only pool reroll (P2.T2).

    AssignCharacteristicCommand accepts any (unassigned stat, pool index)
    pair (lifepath.py:921-927) — the surface enumerates the cross product.
    """
    char = state.character
    unassigned = [s for s in _ALL if s not in char.characteristics]
    options = [
        ChoiceOptionView(
            option_id=f"assign:{i}:{stat}",
            label=f"Assign {value} to {stat}",
            preview=[f"{stat} becomes {value}"],
        )
        for i, value in enumerate(char.unassigned_rolls)
        for stat in unassigned
    ]
    options.append(
        ChoiceOptionView(
            option_id="reroll_pool",
            label="Reroll Pool",
            preview=["discard the pool and roll six new values",
                     "once per character, before any assignment"],
            dimmed=char.pool_rerolled,
            requirement="Pool reroll already used" if char.pool_rerolled else None,
        )
    )
    return ChoicePointView(
        choice_id="assign_characteristics",
        phase="assign_characteristics",
        prompt=f"Assign pool values: {list(char.unassigned_rolls)}",
        options=options,
    )


def choice_background_skills(
    state: GameState, pack: LoadedThemePack, ruleset: RuleSet
) -> ChoicePointView:
    """Background skills (B10): every pack background skill listed (P2.T2)."""
    char = state.character
    picks = char.background_picks_remaining
    if picks == -1:  # phase not started — mirror start_background_phase math
        picks = max(0, 3 + ruleset.characteristic_dm(char.characteristics.get("EDU", 7)))
    options = [
        ChoiceOptionView(
            option_id=f"bg_skill:{sid}",
            label=pack.skills[sid].name if sid in pack.skills else sid.replace("_", " ").title(),
            preview=[f"gain at level 0 ({picks} pick(s) left)"],
        )
        for sid in pack.background_skills
    ]
    return ChoicePointView(
        choice_id="choose_background_skills",
        phase="choose_background_skills",
        prompt=f"Pick {picks} background skills (level 0).",
        options=options,
        allows_freetext=True,
        freetext_hint="Name a background skill, or describe the upbringing you imagine.",
    )


# ---------------------------------------------------------------------------
# Phase builders — career & qualification (P2.T3)
# ---------------------------------------------------------------------------


def choice_career(state: GameState, pack: LoadedThemePack, ruleset: RuleSet) -> ChoicePointView:
    """All pack careers, sorted, with qualification previews (P2.T3, W4).

    Dimmed only when a hard rule blocks attempting: a career already left
    cannot be re-entered — except Drifter (B17, lifepath.py:1206-1209).
    """
    left = {r.career_id for r in state.character.career_history}
    options = []
    for career in sorted(pack.careers.values(), key=lambda c: c.name):
        dm = _qual_dm(state, ruleset, career)
        q = career.qualification
        blocked = career.id in left and career.id != "drifter"
        options.append(
            ChoiceOptionView(
                option_id=f"career:{career.id}",
                label=career.name,
                description=career.description,
                preview=[f"2D6{dm:+d} vs {q.characteristic} {q.target}+ to qualify"],
                odds_line=None if blocked else _check_odds_line(dm, q.target),
                dimmed=blocked,
                requirement="Cannot return to a career already left (B17)" if blocked else None,
            )
        )
    return ChoicePointView(
        choice_id="choose_career", phase="choose_career",
        prompt="Choose a career to qualify for.", options=options,
        allows_freetext=True,
        freetext_hint="Name a career, or describe the life you want.",
    )


def choice_qualification_fallback(
    state: GameState, pack: LoadedThemePack, ruleset: RuleSet
) -> ChoicePointView:
    """Post-failure paths: retry, draft, drifter (P2.T3)."""
    char = state.character
    draft_blocked = char.drafted or not pack.draft_table
    draft_req = "Already drafted" if char.drafted else ("Pack has no draft table" if not pack.draft_table else None)
    options = [
        ChoiceOptionView(option_id="fallback_retry", label="Choose a different career"),
        ChoiceOptionView(
            option_id="fallback_draft", label="Submit to the draft (1D6)",
            preview=["roll 1D6 on the pack's draft table"],
            dimmed=draft_blocked, requirement=draft_req,
        ),
    ]
    if "drifter" in pack.careers:
        drifter = pack.careers["drifter"]
        dm, q = _qual_dm(state, ruleset, drifter), drifter.qualification
        options.append(
            ChoiceOptionView(
                option_id="fallback_drifter", label="Enter the Drifter career",
                preview=[f"2D6{dm:+d} vs {q.characteristic} {q.target}+ to qualify"],
                odds_line=_check_odds_line(dm, q.target),
            )
        )
    return ChoicePointView(
        choice_id="choose_qualification_fallback", phase="choose_qualification_fallback",
        prompt="Qualification failed. Choose your path:", options=options,
    )


def choice_career_change(
    state: GameState, pack: LoadedThemePack, ruleset: RuleSet
) -> ChoicePointView:
    """Career ended: new career at -2 per prior career, or muster out (P2.T3)."""
    dm = -2 * len(state.character.career_history)
    return ChoicePointView(
        choice_id="choose_career_change", phase="choose_career_change",
        prompt="Your career has ended. What next?",
        options=[
            ChoiceOptionView(option_id="career_change_new", label="Try a new career",
                             preview=[f"qualification at DM {dm:+d}"]),
            ChoiceOptionView(option_id="career_change_muster",
                             label="Muster out (end character creation)",
                             preview=["end character creation and roll mustering-out benefits"]),
        ],
    )
