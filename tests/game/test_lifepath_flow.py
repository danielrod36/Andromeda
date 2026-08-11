"""Tests for LifepathController — headless phase determination (U5).

KTD-3 parity: the same flag-reading logic the TUI uses must work headlessly
so saves round-trip across shells.
"""

from __future__ import annotations

from src.engine.commands import Engine, SetFlagCommand
from src.engine.dice import ForcedRoller
from src.engine.lifepath import TermResult
from src.engine.state import AgingSlot, CampaignConfig, CareerTermRecord, GameState
from src.game.lifepath import LifepathController
from src.themepacks.cepheus_scifi import load_scifi_pack


def _make_engine(seed: int = 42) -> Engine:
    state = GameState.new(seed=seed)
    state.campaign = CampaignConfig(resolution_profile="classic")
    state.character.name = "TestHero"
    return Engine(state)


class TestPhaseDetermination:
    """U5: headless phase determination matches the TUI's flag-reading logic."""

    def test_fresh_state_starts_at_roll_characteristics(self):
        """A character with no characteristics starts at roll_characteristics."""
        engine = _make_engine()
        pack = load_scifi_pack()
        controller = LifepathController(engine, pack)
        assert controller.determine_phase() == "roll_characteristics"

    def test_term_phase_flag_read_from_narrative_log(self):
        """The term_phase= flag is read byte-identically to the TUI (KTD-3).

        The controller must be constructed AFTER the flag is in place so the
        U2 reconstruction runs against the persisted state (same lifecycle as
        a web session resume).
        """
        engine = _make_engine()
        engine.state.character.career = "navy"
        engine.state.character.characteristics = {
            "STR": 7,
            "DEX": 8,
            "END": 6,
            "INT": 10,
            "EDU": 9,
            "SOC": 5,
        }
        engine.state.character.alive = True
        engine.apply(SetFlagCommand(key="term_phase", value="re_enlist"))
        controller = LifepathController(engine, load_scifi_pack())
        phase = controller.determine_phase()
        assert phase == "re_enlist"

    def test_mustered_out_flag_leads_to_complete(self):
        """mustered_out=true in narrative_log → phase is 'complete'."""
        engine = _make_engine()
        pack = load_scifi_pack()
        controller = LifepathController(engine, pack)

        engine.state.character.career = "navy"
        engine.state.character.characteristics = {
            "STR": 7,
            "DEX": 8,
            "END": 6,
            "INT": 10,
            "EDU": 9,
            "SOC": 5,
        }
        engine.state.character.alive = True
        engine.apply(SetFlagCommand(key="mustered_out", value="true"))
        assert controller.determine_phase() == "complete"

    def test_dead_character_is_complete(self):
        """A dead character (ironman) is in the complete phase."""
        engine = _make_engine()
        pack = load_scifi_pack()
        controller = LifepathController(engine, pack)

        engine.state.character.career = "navy"
        engine.state.character.characteristics = {
            "STR": 7,
            "DEX": 8,
            "END": 6,
            "INT": 10,
            "EDU": 9,
            "SOC": 5,
        }
        engine.state.character.alive = False
        assert controller.determine_phase() == "complete"

    def test_get_latest_term_phase_returns_most_recent(self):
        """The most recent term_phase flag wins (KTD-3 parity)."""
        engine = _make_engine()

        engine.apply(SetFlagCommand(key="term_phase", value="run_survival"))
        engine.apply(SetFlagCommand(key="term_phase", value="choose_skills"))

        result = LifepathController.get_latest_term_phase(engine.state)
        assert result == "choose_skills"

    def test_get_latest_term_phase_returns_none_when_absent(self):
        """No term_phase flag in the log returns None."""
        engine = _make_engine()
        result = LifepathController.get_latest_term_phase(engine.state)
        assert result is None

    def test_choose_aging_reduction_advances_when_pending_empty(self):
        """choose_aging_reduction auto-advances to re_enlist when pending_aging is empty.

        Parity with the TUI (lines 327-329): all aging slots consumed → re_enlist.
        """
        engine = _make_engine()
        pack = load_scifi_pack()
        controller = LifepathController(engine, pack)

        engine.state.character.career = "navy"
        engine.state.character.characteristics = {
            "STR": 7,
            "DEX": 8,
            "END": 6,
            "INT": 10,
            "EDU": 9,
            "SOC": 5,
        }
        engine.state.character.alive = True
        engine.apply(SetFlagCommand(key="term_phase", value="choose_aging_reduction"))
        # pending_aging defaults to empty list.
        assert controller.determine_phase() == "re_enlist"

    def test_choose_aging_reduction_stays_when_pending_present(self):
        """choose_aging_reduction stays when pending_aging still has slots."""
        from src.engine.state import AgingSlot

        engine = _make_engine()
        pack = load_scifi_pack()
        controller = LifepathController(engine, pack)

        engine.state.character.career = "navy"
        engine.state.character.characteristics = {
            "STR": 7,
            "DEX": 8,
            "END": 6,
            "INT": 10,
            "EDU": 9,
            "SOC": 5,
        }
        engine.state.character.alive = True
        engine.apply(SetFlagCommand(key="term_phase", value="choose_aging_reduction"))
        engine.state.character.pending_aging = [AgingSlot(group="physical", points=1)]
        assert controller.determine_phase() == "choose_aging_reduction"


