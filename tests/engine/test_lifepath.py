"""Tests for the lifepath engine: chargen end-to-end, death mode, aging, mustering out.

Uses ForcedRoller to control every die, making scenarios fully deterministic.
Covers R9 (lifepath playable end-to-end), R10 (death mode honored),
AE2 (Ironman death vs non-Ironman mishap), AE7 (no LLM required).
"""

from __future__ import annotations

import pytest

from src.engine.audit import EventKind, audit_rolls
from src.engine.commands import Engine
from src.engine.dice import ForcedRoller
from src.engine.lifepath import (
    AdvanceTermCommand,
    DraftCommand,
    EndCareerCommand,
    LifepathRunner,
    QualificationCommand,
    ResolveInjuryCrisisCommand,
    SurvivalCommand,
    TermResult,
    apply_skill_result,
    lookup_table_result,
)
from src.engine.state import (
    AgingSlot,
    CampaignConfig,
    CareerTermRecord,
    Character,
    GameState,
    Injury,
)
from src.rulesets.base import SkillTableEntry
from src.rulesets.cepheus import CepheusRuleSet
from src.themepacks.base import get_pack

# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture
def pack():
    return get_pack("scifi")


@pytest.fixture
def ruleset():
    return CepheusRuleSet()


@pytest.fixture
def engine_and_pack():
    """Fresh (engine, pack) for isolated command tests (narrative mode)."""
    pack = get_pack("scifi")
    state = GameState.new(seed=42)
    state.campaign = CampaignConfig(death_mode="narrative")
    engine = Engine(state, roller=ForcedRoller([]))
    return engine, pack


def make_engine(queue, death_mode="narrative", seed=42):
    """Create an engine with ForcedRoller and given death mode."""
    state = GameState.new(seed=seed)
    state.campaign = CampaignConfig(death_mode=death_mode)
    return Engine(state, roller=ForcedRoller(queue))


# ---------------------------------------------------------------------------
# Helper function tests.
# ---------------------------------------------------------------------------


class TestLookupTableResult:
    def test_finds_matching_entry(self):
        entries = [
            SkillTableEntry(min=2, max=3, result="a"),
            SkillTableEntry(min=4, max=6, result="b"),
            SkillTableEntry(min=7, max=12, result="c"),
        ]
        assert lookup_table_result(entries, 5).result == "b"
        assert lookup_table_result(entries, 2).result == "a"
        assert lookup_table_result(entries, 12).result == "c"

    def test_raises_out_of_range(self):
        """Out-of-range rolls raise IndexError instead of clamping (N4)."""
        entries = [SkillTableEntry(min=1, max=6, result="x")]
        with pytest.raises(IndexError):
            lookup_table_result(entries, 7)


class TestApplySkillResult:
    def test_skill_increment(self):
        char = Character()
        gain_type, name = apply_skill_result(char, "pilot")
        assert gain_type == "skill"
        assert name == "pilot"
        assert char.skills["pilot"] == 1

    def test_skill_increment_existing(self):
        char = Character(skills={"pilot": 2})
        apply_skill_result(char, "pilot")
        assert char.skills["pilot"] == 3

    def test_characteristic_increment(self):
        char = Character(characteristics={"STR": 7})
        gain_type, name = apply_skill_result(char, "+1 STR")
        assert gain_type == "characteristic"
        assert name == "STR"
        assert char.characteristics["STR"] == 8


# ---------------------------------------------------------------------------
# Scenario 1 + AE7: Complete lifepath run, no LLM, all rolls logged.
# ---------------------------------------------------------------------------


class TestCompleteLifepath:
    def test_complete_lifepath_two_terms(self, pack, ruleset):
        """Full lifepath: characteristics -> qualification -> 2 terms -> mustering out.

        All rolls go through the funnel and appear in the event log (R9, AE7).
        """
        queue = [
            # Characteristics (6 x 2D6)
            [6, 3],  # STR = 9
            [4, 3],  # DEX = 7
            [5, 3],  # END = 8
            [5, 4],  # INT = 9
            [4, 3],  # EDU = 7
            [4, 2],  # SOC = 6
            # Qualification (INT 9 -> DM +1, target 6)
            [5, 4],  # 9 + 1 = 10 >= 6 -> success
            # Term 1: survival, commission (fails) -> NO advancement at rank 0 (B1),
            # 1 skill roll (hierarchy base).
            [4, 3],  # Survival: INT 9 + DM 1 = 8 >= 5 -> success
            [1, 2],  # Commission: SOC 6 + DM 0 = 3 < 7 -> fail (rank stays 0)
            [5],  # Skill (Personal Dev): 5 -> +1 EDU
            # Term 2: commission available again (rank 0), succeeds; advancement
            # at rank 1 succeeds -> rank 2; 3 skill rolls (1 + comm + adv).
            [3, 3],  # Survival: 6 + 1 = 7 >= 5 -> success
            [4, 4],  # Commission: SOC 6 + DM 0 = 8 >= 7 -> rank 1
            [4, 4],  # Advancement: EDU 8 + DM 0 = 8 >= 6 -> rank 2
            [5],  # Skill (Personal Dev): 5 -> +1 EDU
            [4],  # Skill (Service): 4 -> gunnery_turrets
            [4],  # Skill (Specialist): 4 -> astrogation
            # Mustering out (2 terms, rank 2)
            # Cash: DM = 0, 2 rolls
            [1],  # 1 -> 1,000 Cr
            [1],  # 1 -> 1,000 Cr
            # Material: 2 rolls, DM = 0
            [3],  # 3 -> Weapon
            [5],  # 5 -> +1 SOC
        ]
        engine = make_engine(queue)
        runner = LifepathRunner(engine, pack, ruleset)
        result = runner.run_lifepath("navy", num_terms=2)

        # Characteristics rolled.
        assert result.characteristics == {
            "STR": 9,
            "DEX": 7,
            "END": 8,
            "INT": 9,
            "EDU": 7,
            "SOC": 6,
        }

        # Qualification succeeded.
        assert result.qualification is not None
        assert result.qualification.success
        assert result.qualification.career_id == "navy"

        # Two terms completed.
        assert result.num_terms == 2
        term1 = result.terms[0]
        assert term1.survival_success
        assert not term1.advancement_success  # B1: no advancement at rank 0
        assert term1.rank_after == 0
        assert len(term1.skill_gains) == 1  # hierarchy base only (no comm/adv bonus)
        term2 = result.terms[1]
        assert term2.advancement_success  # rank 1 -> 2
        assert term2.rank_after == 2
        assert len(term2.skill_gains) == 3  # base + commission + advancement

        # Character alive, skills gained.
        assert result.character_alive
        char = engine.state.character
        assert char.alive
        assert char.terms == 2
        assert char.age == 26  # 18 + 2*4
        assert char.rank == 2
        assert "gunnery_turrets" in char.skills
        # EDU went from 7 -> 8 (term 1) -> 9 (term 2)
        assert char.characteristics["EDU"] == 9

        # Mustering out completed (Task 12: benefit_rolls_for(2,2)=2 total,
        # batch allocates cash-first → 2 cash, 0 material).
        assert result.mustering_out is not None
        assert len(result.mustering_out.cash_benefits) == 2
        assert len(result.mustering_out.material_benefits) == 0

        # All rolls logged via the funnel (R9, AE7).
        rolls = audit_rolls(engine.state.events)
        # 6 chars + 1 qual + (1 surv + 1 comm + 1 skill) term 1
        # + (1 surv + 1 comm + 1 adv + 3 skill) term 2 + 2 cash
        assert len(rolls) == 6 + 1 + 3 + 6 + 2

    def test_all_events_are_audited(self, pack):
        """Every lifepath roll appears in the audit log with full inputs (AE1)."""
        queue = [
            [5, 3],
            [4, 3],
            [5, 3],
            [5, 4],
            [4, 3],
            [4, 2],  # chars (INT = 9)
            [5, 4],  # qualification: INT 9 + DM 1 = 10 >= 6 -> success
            [4, 3],  # survival: INT 9 + DM 1 = 8 >= 5 -> success
            [1, 2],  # commission: SOC 6 + DM 0 = 3 < 7 -> fail (B1: no advancement at rank 0)
            [5],  # skill 1 (1D6) — hierarchy base only
            # mustering out (1 term, rank 0): benefit_rolls_for(1,0)=1, cash-first
            [1],  # cash
        ]
        engine = make_engine(queue)
        runner = LifepathRunner(engine, pack)
        runner.run_lifepath("navy", num_terms=1)

        for event in audit_rolls(engine.state.events):
            assert event.kind == EventKind.ROLL
            assert event.roll is not None
            assert event.roll.stream == "lifepath"
            assert event.roll.ndice >= 1
            assert event.roll.sides == 6


