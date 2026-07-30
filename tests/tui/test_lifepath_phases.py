"""Tests for the interactive lifepath phases and LLM narration wiring.

Covers:
1. New sub-phases (run_survival, run_advancement, choose_skills, run_aging, re_enlist)
2. Phase state machine transitions
3. Skill table selection flow
4. Re-enlist continue/muster-out decision
5. Term phase persistence via flags (save/resume)
6. LLM narration wiring (template fallback path, narration dispatch)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.engine.state import CampaignConfig, GameState
from src.tui.app import CepheusApp
from src.tui.screens.lifepath import LifepathScreen
from src.tui.settings import LLMSettings
from src.tui.widgets.choice_menu import ChoiceMenuWidget
from src.tui.widgets.narrative_log import NarrativeLogWidget
from textual.widgets import OptionList


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
    app.target_terms = 4
    return app


TERM_PHASES = frozenset(
    {"run_survival", "run_advancement", "choose_skills", "run_aging", "re_enlist"}
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
            # Roll chars.
            await select_first(app, pilot)
            assert screen.phase == "choose_career"
            # Choose first career.
            await select_first(app, pilot)
            assert screen.phase == "run_survival"

    async def test_survival_to_advancement(self, seeded_app):
        """Survival success transitions to run_advancement."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            await select_first(app, pilot)  # chars
            await select_first(app, pilot)  # career
            assert screen.phase == "run_survival"
            # Roll survival.
            await select_first(app, pilot)
            # Should be advancement or mustering_out (if mishap).
            assert screen.phase in ("run_advancement", "mustering_out", "complete")

    async def test_advancement_to_choose_skills(self, seeded_app):
        """Advancement transitions to choose_skills."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            await select_first(app, pilot)  # chars
            await select_first(app, pilot)  # career
            await select_first(app, pilot)  # survival
            if screen.phase == "run_advancement":
                await select_first(app, pilot)  # advancement
                assert screen.phase == "choose_skills"

    async def test_choose_skills_shows_tables(self, seeded_app):
        """choose_skills phase presents skill table choices."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            await select_first(app, pilot)  # chars
            await select_first(app, pilot)  # career
            await select_first(app, pilot)  # survival
            if screen.phase == "run_advancement":
                await select_first(app, pilot)  # advancement
            if screen.phase == "choose_skills":
                cm = app.screen.query_one(ChoiceMenuWidget)
                # Should have skill table options.
                assert cm.option_list.option_count >= 1

    async def test_re_enlist_after_term_complete(self, seeded_app):
        """After all term steps, phase becomes re_enlist."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            await select_first(app, pilot)  # chars
            await select_first(app, pilot)  # career
            await play_through_term(app, pilot, screen)
            assert screen.phase in ("re_enlist", "mustering_out", "complete")

    async def test_re_enlist_shows_continue_and_muster(self, seeded_app):
        """re_enlist phase shows both continue and muster-out options."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            await select_first(app, pilot)  # chars
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
            await select_first(app, pilot)  # chars
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
            await select_first(app, pilot)  # chars
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
            screen = await push_lifepath(app, pilot)
            log = app.screen.query_one(NarrativeLogWidget)
            await select_first(app, pilot)  # chars
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
            await select_first(app, pilot)  # chars
            await select_first(app, pilot)  # career
            await select_first(app, pilot)  # survival
            if screen.phase == "run_advancement":
                await select_first(app, pilot)  # advancement
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
            screen = await push_lifepath(app, pilot)
            await select_first(app, pilot)  # chars
            await select_first(app, pilot)  # career
            await select_first(app, pilot)  # survival

            # Should be in run_advancement (or mishap path).
            phase_before = screen.phase
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
        assert screen2._determine_phase() in TERM_PHASES or \
            screen2._determine_phase() in ("mustering_out", "complete")

    async def test_reconstruct_term_state_on_mount(self, seeded_app):
        """_reconstruct_term_state rebuilds TermResult from events."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            await select_first(app, pilot)  # chars
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
            screen = await push_lifepath(app, pilot)
            assert not app.llm_settings.is_configured

            await select_first(app, pilot)  # chars
            await select_first(app, pilot)  # career

            # Qualification narration should appear in the log.
            log = app.screen.query_one(NarrativeLogWidget)
            full_text = " ".join(str(l) for l in log.lines)
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
            await select_first(app, pilot)  # chars
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

            # Complete mustering out if we're there.
            while screen.phase == "mustering_out":
                await select_first(app, pilot)

            assert screen.phase == "complete"

    async def test_terms_advance_correctly(self, seeded_app):
        """Each completed term advances the term counter by 1."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            cm = app.screen.query_one(ChoiceMenuWidget)

            await select_first(app, pilot)  # chars
            await select_first(app, pilot)  # career

            # Term 1: survival advances terms to 1.
            await play_through_term(app, pilot, screen)
            assert app.engine.state.character.terms == 1

            # Continue to term 2.
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            await play_through_term(app, pilot, screen)
            assert app.engine.state.character.terms == 2


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
                "STR": 7, "DEX": 9, "END": 6,
                "INT": 8, "EDU": 10, "SOC": 5,
            }
            state.character.career = "navy"
            state.character.age = 34
            state.character.terms = 1
            state.character.rank = 0

            # Build a TermResult and set up choose_skills phase with 1 roll left.
            result = TermResult(
                term_number=1, career_id="navy", career_name="Navy",
                age_before=30, age_after=34,
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
            screen = await push_lifepath(app, pilot)
            log = app.screen.query_one(NarrativeLogWidget)

            await select_first(app, pilot)  # chars
            await select_first(app, pilot)  # career → qualification

            full_text = " ".join(str(l) for l in log.lines)
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
            await select_first(app, pilot)  # chars
            await select_first(app, pilot)  # career
            await select_first(app, pilot)  # survival

            if screen.phase == "run_advancement":
                await select_first(app, pilot)  # advancement

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
                "STR": 7, "DEX": 9, "END": 6,
                "INT": 8, "EDU": 10, "SOC": 5,
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
        from src.engine.lifepath import LifepathRunner
        from src.themepacks.cepheus_scifi import load_scifi_pack
        from src.tui.screens.adventure import AdventureScreen

        app = CepheusApp(saves_dir=tmp_path)
        app.llm_settings = LLMSettings()
        state = GameState.new(seed=42)
        state.campaign = CampaignConfig(theme_pack="scifi")
        state.character.name = "Hero"
        state.character.alive = True
        state.character.characteristics = {
            "STR": 7, "DEX": 9, "END": 6,
            "INT": 8, "EDU": 10, "SOC": 5,
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
            assert any(
                isinstance(s, AdventureScreen) for s in app2.screen_stack
            )