class TestPhaseView:
    """U5: PhaseView assembly."""

    def test_get_phase_view_returns_current_phase(self):
        """get_phase_view returns a PhaseView for the current phase."""
        engine = _make_engine()
        controller = LifepathController(engine, load_scifi_pack())
        view = controller.get_phase_view()
        assert view.phase == "roll_characteristics"
        assert len(view.prompt) > 0


def _make_mid_lifepath_engine(seed: int = 42) -> Engine:
    """Engine with characteristics, background skills, and career set.

    After this, ``determine_phase`` returns ``run_survival``.
    """
    engine = _make_engine(seed=seed)
    char = engine.state.character
    char.characteristics = {
        "STR": 7,
        "DEX": 8,
        "END": 6,
        "INT": 10,
        "EDU": 9,
        "SOC": 5,
    }
    char.career = "navy"
    char.alive = True
    char.background_picks_remaining = 0
    return engine


class TestTermLoop:
    """U7: the term sub-phase machine runs survival → advancement → re-enlist."""

    def test_get_phase_view_for_run_survival_is_read_only(self):
        """get_phase_view() for run_survival must NOT execute mutations (U7)."""
        engine = _make_mid_lifepath_engine()
        controller = LifepathController(engine, load_scifi_pack())
        view = controller.get_phase_view()
        assert view.phase == "run_survival"
        assert "Begin Term" in view.choices[0].label
        # No term_phase flag should have been set just by viewing.
        assert controller.get_latest_term_phase(engine.state) is None

    def test_begin_term_runs_survival_then_advances(self):
        """U2: begin_term starts the interactive term flow (not _auto_advance).

        Survival runs immediately; commission/advancement/skills are now
        separate interactive clicks. The view should show survival receipt
        and land on the next sub-phase (choose_commission for navy).
        """
        engine = _make_mid_lifepath_engine()
        controller = LifepathController(engine, load_scifi_pack())
        view = controller.apply_choice("begin_term")
        # Survival ran — receipt present.
        assert any("Survival" in r for r in view.receipts)
        assert controller._current_term_result is not None
        # Navy is a hierarchy career with commission → lands on choose_commission.
        assert view.phase == "choose_commission"
        # No advancement yet — that's a separate click now.
        event_types = [e.command_type for e in engine.state.events]
        assert "lifepath_advancement" not in event_types

    def test_re_enlist_view_not_overridden_by_term_phases_fallback(self):
        """get_phase_view() for re_enlist returns choices, not a generic prompt."""
        engine = _make_mid_lifepath_engine()
        controller = LifepathController(engine, load_scifi_pack())
        # Fast-forward to re_enlist by setting the flag.
        engine.apply(SetFlagCommand(key="term_phase", value="re_enlist"))
        view = controller.get_phase_view()
        assert view.phase == "re_enlist"
        option_ids = [c.option_id for c in view.choices]
        assert "reenlist_continue" in option_ids
        assert "reenlist_muster" in option_ids

    def test_reenlist_continue_starts_new_term(self):
        """Choosing re-enlist transitions back to run_survival."""
        engine = _make_mid_lifepath_engine()
        controller = LifepathController(engine, load_scifi_pack())
        engine.apply(SetFlagCommand(key="term_phase", value="re_enlist"))
        controller.apply_choice("reenlist_continue")
        assert controller.determine_phase() == "run_survival"

    def test_reenlist_muster_transitions_to_mustering_out(self):
        """Choosing muster out transitions to muster_out_allocate (U3 interactive).

        With terms > 0 the character has benefit rolls; the mustering_out
        phase computes the plan and advances to muster_out_allocate.
        """
        engine = _make_mid_lifepath_engine()
        controller = LifepathController(engine, load_scifi_pack())
        # Give the character a term so benefit_rolls_for > 0.
        engine.state.character.terms = 1
        engine.apply(SetFlagCommand(key="term_phase", value="re_enlist"))
        controller.apply_choice("reenlist_muster")
        assert controller.determine_phase() == "muster_out_allocate"


