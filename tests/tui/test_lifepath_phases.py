"""Tests for the interactive lifepath phases and LLM narration wiring.

Covers:
1. New sub-phases (run_survival, choose_commission, choose_advancement, choose_skills, run_aging, re_enlist)
2. Phase state machine transitions
3. Skill table selection flow
4. Re-enlist continue/muster-out decision
5. Term phase persistence via flags (save/resume)
6. LLM narration wiring (template fallback path, narration dispatch)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.engine.dice import ForcedRoller
from src.engine.state import CampaignConfig, GameState, Injury
from src.tui.app import CepheusApp
from src.tui.screens.lifepath import LifepathScreen
from src.tui.settings import LLMSettings
from src.tui.widgets.choice_menu import ChoiceMenuWidget
from src.tui.widgets.narrative_log import NarrativeLogWidget

# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture
def seeded_app(tmp_path: Path) -> CepheusApp:
    """Create an app with a pre-initialised campaign."""
    app = CepheusApp(saves_dir=tmp_path)
    # Ensure LLM is not configured so tests use template narration.
    app.llm_settings = LLMSettings()
    config = CampaignConfig(
        ruleset="cepheus",
        theme_pack="scifi",
        resolution_profile="classic",
        death_mode="narrative",
    )
    state = GameState.new(seed=42)
    state.campaign = config
    state.character.name = "TestHero"
    from src.engine.commands import Engine
    from src.engine.lifepath import LifepathRunner
    from src.themepacks.cepheus_scifi import load_scifi_pack

    app.engine = Engine(state)
    app.pack = load_scifi_pack()
    app.runner = LifepathRunner(app.engine, app.pack)
    app.campaign_name = "TestHero"
    return app


TERM_PHASES = frozenset(
    {
        "run_survival",
        "choose_commission",
        "choose_advancement",
        "choose_skills",
        "run_aging",
        "re_enlist",
        "mishap_roll",
        "choose_injury_stat",
        "choose_crisis_resolution",
    }
)


async def push_lifepath(app, pilot):
    app.push_screen(LifepathScreen())
    await pilot.pause()
    return app.screen


async def select_first(app, pilot):
    cm = app.screen.query_one(ChoiceMenuWidget)
    cm.option_list.highlighted = 0
    cm.option_list.action_select()
    await pilot.pause()


async def play_through_characteristics(app, pilot):
    """Roll the pool, assign all six characteristics, then pick background
    skills until the phase advances to ``choose_career`` (Tasks 4 + 9).

    Selects the first unassigned characteristic then the first pool value,
    six times. Then picks background skills until exhausted. After this the
    phase is ``choose_career``.
    """
    # Roll the pool (roll_characteristics phase, single "Roll" option).
    await select_first(app, pilot)
    # Assign all six: each assignment is two selections (char then value).
    for _ in range(6):
        await select_first(app, pilot)  # pick first unassigned characteristic
        await select_first(app, pilot)  # pick first pool value
    # Play through background skills (Task 9) to reach choose_career.
    await play_through_background_skills(app, pilot)


async def play_through_background_skills(app, pilot):
    """Pick background skills until the phase advances past
    ``choose_background_skills`` (Task 9 flow).

    Picks the first offered background skill until either no choices remain
    or the phase changes. After this the phase is ``choose_career``.
    """
    for _ in range(20):
        if app.screen.phase != "choose_background_skills":
            return
        cm = app.screen.query_one(ChoiceMenuWidget)
        if cm.option_list.option_count == 0:
            return
        cm.option_list.highlighted = 0
        cm.option_list.action_select()
        await pilot.pause()


async def play_through_term(app, pilot, screen):
    """Play through all sub-phases of one term up to re_enlist."""
    for _ in range(20):
        if screen.phase not in TERM_PHASES or screen.phase == "re_enlist":
            break
        cm = app.screen.query_one(ChoiceMenuWidget)
        if not cm.option_list.option_count:
            break
        cm.option_list.highlighted = 0
        cm.option_list.action_select()
        await pilot.pause()


# ---------------------------------------------------------------------------
# 1. New phase transitions.
# ---------------------------------------------------------------------------


class TestPhaseTransitions:
    """Verify the new sub-phase state machine transitions correctly."""

    async def test_survival_phase_after_career(self, seeded_app):
        """After choosing a career, phase is run_survival."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            # Roll + assign characteristics (pool flow).
            await play_through_characteristics(app, pilot)
            assert screen.phase == "choose_career"
            # Choose first career.
            await select_first(app, pilot)
            assert screen.phase == "run_survival"

    async def test_survival_to_advancement(self, seeded_app):
        """Survival success transitions to choose_commission or choose_advancement."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            await play_through_characteristics(app, pilot)  # chars
            await select_first(app, pilot)  # career
            assert screen.phase == "run_survival"
            # Roll survival.
            await select_first(app, pilot)
            # Should be commission/advancement choice or mustering_out (if mishap).
            assert screen.phase in (
                "choose_commission",
                "choose_advancement",
                "mustering_out",
                "complete",
            )

    async def test_advancement_to_choose_skills(self, seeded_app):
        """Advancement transitions to choose_skills."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            await play_through_characteristics(app, pilot)  # chars
            await select_first(app, pilot)  # career
            await select_first(app, pilot)  # survival
            # Play through commission + advancement choice phases.
            while screen.phase in ("choose_commission", "choose_advancement"):
                await select_first(app, pilot)
            assert screen.phase == "choose_skills"

    async def test_choose_skills_shows_tables(self, seeded_app):
        """choose_skills phase presents skill table choices."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            await play_through_characteristics(app, pilot)  # chars
            await select_first(app, pilot)  # career
            await select_first(app, pilot)  # survival
            while screen.phase in ("choose_commission", "choose_advancement"):
                await select_first(app, pilot)
            if screen.phase == "choose_skills":
                cm = app.screen.query_one(ChoiceMenuWidget)
                # Should have skill table options.
                assert cm.option_list.option_count >= 1

    async def test_re_enlist_after_term_complete(self, seeded_app):
        """After all term steps, phase becomes re_enlist."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            await play_through_characteristics(app, pilot)  # chars
            await select_first(app, pilot)  # career
            await play_through_term(app, pilot, screen)
            assert screen.phase in (
                "re_enlist",
                "mustering_out",
                "choose_career_change",
                "complete",
            )

    async def test_re_enlist_shows_continue_and_muster(self, seeded_app):
        """re_enlist phase shows both continue and muster-out options."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            await play_through_characteristics(app, pilot)  # chars
            await select_first(app, pilot)  # career
            await play_through_term(app, pilot, screen)
            if screen.phase == "re_enlist":
                cm = app.screen.query_one(ChoiceMenuWidget)
                assert cm.option_list.option_count == 2

    async def test_re_enlist_continue_starts_new_term(self, seeded_app):
        """Choosing continue at re_enlist goes to run_survival."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            await play_through_characteristics(app, pilot)  # chars
            await select_first(app, pilot)  # career
            await play_through_term(app, pilot, screen)
            if screen.phase == "re_enlist":
                # Option 0 = continue.
                cm = app.screen.query_one(ChoiceMenuWidget)
                cm.option_list.highlighted = 0
                cm.option_list.action_select()
                await pilot.pause()
                assert screen.phase == "run_survival"

    async def test_re_enlist_muster_out_goes_to_mustering(self, seeded_app):
        """Choosing muster out at re_enlist goes to mustering_out."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            await play_through_characteristics(app, pilot)  # chars
            await select_first(app, pilot)  # career
            await play_through_term(app, pilot, screen)
            if screen.phase == "re_enlist":
                # Option 1 = muster out.
                cm = app.screen.query_one(ChoiceMenuWidget)
                cm.option_list.highlighted = 1
                cm.option_list.action_select()
                await pilot.pause()
                assert screen.phase == "mustering_out"


# ---------------------------------------------------------------------------
# 2. Detailed roll display.
# ---------------------------------------------------------------------------


class TestDetailedRollDisplay:
    """Verify each roll type shows in the narrative log with details."""

    async def test_survival_roll_shown(self, seeded_app):
        """Survival roll details appear in the narrative log."""
        app = seeded_app
        async with app.run_test() as pilot:
            await push_lifepath(app, pilot)
            log = app.screen.query_one(NarrativeLogWidget)
            await play_through_characteristics(app, pilot)  # chars
            await select_first(app, pilot)  # career
            await select_first(app, pilot)  # survival
            # Log should contain "Survival" somewhere.
            lines = log.lines
            full_text = " ".join(str(line) for line in lines)
            assert "Survival" in full_text or "Term" in full_text

    async def test_skill_roll_shows_table_name(self, seeded_app):
        """Skill rolls display the chosen table name."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            await play_through_characteristics(app, pilot)  # chars
            await select_first(app, pilot)  # career
            await select_first(app, pilot)  # survival
            while screen.phase in ("choose_commission", "choose_advancement"):
                await select_first(app, pilot)
            if screen.phase == "choose_skills":
                log = app.screen.query_one(NarrativeLogWidget)
                await select_first(app, pilot)  # pick a skill table
                lines = log.lines
                full_text = " ".join(str(line) for line in lines)
                # Should reference a table name.
                assert any(
                    name in full_text
                    for name in ("Personal Development", "Service Skills", "Advanced Education")
                )