# ---------------------------------------------------------------------------
# Scenario 2: AE2 Ironman death in chargen.
# ---------------------------------------------------------------------------


class TestIronmanDeath:
    def test_failed_survival_kills_character_ironman(self, pack):
        """Ironman mode: failed survival -> alive=False, lifepath ends (AE2)."""
        queue = [
            [5, 3],
            [4, 3],
            [5, 3],
            [5, 4],
            [4, 3],
            [4, 2],  # chars (INT = 9)
            [5, 4],  # qualification: INT 9 + DM 1 = 10 >= 6 -> success
            [1, 1],  # survival: INT 9 + DM 1 = 3 < 5 -> DEATH
        ]
        engine = make_engine(queue, death_mode="ironman")
        runner = LifepathRunner(engine, pack)
        result = runner.run_lifepath("navy", num_terms=3)

        assert not result.character_alive
        assert not engine.state.character.alive
        assert len(result.terms) == 1
        assert result.terms[0].died
        assert result.mustering_out is None  # dead characters don't muster out


# ---------------------------------------------------------------------------
# Scenario 3: AE2 Non-Ironman mishap.
# ---------------------------------------------------------------------------


class TestNonIronmanMishap:
    def test_failed_survival_mishap_narrative_mode(self, pack):
        """Narrative mode: failed survival -> mishap, mustering out proceeds (AE2)."""
        queue = [
            [5, 3],
            [4, 3],
            [5, 3],
            [5, 4],
            [4, 3],
            [4, 2],  # chars (INT = 9)
            [5, 4],  # qualification: INT 9 + DM 1 = 10 >= 6 -> success
            [1, 1],  # survival: INT 9 + DM 1 = 3 < 5 -> mishap
            [2],  # mishap roll (1D6): 2 -> honorably discharged (no injury)
            # Mustering out (1 term, rank 0)
            # Cash: DM = 0, 1 roll
            [3],  # 3 -> 10,000 Cr
            # Material: 1 roll, DM = 0
            [2],  # 2 -> Mid Passage
        ]
        engine = make_engine(queue, death_mode="narrative")
        runner = LifepathRunner(engine, pack)
        result = runner.run_lifepath("navy", num_terms=3)

        assert result.character_alive
        assert engine.state.character.alive
        assert len(result.terms) == 1
        assert result.terms[0].mishap
        assert not result.terms[0].died
        # Mishap ends career but mustering out happens.
        assert result.mustering_out is not None

    def test_failed_survival_mishap_checkpoint_mode(self, pack):
        """Checkpoint mode behaves like narrative for mishap (AE2)."""
        queue = [
            [5, 3],
            [4, 3],
            [5, 3],
            [5, 4],
            [4, 3],
            [4, 2],
            [5, 4],  # qual: INT 9 + DM 1 = 10 >= 6 -> success
            [1, 2],  # survival: INT 9 + DM 1 = 4 < 5 -> mishap
            [2],  # mishap roll (1D6): 2 -> honorably discharged (no injury)
            # Mustering out (1 term, rank 0)
            [3],  # cash: 3 -> 10,000 Cr
            [2],  # material: Mid Passage
        ]
        engine = make_engine(queue, death_mode="checkpoint")
        runner = LifepathRunner(engine, pack)
        result = runner.run_lifepath("navy", num_terms=2)

        assert result.character_alive
        assert result.terms[0].mishap


# ---------------------------------------------------------------------------
# Scenario 5: Qualification failure — player chooses retry / draft / drifter.
# ---------------------------------------------------------------------------