class TestBackgroundSkillMutation:
    """U7: background skill picks go through Engine.apply, not direct writes."""

    def test_bg_skill_choice_uses_engine_funnel(self):
        """Picking a background skill applies GainSkillCommand via the funnel."""
        engine = _make_engine()
        char = engine.state.character
        char.characteristics = {
            "STR": 7,
            "DEX": 8,
            "END": 6,
            "INT": 10,
            "EDU": 9,
            "SOC": 5,
        }
        char.background_picks_remaining = -1  # uninitialized sentinel
        controller = LifepathController(engine, load_scifi_pack())
        # Pick a skill that exists in the scifi pack's background list.
        pack = load_scifi_pack()
        skill = pack.background_skills[0]
        controller.apply_choice(f"bg_skill:{skill}")
        # Skill should be at level 0 in character's skills.
        assert char.skills.get(skill) == 0
        # background_picks_remaining should be > 0 (decremented from 3 + EDU DM).
        assert char.background_picks_remaining > 0
        # Events should prove it went through the funnel (not a direct write).
        event_types = [e.command_type for e in engine.state.events]
        assert "lifepath_gain_skill" in event_types
        assert "lifepath_decrement_background_picks" in event_types


class TestAdvancementOfferGate:
    """B1/B5: the controller offers advancement only at ranks 1-5 (P1.T2/T3)."""

    def test_advancement_not_offered_at_rank_0(self):
        engine = _make_mid_lifepath_engine()
        engine._roller = ForcedRoller([[4, 3]])  # survival: INT 10 + DM 1 = 8 >= 5
        controller = LifepathController(engine, load_scifi_pack())
        view = controller.apply_choice("begin_term")
        assert view.phase == "choose_commission"
        view = controller.apply_choice("commission_decline")
        assert view.phase == "choose_skills"  # NOT choose_advancement (B1)

    def test_advancement_offered_after_successful_commission(self):
        engine = _make_mid_lifepath_engine()
        engine._roller = ForcedRoller([[4, 3], [5, 5]])  # survival, commission 10-1=9 >= 7
        controller = LifepathController(engine, load_scifi_pack())
        controller.apply_choice("begin_term")
        view = controller.apply_choice("commission_attempt")
        assert engine.state.character.rank == 1
        assert view.phase == "choose_advancement"

    def test_advancement_not_offered_at_rank_6(self):
        engine = _make_mid_lifepath_engine()
        engine.state.character.rank = 6
        engine._roller = ForcedRoller([[4, 3]])  # survival pass
        controller = LifepathController(engine, load_scifi_pack())
        view = controller.apply_choice("begin_term")
        assert view.phase == "choose_skills"  # no advancement at the cap (B5)