# ---------------------------------------------------------------------------
# 3. Term phase persistence (save/resume).
# ---------------------------------------------------------------------------


class TestTermPhasePersistence:
    """Verify term_phase flags persist across save/resume."""

    async def test_phase_reconstructable_after_save(self, seeded_app):
        """After saving mid-term, the loaded state reconstructs the phase."""
        app = seeded_app
        async with app.run_test() as pilot:
            await push_lifepath(app, pilot)
            await play_through_characteristics(app, pilot)  # chars
            await select_first(app, pilot)  # career
            await select_first(app, pilot)  # survival

            # Should be in choose_commission/choose_advancement (or mishap path).
            app.save_game()

        # Load into a fresh app.
        app2 = CepheusApp(saves_dir=app.saves_dir)
        app2.llm_settings = LLMSettings()
        save_path = app.saves_dir / "TestHero.json"
        app2.load_campaign(save_path)

        # Create screen to check phase determination.
        screen2 = LifepathScreen()
        app2.push_screen(screen2)

        # Phase should match or be a valid term phase.
        assert screen2._determine_phase() in TERM_PHASES or screen2._determine_phase() in (
            "mustering_out",
            "muster_out_allocate",
            "complete",
        )

    async def test_reconstruct_term_state_on_mount(self, seeded_app):
        """_reconstruct_term_state rebuilds TermResult from events."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            await play_through_characteristics(app, pilot)  # chars
            await select_first(app, pilot)  # career
            await select_first(app, pilot)  # survival

            # The screen should have a current_term_result.
            assert screen._current_term_result is not None
            assert screen._current_term_result.survival_raw > 0


# ---------------------------------------------------------------------------
# 4. LLM narration wiring.
# ---------------------------------------------------------------------------


class TestLLMNarrationWiring:
    """Verify the screen dispatches narration correctly."""

    async def test_template_narration_when_not_configured(self, seeded_app):
        """Without LLM configured, template narration is used synchronously."""
        app = seeded_app
        app.llm_settings = LLMSettings()  # Explicitly unconfigured.

        async with app.run_test() as pilot:
            await push_lifepath(app, pilot)
            assert not app.llm_settings.is_configured

            await play_through_characteristics(app, pilot)  # chars
            await select_first(app, pilot)  # career

            # Qualification narration should appear in the log.
            log = app.screen.query_one(NarrativeLogWidget)
            full_text = " ".join(str(line) for line in log.lines)
            # Template narration contains career name.
            assert len(full_text) > 0

    async def test_narrate_step_dispatches_template(self, seeded_app):
        """_narrate_step calls template_fn when LLM not configured."""
        app = seeded_app
        app.llm_settings = LLMSettings()

        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            called = []

            def template_fn():
                called.append(True)
                return "Template prose."

            def on_complete():
                called.append("complete")

            screen._narrate_step("term", None, template_fn, on_complete)
            await pilot.pause()

            assert True in called
            assert "complete" in called

    async def test_status_bar_shows_template(self, seeded_app):
        """Status bar shows 'Template' when LLM not configured."""
        app = seeded_app
        app.llm_settings = LLMSettings()

        async with app.run_test() as pilot:
            await push_lifepath(app, pilot)
            from textual.widgets import Label

            status = app.screen.query_one("#status-bar", Label)
            rendered = str(status.render())
            assert "Template" in rendered or "template" in rendered.lower()


# ---------------------------------------------------------------------------
# 5. Full multi-term lifepath.
# ---------------------------------------------------------------------------


class TestMultiTermLifepath:
    """Verify multi-term lifepath works with the new phase flow."""

    async def test_two_terms_complete(self, seeded_app):
        """Play two full terms then muster out."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            cm = app.screen.query_one(ChoiceMenuWidget)

            # Setup.
            await play_through_characteristics(app, pilot)  # chars
            await select_first(app, pilot)  # career

            # Term 1.
            await play_through_term(app, pilot, screen)
            # If survival caused a mishap, we go directly to mustering_out.
            if screen.phase == "re_enlist":
                # Continue for a second term.
                cm.option_list.highlighted = 0
                cm.option_list.action_select()
                await pilot.pause()

                # Term 2.
                await play_through_term(app, pilot, screen)

            if screen.phase == "re_enlist":
                # Muster out.
                cm.option_list.highlighted = 1
                cm.option_list.action_select()
                await pilot.pause()

            # A mishap / forced-leave (terms < 7) offers a career change;
            # pick "muster out" (index 1) to proceed to mustering_out.
            while screen.phase == "choose_career_change":
                cm.option_list.highlighted = 1
                cm.option_list.action_select()
                await pilot.pause()

            # Complete mustering out if we're there.
            while screen.phase in ("mustering_out", "muster_out_allocate"):
                await select_first(app, pilot)

            assert screen.phase == "complete"

    async def test_terms_advance_correctly(self, seeded_app):
        """Each completed term advances the term counter by 1."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            cm = app.screen.query_one(ChoiceMenuWidget)

            await play_through_characteristics(app, pilot)  # chars
            await select_first(app, pilot)  # career

            # Term 1: survival advances terms to 1.
            await play_through_term(app, pilot, screen)
            assert app.engine.state.character.terms == 1

            # The B12 re-enlistment roll at end of term 1 may force mustering
            # out (must_leave/must_retire), auto-advance (must_continue), or
            # leave the choice to the player (may_continue → re_enlist phase).
            # must_leave (terms < 7) now routes to choose_career_change (B17).
            if screen.phase in ("mustering_out", "choose_career_change"):
                pytest.skip("re-enlistment roll ended the career early")
            if screen.phase == "re_enlist":
                # may_continue — player chooses to continue.
                cm.option_list.highlighted = 0
                cm.option_list.action_select()
                await pilot.pause()
            # must_continue already auto-advanced to run_survival.

            # Term 2 survival roll advances the counter to 2. play_through_term
            # may continue further if must_continue fires again at end of term 2.
            await play_through_term(app, pilot, screen)
            assert app.engine.state.character.terms >= 2


# ---------------------------------------------------------------------------
# 6. Regression: soft-lock when final skill pick lands at age >= 34.
# ---------------------------------------------------------------------------


class TestSkillPickAgingTransition:
    """Final skill roll at age >= 34 must transition to run_aging.

    Before the fix, the age >= 34 branch only called ``_set_term_phase``
    without setting ``self.phase`` or calling ``_post_step()`` — the choice
    menu kept showing skill tables with "0 left" and the player was stuck.
    """

    async def test_last_skill_pick_at_age_34_advances_to_aging(self, seeded_app):
        """Final skill pick at age 34+ transitions to run_aging, not soft-lock."""
        from src.engine.lifepath import TermResult

        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)

            # Set up a mid-term state at age >= 34.
            state = app.engine.state
            state.character.characteristics = {
                "STR": 7,
                "DEX": 9,
                "END": 6,
                "INT": 8,
                "EDU": 10,
                "SOC": 5,
            }
            state.character.career = "navy"
            state.character.age = 34
            state.character.terms = 1
            state.character.rank = 0

            # Build a TermResult and set up choose_skills phase with 1 roll left.
            result = TermResult(
                term_number=1,
                career_id="navy",
                career_name="Navy",
                age_before=30,
                age_after=34,
            )
            screen._current_term_result = result
            screen._skill_rolls_remaining = 1
            screen._set_term_phase("choose_skills")
            screen.phase = "choose_skills"
            await pilot.pause()

            # Select a skill table — this is the last roll.
            cm = app.screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            # Should have transitioned to run_aging, not soft-locked.
            assert screen.phase == "run_aging"


# ---------------------------------------------------------------------------
# 7. Regression: qualification roll detail uses raw_roll (not roll_total).
# ---------------------------------------------------------------------------


class TestQualificationRollDisplay:
    """The qualification roll detail must actually display.

    Before the fix, the code checked ``hasattr(qual, 'roll_total')`` which
    is always False (QualificationResult has ``raw_roll``, not ``roll_total``),
    making the display branch unreachable.
    """

    async def test_qualification_roll_shown_in_log(self, seeded_app):
        """Qualification roll detail appears in the narrative log."""
        app = seeded_app
        async with app.run_test() as pilot:
            await push_lifepath(app, pilot)
            log = app.screen.query_one(NarrativeLogWidget)

            await play_through_characteristics(app, pilot)  # chars
            await select_first(app, pilot)  # career → qualification

            full_text = " ".join(str(line) for line in log.lines)
            # The roll line includes the label and the dice notation.
            assert "Qualification" in full_text


# ---------------------------------------------------------------------------
# 8. Regression: resume reconstructs term state before phase determination.
# ---------------------------------------------------------------------------


class TestResumeOrdering:
    """Term state reconstruction must run BEFORE phase determination.

    Before the fix, ``_determine_phase`` was called first, reading the initial
    ``_skill_rolls_remaining`` of 0 and skipping a resumed player's remaining
    skill picks (AE8).
    """

    async def test_resume_in_choose_skills_keeps_phase(self, seeded_app):
        """Resuming mid-choose_skills stays in choose_skills, not re_enlist.

        Before the fix, ``_determine_phase`` ran before
        ``_reconstruct_term_state`` in ``on_mount``, reading the initial
        ``_skill_rolls_remaining`` of 0 and skipping to ``re_enlist``.
        """
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            await play_through_characteristics(app, pilot)  # chars
            await select_first(app, pilot)  # career
            await select_first(app, pilot)  # survival

            while screen.phase in ("choose_commission", "choose_advancement"):
                await select_first(app, pilot)

            if screen.phase != "choose_skills":
                pytest.skip("Path did not reach choose_skills")

            assert screen._skill_rolls_remaining > 0
            app.save_game()

        # Load into a fresh app.
        app2 = CepheusApp(saves_dir=app.saves_dir)
        app2.llm_settings = LLMSettings()
        save_path = app.saves_dir / "TestHero.json"
        app2.load_campaign(save_path)

        screen2 = LifepathScreen()
        app2.push_screen(screen2)

        # Before reconstruction, _skill_rolls_remaining is 0, so
        # _determine_phase would WRONGLY return re_enlist.
        assert screen2._skill_rolls_remaining == 0
        assert screen2._determine_phase() != "choose_skills"

        # After reconstruction (as on_mount now does first), rolls are
        # restored and _determine_phase correctly returns choose_skills.
        screen2._reconstruct_term_state()
        assert screen2._skill_rolls_remaining > 0
        assert screen2._determine_phase() == "choose_skills"


# ---------------------------------------------------------------------------
# 14. Background skills phase + Advanced Education EDU-8 gate (Task 9).
# ---------------------------------------------------------------------------


class TestBackgroundSkillsPhase:
    """Verify the TUI ``choose_background_skills`` phase (B10).

    After characteristics are assigned and before career selection, the
    player picks background skills: 3 + EDU DM picks at level 0 from
    ``pack.background_skills``. The phase is resume-safe via
    ``background_picks_remaining != -1``.
    """

    async def test_phase_after_characteristics_is_background(self, seeded_app):
        """After assigning characteristics the phase is choose_background_skills."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            # Roll pool + assign all six characteristics (without picking
            # background skills, so we observe the intermediate phase).
            await select_first(app, pilot)  # roll pool
            for _ in range(6):
                await select_first(app, pilot)  # characteristic
                await select_first(app, pilot)  # pool value
            assert screen.phase == "choose_background_skills"

    async def test_background_phase_offers_pack_skills(self, seeded_app):
        """choose_background_skills lists the pack's background skills."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            # Roll pool + assign all six characteristics to land at the
            # background phase.
            await select_first(app, pilot)  # roll pool
            for _ in range(6):
                await select_first(app, pilot)  # characteristic
                await select_first(app, pilot)  # pool value
            assert screen.phase == "choose_background_skills"
            cm = app.screen.query_one(ChoiceMenuWidget)
            # Should offer each background skill as a choice.
            assert cm.option_list.option_count >= 1

    async def test_picking_all_background_advances_to_career(self, seeded_app):
        """Picking the available count of background skills advances to career."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            # Roll pool + assign all six characteristics to land at the
            # background phase, then pick skills manually.
            await select_first(app, pilot)  # roll pool
            for _ in range(6):
                await select_first(app, pilot)  # characteristic
                await select_first(app, pilot)  # pool value
            assert screen.phase == "choose_background_skills"
            picks = app.engine.state.character.background_picks_remaining
            # Pick that many skills.
            for _ in range(picks):
                cm = app.screen.query_one(ChoiceMenuWidget)
                if cm.option_list.option_count == 0:
                    break
                cm.option_list.highlighted = 0
                cm.option_list.action_select()
                await pilot.pause()
            assert screen.phase == "choose_career"

    async def test_advanced_education_hidden_when_edu_below_8(self, seeded_app):
        """When EDU < 8, the Advanced Education table is hidden from choices."""
        from src.engine.lifepath import TermResult

        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            state = app.engine.state
            state.character.characteristics = {
                "STR": 7,
                "DEX": 9,
                "END": 6,
                "INT": 8,
                "EDU": 7,
                "SOC": 5,
            }
            state.character.career = "navy"
            state.character.age = 18
            state.character.terms = 0
            state.character.rank = 0
            state.character.basic_training_done = True
            result = TermResult(
                term_number=1,
                career_id="navy",
                career_name="Navy",
                age_before=18,
                age_after=22,
            )
            screen._current_term_result = result
            screen._skill_rolls_remaining = 2
            screen._set_term_phase("choose_skills")
            screen.phase = "choose_skills"
            await pilot.pause()

            cm = app.screen.query_one(ChoiceMenuWidget)
            option_ids = [cm.option_list._options[i].id for i in range(cm.option_list.option_count)]
            table_names = [
                oid.split(":", 1)[1] for oid in option_ids if oid and oid.startswith("skill_table:")
            ]
            assert "Advanced Education" not in table_names

    async def test_advanced_education_shown_when_edu_8_plus(self, seeded_app):
        """When EDU >= 8, the Advanced Education table is offered."""
        from src.engine.lifepath import TermResult

        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            state = app.engine.state
            state.character.characteristics = {
                "STR": 7,
                "DEX": 9,
                "END": 6,
                "INT": 8,
                "EDU": 8,
                "SOC": 5,
            }
            state.character.career = "navy"
            state.character.age = 18
            state.character.terms = 0
            state.character.rank = 0
            state.character.basic_training_done = True
            result = TermResult(
                term_number=1,
                career_id="navy",
                career_name="Navy",
                age_before=18,
                age_after=22,
            )
            screen._current_term_result = result
            screen._skill_rolls_remaining = 2
            screen._set_term_phase("choose_skills")
            screen.phase = "choose_skills"
            await pilot.pause()

            cm = app.screen.query_one(ChoiceMenuWidget)
            option_ids = [cm.option_list._options[i].id for i in range(cm.option_list.option_count)]
            table_names = [
                oid.split(":", 1)[1] for oid in option_ids if oid and oid.startswith("skill_table:")
            ]
            assert "Advanced Education" in table_names

    async def test_basic_training_runs_on_first_term(self, seeded_app):
        """Choosing a career triggers basic training (Service Skills at 0)."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            await play_through_characteristics(app, pilot)
            # Skip past background skills.
            picks = app.engine.state.character.background_picks_remaining
            for _ in range(max(0, picks)):
                cm = app.screen.query_one(ChoiceMenuWidget)
                if cm.option_list.option_count == 0:
                    break
                cm.option_list.highlighted = 0
                cm.option_list.action_select()
                await pilot.pause()
            assert screen.phase == "choose_career"
            # Pick the first career.
            await select_first(app, pilot)
            # Basic training should have granted Service Skills at level 0
            # for the chosen career (whichever it is).
            assert app.engine.state.character.basic_training_done is True
            chosen = app.engine.state.character.career
            career = app.pack.careers[chosen]
            service = next(t for t in career.skill_tables if t.name == "Service Skills")
            for entry in service.entries.entries:
                if not entry.result.startswith("+"):
                    assert app.engine.state.character.skills.get(entry.result) == 0


# ---------------------------------------------------------------------------
# 9. Regression: adventure loop reachable from lifepath completion.
# ---------------------------------------------------------------------------


class TestAdventureWiring:
    """A mustered-out character can enter the adventure loop."""

    async def test_complete_shows_begin_adventure(self, seeded_app):
        """The completion screen offers 'Begin Adventure' for living characters."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)

            # Force completion state.
            state = app.engine.state
            state.character.characteristics = {
                "STR": 7,
                "DEX": 9,
                "END": 6,
                "INT": 8,
                "EDU": 10,
                "SOC": 5,
            }
            state.character.career = "navy"
            state.character.alive = True
            from src.engine.commands import SetFlagCommand

            app.engine.apply(SetFlagCommand(key="mustered_out", value="true"))
            screen.phase = "complete"
            await pilot.pause()

            cm = app.screen.query_one(ChoiceMenuWidget)
            # Should have "Begin Adventure" + "Finish".
            assert cm.option_list.option_count == 2

    async def test_load_campaign_routes_to_adventure(self, tmp_path):
        """A mustered-out, living save loads into AdventureScreen."""
        from src.engine.commands import Engine, SetFlagCommand
        from src.themepacks.cepheus_scifi import load_scifi_pack
        from src.tui.screens.adventure import AdventureScreen

        app = CepheusApp(saves_dir=tmp_path)
        app.llm_settings = LLMSettings()
        state = GameState.new(seed=42)
        state.campaign = CampaignConfig(theme_pack="scifi")
        state.character.name = "Hero"
        state.character.alive = True
        state.character.characteristics = {
            "STR": 7,
            "DEX": 9,
            "END": 6,
            "INT": 8,
            "EDU": 10,
            "SOC": 5,
        }
        state.character.career = "navy"
        app.engine = Engine(state)
        app.engine.apply(SetFlagCommand(key="mustered_out", value="true"))
        app.pack = load_scifi_pack()
        app.campaign_name = "Hero"
        save_path = app.save_game()

        # Load into a fresh app — must be async for Textual.
        app2 = CepheusApp(saves_dir=tmp_path)
        async with app2.run_test() as pilot:
            app2.load_campaign(save_path)
            await pilot.pause()
            assert any(isinstance(s, AdventureScreen) for s in app2.screen_stack)