class TestQualificationFailure:
    """Task 10 — qualification failure offers three explicit fallback paths.

    The old silent auto-drifter fallback was removed from ``run_lifepath``;
    batch callers must pass an explicit ``fallback_choice`` ("draft" |
    "drifter" | career_id). When omitted, the failed qualification stands and
    the lifepath ends with zero terms (mustering out) — no silent career
    switch.
    """

    def test_qualification_failure_no_fallback_ends_with_zero_terms(self, pack):
        """Without a fallback_choice, a failed qualification ends the lifepath.

        The qualification result is recorded as a failure; the runner does not
        silently switch careers.
        """
        queue = [
            [2, 1],  # STR = 3
            [2, 1],  # DEX = 3
            [2, 1],  # END = 3
            [2, 1],  # INT = 3 -> DM -1
            [2, 1],  # EDU = 3
            [2, 1],  # SOC = 3
            # Navy qualification: INT 3, DM -1, target 6 -> 3 + (-1) = 2 < 6 fail
            [2, 1],
        ]
        engine = make_engine(queue)
        runner = LifepathRunner(engine, pack)
        result = runner.run_lifepath("navy", num_terms=1)

        assert result.qualification is not None
        assert result.qualification.career_id == "navy"
        assert not result.qualification.success
        assert result.career_id == "navy"
        assert len(result.terms) == 0
        # No career was assigned (qualification failed, no fallback).
        assert engine.state.character.career == ""

    def test_qualification_failure_fallback_drifter_explicit(self, pack):
        """fallback_choice="drifter" qualifies drifter explicitly (F2)."""
        queue = [
            [2, 1],
            [2, 1],
            [2, 1],
            [2, 1],
            [2, 1],
            [2, 1],
            # Navy qualification fail.
            [2, 1],
            # Drifter auto-qualifies (always_open, P3.T8b) — no roll consumed.
            # Term 1 (drifter, non-hierarchy -> 2 skill rolls)
            [4, 3],  # Survival: END 3 + DM -1 = 6 >= 6 -> success
            [5],
            [5],
            # Mustering out (1 term)
            [1],
            [1],
        ]
        engine = make_engine(queue)
        runner = LifepathRunner(engine, pack)
        result = runner.run_lifepath("navy", num_terms=1, fallback_choice="drifter")

        # Final qualification is the drifter result (the explicit fallback).
        assert result.qualification.career_id == "drifter"
        assert result.qualification.success
        assert result.career_id == "drifter"
        assert len(result.terms) == 1

    def test_qualification_failure_fallback_draft(self, pack):
        """fallback_choice="draft" applies DraftCommand (1D6 -> pack table).

        Uses a draft roll of 5 -> pack.draft_table[4] (scout, non-hierarchy)
        so the term queue needs only survival + 2 skill rolls.
        """
        queue = [
            [2, 1],
            [2, 1],
            [2, 1],
            [2, 1],
            [2, 1],
            [2, 1],
            # Navy qualification fail.
            [2, 1],
            # Draft roll: 1D6 = 5 -> pack.draft_table[4] (scout)
            [5],
            # Term 1 (scout is non-hierarchy -> 2 skill rolls, no commission).
            [4, 3],  # Survival: INT 3 + DM -1 = 6 >= 6 -> success
            [5],  # Skill 1 (1D6)
            [5],  # Skill 2 (1D6)
            # Mustering out (1 term, rank 0).
            [1],  # cash
            [1],  # material
        ]
        engine = make_engine(queue)
        runner = LifepathRunner(engine, pack)
        result = runner.run_lifepath("navy", num_terms=1, fallback_choice="draft")

        assert result.career_id == pack.draft_table[4]
        assert engine.state.character.drafted is True
        assert len(result.terms) == 1

    def test_qualification_failure_fallback_career_id(self, pack):
        """fallback_choice=<career_id> attempts qualification for that career."""
        queue = [
            [2, 1],
            [2, 1],
            [2, 1],
            [2, 1],
            [2, 1],
            [2, 1],
            # Navy qualification fail.
            [2, 1],
            # Agent qualification: INT 3 + DM -1 = 2 < 6 -> fail again
            [2, 1],
            # With no further fallback the lifepath ends with zero terms.
        ]
        engine = make_engine(queue)
        runner = LifepathRunner(engine, pack)
        # fallback to agent, which will also fail with these rolls.
        result = runner.run_lifepath("navy", num_terms=1, fallback_choice="agent")

        assert not result.qualification.success
        assert result.qualification.career_id == "agent"
        assert len(result.terms) == 0


class TestDraftCommand:
    """Task 10 — DraftCommand (B16) and run_draft runner method."""

    def test_draft_assigns_career_and_marks_drafted(self, engine_and_pack):
        """DraftCommand sets career + drafted; run_draft returns the career id."""
        engine, pack = engine_and_pack
        engine._roller = ForcedRoller([[2]])
        runner = LifepathRunner(engine, pack)
        career_id = runner.run_draft()
        assert career_id == pack.draft_table[1]
        assert engine.state.character.career == career_id
        assert engine.state.character.drafted is True

    def test_draft_only_once(self, engine_and_pack):
        """A character with drafted=True cannot be drafted again."""
        engine, pack = engine_and_pack
        engine.state.character.drafted = True
        runner = LifepathRunner(engine, pack)
        with pytest.raises(ValueError, match="once"):
            runner.run_draft()

    def test_draft_command_validates_six_careers(self, engine_and_pack):
        """DraftCommand rejects a draft table without exactly 6 entries."""
        engine, _pack = engine_and_pack
        with pytest.raises(ValueError, match="6"):
            engine.apply(DraftCommand(careers=["navy", "army", "marines"]))

    def test_draft_command_event_recorded(self, engine_and_pack):
        """DraftCommand produces an audited event with the career and roll."""
        engine, pack = engine_and_pack
        engine._roller = ForcedRoller([[4]])
        runner = LifepathRunner(engine, pack)
        career_id = runner.run_draft()
        # The last event is the draft.
        last = engine.state.events[-1]
        assert last.command_type == "lifepath_draft"
        assert last.changes["career_id"] == career_id
        assert last.changes["roll_total"] == 4
        assert last.roll is not None
        assert last.roll.stream == "lifepath"


class TestQualificationExtraDM:
    """Task 10 — QualificationCommand.extra_dm (career-change DM hook)."""

    def test_qualification_extra_dm_applies(self, engine_and_pack):
        """extra_dm is added to the characteristic DM in resolve."""
        engine, _pack = engine_and_pack
        engine.state.character.characteristics = {"INT": 7}  # DM 0
        engine._roller = ForcedRoller([[3, 4]])  # 7 + 0 - 2 = 5
        event = engine.apply(
            QualificationCommand(
                career_id="navy",
                characteristic="INT",
                target=5,
                extra_dm=-2,
            )
        )
        assert event.changes["adjusted_total"] == 5
        assert event.changes["success"] is True

    def test_qualification_extra_dm_default_zero(self, engine_and_pack):
        """extra_dm defaults to 0 — unchanged behaviour when omitted."""
        engine, _pack = engine_and_pack
        engine.state.character.characteristics = {"INT": 7}  # DM 0
        engine._roller = ForcedRoller([[3, 4]])  # 7 + 0 = 7
        event = engine.apply(QualificationCommand(career_id="navy", characteristic="INT", target=5))
        assert event.changes["adjusted_total"] == 7
        assert event.changes["char_dm"] == 0


# ---------------------------------------------------------------------------
# Scenario 6b: Career change + EndCareerCommand (B17, Task 11).
# ---------------------------------------------------------------------------