class TestLaterCareerBasicTraining:
    """B3/P1.T7: entering a second career offers one Service skill at 0."""

    def _make_career_change_engine(self) -> Engine:
        engine = _make_mid_lifepath_engine()
        char = engine.state.character
        char.career = ""  # first career ended; choosing a new one
        char.career_history = [
            CareerTermRecord(career_id="army", terms=2, final_rank=1, ended_by="muster_out")
        ]
        char.basic_training_done = True
        char.terms = 2
        engine.apply(SetFlagCommand(key="term_phase", value="choose_career"))
        return engine

    def test_second_career_offers_service_skill_choice(self):
        engine = self._make_career_change_engine()
        engine._roller = ForcedRoller([[6, 6]])  # navy qual: 12 + (1 - 2) = 11 >= 6
        controller = LifepathController(engine, load_scifi_pack())
        view = controller.apply_choice("career:navy")
        assert view.phase == "choose_basic_training_skill"
        option_ids = [c.option_id for c in view.choices]
        # Flat Service skills appear directly.
        assert "bt_skill:engineer" in option_ids
        # C4: cascade skills appear as cascade options (player picks a spec).
        assert "bt_skill:cascade:electronics" in option_ids

    def test_basic_training_choice_grants_skill_and_starts_term(self):
        engine = self._make_career_change_engine()
        engine._roller = ForcedRoller([[6, 6]])
        controller = LifepathController(engine, load_scifi_pack())
        controller.apply_choice("career:navy")
        view = controller.apply_choice("bt_skill:engineer")
        assert engine.state.character.skills.get("engineer") == 0
        assert engine.state.character.skills.get("electronics_comms") is None
        assert view.phase == "run_survival"


class TestIronmanCrisisChoice:
    """P1.T8: interactive ironman offers crisis_pay like other modes."""

    def _make_ironman_crisis_engine(self) -> Engine:
        engine = _make_mid_lifepath_engine()
        state = engine.state
        state.campaign.death_mode = "ironman"
        state.character.characteristics = {
            "STR": 4,
            "DEX": 9,
            "END": 6,
            "INT": 8,
            "EDU": 10,
            "SOC": 5,
        }
        state.character.credits = 15_000
        engine.apply(SetFlagCommand(key="term_phase", value="choose_injury_stat"))
        return engine

    def _prime_term(self, controller: LifepathController) -> None:
        controller._current_term_result = TermResult(
            term_number=1, career_id="navy", career_name="Navy", age_before=18, age_after=22
        )

    def test_ironman_injury_crisis_offers_pay(self):
        engine = self._make_ironman_crisis_engine()
        engine._roller = ForcedRoller([[1], [5, 5]])  # injury -6 PHYSICAL; reenlist
        controller = LifepathController(engine, load_scifi_pack())
        self._prime_term(controller)
        view = controller.apply_choice("injury_stat:STR")  # STR 4 -> 0 crisis
        assert view.phase == "choose_crisis_resolution"  # NOT auto-death (P1.T8)
        assert engine.state.character.alive is True
        assert {c.option_id for c in view.choices} == {"crisis_pay", "crisis_scar"}

        controller.apply_choice("crisis_pay")
        char = engine.state.character
        assert char.alive is True
        assert char.credits == 5_000
        assert char.characteristics["STR"] == 1

    def test_ironman_injury_crisis_decline_is_death(self):
        engine = self._make_ironman_crisis_engine()
        engine._roller = ForcedRoller([[1]])
        controller = LifepathController(engine, load_scifi_pack())
        self._prime_term(controller)
        controller.apply_choice("injury_stat:STR")
        controller.apply_choice("crisis_scar")  # decline payment -> ironman death
        assert engine.state.character.alive is False

    def test_ironman_aging_crisis_offers_pay(self):
        engine = _make_mid_lifepath_engine()
        state = engine.state
        state.campaign.death_mode = "ironman"
        state.character.credits = 15_000
        state.character.pending_aging = [AgingSlot(group="physical", points=7)]
        engine.apply(SetFlagCommand(key="term_phase", value="choose_aging_reduction"))
        controller = LifepathController(engine, load_scifi_pack())
        self._prime_term(controller)
        controller._aging_active = True
        view = controller.apply_choice("aging_stat:STR")  # STR 7 - 7 = 0 crisis
        assert view.phase == "choose_crisis_resolution"
        assert engine.state.character.alive is True