# ---------------------------------------------------------------------------
# 10. Characteristic pool flow (Task 4): roll-six-then-assign + one reroll.
# ---------------------------------------------------------------------------


class TestCharacteristicPoolFlow:
    """Verify the pool-based characteristic flow and its TUI phase.

    Flow: roll_characteristics (roll pool) -> assign_characteristics
    (player assigns each value, one optional reroll) -> choose_career.
    """

    async def test_roll_pool_enters_assign_phase(self, seeded_app):
        """Rolling the pool transitions to assign_characteristics."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            assert screen.phase == "roll_characteristics"
            # Roll the pool.
            await select_first(app, pilot)
            assert screen.phase == "assign_characteristics"
            assert len(app.engine.state.character.unassigned_rolls) == 6
            assert app.engine.state.character.characteristics == {}

    async def test_assign_all_six_reaches_choose_career(self, seeded_app):
        """Assigning all six pool values reaches choose_career (via background)."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            await play_through_characteristics(app, pilot)
            # play_through_characteristics now includes background picks.
            assert screen.phase == "choose_career"
            assert len(app.engine.state.character.characteristics) == 6
            assert app.engine.state.character.unassigned_rolls == []

    async def test_reroll_pool_re_rolls_values(self, seeded_app):
        """Selecting 'Reroll pool' produces a fresh pool of six values."""
        app = seeded_app
        async with app.run_test() as pilot:
            await push_lifepath(app, pilot)
            await select_first(app, pilot)  # roll pool
            pool_before = list(app.engine.state.character.unassigned_rolls)

            # Select the reroll option.
            cm = app.screen.query_one(ChoiceMenuWidget)
            idx = cm.option_list.get_option_index("reroll_pool")
            cm.option_list.highlighted = idx
            cm.option_list.action_select()
            await pilot.pause()

            assert app.engine.state.character.pool_rerolled is True
            pool_after = app.engine.state.character.unassigned_rolls
            assert len(pool_after) == 6
            # Extremely unlikely the re-roll is identical to the original.
            assert list(pool_after) != pool_before

    async def test_reroll_option_disabled_after_use(self, seeded_app):
        """The reroll option is shown disabled once pool_rerolled is True."""
        app = seeded_app
        async with app.run_test() as pilot:
            await push_lifepath(app, pilot)
            await select_first(app, pilot)  # roll pool

            cm = app.screen.query_one(ChoiceMenuWidget)
            idx = cm.option_list.get_option_index("reroll_pool")
            cm.option_list.highlighted = idx
            cm.option_list.action_select()
            await pilot.pause()

            # Option still present but disabled.
            assert cm.option_list.get_option_index("reroll_pool") >= 0
            disabled = cm.option_list._options[
                cm.option_list.get_option_index("reroll_pool")
            ].disabled
            assert disabled is True

    async def test_resume_mid_assignment_preserves_pool(self, seeded_app):
        """AE8: a partially-assigned pool survives save/load and resumes.

        After rolling the pool and assigning two characteristics, the save
        must round-trip ``unassigned_rolls`` (remaining pool) and the partial
        ``characteristics`` map; on reload the phase determination lands
        back in ``assign_characteristics`` and the player can finish.
        """
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            # Roll the pool.
            await select_first(app, pilot)
            assert screen.phase == "assign_characteristics"
            # Assign two characteristics (each is char-pick + value-pick).
            await select_first(app, pilot)
            await select_first(app, pilot)
            await select_first(app, pilot)
            await select_first(app, pilot)
            assert len(app.engine.state.character.characteristics) == 2
            assert len(app.engine.state.character.unassigned_rolls) == 4

            remaining = list(app.engine.state.character.unassigned_rolls)
            assigned = dict(app.engine.state.character.characteristics)
            app.save_game()

        # Load into a fresh app.
        app2 = CepheusApp(saves_dir=app.saves_dir)
        app2.llm_settings = LLMSettings()
        save_path = app.saves_dir / "TestHero.json"
        app2.load_campaign(save_path)

        # Pool and partial assignments survive save/load (by construction:
        # both are serialized state fields).
        assert app2.engine.state.character.unassigned_rolls == remaining
        assert app2.engine.state.character.characteristics == assigned

        # Phase determination lands back in assign_characteristics.
        screen2 = LifepathScreen()
        app2.push_screen(screen2)
        assert screen2._determine_phase() == "assign_characteristics"

        # Sanity: the submenu starts at the characteristic-list step.
        assert screen2._assigning_char is None