class TestCareerChange:
    """Task 11 — EndCareerCommand records history; qualify honours B17."""

    def test_end_career_records_history(self, engine_and_pack):
        engine, _pack = engine_and_pack
        engine.state.character.career = "navy"
        engine.state.character.terms = 2
        engine.state.character.rank = 3
        engine.apply(EndCareerCommand(ended_by="mishap"))
        assert engine.state.character.career == ""
        assert engine.state.character.rank == 0
        # terms (total) is intentionally NOT reset.
        assert engine.state.character.terms == 2
        record = engine.state.character.career_history[-1]
        assert (record.career_id, record.terms, record.final_rank, record.ended_by) == (
            "navy",
            2,
            3,
            "mishap",
        )

    def test_end_career_rejects_no_active_career(self, engine_and_pack):
        import pytest

        engine, _pack = engine_and_pack
        with pytest.raises(ValueError, match="none is active"):
            engine.apply(EndCareerCommand(ended_by="muster_out"))

    def test_career_change_dm_scales_with_previous_careers(self, engine_and_pack):
        engine, pack = engine_and_pack
        engine.state.character.career_history = [
            CareerTermRecord(career_id="navy", terms=2, final_rank=0, ended_by="muster_out")
        ]
        runner = LifepathRunner(engine, pack)
        assert runner.career_change_dm() == -2

    def test_career_change_dm_zero_for_first_career(self, engine_and_pack):
        engine, pack = engine_and_pack
        runner = LifepathRunner(engine, pack)
        assert runner.career_change_dm() == 0

    def test_cannot_return_to_left_career_except_drifter(self, engine_and_pack):
        import pytest

        engine, pack = engine_and_pack
        engine.state.character.career_history = [
            CareerTermRecord(career_id="navy", terms=1, final_rank=0, ended_by="mishap")
        ]
        runner = LifepathRunner(engine, pack)
        with pytest.raises(ValueError, match="already left"):
            runner.qualify("navy")
        # Drifter is always re-enterable, even with history.
        engine._roller = ForcedRoller([[5, 2]])
        runner.qualify("drifter")

    def test_always_open_qualification_produces_audit_event(self, engine_and_pack):
        """always_open careers must route through Engine.apply (Key Invariant #1).

        A direct GameState field write bypasses the funnel — no Event is
        appended, no sequence number assigned — breaking audit/replay. The
        Drifter auto-qualification must still go through the funnel.
        """
        engine, pack = engine_and_pack
        runner = LifepathRunner(engine, pack)
        events_before = len(engine.state.events)
        result = runner.qualify("drifter")
        # Career set on the character.
        assert result.success
        assert engine.state.character.career == "drifter"
        # An Event was appended through the funnel (audit/replay guarantee).
        assert len(engine.state.events) == events_before + 1
        enter_event = engine.state.events[-1]
        assert enter_event.changes["career_id"] == "drifter"

    def test_qualify_applies_career_change_dm(self, engine_and_pack):
        """With one prior career, qualification gets an extra -2 DM."""
        engine, pack = engine_and_pack
        engine.state.character.career_history = [
            CareerTermRecord(career_id="navy", terms=1, final_rank=0, ended_by="muster_out")
        ]
        engine.state.character.characteristics = {"INT": 7}  # DM 0
        engine._roller = ForcedRoller([[5, 2]])  # 7 + 0 - 2 = 5
        runner = LifepathRunner(engine, pack)
        result = runner.qualify("agent")  # agent not in history
        assert result.adjusted_total == 5
        assert result.char_dm == -2


# ---------------------------------------------------------------------------
# Scenario 6: Aging effects at age 34+.
# ---------------------------------------------------------------------------


class TestAging:
    def test_aging_graduated_physical_reduction(self, pack):
        """At age 34+, adjusted roll in the reduction zone produces physical
        slots that the batch runner distributes to STR/DEX/END.

        B4 graduated table: roll 2 at term 4 -> adjusted -2 -> three
        physical x1 slots. Batch auto-assigns one each to the three
        physical characteristics (all tied at 8, picked in STR/DEX/END order).
        """
        queue = [
            [5, 3],  # STR = 8
            [5, 3],  # DEX = 8
            [5, 3],  # END = 8
            [2, 1],  # INT = 3
            [2, 1],  # EDU = 3
            [4, 2],  # SOC = 6
            # Drifter auto-qualifies (always_open, P3.T8b) — no roll consumed.
        ]
        # Terms 1-3 (ages 18->30): survival, 2 skill rolls each (non-hierarchy, B9).
        # No aging checks (age < 34).
        for _term in range(3):
            queue.extend(
                [
                    [4, 3],  # Survival: END 8 + DM 0 = 7 >= 6 -> success
                    [5],  # Skill 1 (1D6)
                    [5],  # Skill 2 (1D6) — non-hierarchy base 2 (B9)
                ]
            )
        # Term 4 (age 30->34): survival, skills, THEN aging.
        queue.extend(
            [
                [4, 3],  # Survival
                [5],  # Skill 1 (1D6)
                [5],  # Skill 2 (1D6) — non-hierarchy base 2 (B9)
                # Aging: 2D6=2, terms=4, adjusted=2-4=-2 -> three physical x1
                [1, 1],
            ]
        )
        # Mustering out (4 terms, rank 0 since drifter has no ranks)
        queue.extend(
            [
                [1],
                [1],
                [1],  # Cash: 3 rolls
                [1],
                [1],
                [1],
                [1],  # Material: 4 rolls
            ]
        )
        engine = make_engine(queue)
        runner = LifepathRunner(engine, pack)
        result = runner.run_lifepath("drifter", num_terms=4)

        assert result.num_terms == 4
        term4 = result.terms[3]
        assert term4.age_after == 34
        assert not term4.aging_success
        # Three physical x1 slots -> aggregated as {"physical": 3} for narration.
        assert term4.aging_reductions == {"physical": 3}

        # Batch auto-applied one point each to STR, DEX, END (all tied at 8).
        char = engine.state.character
        assert char.characteristics["STR"] == 7  # 8 - 1
        assert char.characteristics["DEX"] == 7
        assert char.characteristics["END"] == 7
        # Pending slots fully consumed by the batch runner.
        assert char.pending_aging == []

    def test_aging_success_no_reduction(self, pack):
        """Adjusted roll >= 1 produces no pending aging slots."""
        queue = [
            [5, 3],
            [5, 3],
            [5, 3],
            [2, 1],
            [2, 1],
            [4, 2],
            # Drifter auto-qualifies (always_open, P3.T8b) — no roll consumed.
        ]
        for _term in range(3):
            queue.extend([[4, 3], [5], [5]])
        queue.extend(
            [
                [4, 3],
                [5],
                [5],
                # Aging: 2D6=9, terms=4, adjusted=9-4=5 >= 1 -> no effect
                [5, 4],
            ]
        )
        queue.extend(
            [
                [1],
                [1],
                [1],
                [1],
                [1],
                [1],
                [1],
            ]
        )
        engine = make_engine(queue)
        runner = LifepathRunner(engine, pack)
        result = runner.run_lifepath("drifter", num_terms=4)

        term4 = result.terms[3]
        assert term4.aging_success
        assert term4.aging_reductions == {}
        # Stats unchanged.
        char = engine.state.character
        assert char.characteristics["STR"] == 8
        assert char.pending_aging == []


# ---------------------------------------------------------------------------
# Scenario 6b: Graduated aging table (B4) — terms as negative DM, player-chosen
# reductions via ApplyAgingReductionCommand.
# ---------------------------------------------------------------------------


