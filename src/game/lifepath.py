"""Headless lifepath flow controller (U5, U2).

Ports the phase machine from the TUI's ``LifepathScreen`` into a testable,
UI-agnostic controller. The engine's ``LifepathRunner`` already owns the
mechanical step methods; this controller owns the phase *decision* logic —
which step to run next based on GameState flags — and returns ``PhaseView``
models that shells render without inspecting state directly.

KTD-3 parity: phase flags (``term_phase=...``, ``mustered_out=true``,
``reenlist_outcome=...``) are read and written byte-identical to the TUI's
``SetFlagCommand`` convention so TUI-written saves reconstruct identically
in ``src/game/`` and vice versa.

U2 delivers full interactive parity with the TUI: every runner step the TUI
exercises (survival, commission, advancement, skill rolls, mishap/injury/
crisis, aging reductions, re-enlistment with forced outcomes) runs through
the web controller, with ``_reconstruct_term_state`` rebuilding the in-
memory ``TermResult`` from the event log on resume.
"""

from __future__ import annotations

import logging

from src.engine.commands import Engine, SetFlagCommand
from src.engine.lifepath import (
    ApplyAgingReductionCommand,
    ChooseSpecializationCommand,
    EndCareerCommand,
    InjuryRollCommand,
    LifepathRunner,
    MishapRollCommand,
    MusteringOutResult,
    ResolveInjuryCrisisCommand,
    RollAgingCrisisCostCommand,
    SkillGain,
    TermResult,
)
from src.engine.state import GameState
from src.game.views import ChoiceOption, PhaseView
from src.themepacks.base import LoadedThemePack

logger = logging.getLogger(__name__)

#: Phases that belong to the term sub-state-machine (same set as the TUI).
TERM_PHASES = frozenset(
    {
        "run_survival",
        "choose_commission",
        "choose_advancement",
        "choose_skills",
        "run_aging",
        "choose_aging_reduction",
        "re_enlist",
        "mishap_roll",
        "choose_injury_stat",
        "choose_crisis_resolution",
        "choose_basic_training_skill",
    }
)

_PHYSICAL_CHARACTERISTICS = ("STR", "DEX", "END")
_ALL_CHARACTERISTICS = ("STR", "DEX", "END", "INT", "EDU", "SOC")


def get_pending_crisis_cost(state: GameState) -> int | None:
    """Rolled aging-crisis cost for the open crisis, or None (C2, C-A5)."""
    for entry in reversed(state.narrative_log):
        if entry.startswith("crisis_cost="):
            return int(entry.split("=", 1)[1])
        if entry == "term_phase=choose_crisis_resolution":
            return None
    return None