# ---------------------------------------------------------------------------
# 11. Interactive mishap / injury / crisis phases (Fix 1 — player agency).
# ---------------------------------------------------------------------------


class TestInteractiveMishapFlow:
    """Verify the interactive mishap/injury/crisis phases.

    The player — not the engine — decides:
    - which physical characteristic takes the injury (choose_injury_stat)
    - whether to pay Cr10,000 or accept a lasting scar (choose_crisis_resolution)

    Ironman crisis is auto-death (the rule mandates it — no player choice).
    """

    def _setup_for_survival(self, app, chars=None, credits=0):
        """Set up a character ready for the survival roll (phase = run_survival)."""
        state = app.engine.state
        state.character.characteristics = chars or {
            "STR": 7,
            "DEX": 9,
            "END": 6,
            "INT": 8,
            "EDU": 10,
            "SOC": 5,
        }
        state.character.career = "navy"
        state.character.age = 18
        state.character.terms = 0
        state.character.rank = 0
        state.character.alive = True
        state.character.credits = credits

    # ------------------------------------------------------------------
    # (a) Non-ironman survival fail → mishap roll shown.
    # ------------------------------------------------------------------

    async def test_survival_fail_enters_mishap_roll(self, seeded_app):
        """Non-ironman survival failure enters the mishap_roll phase."""
        app = seeded_app
        self._setup_for_survival(app)
        # Natural 2 (1+1) always fails regardless of DM → mishap.
        app.engine._roller = ForcedRoller([[1, 1]])

        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            assert screen.phase == "run_survival"

            await select_first(app, pilot)  # Roll Survival

            assert screen.phase == "mishap_roll"
            cm = app.screen.query_one(ChoiceMenuWidget)
            assert cm.option_list.option_count == 1

    # ------------------------------------------------------------------
    # (b) Injury entry → choose_injury_stat, chosen stat is reduced.
    # ------------------------------------------------------------------

    async def test_injury_entry_shows_choose_stat_phase(self, seeded_app):
        """Mishap entry 1 chains to injury; choose_injury_stat phase appears."""
        app = seeded_app
        self._setup_for_survival(app)
        # Survival fail (nat 2), mishap=1 (injury chain), injury=2 ("-4 PHYSICAL")
        app.engine._roller = ForcedRoller([[1, 1], [1], [2]])

        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)

            await select_first(app, pilot)  # Roll Survival → mishap_roll
            assert screen.phase == "mishap_roll"

            await select_first(app, pilot)  # Roll Mishap → choose_injury_stat
            assert screen.phase == "choose_injury_stat"

            # Three physical characteristics offered.
            cm = app.screen.query_one(ChoiceMenuWidget)
            assert cm.option_list.option_count == 3

    async def test_chosen_stat_is_the_one_reduced(self, seeded_app):
        """The stat the player selects is the one reduced by the injury."""
        app = seeded_app
        self._setup_for_survival(app)
        # Survival fail, mishap=1, injury=2 ("-4 PHYSICAL")
        app.engine._roller = ForcedRoller([[1, 1], [1], [2]])

        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)

            await select_first(app, pilot)  # survival
            await select_first(app, pilot)  # mishap roll
            assert screen.phase == "choose_injury_stat"

            # Select DEX (index 1).
            cm = app.screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = 1
            cm.option_list.action_select()
            await pilot.pause()

            # DEX was 9, injury roll 2 = "-4 PHYSICAL" → DEX reduced by 4.
            assert app.engine.state.character.characteristics["DEX"] == 5
            # STR and END unchanged.
            assert app.engine.state.character.characteristics["STR"] == 7
            assert app.engine.state.character.characteristics["END"] == 6

    async def test_injury_no_crisis_completes_term(self, seeded_app):
        """Injury without crisis completes the term and goes to mustering_out."""
        app = seeded_app
        self._setup_for_survival(app)
        app.engine._roller = ForcedRoller([[1, 1], [1], [2]])

        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)

            await select_first(app, pilot)  # survival
            await select_first(app, pilot)  # mishap
            assert screen.phase == "choose_injury_stat"

            # Select END (index 2) — END 6 - 4 = 2, no crisis.
            cm = app.screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = 2
            cm.option_list.action_select()
            await pilot.pause()

            # Term completes → mishap (terms < 7) offers a career change.
            assert screen.phase == "choose_career_change"
            # Drive through it: choose "muster out" (index 1) → mustering_out.
            cm.option_list.highlighted = 1
            cm.option_list.action_select()
            await pilot.pause()
            assert screen.phase == "mustering_out"

    # ------------------------------------------------------------------
    # (c) Crisis → choose_crisis_resolution, pay and scar paths.
    # ------------------------------------------------------------------

    async def test_crisis_shows_choose_resolution_phase(self, seeded_app):
        """Stat at 0 after injury enters the choose_crisis_resolution phase."""
        app = seeded_app
        self._setup_for_survival(
            app, chars={"STR": 4, "DEX": 9, "END": 6, "INT": 8, "EDU": 10, "SOC": 5}
        )
        # Survival fail, mishap=1, injury=1 ("-6 PHYSICAL"): STR 4→0 crisis.
        app.engine._roller = ForcedRoller([[1, 1], [1], [1]])

        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)

            await select_first(app, pilot)  # survival
            await select_first(app, pilot)  # mishap

            # Select STR (index 0).
            cm = app.screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            assert screen.phase == "choose_crisis_resolution"

    async def test_crisis_pay_deducts_credits(self, seeded_app):
        """Paying Cr10,000 in crisis deducts credits and stabilises the stat."""
        app = seeded_app
        self._setup_for_survival(
            app,
            chars={"STR": 4, "DEX": 9, "END": 6, "INT": 8, "EDU": 10, "SOC": 5},
            credits=15_000,
        )
        app.engine._roller = ForcedRoller([[1, 1], [1], [1]])

        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)

            await select_first(app, pilot)  # survival
            await select_first(app, pilot)  # mishap

            # Select STR (index 0) → STR 4→0 crisis.
            cm = app.screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            assert screen.phase == "choose_crisis_resolution"

            # Pay (index 0).
            cm = app.screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            assert app.engine.state.character.credits == 5_000
            assert app.engine.state.character.characteristics["STR"] == 1
            assert app.engine.state.character.alive is True

    async def test_crisis_scar_adds_severe_injury(self, seeded_app):
        """Accepting a scar adds a severe Injury and stabilises the stat at 1."""
        app = seeded_app
        self._setup_for_survival(
            app,
            chars={"STR": 4, "DEX": 9, "END": 6, "INT": 8, "EDU": 10, "SOC": 5},
            credits=15_000,
        )
        app.engine._roller = ForcedRoller([[1, 1], [1], [1]])

        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)

            await select_first(app, pilot)  # survival
            await select_first(app, pilot)  # mishap

            # Select STR (index 0) → crisis.
            cm = app.screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            assert screen.phase == "choose_crisis_resolution"

            # Accept scar (index 1).
            cm = app.screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = 1
            cm.option_list.action_select()
            await pilot.pause()

            state = app.engine.state
            assert state.character.characteristics["STR"] == 1
            assert state.character.credits == 15_000  # unchanged
            assert state.character.alive is True
            assert any(isinstance(e, Injury) and e.severity == "severe" for e in state.entities)

    async def test_crisis_pay_disabled_when_unaffordable(self, seeded_app):
        """The pay option is disabled when credits < Cr10,000."""
        app = seeded_app
        self._setup_for_survival(
            app,
            chars={"STR": 4, "DEX": 9, "END": 6, "INT": 8, "EDU": 10, "SOC": 5},
            credits=5_000,  # Cannot afford Cr10,000.
        )
        app.engine._roller = ForcedRoller([[1, 1], [1], [1]])

        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)

            await select_first(app, pilot)  # survival
            await select_first(app, pilot)  # mishap

            # Select STR (index 0) → crisis.
            cm = app.screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            assert screen.phase == "choose_crisis_resolution"

            # Pay option should be disabled.
            cm = app.screen.query_one(ChoiceMenuWidget)
            pay_idx = cm.option_list.get_option_index("crisis_pay")
            assert cm.option_list._options[pay_idx].disabled

    # ------------------------------------------------------------------
    # Ironman crisis offers pay like other modes (P1.T8 — was auto-death).
    # ------------------------------------------------------------------

    async def test_ironman_crisis_offers_pay_and_death_choice(self, seeded_app):
        """In ironman mode, a crisis offers pay/decline — no auto-death (P1.T8).

        Decline (crisis_scar) is death in ironman; pay survives with credits
        deducted. This test exercises the new choose_crisis_resolution path.
        """
        from src.engine.commands import SetFlagCommand
        from src.engine.lifepath import (
            AdvanceTermCommand,
            MishapRollCommand,
            SurvivalCommand,
        )

        app = seeded_app
        state = app.engine.state
        state.character.characteristics = {
            "STR": 4,
            "DEX": 9,
            "END": 6,
            "INT": 8,
            "EDU": 10,
            "SOC": 5,
        }
        state.character.career = "navy"
        state.character.age = 18
        state.character.terms = 0
        state.character.rank = 0
        state.character.alive = True
        state.character.credits = 15_000

        # Apply survival (narrative mode → mishap) + advance term, then
        # the mishap roll (entry 1 → injury chain), all in narrative mode.
        state.campaign.death_mode = "narrative"
        app.engine._roller = ForcedRoller([[1, 1]])
        app.engine.apply(
            SurvivalCommand(
                career_id="navy", characteristic="END", target=5, death_mode="narrative"
            )
        )
        app.engine.apply(AdvanceTermCommand())
        career = app.pack.careers["navy"]
        app.engine._roller = ForcedRoller([[1]])
        app.engine.apply(MishapRollCommand(career_id="navy", entries=career.mishap_table.entries))

        # Persist mid-mishap state, then switch to ironman for the crisis.
        app.engine.apply(SetFlagCommand(key="term_phase", value="choose_injury_stat"))
        state.campaign.death_mode = "ironman"
        # Injury roll: entry 1 ("-6 PHYSICAL") → STR 4→0 crisis.
        app.engine._roller = ForcedRoller([[1]])

        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            assert screen.phase == "choose_injury_stat"

            # Select STR (index 0) → crisis.
            cm = app.screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            # Ironman now OFFERS the crisis choice (P1.T8) — no auto-death.
            assert screen.phase == "choose_crisis_resolution"
            assert app.engine.state.character.alive is True

            # Pay (index 0) — survives, credits deducted.
            cm = app.screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            state_after = app.engine.state
            assert state_after.character.alive is True
            assert state_after.character.credits == 5_000
            assert state_after.character.characteristics["STR"] == 1