class TestGraduatedAging:
    def test_aging_uses_terms_as_negative_dm_and_graduated_table(self, engine_and_pack):
        """Adjusted roll = 2D6 - terms; -1 row yields two physical slots of 1."""
        engine, pack = engine_and_pack
        engine.state.character.terms = 5
        engine.state.character.age = 42
        engine._roller = ForcedRoller([[2, 2]])  # 4 - 5 = -1 -> two physical slots of 1
        runner = LifepathRunner(engine, pack)
        assert (
            runner.run_aging_step(
                TermResult(
                    term_number=5,
                    career_id="navy",
                    career_name="Navy",
                    age_before=38,
                    age_after=42,
                )
            )
            is True
        )
        slots = engine.state.character.pending_aging
        assert [(s.group, s.points) for s in slots] == [("physical", 1), ("physical", 1)]

    def test_aging_no_effect_at_1_plus(self, engine_and_pack):
        """Adjusted roll >= 1 means no aging effect."""
        engine, pack = engine_and_pack
        engine.state.character.terms = 2
        engine._roller = ForcedRoller([[2, 1]])  # 3 - 2 = 1 -> no effect
        runner = LifepathRunner(engine, pack)
        runner.run_aging_step(
            TermResult(
                term_number=2,
                career_id="navy",
                career_name="Navy",
                age_before=26,
                age_after=30,
            )
        )
        assert engine.state.character.pending_aging == []

    def test_apply_aging_reduction_consumes_slots(self, engine_and_pack):
        """ApplyAgingReductionCommand reduces a stat and consumes matching slots."""
        from src.engine.lifepath import ApplyAgingReductionCommand

        engine, _pack = engine_and_pack
        engine.state.character.characteristics = {"STR": 8, "INT": 9}
        engine.state.character.pending_aging = [AgingSlot(group="physical", points=2)]
        engine.apply(ApplyAgingReductionCommand(characteristic="STR", points=2))
        assert engine.state.character.characteristics["STR"] == 6
        assert engine.state.character.pending_aging == []
        with pytest.raises(ValueError):
            engine.apply(ApplyAgingReductionCommand(characteristic="INT", points=1))

    def test_aging_reduction_group_enforced(self, engine_and_pack):
        """A mental characteristic cannot consume a physical slot."""
        from src.engine.lifepath import ApplyAgingReductionCommand

        engine, _pack = engine_and_pack
        engine.state.character.characteristics = {"INT": 9}
        engine.state.character.pending_aging = [AgingSlot(group="physical", points=1)]
        with pytest.raises(ValueError, match="physical"):
            engine.apply(ApplyAgingReductionCommand(characteristic="INT", points=1))


# ---------------------------------------------------------------------------
# Scenario 7: Mustering out benefits computed from career and rank.
# ---------------------------------------------------------------------------


class TestMusteringOut:
    def test_cash_benefits_neutralized_dm(self, pack):
        """Cash benefit rolls use dm=0 (per-term/per-rank DM removed, N3).

        Rank-based rolls and row-7 reachability will be handled in Task 12.
        """
        queue = [
            [5, 3],
            [4, 3],
            [5, 3],
            [5, 4],
            [4, 3],
            [4, 2],  # chars (INT = 9)
            [5, 4],  # qual: INT 9 + DM 1 = 10 >= 6 -> success
        ]
        # Term 1: survival, commission (fails, rank 0) -> NO advancement (B1), 1 skill roll.
        queue.extend(
            [
                [4, 3],  # survival: INT 9 + DM 1 = 8 >= 5 -> success
                [1, 2],  # commission: SOC 6 + DM 0 = 3 < 7 -> fail (rank stays 0)
                [5],  # skill 1 (1D6) — hierarchy base only
            ]
        )
        # Term 2: commission (rank 0, succeeds), advancement (rank 1, succeeds) -> rank 2.
        queue.extend(
            [
                [4, 3],  # survival
                [5, 4],  # commission: SOC 6 + DM 0 = 9 >= 7 -> rank 1
                [5, 3],  # advancement: EDU 7 + DM 0 = 8 >= 6 -> rank 2
                [5],  # skill 1 (1D6)
                [5],  # skill 2 (commission bonus, 1D6)
                [5],  # skill 3 (advancement bonus, 1D6)
            ]
        )
        # Mustering out: 2 terms, rank 2.
        # benefit_rolls_for(2, 2) = 2 total. Batch: cash-first (min(3,2)=2),
        # then material (0 remaining). DM = 0.
        queue.extend(
            [
                [1],  # 1 -> "1,000 Cr" (SRD Navy cash row 1)
                [2],  # 2 -> "5,000 Cr"
            ]
        )
        engine = make_engine(queue)
        runner = LifepathRunner(engine, pack)
        result = runner.run_lifepath("navy", num_terms=2)

        mo = result.mustering_out
        assert mo is not None
        assert mo.terms_served == 2
        assert mo.final_rank == 2
        assert mo.total_rolls == 2
        assert len(mo.cash_benefits) == 2
        assert "1,000 Cr" in mo.cash_benefits
        assert "5,000 Cr" in mo.cash_benefits
        assert len(mo.material_benefits) == 0

    def test_zero_terms_mustering_out(self, pack):
        """Character with 0 terms gets no benefit rolls."""
        engine = make_engine([])
        runner = LifepathRunner(engine, pack)
        # Directly call muster_out on a character with 0 terms.
        mo = runner.muster_out("navy")
        assert mo.total_rolls == 0
        assert mo.cash_benefits == []
        assert mo.material_benefits == []


# ---------------------------------------------------------------------------
# Task 12: Muster-out overhaul — rank bonuses, per-roll allocation, persist.
# ---------------------------------------------------------------------------


