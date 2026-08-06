"""Engine-owned choice surface for chargen (P2, A5).

Pure builders enumerate every legal lifepath decision as a ChoicePointView
with deterministic mechanical previews and odds. No mutation, no dice — the
funnel stays the sole mutation path. Part 6 maps controller phases to these
builders; Parts 4–5 select among the enumerated candidates (A3).
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel

from src.engine.lifepath import benefit_rolls_for, material_dm_for
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
                preview=[
                    "roll six 2D6 values into a pool",
                    "assign each value to a characteristic afterwards",
                ],
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
            preview=[
                "discard the pool and roll six new values",
                "once per character, before any assignment",
            ],
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
        choice_id="choose_career",
        phase="choose_career",
        prompt="Choose a career to qualify for.",
        options=options,
        allows_freetext=True,
        freetext_hint="Name a career, or describe the life you want.",
    )


def choice_qualification_fallback(
    state: GameState, pack: LoadedThemePack, ruleset: RuleSet
) -> ChoicePointView:
    """Post-failure paths: retry, draft, drifter (P2.T3)."""
    char = state.character
    draft_blocked = char.drafted or not pack.draft_table
    draft_req = (
        "Already drafted"
        if char.drafted
        else ("Pack has no draft table" if not pack.draft_table else None)
    )
    options = [
        ChoiceOptionView(option_id="fallback_retry", label="Choose a different career"),
        ChoiceOptionView(
            option_id="fallback_draft",
            label="Submit to the draft (1D6)",
            preview=["roll 1D6 on the pack's draft table"],
            dimmed=draft_blocked,
            requirement=draft_req,
        ),
    ]
    if "drifter" in pack.careers:
        drifter = pack.careers["drifter"]
        dm, q = _qual_dm(state, ruleset, drifter), drifter.qualification
        options.append(
            ChoiceOptionView(
                option_id="fallback_drifter",
                label="Enter the Drifter career",
                preview=[f"2D6{dm:+d} vs {q.characteristic} {q.target}+ to qualify"],
                odds_line=_check_odds_line(dm, q.target),
            )
        )
    return ChoicePointView(
        choice_id="choose_qualification_fallback",
        phase="choose_qualification_fallback",
        prompt="Qualification failed. Choose your path:",
        options=options,
    )


def choice_career_change(
    state: GameState, pack: LoadedThemePack, ruleset: RuleSet
) -> ChoicePointView:
    """Career ended: new career at -2 per prior career, or muster out (P2.T3)."""
    dm = -2 * len(state.character.career_history)
    return ChoicePointView(
        choice_id="choose_career_change",
        phase="choose_career_change",
        prompt="Your career has ended. What next?",
        options=[
            ChoiceOptionView(
                option_id="career_change_new",
                label="Try a new career",
                preview=[f"qualification at DM {dm:+d}"],
            ),
            ChoiceOptionView(
                option_id="career_change_muster",
                label="Muster out (end character creation)",
                preview=["end character creation and roll mustering-out benefits"],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Phase builders — term choices (P2.T4)
# ---------------------------------------------------------------------------


def choice_survival(state: GameState, pack: LoadedThemePack, ruleset: RuleSet) -> ChoicePointView:
    """Begin-term survival preview; natural 2 always fails (P2.T4, N1)."""
    char, career = state.character, _career(state, pack)
    s = career.survival
    dm = _char_dm(ruleset, state, s.characteristic)
    failure = (
        "death (ironman)" if state.campaign.death_mode == "ironman" else "mishap — leave career"
    )
    return ChoicePointView(
        choice_id="run_survival",
        phase="run_survival",
        prompt=f"Term {char.terms + 1} — {career.name}: ready to begin.",
        options=[
            ChoiceOptionView(
                option_id="begin_term",
                label="Begin Term",
                preview=[
                    f"2D6{dm:+d} vs {s.characteristic} {s.target}+ to survive",
                    "natural 2 always fails (N1)",
                    f"failure: {failure}",
                ],
                odds_line=_check_odds_line(dm, s.target, min_raw=3),
            )
        ],
    )


def choice_commission(state: GameState, pack: LoadedThemePack, ruleset: RuleSet) -> ChoicePointView:
    """Commission attempt/decline at rank 0, hierarchy careers (P2.T4, B8)."""
    char, career = state.character, _career(state, pack)
    c = career.commission
    assert c is not None  # controller reaches this phase only for hierarchy careers
    dm = _char_dm(ruleset, state, c.characteristic)
    return ChoicePointView(
        choice_id="choose_commission",
        phase="choose_commission",
        prompt=f"Term {char.terms} — commission check (rank 0).",
        options=[
            ChoiceOptionView(
                option_id="commission_attempt",
                label=f"Attempt Commission (2D6 vs {c.target})",
                preview=[
                    f"2D6{dm:+d} vs {c.characteristic} {c.target}+",
                    "success grants rank 1 and an extra skill roll",
                ],
                odds_line=_check_odds_line(dm, c.target),
            ),
            ChoiceOptionView(
                option_id="commission_decline",
                label="Decline Commission",
                preview=["skip the commission roll this term"],
            ),
        ],
    )


def choice_advancement(
    state: GameState, pack: LoadedThemePack, ruleset: RuleSet
) -> ChoicePointView:
    """Advancement attempt/decline with next-rank title preview (P2.T4)."""
    char, career = state.character, _career(state, pack)
    a = career.advancement
    assert a is not None
    dm = _char_dm(ruleset, state, a.characteristic)
    title = next((r.title for r in career.ranks if r.rank == char.rank + 1), "")
    promotion = f"success promotes to rank {char.rank + 1}"
    if title:
        promotion += f" ('{title}')"
    return ChoicePointView(
        choice_id="choose_advancement",
        phase="choose_advancement",
        prompt=f"Term {char.terms} — advancement check.",
        options=[
            ChoiceOptionView(
                option_id="advancement_attempt",
                label=f"Attempt Advancement (2D6 vs {a.target})",
                preview=[
                    f"2D6{dm:+d} vs {a.characteristic} {a.target}+",
                    promotion + " and grants an extra skill roll",
                ],
                odds_line=_check_odds_line(dm, a.target),
            ),
            ChoiceOptionView(
                option_id="advancement_decline",
                label="Decline Advancement",
                preview=["skip the advancement roll"],
            ),
        ],
    )


def choice_skills(state: GameState, pack: LoadedThemePack, ruleset: RuleSet) -> ChoicePointView:
    """Skill-table picks with full result previews; EDU 8+ gates Advanced Education (P2.T4, B7)."""
    char, career = state.character, _career(state, pack)
    edu = char.characteristics.get("EDU", 0)
    options = []
    for table in career.skill_tables:
        results = ", ".join(e.result for e in table.entries.entries)
        gated = table.name == "Advanced Education" and edu < 8
        options.append(
            ChoiceOptionView(
                option_id=f"skill_table:{table.name}",
                label=table.name,
                preview=[f"roll 1D6; possible: {results}"],
                dimmed=gated,
                requirement="Requires EDU 8+" if gated else None,
            )
        )
    return ChoicePointView(
        choice_id="choose_skills",
        phase="choose_skills",
        prompt="Choose a skill table for each roll.",
        options=options,
    )


# ---------------------------------------------------------------------------
# Phase builders — aging, mishap, crisis (P2.T5)
# ---------------------------------------------------------------------------


def choice_aging(state: GameState, pack: LoadedThemePack, ruleset: RuleSet) -> ChoicePointView:
    """Aging roll at 34+: 2D6 - terms against the graduated table (P2.T5, B4)."""
    terms = state.character.terms
    return ChoicePointView(
        choice_id="run_aging",
        phase="run_aging",
        prompt=f"Aging check (age 34+): roll 2D6 - terms({terms}).",
        options=[
            ChoiceOptionView(
                option_id="roll_aging",
                label="Roll Aging",
                preview=[
                    f"roll 2D6 - {terms} (terms)",
                    "adjusted 0 or less = reductions from the graduated aging table",
                ],
            )
        ],
    )


def choice_aging_reduction(
    state: GameState, pack: LoadedThemePack, ruleset: RuleSet
) -> ChoicePointView:
    """Assign the next pending aging slot to one characteristic (P2.T5)."""
    char = state.character
    slot = char.pending_aging[0]
    options = []
    for s in _PHYSICAL if slot.group == "physical" else _MENTAL:
        val = char.characteristics.get(s, 0)
        crisis = " — crisis at 0!" if val - slot.points <= 0 else ""
        options.append(
            ChoiceOptionView(
                option_id=f"aging_stat:{s}",
                label=f"{s} ({val})",
                preview=[f"{s} {val} → {max(0, val - slot.points)}{crisis}"],
            )
        )
    return ChoicePointView(
        choice_id="choose_aging_reduction",
        phase="choose_aging_reduction",
        prompt=(
            f"Aging reduction ({slot.group} -{slot.points}). "
            f"Choose a characteristic ({len(char.pending_aging)} slot(s) left)."
        ),
        options=options,
    )


def choice_mishap(state: GameState, pack: LoadedThemePack, ruleset: RuleSet) -> ChoicePointView:
    """Mishap table roll with full entry preview (P2.T5, B13)."""
    career = _career(state, pack)
    entries = career.mishap_table.entries if career.mishap_table else []
    preview = []
    for e in entries:
        span = f"{e.min}" if e.min == e.max else f"{e.min}-{e.max}"
        preview.append(f"{span}: {e.result}")
    if entries:
        preview.append("1 and 6 chain to the injury table")
    return ChoicePointView(
        choice_id="mishap_roll",
        phase="mishap_roll",
        prompt=f"Roll on the {career.name} mishap table (1D6).",
        options=[ChoiceOptionView(option_id="roll_mishap", label="Roll Mishap", preview=preview)],
    )


def choice_injury_stat(
    state: GameState, pack: LoadedThemePack, ruleset: RuleSet
) -> ChoicePointView:
    """Pick the physical characteristic the injury hits (P2.T5)."""
    chars = state.character.characteristics
    return ChoicePointView(
        choice_id="choose_injury_stat",
        phase="choose_injury_stat",
        prompt="Choose which physical characteristic takes the injury:",
        options=[
            ChoiceOptionView(
                option_id=f"injury_stat:{s}",
                label=f"{s} ({chars.get(s, 0)})",
                preview=[f"the injury reduction applies to {s}"],
            )
            for s in _PHYSICAL
        ],
    )


def choice_crisis_resolution(
    state: GameState, pack: LoadedThemePack, ruleset: RuleSet
) -> ChoicePointView:
    """Injury crisis: pay Cr10,000 or take the scar (P2.T5, B13)."""
    char = state.character
    stat = next((s for s in _ALL if char.characteristics.get(s, 0) <= 0), "a characteristic")
    can_afford = char.credits >= 10_000
    return ChoicePointView(
        choice_id="choose_crisis_resolution",
        phase="choose_crisis_resolution",
        prompt=f"Injury crisis: {stat} reached 0. Choose your response:",
        options=[
            ChoiceOptionView(
                option_id="crisis_pay",
                label=f"Pay Cr10,000 (have Cr{char.credits:,})",
                preview=[f"pay for medical care; {stat} stabilises at 1"],
                dimmed=not can_afford,
                requirement=None if can_afford else "Requires Cr10,000",
            ),
            ChoiceOptionView(
                option_id="crisis_scar",
                label="Accept lasting scar",
                preview=[f"{stat} stabilises at 1 with a permanent severe Injury"],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Phase builders — re-enlist, muster, complete (P2.T6)
# ---------------------------------------------------------------------------


def choice_re_enlist(state: GameState, pack: LoadedThemePack, ruleset: RuleSet) -> ChoicePointView:
    """Continue another term or muster out (P2.T6, B12)."""
    char, career = state.character, _career(state, pack)
    age_after = char.age + 4
    note = "serve another 4-year term"
    if age_after >= 34:
        note += "; aging check will apply"
    continue_preview = [note]
    if career.re_enlistment:
        continue_preview.append(
            f"re-enlistment 2D6 vs {career.re_enlistment}: "
            "natural 12 must continue, below target must leave"
        )
    return ChoicePointView(
        choice_id="re_enlist",
        phase="re_enlist",
        prompt=(
            f"Term {char.terms} complete ({career.name}, rank {char.rank}, "
            f"age {char.age}). Re-enlist?"
        ),
        options=[
            ChoiceOptionView(
                option_id="reenlist_continue",
                label=f"Continue for another term (age {age_after})",
                preview=continue_preview,
            ),
            ChoiceOptionView(
                option_id="reenlist_muster",
                label="Muster Out and Finish Character",
                preview=["leave service and collect mustering-out benefits"],
            ),
        ],
    )


def _muster_plan(state: GameState) -> tuple[str, int, int]:
    """(career_id, total_rolls, material_dm) without rolling (P2.T6, B15).

    B2-safe: when the career has already ended, rank comes from the final
    CareerTermRecord (EndCareerCommand resets character.rank).
    """
    char = state.character
    if char.career:
        rank = char.rank
        return char.career, benefit_rolls_for(char.terms, rank), material_dm_for(rank)
    if char.career_history:
        last = char.career_history[-1]
        rank = last.final_rank
        return last.career_id, benefit_rolls_for(char.terms, rank), material_dm_for(rank)
    return "", 0, 0


def _benefit_counts(state: GameState) -> tuple[int, int]:
    """(cash_taken, material_taken) counted from lifepath_benefit events (resume-safe)."""
    cash = sum(
        1
        for e in state.events
        if e.command_type == "lifepath_benefit" and e.changes.get("benefit_type") == "cash"
    )
    material = sum(
        1
        for e in state.events
        if e.command_type == "lifepath_benefit" and e.changes.get("benefit_type") == "material"
    )
    return cash, material


def choice_mustering_out(
    state: GameState, pack: LoadedThemePack, ruleset: RuleSet
) -> ChoicePointView:
    """Transitional plan summary; the controller auto-advances to allocation (P2.T6)."""
    career_id, total, _mat_dm = _muster_plan(state)
    career = pack.careers.get(career_id)
    name = career.name if career else career_id
    return ChoicePointView(
        choice_id="mustering_out",
        phase="mustering_out",
        prompt=f"Mustering out of {name}: {total} benefit roll(s).",
        options=[],
        allows_advisor=False,
    )


def choice_muster_out_allocate(
    state: GameState, pack: LoadedThemePack, ruleset: RuleSet
) -> ChoicePointView:
    """Per-roll cash/material allocation; cash capped at 3 (P2.T6, B15)."""
    career_id, total, mat_dm = _muster_plan(state)
    career = pack.careers.get(career_id)
    cash_taken, material_taken = _benefit_counts(state)
    remaining = total - cash_taken - material_taken
    options = []
    if career and career.mustering_out_cash:
        options.append(
            ChoiceOptionView(
                option_id="claim_cash",
                label=f"Cash table ({cash_taken}/3 taken)",
                preview=[f"roll 1D6 on the cash benefits table ({remaining} roll(s) left)"],
                dimmed=cash_taken >= 3,
                requirement="Cash rolls exhausted" if cash_taken >= 3 else None,
            )
        )
    if career and career.mustering_out_material:
        preview = ["roll 1D6 on the material benefits table"]
        if mat_dm:
            preview.append(f"material DM +{mat_dm} (rank 5+)")
        options.append(
            ChoiceOptionView(option_id="claim_material", label="Material table", preview=preview)
        )
    return ChoicePointView(
        choice_id="muster_out_allocate",
        phase="muster_out_allocate",
        prompt=f"Allocate benefit roll ({remaining} remaining of {total}).",
        options=options,
    )


def choice_complete(state: GameState, pack: LoadedThemePack, ruleset: RuleSet) -> ChoicePointView:
    """Terminal phase — no further choices (P2.T6)."""
    char = state.character
    return ChoicePointView(
        choice_id="complete",
        phase="complete",
        prompt=f"Lifepath complete. Character: {char.name}, terms: {char.terms}.",
        options=[],
        allows_advisor=False,
    )


# ---------------------------------------------------------------------------
# P3 stubs (replaced by Part 3)
# ---------------------------------------------------------------------------


def choice_specialization(
    state: GameState, pack: LoadedThemePack, ruleset: RuleSet
) -> ChoicePointView:
    """Cascade-specialization pick on skill grant — P3 (SRD: player chooses on grant)."""
    raise NotImplementedError("P3: cascade specialization choice lands with pack schema v2")


def choice_muster_out_per_career(
    state: GameState, pack: LoadedThemePack, ruleset: RuleSet
) -> ChoicePointView:
    """Per-career mustering out (G4) — P3."""
    raise NotImplementedError("P3: per-career muster-out lands with Character.mustered_careers")


# ---------------------------------------------------------------------------
# Later-career basic training (Part 1 B3, added to dispatcher in doc-review)
# ---------------------------------------------------------------------------


def choice_basic_training_skill(
    state: GameState, pack: LoadedThemePack, ruleset: RuleSet
) -> ChoicePointView:
    """Later-career basic training: pick one Service Skills entry at level 0 (P2.T6, Part 1 B3)."""
    career = _career(state, pack)
    service_table = next(
        (t for t in career.skill_tables if t.name == "Service Skills"),
        career.skill_tables[0] if career.skill_tables else None,
    )
    options: list[ChoiceOptionView] = []
    if service_table:
        seen: set[str] = set()
        for entry in service_table.entries.entries:
            skill_id = entry.result.strip()
            if skill_id not in seen:
                seen.add(skill_id)
                options.append(
                    ChoiceOptionView(
                        option_id=f"bt_skill:{skill_id}",
                        label=f"{skill_id.replace('_', ' ').title()}-0",
                        preview=[f"Gain {skill_id} at level 0 (basic training)"],
                    )
                )
    return ChoicePointView(
        choice_id="basic_training_skill",
        phase="choose_basic_training_skill",
        prompt="Your previous training transfers. Pick one Service skill at level 0:",
        options=options,
        allows_freetext=False,
    )


# ---------------------------------------------------------------------------
# Phase dispatcher (P2.T6)
# ---------------------------------------------------------------------------

_BUILDERS: dict[str, Callable[[GameState, LoadedThemePack, RuleSet], ChoicePointView]] = {
    "roll_characteristics": choice_roll_characteristics,
    "assign_characteristics": choice_assign_characteristics,
    "choose_background_skills": choice_background_skills,
    "choose_career": choice_career,
    "choose_qualification_fallback": choice_qualification_fallback,
    "choose_career_change": choice_career_change,
    "run_survival": choice_survival,
    "choose_commission": choice_commission,
    "choose_advancement": choice_advancement,
    "choose_skills": choice_skills,
    "choose_basic_training_skill": choice_basic_training_skill,
    "run_aging": choice_aging,
    "choose_aging_reduction": choice_aging_reduction,
    "mishap_roll": choice_mishap,
    "choose_injury_stat": choice_injury_stat,
    "choose_crisis_resolution": choice_crisis_resolution,
    "re_enlist": choice_re_enlist,
    "mustering_out": choice_mustering_out,
    "muster_out_allocate": choice_muster_out_allocate,
    "complete": choice_complete,
}

ALL_PHASES: tuple[str, ...] = tuple(_BUILDERS)


def choice_point_for_phase(
    phase: str, state: GameState, pack: LoadedThemePack, ruleset: RuleSet
) -> ChoicePointView:
    """Dispatch a controller phase to its choice-point builder (P2.T6).

    Raises ``ValueError`` for phases with no registered builder.
    """
    builder = _BUILDERS.get(phase)
    if builder is None:
        raise ValueError(f"No choice-point builder for phase {phase!r}")
    return builder(state, pack, ruleset)