class LifepathController:
    """Headless lifepath phase controller (U5, U2).

    Wraps the engine and theme pack, providing:

    - ``determine_phase()`` — reads state flags to determine the current phase
    - ``get_phase_view()`` — builds a :class:`PhaseView` for the current phase
    - ``apply_choice()`` — routes a choice to the appropriate step handler

    The controller never caches GameState — it reads through ``engine.state``
    every call so ``swap_state`` (rewind) is always reflected. The in-memory
    ``_current_term_result`` IS cached and rebuilt from the event log on
    construction (U2 reconstruction for resume).
    """

    def __init__(self, engine: Engine, pack: LoadedThemePack) -> None:
        self._engine = engine
        self._pack = pack
        self._runner = LifepathRunner(engine, pack)
        self._current_term_result: TermResult | None = None
        #: Skill rolls remaining for the current term's choose_skills phase.
        self._skill_rolls_remaining: int = 0
        #: Tracks whether a crisis resolution should return to the aging loop
        #: (True) rather than completing the term (False).
        self._aging_active: bool = False
        #: U3: mustering-out plan (computed once when mustering_out begins).
        self._muster_plan: MusteringOutResult | None = None
        #: U3: benefit rolls remaining in muster_out_allocate.
        self._benefit_rolls_remaining: int = 0
        #: P6.T1: provenance of the most-recent choice (ADR A10).
        self._choice_origin: str = "player"

        # U2: reconstruct term-level instance state on construction when
        # the persisted term_phase sits inside the term sub-machine.
        phase = self.get_latest_term_phase(engine.state)
        if phase in TERM_PHASES:
            self._reconstruct_term_state()
        # U3: reconstruct muster-out allocation state on construction when
        # the persisted term_phase is inside the muster-out sub-machine.
        if phase in ("mustering_out", "muster_out_allocate"):
            self._reconstruct_muster_state()

    @property
    def _origin_stamp(self) -> str | None:
        """Return ``_choice_origin`` for ``SetFlagCommand``, or ``None`` when
        the default ``"player"`` so existing events stay byte-identical (ADR A10
        only requires non-player origins to be surfaced).
        """
        return self._choice_origin if self._choice_origin != "player" else None

    @property
    def engine(self) -> Engine:
        return self._engine

    @property
    def pack(self) -> LoadedThemePack:
        return self._pack

    @property
    def runner(self) -> LifepathRunner:
        return self._runner

    # ------------------------------------------------------------------
    # Phase flag helpers (KTD-3 byte-identical parity with the TUI).
    # ------------------------------------------------------------------

    @staticmethod
    def get_latest_term_phase(state: GameState) -> str | None:
        """Return the most recent ``term_phase=`` flag from the narrative log."""
        for entry in reversed(state.narrative_log):
            if entry.startswith("term_phase="):
                return entry.split("=", 1)[1]
        return None

    def _set_term_phase(self, phase: str) -> None:
        """Persist a ``term_phase`` flag via the command funnel (AE8-safe)."""
        self._engine.apply(SetFlagCommand(key="term_phase", value=phase, origin=self._origin_stamp))

    @staticmethod
    def _get_reenlist_outcome(state: GameState) -> str | None:
        """Return ``reenlist_outcome`` set after the most recent ``re_enlist``.

        Scans the narrative log backward: if a ``reenlist_outcome=`` entry
        appears before (i.e. later in the log than) the most recent
        ``term_phase=re_enlist``, the player has already chosen.
        """
        for i in range(len(state.narrative_log) - 1, -1, -1):
            entry = state.narrative_log[i]
            if entry == "term_phase=re_enlist":
                return None
            if entry.startswith("reenlist_outcome="):
                return entry.split("=", 1)[1]
        return None

    def _find_stat_at_zero(self) -> str | None:
        """Return the first characteristic at or below 0, or None.

        Scans all six characteristics, physical-first.
        """
        chars = self._engine.state.character.characteristics
        for stat in _ALL_CHARACTERISTICS:
            if chars.get(stat, 0) <= 0:
                return stat
        return None

    def _injury_stat_choices(self) -> list[ChoiceOption]:
        """Build the three physical-characteristic injury-stat choices."""
        chars = self._engine.state.character.characteristics
        return [
            ChoiceOption(label=f"STR ({chars.get('STR', 0)})", option_id="injury_stat:STR"),
            ChoiceOption(label=f"DEX ({chars.get('DEX', 0)})", option_id="injury_stat:DEX"),
            ChoiceOption(label=f"END ({chars.get('END', 0)})", option_id="injury_stat:END"),
        ]

    # ------------------------------------------------------------------
    # Term-state reconstruction (U2 — ported from TUI _reconstruct_term_state).
    # ------------------------------------------------------------------

    def _reconstruct_term_state(self) -> None:
        """Rebuild ``_current_term_result`` from events on save/resume.

        Ports the TUI's ``_reconstruct_term_state`` line-for-line, with one
        deliberate fix: guard the optional ``advancement`` block so non-
        hierarchy careers (scout, drifter, etc. whose ``advancement`` is None)
        don't crash on the ``.target`` dereference.
        """
        state = self._engine.state
        char = state.character
        career_id = char.career
        if not career_id:
            return

        # Find the survival event for the current term (most recent).
        surv_events = [e for e in state.events if e.command_type == "lifepath_survival"]
        if not surv_events:
            return

        last_surv = surv_events[-1]
        sc = last_surv.changes
        career = self._pack.careers.get(career_id)

        result = TermResult(
            term_number=char.terms,
            career_id=career_id,
            career_name=career.name if career else career_id,
            age_before=char.age - 4,
            age_after=char.age,
            rank_before=char.rank,
            survival_target=sc.get("target", 0),
            # U2 critical fix: guard advancement (None for non-hierarchy careers).
            advancement_target=career.advancement.target if career and career.advancement else 0,
        )
        result.survival_raw = sc.get("raw_roll", 0)
        result.survival_dm = sc.get("char_dm", 0)
        result.survival_total = sc.get("adjusted_total", 0)
        result.survival_success = sc.get("success", True)
        result.died = sc.get("died", False)
        result.mishap = sc.get("mishap", False)
        result.rank_after = char.rank

        # Scan events after the survival event for commission/advancement/skill/aging.
        surv_idx = state.events.index(last_surv)
        saw_aging = False
        for event in state.events[surv_idx + 1 :]:
            if event.command_type == "lifepath_commission":
                cc = event.changes
                result.commission_raw = cc.get("raw_roll", 0)
                result.commission_dm = cc.get("char_dm", 0)
                result.commission_total = cc.get("adjusted_total", 0)
                result.commission_target = cc.get("target", 0)
                result.commission_success = cc.get("success", False)
            elif event.command_type == "lifepath_advancement":
                ac = event.changes
                result.advancement_raw = ac.get("raw_roll", 0)
                result.advancement_dm = ac.get("char_dm", 0)
                result.advancement_total = ac.get("adjusted_total", 0)
                result.advancement_success = ac.get("success", False)
                result.rank_after = ac.get("new_rank", char.rank)
            elif event.command_type == "lifepath_skill_roll":
                sec = event.changes
                result.skill_gains.append(
                    SkillGain(
                        table_name=sec.get("table_name", ""),
                        roll=sec.get("roll_total", 0),
                        result_text=sec.get("result_text", ""),
                        gain_type=sec.get("gain_type", "skill"),
                        gain_name=sec.get("gain_name", ""),
                        cascade_parent=sec.get("cascade_parent"),
                    )
                )
            elif event.command_type == "lifepath_aging":
                saw_aging = True
                agc = event.changes
                result.aging_raw = agc.get("raw_roll", 0)
                result.aging_success = agc.get("success", True)
                slots = agc.get("slots", [])
                reductions: dict[str, int] = {}
                for slot in slots:
                    g = slot.get("group", "physical")
                    reductions[g] = reductions.get(g, 0) + slot.get("points", 0)
                result.aging_reductions = reductions

        self._current_term_result = result

        # Rebuild skill rolls remaining if in choose_skills.
        phase = self.get_latest_term_phase(state)
        if phase == "choose_skills":
            total = self._runner.compute_num_skill_rolls(result)
            self._skill_rolls_remaining = total - len(result.skill_gains)

        # Rebuild aging-active flag: if the current term had an aging roll,
        # crisis resolution should return to the aging loop.
        self._aging_active = saw_aging

    # ------------------------------------------------------------------
    # Muster-out state reconstruction (U3 — resume from mid-allocation).
    # ------------------------------------------------------------------

    def _reconstruct_muster_state(self) -> None:
        """Rebuild ``_muster_plan`` and ``_benefit_rolls_remaining`` on resume.

        Counts ``lifepath_benefit`` events in the audit log to determine how
        many rolls have already been claimed, then recomputes the plan's
        ``total_rolls`` from state (terms + rank) so remaining = total - claimed.
        """
        career_id = self._get_muster_career_id()
        if not career_id:
            return
        plan = self._runner.muster_out(career_id)
        self._muster_plan = plan

        # Sync counters from events so the cap is enforced on resume.
        self._benefit_rolls_remaining = self._runner.reconstruct_muster_counters(plan.total_rolls)

    # ------------------------------------------------------------------
    # Phase determination — headless port of the TUI's _determine_phase.
    # ------------------------------------------------------------------

    def determine_phase(self) -> str:
        """Determine the current lifepath phase from engine state.

        Reads the same flags and character fields the TUI does (KTD-3 parity).
        """
        state = self._engine.state
        char = state.character

        # Characteristics not fully assigned yet.
        if len(char.characteristics) < 6:
            return "assign_characteristics" if char.unassigned_rolls else "roll_characteristics"

        # C3 (C-A3): a pending cascade grant interrupts everything else.
        if char.pending_cascades:
            return "choose_specialization"

        # No career chosen yet.
        if not char.career:
            # Mustering out completed (career cleared by EndCareerCommand).
            if "mustered_out=true" in state.narrative_log:
                return "complete"
            term_phase = self.get_latest_term_phase(state)
            if term_phase == "mustering_out":
                return "mustering_out"
            if term_phase == "muster_out_allocate":
                return "muster_out_allocate"
            if term_phase == "choose_qualification_fallback":
                return "choose_qualification_fallback"
            if term_phase == "choose_career_change":
                return "choose_career_change"
            # Background skills phase.
            if not char.career_history:
                if char.background_picks_remaining == -1:
                    return "choose_background_skills"
                if char.background_picks_remaining > 0:
                    return "choose_background_skills"
            return "choose_career"

        # Character is dead (ironman death during lifepath).
        if not char.alive:
            return "complete"

        # Mustering out completed.
        if "mustered_out=true" in state.narrative_log:
            return "complete"

        # Check the persisted term_phase flag.
        term_phase = self.get_latest_term_phase(state)
        if term_phase:
            if term_phase == "run_advancement":
                term_phase = "choose_advancement"
            if term_phase == "mustering_out":
                return "mustering_out"
            if term_phase == "muster_out_allocate":
                return "muster_out_allocate"
            if term_phase in TERM_PHASES:
                # During skill selection, check if rolls are exhausted.
                if term_phase == "choose_skills":
                    remaining = self._skill_rolls_remaining
                    if remaining <= 0:
                        if char.age >= 34:
                            return "run_aging"
                        return "re_enlist"
                if term_phase == "choose_aging_reduction" and not char.pending_aging:
                    return "re_enlist"
                # Player already chose at the re_enlist prompt — advance.
                if term_phase == "re_enlist":
                    outcome = self._get_reenlist_outcome(state)
                    if outcome == "continued":
                        return "run_survival"
                    if outcome == "mustered":
                        return "mustering_out"
                return term_phase
        return "run_survival"

    # ------------------------------------------------------------------
    # Phase view assembly (U2).
    # ------------------------------------------------------------------

    def get_phase_view(self) -> PhaseView:
        """Build a PhaseView for the current phase."""
        phase = self.determine_phase()
        state = self._engine.state
        char = state.character

        if phase == "roll_characteristics":
            return PhaseView(
                phase=phase,
                prompt="Roll six 2D6 values for your characteristics.",
                choices=[ChoiceOption(label="Roll Pool", option_id="roll_pool")],
            )

        if phase == "assign_characteristics":
            pool = char.unassigned_rolls
            assigned = set(char.characteristics.keys())
            unassigned_stats = [s for s in _ALL_CHARACTERISTICS if s not in assigned]
            choices = []
            for i, val in enumerate(pool):
                stat = unassigned_stats[i] if i < len(unassigned_stats) else f"slot_{i}"
                choices.append(
                    ChoiceOption(
                        label=f"Assign {val} to {stat}",
                        option_id=f"assign:{i}:{stat}",
                    )
                )
            choices.append(
                ChoiceOption(
                    label="Reroll Pool",
                    option_id="reroll_pool",
                    description="Discard the pool and roll six new values (once per character).",
                    dimmed=char.pool_rerolled,
                    requirement="Pool reroll already used" if char.pool_rerolled else "",
                )
            )
            return PhaseView(
                phase=phase,
                prompt=f"Assign pool values: {list(pool)}",
                choices=choices,
                drawer_pinned=True,
            )

        if phase == "choose_background_skills":
            picks_left = (
                char.background_picks_remaining if char.background_picks_remaining > 0 else 3
            )
            all_bg = list(self._pack.background_skills) if self._pack.background_skills else []
            bg_skills = [s for s in all_bg if s not in char.skills]
            if picks_left > 0 and not bg_skills:
                bg_skills = all_bg  # C1 fallback: never soft-lock
            choices = [
                ChoiceOption(label=f"{s} (level 0)", option_id=f"bg_skill:{s}") for s in bg_skills
            ]
            return PhaseView(
                phase=phase,
                prompt=f"Pick {picks_left} background skills (level 0).",
                choices=choices,
                drawer_pinned=True,
            )

        if phase == "choose_career":
            careers = sorted(self._pack.careers.values(), key=lambda c: c.name)
            left = {r.career_id for r in char.career_history}
            choices = []
            for c in careers:
                blocked = c.id in left and c.id != "drifter"
                q = c.qualification
                choices.append(
                    ChoiceOption(
                        label=c.name,
                        option_id=f"career:{c.id}",
                        description=f"Qualify: 2D6 vs {q.characteristic} {q.target}+",
                        dimmed=blocked,
                        requirement="Cannot return to a career already left (B17)"
                        if blocked
                        else "",
                    )
                )
            return PhaseView(
                phase=phase,
                prompt="Choose a career to qualify for.",
                choices=choices,
            )

        if phase == "choose_qualification_fallback":
            return self._view_qualification_fallback()

        if phase == "choose_career_change":
            return self._view_career_change()

        if phase == "run_survival":
            career = self._pack.careers.get(char.career)
            career_name = career.name if career else char.career
            return PhaseView(
                phase=phase,
                prompt=f"Term {char.terms + 1} — {career_name}: Ready to begin.",
                choices=[ChoiceOption(label="Begin Term", option_id="begin_term")],
            )

        if phase == "choose_commission":
            career = self._pack.careers.get(char.career)
            comm_char = career.commission.characteristic if career and career.commission else "?"
            comm_target = career.commission.target if career and career.commission else "?"
            return PhaseView(
                phase=phase,
                prompt=(
                    f"Term {char.terms} — Commission Check (Rank 0): "
                    f"2D6 vs {comm_target}, {comm_char}"
                ),
                choices=[
                    ChoiceOption(
                        label=f"Attempt Commission (2D6 vs {comm_target})",
                        option_id="commission_attempt",
                        description="Success grants rank 1 and an extra skill roll.",
                    ),
                    ChoiceOption(
                        label="Decline Commission",
                        option_id="commission_decline",
                        description="Skip the commission roll this term.",
                    ),
                ],
            )

        if phase == "choose_advancement":
            career = self._pack.careers.get(char.career)
            adv_char = career.advancement.characteristic if career and career.advancement else "?"
            adv_target = career.advancement.target if career and career.advancement else "?"
            return PhaseView(
                phase=phase,
                prompt=f"Term {char.terms} — Advancement Check: 2D6 vs {adv_target}, {adv_char}",
                choices=[
                    ChoiceOption(
                        label=f"Attempt Advancement (2D6 vs {adv_target})",
                        option_id="advancement_attempt",
                        description="Success grants a promotion and an extra skill roll.",
                    ),
                    ChoiceOption(
                        label="Decline Advancement",
                        option_id="advancement_decline",
                        description="Skip the advancement roll.",
                    ),
                ],
            )

        if phase == "choose_skills":
            career = self._pack.careers.get(char.career)
            remaining = self._skill_rolls_remaining
            edu = char.characteristics.get("EDU", 0)
            choices = []
            if career:
                for table in career.skill_tables:
                    # B7: Advanced Education requires EDU 8+.
                    if table.name == "Advanced Education" and edu < 8:
                        choices.append(
                            ChoiceOption(
                                label=f"{table.name} ({remaining} left)",
                                option_id=f"skill_table:{table.name}",
                                description="Requires EDU 8+",
                                dimmed=True,
                                requirement="Requires EDU 8+",
                            )
                        )
                        continue
                    skills_preview = [e.result for e in table.entries.entries]
                    preview = ", ".join(skills_preview[:4])
                    if len(skills_preview) > 4:
                        preview += ", ..."
                    choices.append(
                        ChoiceOption(
                            label=f"{table.name} ({remaining} left)",
                            option_id=f"skill_table:{table.name}",
                            description=f"Possible: {preview}",
                        )
                    )
            return PhaseView(
                phase=phase,
                prompt=(
                    f"Choose skill tables ({remaining} roll"
                    f"{'s' if remaining != 1 else ''} remaining):"
                ),
                choices=choices,
            )

        if phase == "run_aging":
            terms = char.terms
            return PhaseView(
                phase=phase,
                prompt=f"Aging Check (age 34+): Roll 2D6 - terms({terms})",
                choices=[ChoiceOption(label="Roll Aging", option_id="roll_aging")],
            )

        if phase == "choose_aging_reduction":
            return self._view_aging_reduction()

        if phase == "mishap_roll":
            return PhaseView(
                phase=phase,
                prompt="Roll on the career mishap table (1D6).",
                choices=[ChoiceOption(label="Roll Mishap", option_id="roll_mishap")],
            )

        if phase == "choose_injury_stat":
            return PhaseView(
                phase=phase,
                prompt="Choose which physical characteristic takes the injury:",
                choices=self._injury_stat_choices(),
            )

        if phase == "choose_crisis_resolution":
            crisis_stat = self._find_stat_at_zero() or "a characteristic"
            cost = get_pending_crisis_cost(state) or 10_000
            can_afford = char.credits >= cost
            pay_label = (
                f"Pay Cr{cost:,} (have Cr{char.credits:,})"
                if can_afford
                else f"Pay Cr{cost:,} (have Cr{char.credits:,} — cannot afford)"
            )
            pay_option = ChoiceOption(
                label=pay_label,
                option_id="crisis_pay",
                description=f"Pay for medical care. {crisis_stat} stabilises at 1.",
            )
            if not can_afford:
                pay_option = ChoiceOption(
                    label=pay_label,
                    option_id="crisis_pay",
                    description=f"Cannot afford Cr{cost:,}.",
                    dimmed=True,
                    requirement=f"Requires Cr{cost:,}",
                )
            decline_option = (
                ChoiceOption(
                    label="Accept death",
                    option_id="crisis_scar",
                    description="Ironman: the crisis is fatal. The character dies.",
                )
                if state.campaign.death_mode == "ironman"
                else ChoiceOption(
                    label="Accept lasting scar",
                    option_id="crisis_scar",
                    description=f"{crisis_stat} stabilises at 1 with a permanent severe Injury.",
                )
            )
            return PhaseView(
                phase=phase,
                prompt=f"Crisis: {crisis_stat} reached 0. Choose your response:",
                choices=[pay_option, decline_option],
            )

        if phase == "choose_basic_training_skill":
            career = self._pack.careers.get(char.career)
            service = (
                next((t for t in career.skill_tables if t.name == "Service Skills"), None)
                if career
                else None
            )
            skill_ids = (
                [e.result for e in service.entries.entries if not e.result.startswith("+")]
                if service
                else []
            )
            return PhaseView(
                phase=phase,
                prompt=(
                    f"Basic training ({career.name if career else char.career}): "
                    "choose ONE Service skill at level 0."
                ),
                choices=[
                    ChoiceOption(
                        label=f"{s.replace('_', ' ')} (level 0)", option_id=f"bt_skill:{s}"
                    )
                    for s in skill_ids
                ],
            )

        if phase == "re_enlist":
            career = self._pack.careers.get(char.career)
            career_name = career.name if career else char.career
            age_after = char.age + 4
            aging_note = " Aging check will apply." if age_after >= 34 else ""
            # Reconstruct the re-enlistment roll receipt from the event log
            # so it survives a page refresh / controller rebuild (U2).
            receipts: list[str] = []
            outcome = self._get_reenlist_outcome(state)
            receipt = self._format_reenlistment_receipt(state, char.career, outcome)
            if receipt:
                receipts.append(receipt)
            return PhaseView(
                phase=phase,
                prompt=(
                    f"Term {char.terms} complete ({career_name}, Rank {char.rank}, "
                    f"Age {char.age}). Re-enlist?"
                ),
                choices=[
                    ChoiceOption(
                        label=f"Continue for another term (Age {age_after})",
                        option_id="reenlist_continue",
                        description=f"Serve another 4-year term.{aging_note}",
                    ),
                    ChoiceOption(
                        label="Muster Out and Finish Character",
                        option_id="reenlist_muster",
                        description="Leave service and collect mustering-out benefits.",
                    ),
                ],
                receipts=receipts,
            )

        if phase == "mustering_out":
            # U3: compute the plan and advance to allocation immediately.
            career_id = self._get_muster_career_id()
            if career_id:
                self._muster_plan = self._runner.muster_out(career_id)
                self._benefit_rolls_remaining = self._runner.reconstruct_muster_counters(
                    self._muster_plan.total_rolls
                )
                if self._benefit_rolls_remaining <= 0:
                    # No benefit rolls — go straight to complete.
                    self._engine.apply(
                        SetFlagCommand(key="mustered_out", value="true", origin=self._origin_stamp)
                    )
                    return self.get_phase_view()
                self._set_term_phase("muster_out_allocate")
                return self._view_muster_out_allocate([])
            return PhaseView(
                phase="mustering_out",
                prompt="Mustering out...",
                choices=[],
            )

        if phase == "muster_out_allocate":
            return self._view_muster_out_allocate([])

        if phase == "choose_specialization":
            pending = char.pending_cascades[0]
            cascade = self._pack.cascades.get(pending.parent)
            members = cascade.specializations if cascade else []
            name = cascade.name if cascade else pending.parent.replace("_", " ").title()
            return PhaseView(
                phase=phase,
                prompt=f"Choose a {name} specialization:",
                choices=[
                    ChoiceOption(label=sid.replace("_", " "), option_id=f"spec:{sid}")
                    for sid in members
                ],
            )

        if phase == "complete":
            return PhaseView(
                phase="complete",
                prompt=(
                    f"Lifepath complete. Character: {char.name}, "
                    f"Career: {char.career}, Terms: {char.terms}."
                ),
                # The template renders a GET link to /adventure/{save_name}
                # rather than a POST choice. No choices needed here.
                choices=[],
            )

        # Fallback for any unrecognized term phase.
        if phase in TERM_PHASES:
            return PhaseView(
                phase=phase,
                prompt=f"Processing: {phase.replace('_', ' ')}...",
                choices=[ChoiceOption(label="Continue", option_id="auto_advance")],
            )

        return PhaseView(
            phase=phase,
            prompt=phase.replace("_", " ").title(),
        )

    # ------------------------------------------------------------------
    # Specialized view builders.
    # ------------------------------------------------------------------

    def _view_qualification_fallback(self) -> PhaseView:
        """Build the qualification-fallback PhaseView (TUI parity)."""
        char = self._engine.state.character
        choices = [ChoiceOption(label="Choose a different career", option_id="fallback_retry")]
        if not char.drafted and self._pack.draft_table:
            choices.append(
                ChoiceOption(
                    label="Submit to the draft (1D6)",
                    option_id="fallback_draft",
                    description="Roll 1D6 on the pack's draft table.",
                )
            )
        if "drifter" in self._pack.careers:
            choices.append(
                ChoiceOption(
                    label="Enter the Drifter career",
                    option_id="fallback_drifter",
                    description="Attempt drifter qualification (SOC target 2).",
                )
            )
        return PhaseView(
            phase="choose_qualification_fallback",
            prompt="Qualification failed. Choose your path:",
            choices=choices,
        )

    def _view_career_change(self) -> PhaseView:
        """Build the career-change PhaseView."""
        history = self._engine.state.character.career_history
        dm = -2 * len(history)
        return PhaseView(
            phase="choose_career_change",
            prompt="Your career has ended. What next?",
            choices=[
                ChoiceOption(
                    label="Try a new career",
                    option_id="career_change_new",
                    description=f"Qualification at DM {dm:+d}.",
                ),
                ChoiceOption(
                    label="Muster out (end character creation)",
                    option_id="career_change_muster",
                    description="End character creation and roll mustering-out benefits.",
                ),
            ],
        )

    def _view_aging_reduction(self) -> PhaseView:
        """Build the per-slot aging-reduction PhaseView."""
        char = self._engine.state.character
        pending = char.pending_aging
        if not pending:
            return PhaseView(
                phase="choose_aging_reduction",
                prompt="No aging reductions pending.",
                choices=[],
            )
        slot = pending[0]
        group = slot.group
        points = slot.points
        stats = list(_PHYSICAL_CHARACTERISTICS) if group == "physical" else ["INT", "EDU", "SOC"]
        choices = []
        for s in stats:
            val = char.characteristics.get(s, 0)
            desc = (
                f"{s} is currently {val}. "
                f"Reducing by {points}"
                f"{' — crisis at 0!' if val - points <= 0 else ''}."
            )
            choices.append(
                ChoiceOption(label=f"{s} ({val})", option_id=f"aging_stat:{s}", description=desc)
            )
        return PhaseView(
            phase="choose_aging_reduction",
            prompt=(
                f"Aging reduction ({group} -{points}). "
                f"Choose a characteristic ({len(pending)} slot(s) left):"
            ),
            choices=choices,
        )

    def _view_muster_out_allocate(self, receipts: list[str]) -> PhaseView:
        """Build the per-roll muster-out allocation PhaseView (U3).

        Offers Cash table and Material table choices. Cash is dimmed when
        the 3-roll cap is reached. Tracks remaining rolls via
        ``plan.total_rolls - (cash_taken + material_taken)``.
        """
        career_id = self._get_muster_career_id()
        plan = self._muster_plan
        if plan is None:
            if not career_id:
                return PhaseView(
                    phase="muster_out_allocate",
                    prompt="Mustering out...",
                    choices=[],
                )
            plan = self._runner.muster_out(career_id)
            self._muster_plan = plan

        career = self._pack.careers.get(career_id)

        # Rebuild remaining from events (resume-safe, consistent with TUI).
        self._benefit_rolls_remaining = self._runner.reconstruct_muster_counters(plan.total_rolls)

        remaining = self._benefit_rolls_remaining
        if remaining <= 0:
            # All rolls exhausted — mark muster out and go to complete.
            self._engine.apply(
                SetFlagCommand(key="mustered_out", value="true", origin=self._origin_stamp)
            )
            char = self._engine.state.character
            return PhaseView(
                phase="complete",
                prompt=(
                    f"Lifepath complete. Character: {char.name}, "
                    f"Career: {char.career}, Terms: {char.terms}."
                ),
                choices=[],
            )

        cash_taken = self._runner.cash_rolls_taken
        choices: list[ChoiceOption] = []

        if career and career.mustering_out_cash:
            if cash_taken < 3:
                choices.append(
                    ChoiceOption(
                        label=f"Cash table ({cash_taken}/3 taken)",
                        option_id="claim_cash",
                        description=f"Roll on the cash benefits table. {3 - cash_taken} cash roll(s) remaining.",
                    )
                )
            else:
                choices.append(
                    ChoiceOption(
                        label="Cash table (3/3 — full)",
                        option_id="claim_cash",
                        description="Cash rolls exhausted (3/3 taken).",
                        dimmed=True,
                        requirement="Cash rolls exhausted",
                    )
                )

        if career and career.mustering_out_material:
            mat_desc = "Roll on the material benefits table for gear, passages, or perks."
            if plan.material_dm:
                mat_desc += f" Material DM +{plan.material_dm} (rank {plan.final_rank})."
            choices.append(
                ChoiceOption(
                    label="Material table",
                    option_id="claim_material",
                    description=mat_desc,
                )
            )

        return PhaseView(
            phase="muster_out_allocate",
            prompt=(f"Allocate benefit roll ({remaining} remaining of {plan.total_rolls}):"),
            choices=choices,
            receipts=receipts,
        )

    # ------------------------------------------------------------------
    # Choice application — routes a choice to the appropriate step handler.
    # ------------------------------------------------------------------

    def apply_choice(self, option_id: str, *, origin: str = "player") -> PhaseView:
        """Apply a player's choice and return the next PhaseView.

        Routes the ``option_id`` to the appropriate LifepathRunner method.
        Sets term_phase flags via SetFlagCommand (KTD-3 byte-identical).

        ``origin`` (P6.T1, ADR A10) is surfaced on the resulting
        ``SetFlagCommand`` events via ``changes["origin"]`` — ``"player"``
        (default, omitted from changes for byte-identical events),
        ``"advisor"``, or ``"freetext"``.
        """
        self._choice_origin = origin
        # --- Pre-career phases ---
        if option_id == "roll_pool":
            self._runner.roll_pool()
            return self.get_phase_view()

        if option_id.startswith("assign:"):
            parts = option_id.split(":", 2)
            pool_index = int(parts[1])
            stat_name = parts[2] if len(parts) > 2 else ""
            self._runner.assign_characteristic(stat_name, pool_index)
            return self.get_phase_view()

        if option_id == "reroll_pool":
            self._runner.reroll_pool()
            return self.get_phase_view()

        if option_id.startswith("bg_skill:"):
            skill = option_id.split(":", 1)[1]
            self._runner.start_background_phase()
            self._runner.pick_background_skill(skill)
            return self.get_phase_view()

        if option_id.startswith("career:"):
            career_id = option_id.split(":", 1)[1]
            return self._do_choose_career(career_id)

        # --- Qualification fallback ---
        if option_id == "fallback_retry":
            self._set_term_phase("choose_career")
            return self.get_phase_view()

        if option_id == "fallback_draft":
            return self._do_fallback_draft()

        if option_id == "fallback_drifter":
            return self._do_fallback_drifter()

        # --- Career change ---
        if option_id == "career_change_new":
            self._set_term_phase("choose_career")
            return self.get_phase_view()

        if option_id == "career_change_muster":
            self._set_term_phase("mustering_out")
            return self.get_phase_view()

        # --- Term sub-phases ---
        if option_id.startswith("bt_skill:"):
            return self._do_basic_training_choice(option_id.split(":", 1)[1])

        if option_id.startswith("spec:"):
            return self._do_choose_specialization(option_id.split(":", 1)[1])

        if option_id == "begin_term":
            return self._do_survival_roll()

        if option_id == "commission_attempt":
            return self._do_commission_roll()

        if option_id == "commission_decline":
            return self._decline_commission()

        if option_id == "advancement_attempt":
            return self._do_advancement_roll()

        if option_id == "advancement_decline":
            return self._decline_advancement()

        if option_id.startswith("skill_table:"):
            table_name = option_id.split(":", 1)[1]
            return self._do_skill_table_choice(table_name)

        if option_id == "roll_aging":
            return self._do_aging_roll()

        if option_id.startswith("aging_stat:"):
            stat = option_id.split(":", 1)[1]
            return self._do_choose_aging_reduction(stat)

        if option_id == "roll_mishap":
            return self._do_mishap_roll()

        if option_id.startswith("injury_stat:"):
            stat = option_id.split(":", 1)[1]
            return self._do_choose_injury_stat(stat)

        if option_id == "crisis_pay":
            return self._do_choose_crisis_resolution(pay=True)

        if option_id == "crisis_scar":
            return self._do_choose_crisis_resolution(pay=False)

        if option_id == "reenlist_continue":
            return self._do_re_enlist_continue()

        if option_id == "reenlist_muster":
            return self._do_re_enlist_muster_out()

        if option_id == "claim_cash":
            return self._do_claim_benefit("cash")

        if option_id == "claim_material":
            return self._do_claim_benefit("material")

        if option_id == "begin_adventure":
            return self.get_phase_view()

        if option_id == "auto_advance":
            # Muster-out auto-advance (legacy path — no longer used by U3,
            # which routes through claim_cash/claim_material). Keep as a
            # harmless no-op for any old save that might hit it.
            return self.get_phase_view()

        # Unknown choice — return current view unchanged.
        return self.get_phase_view()

    # ------------------------------------------------------------------
    # Career choice + qualification fallback handlers.
    # ------------------------------------------------------------------

    def _do_choose_career(self, career_id: str) -> PhaseView:
        """Attempt qualification. On failure, route to the fallback phase."""
        qual = self._runner.qualify(career_id)
        receipt = self._format_roll_receipt(
            "Qualification",
            qual.raw_roll,
            qual.adjusted_total - qual.raw_roll,
            qual.adjusted_total,
            qual.target,
            qual.success,
        )
        if not qual.success:
            self._set_term_phase("choose_qualification_fallback")
            view = self.get_phase_view()
            return PhaseView(
                phase="choose_qualification_fallback",
                prompt=view.prompt,
                choices=view.choices,
                receipts=[receipt],
            )

        # Basic training (B11): first career grants all Service Skills at level 0.
        self._run_basic_training_for_career(career_id)
        view = self.get_phase_view()
        return PhaseView(
            phase=view.phase,
            prompt=view.prompt,
            receipts=[receipt],
            choices=view.choices,
        )

    def _run_basic_training_for_career(self, career_id: str) -> None:
        """Trigger basic training on career entry (B11, P1.T7).

        First career (empty history): grants all Service Skills at level 0
        immediately. Later careers: sets the ``choose_basic_training_skill``
        phase so the player picks ONE Service skill at level 0 (B3 — this
        path was previously unreachable). Re-entered careers grant nothing.
        """
        state = self._engine.state
        history = state.character.career_history
        if not history:
            if state.character.basic_training_done:
                return
            if self._pack.careers.get(career_id) is None:
                return
            self._runner.run_basic_training(career_id)
            return
        if career_id in {r.career_id for r in history}:
            return  # re-entered career — training already received
        self._set_term_phase("choose_basic_training_skill")

    def _do_basic_training_choice(self, skill: str) -> PhaseView:
        """Apply the player's later-career basic training pick (B11, P1.T7)."""
        career_id = self._engine.state.character.career
        self._runner.run_basic_training(career_id, chosen_skill=skill)
        self._set_term_phase("run_survival")
        return self.get_phase_view()

    def _do_choose_specialization(self, skill_id: str) -> PhaseView:
        """Apply the player's cascade specialization pick (C3)."""
        state = self._engine.state
        if not state.character.pending_cascades:
            return self.get_phase_view()
        pending = state.character.pending_cascades[0]
        cascade = self._pack.cascades.get(pending.parent)
        members = list(cascade.specializations) if cascade else []
        event = self._engine.apply(
            ChooseSpecializationCommand(
                cascade_parent=pending.parent,
                skill_id=skill_id,
                grant_mode=pending.grant_mode,
                specializations=members,
            )
        )
        receipt = event.description
        view = self.get_phase_view()
        return PhaseView(
            phase=view.phase, prompt=view.prompt, choices=view.choices, receipts=[receipt]
        )

    def _do_fallback_draft(self) -> PhaseView:
        """Apply DraftCommand + basic training, then route to run_survival."""
        try:
            career_id = self._runner.run_draft()
        except ValueError:
            logger.warning("draft rejected for character %s", self._engine.state.character.name)
            return self.get_phase_view()
        self._run_basic_training_for_career(career_id)
        return self.get_phase_view()

    def _do_fallback_drifter(self) -> PhaseView:
        """Attempt drifter qualification. On success, basic training runs."""
        qual = self._runner.qualify("drifter")
        if qual.success:
            self._run_basic_training_for_career("drifter")
        return self.get_phase_view()

    # ------------------------------------------------------------------
    # Term sub-step handlers.
    # ------------------------------------------------------------------

    def _do_survival_roll(self) -> PhaseView:
        """Start a term and roll survival (the run_survival entry point)."""
        state = self._engine.state
        career_id = state.character.career
        term_number = state.character.terms + 1

        result = self._runner.start_term(career_id, term_number)
        self._current_term_result = result
        self._runner.run_survival_step(career_id, result)

        receipt = self._format_roll_receipt(
            "Survival",
            result.survival_raw,
            result.survival_dm,
            result.survival_total,
            result.survival_target,
            result.survival_success,
            "MISHAP" if result.mishap else ("DEATH" if result.died else ""),
        )
        receipts = [receipt]

        if result.died:
            return PhaseView(
                phase="complete",
                prompt="The character did not survive.",
                receipts=receipts,
            )

        if result.mishap:
            self._set_term_phase("mishap_roll")
            return PhaseView(
                phase="mishap_roll",
                prompt="Roll on the career mishap table (1D6).",
                choices=[ChoiceOption(label="Roll Mishap", option_id="roll_mishap")],
                receipts=receipts,
            )

        # Route to the next term phase.
        return self._advance_after_survival(career_id, receipts)

    def _advance_after_survival(self, career_id: str, receipts: list[str]) -> PhaseView:
        """Route to commission/advancement/skills after successful survival."""
        if self._runner.commission_available(career_id):
            self._set_term_phase("choose_commission")
            view = self.get_phase_view()
            return PhaseView(
                phase="choose_commission",
                prompt=view.prompt,
                choices=view.choices,
                receipts=receipts,
            )
        if self._runner.advancement_available(career_id):
            self._set_term_phase("choose_advancement")
            view = self.get_phase_view()
            return PhaseView(
                phase="choose_advancement",
                prompt=view.prompt,
                choices=view.choices,
                receipts=receipts,
            )
        return self._enter_choose_skills(receipts)

    def _do_commission_roll(self) -> PhaseView:
        """Roll commission for the current term (player chose Attempt)."""
        state = self._engine.state
        career_id = state.character.career
        result = self._current_term_result
        if result is None:
            return self.get_phase_view()

        self._runner.run_commission_step(career_id, result)
        receipt = self._format_roll_receipt(
            "Commission",
            result.commission_raw,
            result.commission_dm,
            result.commission_total,
            result.commission_target,
            result.commission_success,
        )
        return self._advance_after_commission(career_id, [receipt])

    def _decline_commission(self) -> PhaseView:
        """Skip the commission roll (player chose Decline)."""
        career_id = self._engine.state.character.career
        return self._advance_after_commission(career_id, [])

    def _advance_after_commission(self, career_id: str, receipts: list[str]) -> PhaseView:
        """Route to advancement (if available) or skill rolls after commission."""
        if self._runner.advancement_available(career_id):
            self._set_term_phase("choose_advancement")
            view = self.get_phase_view()
            return PhaseView(
                phase="choose_advancement",
                prompt=view.prompt,
                choices=view.choices,
                receipts=receipts,
            )
        return self._enter_choose_skills(receipts)

    def _decline_advancement(self) -> PhaseView:
        """Skip the advancement roll."""
        return self._enter_choose_skills([])

    def _do_advancement_roll(self) -> PhaseView:
        """Roll advancement for the current term."""
        state = self._engine.state
        career_id = state.character.career
        result = self._current_term_result
        if result is None:
            return self.get_phase_view()

        self._runner.run_advancement_step(career_id, result)
        receipt = self._format_roll_receipt(
            "Advancement",
            result.advancement_raw,
            result.advancement_dm,
            result.advancement_total,
            result.advancement_target,
            result.advancement_success,
        )
        return self._enter_choose_skills([receipt])

    def _enter_choose_skills(self, receipts: list[str]) -> PhaseView:
        """Compute skill rolls and transition to the choose_skills phase."""
        result = self._current_term_result
        if result is None:
            return self.get_phase_view()
        num_rolls = self._runner.compute_num_skill_rolls(result)
        self._skill_rolls_remaining = num_rolls
        self._set_term_phase("choose_skills")
        view = self.get_phase_view()
        return PhaseView(
            phase="choose_skills",
            prompt=view.prompt,
            choices=view.choices,
            receipts=receipts,
        )

    def _do_skill_table_choice(self, table_name: str) -> PhaseView:
        """Roll on the player's chosen skill table."""
        state = self._engine.state
        career_id = state.character.career
        result = self._current_term_result
        if result is None or self._skill_rolls_remaining <= 0:
            return self.get_phase_view()

        gain = self._runner.run_skill_roll_step(career_id, result, table_name)
        self._skill_rolls_remaining -= 1

        receipt = f"Skill Roll ({table_name}): roll {gain.roll} -> {gain.result_text}"
        receipts = [receipt]

        if self._skill_rolls_remaining > 0:
            # More picks — refresh the view with updated count.
            self._set_term_phase("choose_skills")
            view = self.get_phase_view()
            return PhaseView(
                phase="choose_skills",
                prompt=view.prompt,
                choices=view.choices,
                receipts=receipts,
            )
        # All skill rolls done — advance to aging or re_enlist.
        char = self._engine.state.character
        if char.age >= 34:
            self._set_term_phase("run_aging")
            view = self.get_phase_view()
            return PhaseView(
                phase="run_aging",
                prompt=view.prompt,
                choices=view.choices,
                receipts=receipts,
            )
        # No aging needed — finalize and go to re_enlist.
        self._runner.finalize_term(career_id, result)
        self._set_term_phase("re_enlist")
        return self._resolve_reenlistment_and_view(career_id, receipts)

    # ------------------------------------------------------------------
    # Mishap / injury / crisis interactive handlers (B13).
    # ------------------------------------------------------------------

    def _do_mishap_roll(self) -> PhaseView:
        """Roll the career mishap table (step 1 of the interactive mishap flow).

        Applies ``MishapRollCommand`` directly rather than calling
        ``runner.run_mishap``: the runner auto-picks ``_highest_physical_stat()``
        for the injury, but the web shell wants the *player* to choose, so we
        stop after the mishap roll and route to ``choose_injury_stat`` when the
        entry chains to the injury table.
        """
        result = self._current_term_result
        if result is None:
            return self.get_phase_view()

        state = self._engine.state
        career_id = state.character.career
        career = self._pack.careers.get(career_id)
        if career is None or career.mishap_table is None:
            return self._complete_term(result, [])

        mishap_event = self._engine.apply(
            MishapRollCommand(career_id=career_id, entries=career.mishap_table.entries)
        )
        mc = mishap_event.changes
        receipt = f"Mishap (roll {mc['roll_total']}): {mc['result_text']}"
        receipts = [receipt]

        if mc["injury"] and self._pack.injury_table is not None:
            self._set_term_phase("choose_injury_stat")
            return PhaseView(
                phase="choose_injury_stat",
                prompt="Choose which physical characteristic takes the injury:",
                choices=self._injury_stat_choices(),
                receipts=receipts,
            )
        # No injury — go to re_enlist (or mustering out).
        return self._complete_term(result, receipts)

    def _do_choose_injury_stat(self, stat: str) -> PhaseView:
        """Apply the injury roll with the player's chosen stat (step 2)."""
        result = self._current_term_result
        if result is None:
            return self.get_phase_view()

        injury_table = self._pack.injury_table
        if injury_table is None:
            return self._complete_term(result, [])

        event = self._engine.apply(
            InjuryRollCommand(entries=injury_table.entries, chosen_stat=stat)
        )
        ic = event.changes
        reductions = ic["reductions"]
        rstr = ", ".join(f"{s} -{a}" for s, a in reductions.items())
        receipt = f"Injury: {rstr}"
        receipts = [receipt]

        crisis_stat = self._find_stat_at_zero()
        if crisis_stat:
            self._set_term_phase("choose_crisis_resolution")
            view = self.get_phase_view()
            return PhaseView(
                phase="choose_crisis_resolution",
                prompt=f"Crisis: {crisis_stat} reached 0. Choose your response:",
                choices=view.choices,
                receipts=receipts,
            )
        # No crisis — complete the term.
        return self._complete_term(result, receipts)

    def _do_choose_crisis_resolution(self, pay: bool) -> PhaseView:
        """Apply the player's crisis resolution choice (step 3)."""
        result = self._current_term_result
        if result is None:
            return self.get_phase_view()

        cost = get_pending_crisis_cost(self._engine.state) or 10_000
        if pay and self._engine.state.character.credits < cost:
            return self.get_phase_view()  # dimmed option; ignore crafted posts

        crisis_stat = self._find_stat_at_zero()
        if not crisis_stat:
            return self._after_crisis_resolution(result, [])

        event = self._engine.apply(
            ResolveInjuryCrisisCommand(stat=crisis_stat, pay=pay, crisis_cost_cr=cost)
        )
        outcome = event.changes["outcome"]
        receipts = [f"Crisis ({crisis_stat}): {outcome}"]

        if outcome == "death":
            result.died = True

        return self._after_crisis_resolution(result, receipts)

    def _after_crisis_resolution(self, result: TermResult, receipts: list[str]) -> PhaseView:
        """Transition after a crisis is resolved.

        If the aging loop is active and slots remain, return to it; if the
        aging loop is active but empty, finalise the term. Otherwise (injury
        crisis path) complete the term.
        """
        if result.died:
            self._aging_active = False
            return self._complete_term(result, receipts)
        if self._aging_active:
            if self._engine.state.character.pending_aging:
                self._set_term_phase("choose_aging_reduction")
                view = self.get_phase_view()
                return PhaseView(
                    phase="choose_aging_reduction",
                    prompt=view.prompt,
                    choices=view.choices,
                    receipts=receipts,
                )
            self._aging_active = False
            career_id = self._engine.state.character.career
            self._runner.finalize_term(career_id, result)
            return self._complete_term(result, receipts)
        return self._complete_term(result, receipts)

    # ------------------------------------------------------------------
    # Aging handler (B4 graduated table).
    # ------------------------------------------------------------------

    def _do_aging_roll(self) -> PhaseView:
        """Roll the graduated aging check (2D6 - terms, B4)."""
        state = self._engine.state
        career_id = state.character.career
        result = self._current_term_result
        if result is None:
            return self.get_phase_view()

        terms = state.character.terms
        self._runner.run_aging_step(result)

        adjusted = result.aging_raw - terms
        receipt = self._format_roll_receipt(
            "Aging",
            result.aging_raw,
            -terms,
            adjusted,
            1,
            result.aging_success,
        )
        receipts = [receipt]

        if result.aging_success:
            self._runner.finalize_term(career_id, result)
            return self._complete_term(result, receipts)

        # Aging effects pending — enter choose_aging_reduction.
        self._aging_active = True
        self._set_term_phase("choose_aging_reduction")
        view = self.get_phase_view()
        return PhaseView(
            phase="choose_aging_reduction",
            prompt=view.prompt,
            choices=view.choices,
            receipts=receipts,
        )

    def _do_choose_aging_reduction(self, stat: str) -> PhaseView:
        """Apply one pending aging slot to the player's chosen characteristic."""
        state = self._engine.state
        career_id = state.character.career
        result = self._current_term_result
        if result is None or not state.character.pending_aging:
            return self.get_phase_view()

        slot = state.character.pending_aging[0]
        event = self._engine.apply(
            ApplyAgingReductionCommand(characteristic=stat, points=slot.points)
        )
        new_val = event.changes["new_value"]
        receipt = f"Aging: {stat} -{slot.points} (now {new_val})"
        receipts = [receipt]

        if event.changes.get("crisis"):
            self._set_term_phase("choose_crisis_resolution")
            # C2/C-A5: aging crisis costs 1D6 x 10k. Roll AFTER setting the
            # term_phase flag so get_pending_crisis_cost finds the cost first.
            cost_event = self._engine.apply(RollAgingCrisisCostCommand())
            self._engine.apply(
                SetFlagCommand(
                    key="crisis_cost",
                    value=str(cost_event.changes["crisis_multiplier"] * 10_000),
                    origin=self._origin_stamp,
                )
            )
            view = self.get_phase_view()
            return PhaseView(
                phase="choose_crisis_resolution",
                prompt=view.prompt,
                choices=view.choices,
                receipts=receipts,
            )

        # No crisis — check for remaining slots.
        if state.character.pending_aging:
            self._set_term_phase("choose_aging_reduction")
            view = self.get_phase_view()
            return PhaseView(
                phase="choose_aging_reduction",
                prompt=view.prompt,
                choices=view.choices,
                receipts=receipts,
            )
        # All slots consumed — finalize the term.
        self._aging_active = False
        self._runner.finalize_term(career_id, result)
        return self._complete_term(result, receipts)

    # ------------------------------------------------------------------
    # Re-enlistment handler (B12).
    # ------------------------------------------------------------------

    def _complete_term(self, result: TermResult, receipts: list[str]) -> PhaseView:
        """After all term steps, set the re_enlist phase and resolve forced outcomes."""
        if result.died:
            return PhaseView(
                phase="complete",
                prompt="The character did not survive.",
                receipts=receipts,
            )
        # Set rank_title for all non-death paths — mishap/crisis callers
        # may have skipped finalize_term (kilo-code-bot review feedback).
        career_id = self._engine.state.character.career
        if career_id:
            self._runner.finalize_term(career_id, result)
        if result.mishap:
            # Career ended via mishap — end career, then choose or muster.
            state = self._engine.state
            if state.character.career:
                self._engine.apply(EndCareerCommand(ended_by="mishap"))
            if state.character.terms < 7:
                self._set_term_phase("choose_career_change")
                view = self.get_phase_view()
                return PhaseView(
                    phase="choose_career_change",
                    prompt=view.prompt,
                    choices=view.choices,
                    receipts=receipts,
                )
            self._set_term_phase("mustering_out")
            view = self.get_phase_view()
            return PhaseView(
                phase="mustering_out",
                prompt="Mustering out...",
                choices=view.choices,
                receipts=receipts,
            )

        # Normal term completion — go to re_enlist.
        career_id = self._engine.state.character.career
        self._set_term_phase("re_enlist")
        return self._resolve_reenlistment_and_view(career_id, receipts)

    def _resolve_reenlistment_and_view(self, career_id: str, receipts: list[str]) -> PhaseView:
        """Run the re-enlistment roll and build the appropriate PhaseView.

        Honors forced outcomes:
        - ``must_continue``: auto-advance to next term (run_survival).
        - ``must_leave`` / ``must_retire``: route to mustering out.
        - ``may_continue``: offer the player Continue vs Muster Out.
        """
        state = self._engine.state

        # Don't re-roll if the outcome was already persisted (resume safety).
        outcome = self._get_reenlist_outcome(state)
        if outcome is None:
            outcome = self._runner.run_reenlistment_step(career_id)
            self._engine.apply(
                SetFlagCommand(key="reenlist_outcome", value=outcome, origin=self._origin_stamp)
            )

        # Build the re-enlistment receipt (shared with get_phase_view).
        receipt = self._format_reenlistment_receipt(state, career_id, outcome)
        if receipt:
            receipts.append(receipt)

        if outcome == "must_continue":
            # Auto-advance to next term.
            self._engine.apply(
                SetFlagCommand(key="reenlist_outcome", value="continued", origin=self._origin_stamp)
            )
            self._current_term_result = None
            self._skill_rolls_remaining = 0
            self._set_term_phase("run_survival")
            view = self.get_phase_view()
            return PhaseView(
                phase="run_survival",
                prompt=view.prompt,
                choices=view.choices,
                receipts=receipts,
            )
        if outcome in ("must_leave", "must_retire"):
            if state.character.career:
                ended_by = "muster_out"
                self._engine.apply(EndCareerCommand(ended_by=ended_by))
            self._set_term_phase("mustering_out")
            view = self.get_phase_view()
            return PhaseView(
                phase="mustering_out",
                prompt="Mustering out...",
                choices=view.choices,
                receipts=receipts,
            )
        # may_continue — offer Continue vs Muster Out.
        view = self.get_phase_view()
        return PhaseView(
            phase="re_enlist",
            prompt=view.prompt,
            choices=view.choices,
            receipts=receipts,
        )

    def _do_re_enlist_continue(self) -> PhaseView:
        """Player chooses to continue for another term."""
        self._current_term_result = None
        self._skill_rolls_remaining = 0
        self._set_term_phase("run_survival")
        return self.get_phase_view()

    def _do_re_enlist_muster_out(self) -> PhaseView:
        """Player chooses to muster out."""
        state = self._engine.state
        if state.character.career:
            self._engine.apply(EndCareerCommand(ended_by="muster_out"))
        self._set_term_phase("mustering_out")
        return self.get_phase_view()

    # ------------------------------------------------------------------
    # Muster-out benefit allocation handlers (U3 — per-roll choice).
    # ------------------------------------------------------------------

    def _do_claim_benefit(self, table: str) -> PhaseView:
        """Roll one benefit on the chosen table and show the receipt.

        Cash is capped at 3 rolls total (enforced by ``runner.claim_benefit``).
        After all rolls are exhausted, sets ``mustered_out=true`` and advances
        to ``complete``.
        """
        career_id = self._get_muster_career_id()
        if not career_id:
            return self.get_phase_view()

        plan = self._muster_plan
        if plan is None:
            plan = self._runner.muster_out(career_id)
            self._muster_plan = plan

        dm = 0 if table == "cash" else plan.material_dm

        # Guard the cash cap explicitly so genuine ValueErrors (unknown table,
        # missing benefit table) propagate instead of being swallowed.
        if table == "cash" and self._runner.cash_rolls_taken >= 3:
            return self._view_muster_out_allocate(["Cash rolls exhausted (3/3 taken)."])

        result_text = self._runner.claim_benefit(career_id, table=table, dm=dm)

        label = "Cash" if table == "cash" else "Material"
        receipt = f"{label} Benefit: {result_text}"
        if table == "cash":
            receipt += f" (Credits: {self._engine.state.character.credits:,})"

        # Rebuild remaining from events (authoritative, same as TUI).
        self._benefit_rolls_remaining = self._runner.reconstruct_muster_counters(plan.total_rolls)

        if self._benefit_rolls_remaining <= 0:
            self._engine.apply(
                SetFlagCommand(key="mustered_out", value="true", origin=self._origin_stamp)
            )
            view = self.get_phase_view()
            return PhaseView(
                phase=view.phase,
                prompt=view.prompt,
                choices=view.choices,
                receipts=[receipt],
            )

        return self._view_muster_out_allocate([receipt])

    def _get_muster_career_id(self) -> str:
        """Return the career id for mustering out (current or last in history)."""
        state = self._engine.state
        if state.character.career:
            return state.character.career
        if state.character.career_history:
            return state.character.career_history[-1].career_id
        return ""

    # ------------------------------------------------------------------
    # Receipt formatting.
    # ------------------------------------------------------------------

    @staticmethod
    def _format_roll_receipt(
        label: str,
        raw: int,
        dm: int,
        total: int,
        target: int,
        success: bool,
        tier: str = "",
    ) -> str:
        """Format a dice roll receipt with full detail (R7).

        Format mirrors the adventure screen's mechanics line:
        ``Label: 2D6({raw})+DM({dm})={total} vs {target} -> {outcome}``
        """
        outcome = "success" if success else "failure"
        dm_str = f"+DM({dm})" if dm else ""
        tier_str = f" [{tier}]" if tier else ""
        return f"{label}: 2D6({raw}){dm_str}={total} vs {target} -> {outcome}{tier_str}"

    def _format_reenlistment_receipt(
        self, state: GameState, career_id: str, outcome: str | None
    ) -> str | None:
        """Format the re-enlistment receipt from the most recent event, or None.

        Shared by ``get_phase_view`` (resume reconstruction) and
        ``_resolve_reenlistment_and_view`` (live roll) so the format stays
        in one place.
        """
        career = self._pack.careers.get(career_id or "")
        for e in reversed(state.events):
            if e.command_type != "lifepath_reenlistment":
                continue
            if e.roll is not None:
                raw = sum(e.roll.rolls)
                target_val = career.re_enlistment if career and career.re_enlistment else "—"
                return f"Re-enlistment: 2D6={raw} vs {target_val} -> {outcome}"
            if outcome == "must_retire":
                return "Re-enlistment: mandatory retirement (7+ terms)"
            return f"Re-enlistment: {outcome}"
        return None