class TestMusterOutOverhaul:
    """Task 12: benefit_rolls_for rank bonus, persist to credits/inventory,
    cash cap, material_dm_for rank DM."""

    def test_benefit_rolls_include_rank_bonus(self):
        from src.engine.lifepath import benefit_rolls_for

        assert benefit_rolls_for(terms=3, rank=0) == 3
        assert benefit_rolls_for(terms=3, rank=4) == 4
        assert benefit_rolls_for(terms=3, rank=5) == 5
        assert benefit_rolls_for(terms=3, rank=6) == 6

    def test_material_dm_for_rank(self):
        from src.engine.lifepath import material_dm_for

        assert material_dm_for(0) == 0
        assert material_dm_for(4) == 0
        assert material_dm_for(5) == 1
        assert material_dm_for(6) == 1

    def test_cash_benefit_persists_to_credits(self, engine_and_pack):
        engine, pack = engine_and_pack
        engine.state.character.career = "navy"
        engine._roller = ForcedRoller([[6]])  # top cash row = 50,000 Cr
        runner = LifepathRunner(engine, pack)
        runner.claim_benefit("navy", table="cash", dm=0)
        assert engine.state.character.credits == 50_000

    def test_material_benefit_persists_to_inventory(self, engine_and_pack):
        engine, pack = engine_and_pack
        engine._roller = ForcedRoller([[6]])
        runner = LifepathRunner(engine, pack)
        runner.claim_benefit("navy", table="material", dm=1)  # 6+1=7 -> row 7
        assert len(engine.state.character.inventory) == 1

    def test_cash_rolls_capped_at_three(self, engine_and_pack):
        engine, pack = engine_and_pack
        engine.state.character.career = "navy"
        engine._roller = ForcedRoller([[1]])
        runner = LifepathRunner(engine, pack)
        runner._cash_rolls_taken = 3
        with pytest.raises(ValueError, match="cash"):
            runner.claim_benefit("navy", table="cash", dm=0)

    def test_muster_out_returns_plan_without_rolling(self, engine_and_pack):
        """muster_out computes total_rolls and DMs without rolling dice."""
        engine, pack = engine_and_pack
        engine.state.character.career = "navy"
        engine.state.character.terms = 3
        engine.state.character.rank = 5  # rank bonus: +2
        runner = LifepathRunner(engine, pack)
        plan = runner.muster_out("navy")
        assert plan.total_rolls == 5  # 3 terms + 2 rank bonus
        assert plan.cash_dm == 0
        assert plan.material_dm == 1  # rank >= 5
        assert plan.terms_served == 3
        assert plan.final_rank == 5
        # No rolls consumed — lists empty.
        assert plan.cash_benefits == []
        assert plan.material_benefits == []

    def test_muster_out_reads_final_rank_after_end_career(self, engine_and_pack):
        """B2: rank-based muster bonuses survive EndCareerCommand (P1.T4).

        EndCareerCommand resets character.rank to 0; the plan must read the
        CareerTermRecord's final_rank so O4+ bonus rolls and the O5+ material
        DM apply on every muster path.
        """
        from src.engine.lifepath import EndCareerCommand

        engine, pack = engine_and_pack
        engine.state.character.career = "navy"
        engine.state.character.terms = 3
        engine.state.character.rank = 5
        engine.apply(EndCareerCommand(ended_by="muster_out"))
        assert engine.state.character.rank == 0  # reset by EndCareerCommand
        runner = LifepathRunner(engine, pack)
        plan = runner.muster_out()  # career + rank both resolved from history
        assert plan.final_rank == 5
        assert plan.total_rolls == 5  # benefit_rolls_for(3, 5) = 3 + 2
        assert plan.material_dm == 1  # rank >= 5

    def test_muster_out_uses_live_rank_while_career_active(self, engine_and_pack):
        """A plan computed before EndCareer (TUI player-chosen path) agrees."""
        engine, pack = engine_and_pack
        engine.state.character.career = "navy"
        engine.state.character.terms = 3
        engine.state.character.rank = 5
        runner = LifepathRunner(engine, pack)
        plan = runner.muster_out("navy")
        assert plan.final_rank == 5
        assert plan.total_rolls == 5
        assert plan.material_dm == 1

    def test_batch_muster_out_allocates_cash_first(self, pack):
        """Batch path allocates cash-first (up to 3), then material."""
        queue = [
            [5, 3],
            [4, 3],
            [5, 3],
            [5, 4],
            [4, 3],
            [4, 2],  # chars (INT = 9)
            [5, 4],  # qual
            [4, 3],  # survival
            [1, 2],  # commission fail (B1: no advancement at rank 0)
            [5],  # skill 1 (1D6) — hierarchy base only
        ]
        # 1 term, rank 0: benefit_rolls_for(1, 0) = 1 total, 1 cash, 0 material.
        queue.append([3])  # cash: 10,000 Cr
        engine = make_engine(queue)
        runner = LifepathRunner(engine, pack)
        result = runner.run_lifepath("navy", num_terms=1)
        mo = result.mustering_out
        assert mo is not None
        assert mo.total_rolls == 1
        assert len(mo.cash_benefits) == 1
        assert mo.cash_benefits[0] == "10,000 Cr"
        assert len(mo.material_benefits) == 0
        assert engine.state.character.credits == 10_000


# ---------------------------------------------------------------------------
# Scenario: Career with no ranks (Scout/Drifter).
# ---------------------------------------------------------------------------


class TestNoRanksCareer:
    def test_scout_advancement_no_rank_increase(self, pack):
        """Scout is non-hierarchy: 2 skill rolls, no advancement/commission, rank stays 0."""
        queue = [
            [5, 3],
            [4, 3],
            [5, 3],
            [5, 4],
            [4, 3],
            [4, 2],  # chars (INT = 9)
            # Scout qualification: INT 9, DM +1, target 6
            [4, 3],  # 7 + 1 = 8 >= 6 -> success
            # Term 1: survival (INT 6+), no commission/advancement (non-hierarchy),
            # 2 skill rolls (non-hierarchy base 2, B9).
            [4, 3],  # Survival: INT 9 + DM 1 = 8 >= 6 -> success
            [5],  # Skill 1 (1D6)
            [4],  # Skill 2 (1D6)
            # Mustering out (1 term, rank 0)
            [1],  # cash
            [1],  # material
        ]
        engine = make_engine(queue)
        runner = LifepathRunner(engine, pack)
        result = runner.run_lifepath("scout", num_terms=1)

        term1 = result.terms[0]
        assert not term1.advancement_success  # no advancement for non-hierarchy
        assert not term1.commission_success  # no commission for non-hierarchy
        assert term1.rank_after == 0  # no ranks -> stays 0
        assert engine.state.character.rank == 0
        # Non-hierarchy careers grant 2 skill rolls per term (B9).
        assert len(term1.skill_gains) == 2


# ---------------------------------------------------------------------------
# Scenario: Determinism — same seed + same queue = same result.
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_queue_produces_identical_state(self, pack):
        """Two runners with the same ForcedRoller queue produce identical state."""
        queue = [
            [5, 3],
            [4, 3],
            [5, 3],
            [5, 4],
            [4, 3],
            [4, 2],
            [5, 4],  # qual: INT 9 + DM 1 = 10 >= 6 -> success
            [4, 3],  # survival
            [1, 2],  # commission fail (B1: no advancement at rank 0)
            [5],  # skill 1 (1D6) — hierarchy base only
            [3],  # cash — benefit_rolls_for(1,0)=1
        ]
        engine_a = make_engine(list(queue))
        engine_b = make_engine(list(queue))
        runner_a = LifepathRunner(engine_a, pack)
        runner_b = LifepathRunner(engine_b, pack)

        runner_a.run_lifepath("navy", num_terms=1)
        runner_b.run_lifepath("navy", num_terms=1)

        assert engine_a.state.model_dump_json() == engine_b.state.model_dump_json()


# ---------------------------------------------------------------------------
# AdvanceTermCommand — funnel-routed age/terms advancement (Fix #2C).
# ---------------------------------------------------------------------------


class TestAdvanceTermCommand:
    """Age and terms advance through the command funnel (Fix #2C)."""

    def test_advance_term_bumps_age_and_terms(self):
        """AdvanceTermCommand increments age by 4 and terms by 1."""
        state = GameState.new(seed=99)
        state.character.age = 22
        state.character.terms = 1
        engine = Engine(state, roller=ForcedRoller([]))

        event = engine.apply(AdvanceTermCommand())

        assert state.character.age == 26
        assert state.character.terms == 2
        assert event.command_type == "lifepath_advance_term"
        assert event.changes["age_before"] == 22
        assert event.changes["age_after"] == 26
        assert event.changes["terms_before"] == 1
        assert event.changes["terms_after"] == 2

    def test_advance_term_produces_audit_event(self):
        """The term advancement is recorded in the event log."""
        state = GameState.new(seed=99)
        state.character.age = 18
        state.character.terms = 0
        engine = Engine(state, roller=ForcedRoller([]))
        initial_events = len(state.events)

        engine.apply(AdvanceTermCommand())

        assert len(state.events) == initial_events + 1
        event = state.events[-1]
        assert event.kind == EventKind.STATE_CHANGE
        assert "age 18 -> 22" in event.description
        assert "terms 0 -> 1" in event.description

    def test_run_term_uses_funnel_for_advancement(self, pack):
        """run_term routes age/terms advancement through the funnel."""
        # Set up a character that has already qualified for navy.
        state = GameState.new(seed=42)
        state.campaign = CampaignConfig(death_mode="narrative")
        state.character.characteristics = {
            "STR": 7,
            "DEX": 9,
            "END": 8,
            "INT": 8,
            "EDU": 10,
            "SOC": 5,
        }
        state.character.career = "navy"
        # Queue: survival roll (low roll -> mishap, returns early after advance),
        # plus a mishap roll (1D6=2 -> honorably discharged, no injury chain).
        queue = [[1, 1], [2]]  # END 8 -> DM 1, roll 2+1=3 < 5 -> mishap
        engine = Engine(state, roller=ForcedRoller(queue))
        runner = LifepathRunner(engine, pack)

        initial_events = len(engine.state.events)
        runner.run_term("navy", term_number=1)

        # The advance_term event should be in the log.
        advance_events = [
            e
            for e in engine.state.events[initial_events:]
            if e.command_type == "lifepath_advance_term"
        ]
        assert len(advance_events) == 1
        assert engine.state.character.age == 22  # 18 + 4
        assert engine.state.character.terms == 1