class TestPendingCrisisCost:
    """C2 — aging crisis cost roll surfaces in the interactive flow (C-A5)."""

    def test_scan_order(self):
        """Cost found only when set after the crisis term_phase flag (C-A5)."""
        from src.game.lifepath import get_pending_crisis_cost

        engine = _make_engine(seed=42)
        state = engine.state
        assert get_pending_crisis_cost(state) is None
        engine.apply(SetFlagCommand(key="crisis_cost", value="40000"))
        assert get_pending_crisis_cost(state) == 40000
        # A newer crisis term_phase buries the stale cost (injury path -> None):
        engine.apply(SetFlagCommand(key="term_phase", value="choose_crisis_resolution"))
        assert get_pending_crisis_cost(state) is None
        # Aging path sets term_phase first, then cost -> found:
        engine.apply(SetFlagCommand(key="crisis_cost", value="20000"))
        assert get_pending_crisis_cost(state) == 20000

    def test_aging_crisis_rolls_cost_and_charges_it(self):
        """Interactive aging crisis: 1D6 cost rolled, previewed, charged (C2)."""
        engine = _make_mid_lifepath_engine()
        state = engine.state
        state.character.credits = 50_000
        state.character.pending_aging = [AgingSlot(group="physical", points=7)]
        engine.apply(SetFlagCommand(key="term_phase", value="choose_aging_reduction"))
        engine._roller = ForcedRoller([[4], [5, 5]])  # cost roll 4 -> 40k; reenlist
        controller = LifepathController(engine, load_scifi_pack())
        controller._current_term_result = TermResult(
            term_number=1, career_id="navy", career_name="Navy", age_before=30, age_after=34
        )
        controller._aging_active = True

        view = controller.apply_choice("aging_stat:STR")  # STR 7 - 7 = 0 crisis
        assert view.phase == "choose_crisis_resolution"
        kinds = [e.command_type for e in state.events]
        assert "lifepath_aging_crisis_cost" in kinds
        pay = next(c for c in view.choices if c.option_id == "crisis_pay")
        assert "40,000" in pay.label
        assert pay.dimmed is False  # 50k affords 40k

        controller.apply_choice("crisis_pay")
        assert state.character.credits == 10_000  # charged 40k, not 10k
        assert state.character.characteristics["STR"] == 1
        assert state.character.alive is True

    def test_injury_crisis_stays_flat_10k(self):
        """Injury path: no cost roll consumed, flat Cr10,000 (C2)."""
        engine = _make_mid_lifepath_engine()
        state = engine.state
        state.character.characteristics["STR"] = 4
        state.character.credits = 15_000
        engine.apply(SetFlagCommand(key="term_phase", value="choose_injury_stat"))
        engine._roller = ForcedRoller([[1], [5, 5]])  # injury -6 PHYSICAL; reenlist
        controller = LifepathController(engine, load_scifi_pack())
        controller._current_term_result = TermResult(
            term_number=1, career_id="navy", career_name="Navy", age_before=18, age_after=22
        )
        view = controller.apply_choice("injury_stat:STR")
        assert view.phase == "choose_crisis_resolution"
        assert "lifepath_aging_crisis_cost" not in [e.command_type for e in state.events]
        pay = next(c for c in view.choices if c.option_id == "crisis_pay")
        assert "10,000" in pay.label
        controller.apply_choice("crisis_pay")
        assert state.character.credits == 5_000


# ---------------------------------------------------------------------------
# C3 — cascade specialization phase (controller routing).
# ---------------------------------------------------------------------------


def _cascade_pack():
    """Minimal synthetic pack: one career, one declared cascade (C3)."""
    from src.themepacks.base import validate_pack

    return validate_pack(
        {
            "pack": {"id": "casc", "name": "CascadeTest", "description": "t"},
            "careers": {
                "navy": {
                    "id": "navy",
                    "name": "Navy",
                    "description": "t",
                    "qualification": {"characteristic": "INT", "target": 5},
                    "survival": {"characteristic": "END", "target": 5},
                    "has_hierarchy": False,
                    "skill_tables": [
                        {
                            "name": "Service Skills",
                            "entries": {
                                "num_dice": 1,
                                "die_size": 6,
                                "entries": [
                                    {"min": 1, "max": 3, "result": "mechanic"},
                                    {"min": 4, "max": 6, "result": "cascade:gun_combat"},
                                ],
                            },
                        },
                    ],
                    "ranks": [],
                }
            },
            "skills": {
                "mechanic": {"id": "mechanic", "name": "Mechanic"},
                "gun_combat_slug_rifle": {
                    "id": "gun_combat_slug_rifle",
                    "name": "Gun Combat (Slug Rifle)",
                },
                "gun_combat_slug_pistol": {
                    "id": "gun_combat_slug_pistol",
                    "name": "Gun Combat (Slug Pistol)",
                },
                "gun_combat_energy_rifle": {
                    "id": "gun_combat_energy_rifle",
                    "name": "Gun Combat (Energy Rifle)",
                },
            },
            "cascades": {
                "gun_combat": {
                    "id": "gun_combat",
                    "name": "Gun Combat",
                    "specializations": [
                        "gun_combat_slug_rifle",
                        "gun_combat_slug_pistol",
                        "gun_combat_energy_rifle",
                    ],
                }
            },
            "oracle_tables": {},
            "complication_tables": {},
            "mission_tables": {},
        }
    )