# ---------------------------------------------------------------------------
# 12. Regression: aging crisis on a mental characteristic (Fix 2).
# ---------------------------------------------------------------------------


class TestAgingMentalCrisisResolution:
    """Verify aging crisis resolution for mental characteristics.

    The graduated aging table's -6 row produces a ``mental`` slot
    (``("mental", 1)``).  If the player assigns that reduction to a mental
    characteristic (INT/EDU/SOC) at 1, ``ApplyAgingReductionCommand``
    correctly sets ``crisis: True`` and the TUI routes to
    ``choose_crisis_resolution``.  But ``_find_stat_at_zero`` only scanned
    physical characteristics (STR/DEX/END) — so
    ``_do_choose_crisis_resolution`` could not find the mental stat at 0 and
    ``ResolveInjuryCrisisCommand`` was never applied, leaving the stat at 0
    silently.  The fix expands the scan to all six characteristics
    (physical-first).
    """

    def _setup_for_aging_mental_crisis(self, app, chars=None, credits=15_000):
        """Set up a mid-term character at choose_aging_reduction with a mental slot.

        Places a single ``mental`` aging slot on ``pending_aging`` (as if the
        -6 row's physical slots were already consumed) and persists
        ``term_phase=choose_aging_reduction`` via the funnel so the screen
        resumes into the aging-reduction phase.
        """
        from src.engine.commands import SetFlagCommand
        from src.engine.state import AgingSlot

        state = app.engine.state
        state.character.characteristics = chars or {
            "STR": 7,
            "DEX": 9,
            "END": 6,
            "INT": 1,  # mental stat at 1 — will hit 0 from the mental slot
            "EDU": 10,
            "SOC": 5,
        }
        state.character.career = "navy"
        state.character.age = 38
        state.character.terms = 2
        state.character.rank = 0
        state.character.alive = True
        state.character.credits = credits
        # Single mental slot remains (physical slots already consumed).
        state.character.pending_aging = [AgingSlot(group="mental", points=1)]
        app.engine.apply(SetFlagCommand(key="term_phase", value="choose_aging_reduction"))

    async def test_aging_mental_crisis_shows_choose_resolution(self, seeded_app):
        """Aging a mental stat to 0 enters the choose_crisis_resolution phase."""
        app = seeded_app
        self._setup_for_aging_mental_crisis(app)

        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            assert screen.phase == "choose_aging_reduction"

            # Provide the TermResult and aging flag the interactive step expects.
            from src.engine.lifepath import TermResult

            screen._current_term_result = TermResult(
                term_number=2,
                career_id="navy",
                career_name="Navy",
                age_before=34,
                age_after=38,
            )
            screen._aging_active = True
            screen.phase = "choose_aging_reduction"
            await pilot.pause()

            # Mental group lists INT, EDU, SOC — INT is index 0.
            cm = app.screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            # INT 1 - 1 = 0 → crisis → choose_crisis_resolution.
            assert screen.phase == "choose_crisis_resolution"
            assert app.engine.state.character.characteristics["INT"] == 0

    async def test_aging_mental_crisis_pay_stabilizes_stat(self, seeded_app):
        """Paying for a mental-stat crisis applies ResolveInjuryCrisisCommand.

        Before the fix ``_find_stat_at_zero`` only scanned physical stats, so
        the mental stat at 0 was not detected and the crisis command was
        never applied — INT stayed at 0 and credits were unchanged.
        """
        app = seeded_app
        self._setup_for_aging_mental_crisis(app, credits=15_000)

        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            assert screen.phase == "choose_aging_reduction"

            from src.engine.lifepath import TermResult

            screen._current_term_result = TermResult(
                term_number=2,
                career_id="navy",
                career_name="Navy",
                age_before=34,
                age_after=38,
            )
            screen._aging_active = True
            screen.phase = "choose_aging_reduction"
            await pilot.pause()

            # Select INT (index 0) → INT 1→0 → crisis.
            cm = app.screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()
            assert screen.phase == "choose_crisis_resolution"

            # Pay (index 0).
            cm = app.screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            # Crisis command was applied: INT stabilised at 1, credits reduced.
            assert app.engine.state.character.characteristics["INT"] == 1
            assert app.engine.state.character.credits == 5_000
            assert app.engine.state.character.alive is True

    async def test_aging_mental_crisis_scar_adds_injury(self, seeded_app):
        """Accepting a scar for a mental-stat crisis adds a severe Injury."""
        app = seeded_app
        self._setup_for_aging_mental_crisis(app, credits=15_000)

        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            assert screen.phase == "choose_aging_reduction"

            from src.engine.lifepath import TermResult

            screen._current_term_result = TermResult(
                term_number=2,
                career_id="navy",
                career_name="Navy",
                age_before=34,
                age_after=38,
            )
            screen._aging_active = True
            screen.phase = "choose_aging_reduction"
            await pilot.pause()

            # Select INT (index 0) → crisis.
            cm = app.screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()
            assert screen.phase == "choose_crisis_resolution"

            # Accept scar (index 1).
            cm = app.screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = 1
            cm.option_list.action_select()
            await pilot.pause()

            state = app.engine.state
            assert state.character.characteristics["INT"] == 1
            assert state.character.credits == 15_000  # unchanged
            assert state.character.alive is True
            assert any(isinstance(e, Injury) and e.severity == "severe" for e in state.entities)