# ---------------------------------------------------------------------------
# Task 5: Natural-2 survival fail, mishap → injury chain, injury crisis (B13/N1).
# ---------------------------------------------------------------------------


class TestNatural2SurvivalFail:
    """N1: a natural 2 on the survival roll always fails, regardless of DM."""

    def test_natural_2_always_fails_survival(self, engine_and_pack):
        engine, _pack = engine_and_pack
        engine.state.character.characteristics = {"END": 15}  # +3 DM
        engine._roller = ForcedRoller([[1, 1]])
        event = engine.apply(SurvivalCommand(career_id="navy", characteristic="END", target=5))
        # Raw 2 + DM 3 = 5 >= 5, but natural 2 always fails.
        assert event.changes["success"] is False
        assert event.changes["mishap"] is True  # narrative mode


class TestMishapInjuryChain:
    """Failed-non-ironman survival rolls the career mishap table; entries 1
    and 6 chain to the pack injury table (B13)."""

    def test_mishap_injury_chain_applies_reduction(self, engine_and_pack):
        engine, pack = engine_and_pack
        engine.state.character.characteristics = {"STR": 10, "DEX": 9, "END": 8}
        engine.state.character.career = "navy"
        # mishap roll lands on an injury entry; injury roll then reduces chosen stat
        engine._roller = ForcedRoller([[1], [2]])  # mishap=1 -> injury; injury=2
        runner = LifepathRunner(engine, pack)
        outcome = runner.run_mishap("navy")
        assert outcome["injury"] is True
        assert sum(engine.state.character.characteristics.values()) < 27


class TestInjuryCrisis:
    """Characteristic at 0 triggers an injury crisis (B13)."""

    def test_injury_crisis_pay_or_suffer(self, engine_and_pack):
        engine, _pack = engine_and_pack
        engine.state.character.characteristics = {"STR": 1}
        engine.state.character.credits = 12000
        engine.apply(ResolveInjuryCrisisCommand(stat="STR", pay=True))
        assert engine.state.character.credits == 2000
        assert engine.state.character.characteristics["STR"] == 1
        assert engine.state.character.alive is True

    def test_injury_crisis_unaffordable_non_ironman(self, engine_and_pack):
        engine, _pack = engine_and_pack
        engine.state.character.characteristics = {"STR": 0}
        engine.state.character.credits = 0
        engine.apply(ResolveInjuryCrisisCommand(stat="STR", pay=False))
        assert engine.state.character.alive is True  # narrative mode: floored + scar
        assert engine.state.character.characteristics["STR"] == 1
        assert any(isinstance(e, Injury) for e in engine.state.entities)


# ---------------------------------------------------------------------------
# RULE-1: fantasy rank-5+ material muster-out crash.
# The fantasy material tables are 1D6 (6 rows, range 1-6) but
# material_dm_for(rank >= 5) = +1, so a max material roll becomes 7 and
# lookup_table_result raises IndexError ("Roll 7 outside table range [1..6]").
# The sci-fi pack has a 7th row for the rank-5+ reward; the fantasy pack
# (Task 15 structural alignment) missed it.
# ---------------------------------------------------------------------------


class TestFantasyMusterRow7:
    """Fantasy material tables must cover the rank-5+ row (RULE-1)."""

    def test_fantasy_material_benefit_at_rank5_max_roll_does_not_crash(self):
        """A rank-5+ fantasy character claiming a material benefit with the
        +1 DM, rolling a 6 (total 7), must resolve to a 7th-row result —
        not raise IndexError.
        """
        from src.themepacks.fantasy import load_fantasy_pack

        pack = load_fantasy_pack()
        engine = make_engine([[6]])  # material roll: 1D6 = 6, +1 DM -> 7
        runner = LifepathRunner(engine, pack)
        # Pick any fantasy career that has a material table.
        career_id = next(iter(pack.careers))
        engine.state.character.career = career_id
        engine.state.character.rank = 5  # >= 5 -> material_dm +1
        engine.state.character.terms = 1

        result = runner.claim_benefit(career_id, "material", dm=1)
        assert isinstance(result, str)
        assert result  # non-empty

    def test_every_fantasy_career_material_table_covers_row_7(self):
        """Structural invariant: every fantasy material table must have a
        row covering roll 7 (the rank-5+ reward via +1 DM), matching the
        sci-fi pack's 7-row tables. A missing row is the RULE-1 crash.
        """
        from src.themepacks.fantasy import load_fantasy_pack

        pack = load_fantasy_pack()
        missing = []
        for cid, career in pack.careers.items():
            mat = career.mustering_out_material
            if mat is None:
                continue
            max_range = max(e.max for e in mat.entries.entries)
            if max_range < 7:
                missing.append((cid, max_range))
        assert not missing, f"fantasy material tables missing row 7: {missing}"


class TestGamblingCashDM:
    """G2: Gambling skill or retirement grants +1 DM on cash benefit rolls (P3.T3)."""

    def test_gambling_grants_cash_dm(self, pack, ruleset):
        engine = make_engine([])
        engine.state.character.skills["gambler"] = 1
        engine.state.character.terms = 2
        engine.state.character.career = "navy"
        runner = LifepathRunner(engine, pack, ruleset)
        result = runner.muster_out("navy")
        assert result.cash_dm == 1

    def test_retirement_grants_cash_dm(self, pack, ruleset):
        engine = make_engine([])
        engine.state.character.terms = 7
        engine.state.character.career = "navy"
        runner = LifepathRunner(engine, pack, ruleset)
        result = runner.muster_out("navy")
        assert result.cash_dm == 1

    def test_no_gambling_no_retirement_zero_dm(self, pack, ruleset):
        engine = make_engine([])
        engine.state.character.terms = 2
        engine.state.character.career = "navy"
        runner = LifepathRunner(engine, pack, ruleset)
        result = runner.muster_out("navy")
        assert result.cash_dm == 0