def _make_cascade_controller():
    """Mid-lifepath controller on the synthetic cascade pack (C3)."""
    pack = _cascade_pack()
    engine = _make_engine(seed=42)
    char = engine.state.character
    char.characteristics = {"STR": 7, "DEX": 8, "END": 6, "INT": 10, "EDU": 9, "SOC": 5}
    char.career = "navy"
    char.background_picks_remaining = 0
    return engine, LifepathController(engine, pack)


class TestCascadePhase:
    """C3: pending cascade interrupts the phase machine (C-A3)."""

    def test_pending_cascade_surfaces_choice_and_applies(self):
        from src.engine.lifepath import SkillTableRollCommand
        from src.rulesets.base import SkillTableEntry

        engine, controller = _make_cascade_controller()
        assert controller.determine_phase() == "run_survival"  # baseline
        engine.apply(
            SkillTableRollCommand(
                table_name="Service Skills",
                entries=[SkillTableEntry(min=1, max=6, result="cascade:gun_combat")],
            )
        )
        assert controller.determine_phase() == "choose_specialization"
        view = controller.get_phase_view()
        ids = {c.option_id for c in view.choices}
        assert "spec:gun_combat_slug_rifle" in ids
        assert "spec:gun_combat_slug_pistol" in ids

        controller.apply_choice("spec:gun_combat_slug_pistol")
        assert engine.state.character.skills["gun_combat_slug_pistol"] == 1
        assert engine.state.character.pending_cascades == []
        assert controller.determine_phase() == "run_survival"

    def test_restore_mid_cascade_byte_identical(self):
        """serialize/validate with a pending cascade: same phase, same bytes (C3)."""
        import json as _json

        from src.engine.state import GameState, PendingCascade

        engine, controller = _make_cascade_controller()
        engine.state.character.pending_cascades.append(
            PendingCascade(parent="gun_combat", grant_mode="set_zero")
        )
        blob = engine.state.model_dump_json()
        restored = GameState.model_validate(_json.loads(blob))
        controller2 = LifepathController(Engine(restored), _cascade_pack())
        assert restored.model_dump_json() == blob
        assert controller2.determine_phase() == "choose_specialization"
        # Same choice on both engines yields identical skill state:
        for ctrl in (controller, controller2):
            ctrl.apply_choice("spec:gun_combat_slug_rifle")
        assert engine.state.character.skills == controller2._engine.state.character.skills