# ---------------------------------------------------------------------------
# 13. Re-enlistment roll at term end (Task 8 — B12).
# ---------------------------------------------------------------------------


class TestReenlistmentPhase:
    """Verify the TUI re_enlist phase honors the SRD re-enlistment roll (B12).

    The roll runs once per term inside ``_transition_after_term``; forced
    outcomes drive the next phase: ``must_continue`` auto-advances to the next
    term, ``must_leave``/``must_retire`` route to mustering out, and
    ``may_continue`` falls through to the existing Continue/Muster Out choice.
    """

    def _setup_completed_term(self, app, terms=1, chars=None):
        """Set up state as if a term just completed (pre re-enlistment roll)."""
        state = app.engine.state
        state.character.characteristics = chars or {
            "STR": 7,
            "DEX": 9,
            "END": 6,
            "INT": 8,
            "EDU": 10,
            "SOC": 5,
        }
        state.character.career = "navy"
        state.character.age = 18 + (terms * 4)
        state.character.terms = terms
        state.character.rank = 0
        state.character.alive = True

    async def test_must_continue_auto_advances_to_next_term(self, seeded_app):
        """Natural 12 forces another term — phase becomes run_survival."""
        from src.engine.lifepath import TermResult

        app = seeded_app
        self._setup_completed_term(app, terms=1)
        app.engine._roller = ForcedRoller([[6, 6]])  # natural 12

        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            result = TermResult(
                term_number=1,
                career_id="navy",
                career_name="Navy",
                age_before=18,
                age_after=22,
            )
            screen._transition_after_term(result)
            await pilot.pause()
            assert screen.phase == "run_survival"

    async def test_must_leave_routes_to_career_change(self, seeded_app):
        """Roll below target (terms < 7) offers a career change (B17)."""
        from src.engine.lifepath import TermResult

        app = seeded_app
        self._setup_completed_term(app, terms=1)
        app.engine._roller = ForcedRoller([[1, 1]])  # 2 < 6 -> must_leave

        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            result = TermResult(
                term_number=1,
                career_id="navy",
                career_name="Navy",
                age_before=18,
                age_after=22,
            )
            screen._transition_after_term(result)
            await pilot.pause()
            # Under 7 terms: the player may try a new career or muster out.
            assert screen.phase == "choose_career_change"

    async def test_must_retire_routes_to_mustering_out(self, seeded_app):
        """7+ terms forces retirement — no roll, straight to mustering out."""
        from src.engine.lifepath import TermResult

        app = seeded_app
        self._setup_completed_term(app, terms=7)
        app.engine._roller = ForcedRoller([])  # no roll should happen

        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            result = TermResult(
                term_number=7,
                career_id="navy",
                career_name="Navy",
                age_before=42,
                age_after=46,
            )
            screen._transition_after_term(result)
            await pilot.pause()
            assert screen.phase == "mustering_out"

    async def test_may_continue_shows_continue_and_muster(self, seeded_app):
        """Roll at/above target leaves the Continue/Muster Out choice to the player."""
        from src.engine.lifepath import TermResult

        app = seeded_app
        self._setup_completed_term(app, terms=1)
        app.engine._roller = ForcedRoller([[6, 4]])  # 10 >= 6 -> may_continue

        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            result = TermResult(
                term_number=1,
                career_id="navy",
                career_name="Navy",
                age_before=18,
                age_after=22,
            )
            screen._transition_after_term(result)
            await pilot.pause()
            assert screen.phase == "re_enlist"
            cm = app.screen.query_one(ChoiceMenuWidget)
            assert cm.option_list.option_count == 2

    async def test_may_continue_then_muster_out(self, seeded_app):
        """After may_continue, selecting Muster Out goes to mustering_out."""
        from src.engine.lifepath import TermResult

        app = seeded_app
        self._setup_completed_term(app, terms=1)
        app.engine._roller = ForcedRoller([[6, 4]])

        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            result = TermResult(
                term_number=1,
                career_id="navy",
                career_name="Navy",
                age_before=18,
                age_after=22,
            )
            screen._transition_after_term(result)
            await pilot.pause()
            assert screen.phase == "re_enlist"
            # Select Muster Out (index 1).
            cm = app.screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = 1
            cm.option_list.action_select()
            await pilot.pause()
            assert screen.phase == "mustering_out"

    async def test_reenlistment_outcome_persisted_no_reroll_on_resume(self, seeded_app, tmp_path):
        """Resume into re_enlist (may_continue) doesn't re-roll.

        After the roll is persisted, a save/load cycle must not consume another
        dice from the queue — the persisted ``reenlist_outcome`` flag is
        consulted and the existing outcome reused.
        """
        from src.engine.lifepath import TermResult

        app = seeded_app
        self._setup_completed_term(app, terms=1)
        # Provide only ONE roll in the queue; if resume re-rolls, the queue
        # is empty and ForcedRoller raises.
        app.engine._roller = ForcedRoller([[6, 4]])  # may_continue

        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            result = TermResult(
                term_number=1,
                career_id="navy",
                career_name="Navy",
                age_before=18,
                age_after=22,
            )
            screen._transition_after_term(result)
            await pilot.pause()
            assert screen.phase == "re_enlist"
            app.save_game()

        # Load into a fresh app with an EMPTY roller queue.
        app2 = CepheusApp(saves_dir=app.saves_dir)
        app2.llm_settings = LLMSettings()
        save_path = app.saves_dir / "TestHero.json"
        app2.load_campaign(save_path)
        from src.engine.lifepath import LifepathRunner
        from src.themepacks.cepheus_scifi import load_scifi_pack

        app2.pack = load_scifi_pack()
        app2.runner = LifepathRunner(app2.engine, app2.pack)
        app2.engine._roller = ForcedRoller([])  # empty — re-roll would fail

        screen2 = LifepathScreen()
        app2.push_screen(screen2)
        # Phase determination should land in re_enlist (may_continue persisted).
        assert screen2._determine_phase() == "re_enlist"
        # The persisted outcome is readable without a new roll.
        assert screen2._get_reenlistment_outcome() == "may_continue"