class TestMishapConsequences:
    """G3: mishap effects (debt, lose_benefits) apply mechanically (P3.T5)."""

    def test_mishap_debt_applies(self, pack):
        from src.engine.lifepath import MishapRollCommand
        from src.rulesets.base import SkillTableEntry

        engine = make_engine([])
        entries = [
            SkillTableEntry(min=1, max=1, result="Injured in action."),
            SkillTableEntry(min=2, max=2, result="Honorably discharged."),
            SkillTableEntry(
                min=3,
                max=3,
                result="Debt of Cr10,000.",
                effects=[{"type": "debt", "amount": 10000}],
            ),
            SkillTableEntry(min=4, max=6, result="Other."),
        ]
        engine._roller = ForcedRoller([[3]])
        event = engine.apply(MishapRollCommand(career_id="navy", entries=entries))
        assert engine.state.character.debt_cr == 10000
        assert "debt:10000" in event.changes.get("effects_applied", [])

    def test_mishap_lose_benefits_zeroes_muster(self, pack):
        from src.engine.lifepath import MishapRollCommand
        from src.rulesets.base import SkillTableEntry

        engine = make_engine([])
        engine.state.character.career = "navy"
        engine.state.character.terms = 3
        entries = [
            SkillTableEntry(
                min=4,
                max=4,
                result="Dishonorably discharged. Lose all benefits.",
                effects=[{"type": "lose_benefits"}],
            ),
        ]
        engine._roller = ForcedRoller([[4]])
        engine.apply(MishapRollCommand(career_id="navy", entries=entries))
        assert engine.state.character.benefits_lost is True
        runner = LifepathRunner(engine, pack)
        result = runner.muster_out("navy")
        assert result.total_rolls == 0


class TestDuplicateBenefits:
    """G5: duplicate material benefits handled per pack rules (P3.T7)."""

    def test_weapon_duplicate_grants_skill(self, pack):
        """Second 'Weapon' result grants a weapon skill level (P3.T7)."""
        from src.engine.lifepath import BenefitRollCommand
        from src.rulesets.base import SkillTableEntry

        engine = make_engine([])
        weapon_entry = SkillTableEntry(
            min=3,
            max=3,
            result="Weapon",
            on_duplicate="skill:gun_combat",
        )
        # First weapon → inventory
        engine._roller = ForcedRoller([[3]])
        engine.apply(BenefitRollCommand(benefit_type="material", entries=[weapon_entry]))
        assert "Weapon" in engine.state.character.inventory

        # Second weapon → gun_combat skill, not a second inventory item
        engine._roller = ForcedRoller([[3]])
        engine.apply(BenefitRollCommand(benefit_type="material", entries=[weapon_entry]))
        assert engine.state.character.inventory.count("Weapon") == 1
        assert engine.state.character.skills.get("gun_combat", 0) >= 1

    def test_once_only_benefit_rerolls_if_already_owned(self, pack):
        """Explorers' Society (once=True) rerolls if already in inventory (P3.T7)."""
        from src.engine.lifepath import BenefitRollCommand
        from src.rulesets.base import SkillTableEntry

        engine = make_engine([])
        engine.state.character.inventory.append("Explorers' Society")
        engine._roller = ForcedRoller([[6], [2]])  # 6→already have→reroll→2
        engine.apply(
            BenefitRollCommand(
                benefit_type="material",
                entries=[
                    SkillTableEntry(min=1, max=2, result="+1 EDU"),
                    SkillTableEntry(min=6, max=6, result="Explorers' Society", once=True),
                ],
            )
        )
        assert engine.state.character.inventory.count("Explorers' Society") == 1

    def test_reroll_preserves_material_dm(self, pack):
        """A rank-5+ character's material DM applies to the reroll too (SRD).

        The reroll is still a roll on the material benefits table, so the rank
        DM (``self.dm``) should carry through — not be silently dropped to 0.
        """
        from src.engine.lifepath import BenefitRollCommand
        from src.rulesets.base import SkillTableEntry

        engine = make_engine([])
        engine.state.character.inventory.append("Explorers' Society")
        # dm=1 (rank 5+): first roll 5+1=6 -> once-only dup -> reroll;
        # reroll 1+1=2 -> "Item B". With modifiers=0 the reroll totals 1
        # and lands on "Item A" instead — the bug this test guards against.
        engine._roller = ForcedRoller([[5], [1]])
        event = engine.apply(
            BenefitRollCommand(
                benefit_type="material",
                dm=1,
                entries=[
                    SkillTableEntry(min=1, max=1, result="Item A"),
                    SkillTableEntry(min=2, max=2, result="Item B"),
                    SkillTableEntry(min=6, max=6, result="Explorers' Society", once=True),
                ],
            )
        )
        assert event.roll.modifiers == 1
        assert "Item B" in engine.state.character.inventory
        assert "Item A" not in engine.state.character.inventory


class TestAgingCrisisCostRoll:
    """C2: aging crisis cost is 1D6 x 10,000 rolled on the lifepath stream (SRD)."""

    def test_roll_records_multiplier(self, pack):
        from src.engine.lifepath import RollAgingCrisisCostCommand

        engine, _ = setup_qualified_engine([[4]], pack)
        event = engine.apply(RollAgingCrisisCostCommand())
        assert event.changes["crisis_multiplier"] == 4
        assert engine.state.character.credits == 0  # no state mutation
        assert event.roll is not None and sum(event.roll.rolls) == 4

    def test_crisis_cost_command_parameterizes_payment(self, pack):
        """P3.8a's planned test, wired end-to-end (C2)."""
        from src.engine.lifepath import ResolveInjuryCrisisCommand, RollAgingCrisisCostCommand

        engine, _ = setup_qualified_engine([[4]], pack)
        state = engine.state
        state.character.credits = 100_000
        state.character.characteristics["STR"] = 0
        event = engine.apply(RollAgingCrisisCostCommand())  # consumes the [4]
        cost = event.changes["crisis_multiplier"] * 10_000
        resolved = engine.apply(
            ResolveInjuryCrisisCommand(stat="STR", pay=True, crisis_cost_cr=cost)
        )
        assert state.character.credits == 60_000
        assert resolved.changes["outcome"] == "paid_cr40000"

    def test_batch_aging_crisis_rolls_cost(self, pack):
        """Batch aging crisis pays 1D6 x 10k via the funnel (C2)."""
        engine, runner = setup_qualified_engine([[2]], pack)  # cost roll = 2 -> 20k
        state = engine.state
        state.character.credits = 100_000
        state.character.characteristics["END"] = 0
        outcome = runner.auto_resolve_crisis("END", crisis_kind="aging")
        assert outcome == "paid_cr20000"
        assert state.character.credits == 80_000
        kinds = [e.command_type for e in state.events]
        assert "lifepath_aging_crisis_cost" in kinds

    def test_injury_crisis_consumes_no_cost_roll(self, pack):
        """Injury crisis stays flat 10k and never touches the cost roll (C2)."""
        engine, runner = setup_qualified_engine([], pack)
        state = engine.state
        state.character.credits = 50_000
        state.character.characteristics["STR"] = 0
        outcome = runner.auto_resolve_crisis("STR", crisis_kind="injury")
        assert outcome == "paid_cr10000"
        assert state.character.credits == 40_000
        assert "lifepath_aging_crisis_cost" not in [e.command_type for e in state.events]