class TestPerCareerMusterFlow:
    """C6 — G4: muster phases run at every career exit (C-A6)."""

    def test_mishap_ejection_musters_before_career_change(self):
        """Mishap exit: muster THIS career's benefits, then offer career change."""
        engine = _make_mid_lifepath_engine()
        state = engine.state
        state.character.terms = 1
        # survival fail [2,1]=3+1 <5 -> narrative mishap; mishap row 2 (no injury);
        # benefit cash roll [1].
        engine._roller = ForcedRoller([[2, 1], [2], [1]])
        controller = LifepathController(engine, load_scifi_pack())
        view = controller.apply_choice("begin_term")
        assert view.phase == "mishap_roll"
        view = controller.apply_choice("roll_mishap")
        # C6: mishap exit musters first — NOT straight to career change.
        assert controller.determine_phase() == "muster_out_allocate"
        view = controller.apply_choice("claim_cash")
        # Rolls exhausted -> career change offered (terms < 7).
        assert controller.determine_phase() == "choose_career_change"
        assert state.character.mustered_careers == ["navy"]
        assert state.character.career_history[-1].terms_in_career == 1
        assert "mustered_out=true" not in state.narrative_log

    def test_voluntary_muster_offers_career_change(self):
        """reenlist_muster no longer ends chargen (C6)."""
        engine = _make_mid_lifepath_engine()
        state = engine.state
        state.character.terms = 1
        engine._roller = ForcedRoller([[1]])  # the single cash claim
        engine.apply(SetFlagCommand(key="term_phase", value="re_enlist"))
        controller = LifepathController(engine, load_scifi_pack())
        controller.apply_choice("reenlist_muster")
        assert controller.determine_phase() == "muster_out_allocate"
        controller.apply_choice("claim_cash")
        assert controller.determine_phase() == "choose_career_change"
        assert "mustered_out=true" not in state.narrative_log

    def test_retirement_is_terminal(self):
        """7-term character musters then completes — no career change (C-A6)."""
        engine = _make_mid_lifepath_engine()
        state = engine.state
        state.character.terms = 7
        # 7 benefit rolls; cash cap allows 3 cash, rest material: queue 7 pips.
        engine._roller = ForcedRoller([[1], [1], [1], [1], [1], [1], [1]])
        engine.apply(SetFlagCommand(key="term_phase", value="re_enlist"))
        controller = LifepathController(engine, load_scifi_pack())
        controller.apply_choice("reenlist_muster")
        assert controller.determine_phase() == "muster_out_allocate"
        for choice in (
            "claim_cash",
            "claim_cash",
            "claim_cash",
            "claim_material",
            "claim_material",
            "claim_material",
            "claim_material",
        ):
            controller.apply_choice(choice)
        assert controller.determine_phase() == "complete"
        assert "mustered_out=true" in state.narrative_log
        assert state.character.mustered_careers == ["navy"]

    def test_career_change_finish_ends_chargen(self):
        """career_change_finish sets the terminal flag (C6)."""
        engine = _make_mid_lifepath_engine()
        engine.state.character.terms = 1
        engine.apply(SetFlagCommand(key="term_phase", value="choose_career_change"))
        engine.state.character.career = ""  # career already ended
        controller = LifepathController(engine, load_scifi_pack())
        assert controller.determine_phase() == "choose_career_change"
        controller.apply_choice("career_change_finish")
        assert "mustered_out=true" in engine.state.narrative_log
        assert controller.determine_phase() == "complete"

    def test_cash_cap_is_lifetime_across_musters(self):
        """3 cash claims in muster #1 dim cash in muster #2 (C-A6)."""
        from src.engine.lifepath import BenefitRollCommand

        engine = _make_mid_lifepath_engine()
        state = engine.state
        pack = load_scifi_pack()
        navy = pack.careers["navy"]
        # Three lifetime cash claims from a previous muster:
        engine._roller = ForcedRoller([[1], [1], [1]])
        for _ in range(3):
            engine.apply(
                BenefitRollCommand(
                    benefit_type="cash", entries=navy.mustering_out_cash.entries.entries
                )
            )
        # Second career ends; muster #2 begins.
        state.character.career_history = [
            CareerTermRecord(
                career_id="navy", terms=3, terms_in_career=3, final_rank=0, ended_by="muster_out"
            )
        ]
        state.character.career = "army"
        state.character.terms = 4  # 1 term in army
        engine.apply(SetFlagCommand(key="term_phase", value="re_enlist"))
        controller = LifepathController(engine, pack)
        controller.apply_choice("reenlist_muster")
        assert controller.determine_phase() == "muster_out_allocate"
        view = controller.get_phase_view()
        cash = next(c for c in view.choices if c.option_id == "claim_cash")
        assert cash.dimmed is True

    def test_resume_mid_second_muster_reconstructs(self):
        """Resume after career B's first claim: per-exit remaining (C6)."""
        engine = _make_mid_lifepath_engine()
        state = engine.state
        state.character.career_history = [
            CareerTermRecord(
                career_id="navy", terms=2, terms_in_career=2, final_rank=0, ended_by="muster_out"
            )
        ]
        state.character.career = "army"
        state.character.terms = 4  # 2 terms in army -> 2 rolls this exit
        engine._roller = ForcedRoller([[1]])
        engine.apply(SetFlagCommand(key="term_phase", value="re_enlist"))
        controller = LifepathController(engine, load_scifi_pack())
        controller.apply_choice("reenlist_muster")
        controller.apply_choice("claim_cash")
        # Resume: rebuild the controller on the same state.
        resumed = LifepathController(engine, load_scifi_pack())
        assert resumed.determine_phase() == "muster_out_allocate"
        assert resumed._benefit_rolls_remaining == 1  # 2 per-exit rolls - 1 claim