# ---------------------------------------------------------------------------
# Task 10 — qualification-failure fallback (retry / draft / drifter).
# ---------------------------------------------------------------------------


class TestQualificationFallbackPhase:
    """The ``choose_qualification_fallback`` phase offers three explicit paths
    (F2 / "always more player choice") instead of the old silent auto-drifter."""

    async def _drive_to_fallback(self, app, pilot):
        """Play through characteristics + background, then force a failed
        qualification so the screen lands in ``choose_qualification_fallback``."""
        screen = await push_lifepath(app, pilot)
        await play_through_characteristics(app, pilot)
        assert screen.phase == "choose_career"
        # Force the qualification roll to 2 (fails any target) — survival's
        # natural-2 rule doesn't apply to qualification, but a raw 2 + DM
        # stays below every career's target here.
        app.engine._roller = ForcedRoller([[1, 1]])
        await select_first(app, pilot)  # pick first career -> qual fails
        return screen

    @staticmethod
    def _option_index(cm, option_id: str) -> int:
        for i in range(cm.option_list.option_count):
            if cm.option_list._options[i].id == option_id:
                return i
        raise AssertionError(f"option {option_id!r} not in menu")

    async def test_failed_qualification_enters_fallback_with_three_options(self, seeded_app):
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await self._drive_to_fallback(app, pilot)
            assert screen.phase == "choose_qualification_fallback"
            cm = app.screen.query_one(ChoiceMenuWidget)
            ids = {cm.option_list._options[i].id for i in range(cm.option_list.option_count)}
            assert {"fallback_retry", "fallback_draft", "fallback_drifter"} <= ids

    async def test_fallback_retry_returns_to_choose_career(self, seeded_app):
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await self._drive_to_fallback(app, pilot)
            cm = app.screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = self._option_index(cm, "fallback_retry")
            cm.option_list.action_select()
            await pilot.pause()
            assert screen.phase == "choose_career"
            assert app.engine.state.character.career == ""

    async def test_fallback_draft_assigns_career_and_marks_drafted(self, seeded_app):
        app = seeded_app
        async with app.run_test() as pilot:
            await self._drive_to_fallback(app, pilot)
            # Draft rolls 1D6; force a 1 -> first entry of the pack draft table.
            app.engine._roller = ForcedRoller([[1]])
            cm = app.screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = self._option_index(cm, "fallback_draft")
            cm.option_list.action_select()
            await pilot.pause()
            char = app.engine.state.character
            assert char.drafted is True
            assert char.career == app.pack.draft_table[0]

    async def test_fallback_drifter_enters_drifter_career(self, seeded_app):
        app = seeded_app
        async with app.run_test() as pilot:
            await self._drive_to_fallback(app, pilot)
            # Drifter qual target is 2 (auto-qualify); force a comfortable pass.
            app.engine._roller = ForcedRoller([[5, 2]])
            cm = app.screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = self._option_index(cm, "fallback_drifter")
            cm.option_list.action_select()
            await pilot.pause()
            assert app.engine.state.character.career == "drifter"
            assert app.engine.state.character.drafted is False


# ---------------------------------------------------------------------------
# Task 11 — career-change choice + ironman restart (B17, AE2).
# ---------------------------------------------------------------------------


class TestCareerChangeAndRestart:
    """The ``choose_career_change`` phase and the ironman restart option."""

    async def test_career_change_new_returns_to_choose_career(self, seeded_app):
        """Selecting 'Try a new career' returns to the career list, with the
        just-ended career recorded in history (so the -2 DM applies)."""
        from src.engine.lifepath import TermResult

        app = seeded_app
        # Inline setup: state as if a term just completed (pre re-enlistment).
        st = app.engine.state
        st.character.characteristics = {"STR": 7, "DEX": 9, "END": 6, "INT": 8, "EDU": 10, "SOC": 5}
        st.character.career = "navy"
        st.character.age = 22
        st.character.terms = 1
        st.character.rank = 0
        st.character.alive = True
        app.engine._roller = ForcedRoller([[1, 1]])  # must_leave -> career change

        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            result = TermResult(
                term_number=1,
                career_id="navy",
                career_name="Navy",
                age_before=18,
                age_after=22,
            )
            screen._transition_after_term(result)
            await pilot.pause()
            assert screen.phase == "choose_career_change"
            # Select 'Try a new career' (index 0).
            cm = app.screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()
            assert screen.phase == "choose_career"
            # The navy career was recorded in history (career cleared).
            assert app.engine.state.character.career == ""
            assert app.engine.state.character.career_history[-1].career_id == "navy"

    async def test_ironman_death_offers_new_lifepath(self, seeded_app):
        """An ironman death shows a 'Begin a new lifepath' restart option."""
        app = seeded_app
        # Dead mid-career (ironman survival failure): career still set so
        # _determine_phase reaches the `not alive` -> complete branch.
        app.engine.state.campaign.death_mode = "ironman"
        app.engine.state.character.characteristics = {
            "STR": 7,
            "DEX": 9,
            "END": 6,
            "INT": 8,
            "EDU": 10,
            "SOC": 5,
        }
        app.engine.state.character.career = "navy"
        app.engine.state.character.alive = False

        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            await pilot.pause()
            assert screen.phase == "complete"
            cm = app.screen.query_one(ChoiceMenuWidget)
            ids = {cm.option_list._options[i].id for i in range(cm.option_list.option_count)}
            assert "begin_new_lifepath" in ids

    async def test_restart_rebuilds_character(self, seeded_app):
        """Selecting 'Begin a new lifepath' starts a fresh, living character."""
        app = seeded_app
        app.engine.state.campaign.death_mode = "ironman"
        app.engine.state.character.characteristics = {
            "STR": 7,
            "DEX": 9,
            "END": 6,
            "INT": 8,
            "EDU": 10,
            "SOC": 5,
        }
        app.engine.state.character.career = "navy"
        app.engine.state.character.alive = False

        async with app.run_test() as pilot:
            await push_lifepath(app, pilot)
            await pilot.pause()
            cm = app.screen.query_one(ChoiceMenuWidget)
            restart_idx = next(
                i
                for i in range(cm.option_list.option_count)
                if cm.option_list._options[i].id == "begin_new_lifepath"
            )
            cm.option_list.highlighted = restart_idx
            cm.option_list.action_select()
            await pilot.pause()
            new_char = app.engine.state.character
            assert new_char.alive is True
            assert new_char.career == ""
            assert new_char.career_history == []
            # The fresh character starts at characteristics-rolling.
            assert app.screen.phase == "roll_characteristics"


# ---------------------------------------------------------------------------
# Career choice description (Gap 2): descriptions must not be truncated.
# ---------------------------------------------------------------------------


def test_career_choice_description_not_truncated():
    """The full career description appears, never sliced to 80 chars.

    Regression for the ``[:80]`` slice that cut career descriptions mid-word
    in the choose-career menu. The theme-pack YAML is complete; only the UI
    code was truncating it.
    """
    from src.rulesets.base import CareerData, CheckRef
    from src.tui.screens.lifepath import career_choice_description

    long_description = "A" * 200  # well beyond the old 80-char cap
    career = CareerData(
        id="x",
        name="X",
        description=long_description,
        qualification=CheckRef(characteristic="INT", target=6),
        survival=CheckRef(characteristic="END", target=5),
        skill_tables=[],
    )
    desc = career_choice_description(career)

    # The complete description is present (not sliced), with the mechanic
    # prefix prepended.
    assert long_description in desc
    assert "Qualify: INT target 6" in desc
    assert "Survival: END target 5" in desc


# ---------------------------------------------------------------------------
# U1 / TUI-5: Input lock during lifepath narration.
# ---------------------------------------------------------------------------


class TestLifepathInputLock:
    """U1/TUI-5: inputs are locked during lifepath term narration."""

    async def test_input_locked_during_term_narration(self, seeded_app):
        """Same locking as adventure: option selection ignored during narration.

        Configures a slow mock adapter so the narration worker stays in flight
        while the test verifies the busy flag and input guard.
        """
        import asyncio

        from src.llm.adapter import NarrationResult
        from src.tui.settings import LLMSettings

        app = seeded_app
        # Configure LLM so the worker path is taken.
        app.llm_settings = LLMSettings(
            provider="anthropic", model="claude-sonnet-5", api_key="fake-key"
        )

        narration_started = asyncio.Event()
        release = asyncio.Event()

        class BlockingAdapter:
            async def narrate_qualification(self, state, engine, result_obj, *, on_attempt=None):
                if on_attempt:
                    on_attempt(1)
                narration_started.set()
                await release.wait()
                return NarrationResult(prose="LLM qualification text.", source="llm")

            async def narrate_term(self, state, engine, result_obj, *, on_attempt=None):
                if on_attempt:
                    on_attempt(1)
                narration_started.set()
                await release.wait()
                return NarrationResult(prose="LLM term text.", source="llm")

            async def narrate_mustering_out(self, *a, **kw):
                return NarrationResult(prose="LLM mustering text.", source="llm")

            async def narrate_lifepath(self, *a, **kw):
                return NarrationResult(prose="LLM summary text.", source="llm")

        app.create_llm_adapter = lambda: BlockingAdapter()

        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            await play_through_characteristics(app, pilot)
            await select_first(app, pilot)  # choose career

            # Qualification narration worker starts.
            await asyncio.wait_for(narration_started.wait(), timeout=2)
            await pilot.pause()

            # While busy, selecting should be ignored.
            assert screen._busy is True
            cm = app.screen.query_one(ChoiceMenuWidget)
            phase_before = screen.phase
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()
            assert screen.phase == phase_before  # No phase change.

            # Release the narration worker.
            release.set()
            await pilot.pause()
            await pilot.pause()
            assert screen._busy is False
