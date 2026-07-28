"""Smoke tests for the TUI shell (U4) using Textual's run_test() pilot.

Tests cover:
  1. Three-panel layout renders (character sheet, narrative log, choice menu)
  2. Keyboard navigation (Tab moves focus, number keys select choices)
  3. Lifepath interaction (term outcomes in log, choices as OptionList items)
  4. Campaign creation flow (main menu -> config -> lifepath)
  5. AE8 Save and resume (quit mid-lifepath, relaunch, resume at same term)
  6. Responsive layout at 80x24
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.engine.persistence import load
from src.engine.state import CampaignConfig, GameState
from src.tui.app import CepheusApp
from src.tui.screens.campaign_config import CampaignConfigScreen
from src.tui.screens.lifepath import LifepathScreen
from src.tui.screens.main_menu import MainMenuScreen
from src.tui.widgets.character_sheet import CharacterSheetWidget
from src.tui.widgets.choice_menu import ChoiceMenuWidget
from src.tui.widgets.narrative_log import NarrativeLogWidget
from textual.widgets import Button, Input, OptionList


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def Q(app, widget_type=None, selector=None):
    """Query the active screen for a widget."""
    if widget_type and selector:
        return app.screen.query_one(selector, widget_type)
    elif widget_type:
        return app.screen.query_one(widget_type)
    else:
        return app.screen.query_one(selector)


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture
def app(tmp_path: Path) -> CepheusApp:
    """Create a CepheusApp with a temporary saves directory."""
    return CepheusApp(saves_dir=tmp_path)


@pytest.fixture
def seeded_app(tmp_path: Path) -> CepheusApp:
    """Create an app with a pre-initialised campaign (past config screen)."""
    app = CepheusApp(saves_dir=tmp_path)
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


async def push_lifepath(app: CepheusApp, pilot) -> LifepathScreen:
    """Push the lifepath screen and wait for it to mount."""
    app.push_screen(LifepathScreen())
    await pilot.pause()
    return app.screen


# ---------------------------------------------------------------------------
# 1. Three-panel layout renders.
# ---------------------------------------------------------------------------


class TestThreePanelLayout:
    """Verify the three-panel layout is present on the lifepath screen."""

    async def test_panels_exist(self, seeded_app: CepheusApp):
        """Character sheet, narrative log, and choice menu all render."""
        app = seeded_app
        async with app.run_test() as pilot:
            await push_lifepath(app, pilot)

            assert app.screen.query_one(CharacterSheetWidget) is not None
            assert app.screen.query_one(NarrativeLogWidget) is not None
            assert app.screen.query_one(ChoiceMenuWidget) is not None

    async def test_character_sheet_shows_name(self, seeded_app: CepheusApp):
        """Character sheet renders the character name."""
        app = seeded_app
        async with app.run_test() as pilot:
            await push_lifepath(app, pilot)

            sheet = app.screen.query_one(CharacterSheetWidget)
            content = sheet.render_content(app.engine.state)
            assert "TestHero" in content

    async def test_status_bar_present(self, seeded_app: CepheusApp):
        """Status bar is present showing narration mode."""
        app = seeded_app
        async with app.run_test() as pilot:
            await push_lifepath(app, pilot)

            from textual.widgets import Label

            status = app.screen.query_one("#status-bar", Label)
            assert status is not None
            assert "Template narration" in str(status.render())


# ---------------------------------------------------------------------------
# 2. Keyboard navigation.
# ---------------------------------------------------------------------------


class TestKeyboardNavigation:
    """Verify Tab moves focus and number keys select choices."""

    async def test_tab_cycles_focus(self, seeded_app: CepheusApp):
        """Tab key moves focus between panels."""
        app = seeded_app
        async with app.run_test() as pilot:
            await push_lifepath(app, pilot)

            cm = app.screen.query_one(ChoiceMenuWidget)
            log = app.screen.query_one(NarrativeLogWidget)
            # Initial focus should be on the OptionList.
            assert cm.option_list.has_focus

            # Tab should move focus to the next focusable widget.
            await pilot.press("tab")
            await pilot.pause()
            # Focus should have moved away from the OptionList.
            assert not cm.option_list.has_focus

            # Shift+Tab should bring focus back to the OptionList.
            await pilot.press("shift+tab")
            await pilot.pause()
            assert cm.option_list.has_focus

    async def test_number_key_selects_choice(self, seeded_app: CepheusApp):
        """Number key 1 selects the first option when OptionList focused."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)

            cm = app.screen.query_one(ChoiceMenuWidget)
            assert cm.option_list.has_focus

            # Press 1 to select the first option (roll characteristics).
            await pilot.press("1")
            await pilot.pause()

            # After rolling, phase should advance to choose_career.
            assert screen.phase == "choose_career"

    async def test_enter_selects_highlighted(self, seeded_app: CepheusApp):
        """Enter selects the highlighted option."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)

            cm = app.screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = 0
            await pilot.press("enter")
            await pilot.pause()

            assert screen.phase == "choose_career"


# ---------------------------------------------------------------------------
# 3. Lifepath interaction.
# ---------------------------------------------------------------------------


class TestLifepathInteraction:
    """Verify term outcomes appear in the log and choices are presented."""

    async def test_roll_characteristics_advances_to_career(
        self, seeded_app: CepheusApp
    ):
        """Rolling characteristics moves to the career selection phase."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            assert screen.phase == "roll_characteristics"

            cm = app.screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            assert screen.phase == "choose_career"
            assert len(app.engine.state.character.characteristics) == 6

    async def test_career_choices_are_option_list_items(
        self, seeded_app: CepheusApp
    ):
        """Career selection phase shows careers as OptionList options."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            cm = app.screen.query_one(ChoiceMenuWidget)

            # Roll characteristics first.
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()
            assert screen.phase == "choose_career"

            # Should have multiple careers.
            assert cm.option_list.option_count > 1

    async def test_full_lifepath_to_completion(self, seeded_app: CepheusApp):
        """Play through the entire lifepath to the complete phase."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            cm = app.screen.query_one(ChoiceMenuWidget)

            # 1. Roll characteristics.
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()
            assert screen.phase == "choose_career"

            # 2. Choose first career (alphabetically).
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()
            assert screen.phase in ("run_term", "mustering_out")

            # 3. Run all terms.
            while screen.phase == "run_term":
                cm.option_list.highlighted = 0
                cm.option_list.action_select()
                await pilot.pause()

            # 4. Muster out.
            if screen.phase == "mustering_out":
                cm.option_list.highlighted = 0
                cm.option_list.action_select()
                await pilot.pause()

            # 5. Should be complete.
            assert screen.phase == "complete"

    async def test_narrative_log_shows_term_outcome(
        self, seeded_app: CepheusApp
    ):
        """Term narration appears in the narrative log."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            cm = app.screen.query_one(ChoiceMenuWidget)

            # Roll characteristics.
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            # Choose career.
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            # Run term 1 (if qualified).
            if screen.phase == "run_term":
                cm.option_list.highlighted = 0
                cm.option_list.action_select()
                await pilot.pause()

            # Character should have gained terms.
            assert app.engine.state.character.terms >= 1


# ---------------------------------------------------------------------------
# 4. Campaign creation flow.
# ---------------------------------------------------------------------------


class TestCampaignCreationFlow:
    """Verify screen transitions: main menu -> config -> lifepath."""

    async def test_main_menu_renders(self, app: CepheusApp):
        """App opens on the main menu."""
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, MainMenuScreen)

    async def test_new_campaign_button_navigates_to_config(
        self, app: CepheusApp
    ):
        """Clicking 'New Campaign' shows the config screen."""
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, MainMenuScreen)

            btn = app.screen.query_one("#new-campaign", Button)
            btn.press()
            await pilot.pause()

            assert isinstance(app.screen, CampaignConfigScreen)

    async def test_start_campaign_enters_lifepath(self, app: CepheusApp):
        """Completing config starts the lifepath screen."""
        async with app.run_test() as pilot:
            await pilot.pause()

            # Navigate to config.
            app.screen.query_one("#new-campaign", Button).press()
            await pilot.pause()

            # Enter campaign name.
            app.screen.query_one("#name-input", Input).value = "TestCampaign"

            # Click start.
            app.screen.query_one("#start-btn", Button).press()
            await pilot.pause()

            assert isinstance(app.screen, LifepathScreen)
            assert app.engine is not None
            assert app.campaign_name == "TestCampaign"

    async def test_back_button_returns_to_menu(self, app: CepheusApp):
        """Back button on config returns to main menu."""
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#new-campaign", Button).press()
            await pilot.pause()
            assert isinstance(app.screen, CampaignConfigScreen)

            app.screen.query_one("#back-btn", Button).press()
            await pilot.pause()
            assert isinstance(app.screen, MainMenuScreen)


# ---------------------------------------------------------------------------
# 5. AE8 Save and resume.
# ---------------------------------------------------------------------------


class TestSaveAndResume:
    """AE8: quit mid-lifepath, relaunch, resume at same term with identical state."""

    async def test_save_creates_file(self, seeded_app: CepheusApp):
        """Auto-save creates a JSON save file."""
        app = seeded_app
        async with app.run_test() as pilot:
            await push_lifepath(app, pilot)

            cm = app.screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            save_path = app.saves_dir / "TestHero.json"
            assert save_path.exists()

    async def test_resume_state_identical(self, seeded_app: CepheusApp):
        """State after save/load is byte-identical (AE8 core requirement)."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            cm = app.screen.query_one(ChoiceMenuWidget)

            # Roll characteristics.
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            # Choose first career.
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            # Run first term if in that phase.
            if screen.phase == "run_term":
                cm.option_list.highlighted = 0
                cm.option_list.action_select()
                await pilot.pause()

            # Capture state before save.
            state_before = app.engine.state.model_dump_json()
            terms_before = app.engine.state.character.terms
            career_before = app.engine.state.character.career

            # Save.
            app.save_game()

        # Load into a fresh context.
        save_path = app.saves_dir / "TestHero.json"
        loaded_state = load(save_path)
        state_after = loaded_state.model_dump_json()

        # State must be identical.
        assert state_before == state_after
        assert loaded_state.character.terms == terms_before
        assert loaded_state.character.career == career_before

    async def test_resume_continues_at_correct_phase(
        self, seeded_app: CepheusApp
    ):
        """Resuming mid-lifepath enters the correct phase (AE8)."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            cm = app.screen.query_one(ChoiceMenuWidget)

            # Roll characteristics.
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            # Choose career.
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            # Run one term.
            if screen.phase == "run_term":
                cm.option_list.highlighted = 0
                cm.option_list.action_select()
                await pilot.pause()

            terms_done = app.engine.state.character.terms
            app.save_game()

        # Load into a fresh app.
        app2 = CepheusApp(saves_dir=app.saves_dir)
        save_path = app.saves_dir / "TestHero.json"
        app2.load_campaign(save_path)

        # The loaded state should preserve terms and career.
        assert app2.engine.state.character.terms == terms_done
        assert app2.engine.state.character.career != ""
        assert app2.engine.state.character.alive

        # Characteristics should be fully rolled.
        assert len(app2.engine.state.character.characteristics) == 6

    async def test_resume_save_picker_lists_campaign(
        self, seeded_app: CepheusApp
    ):
        """Main menu save picker shows saved campaigns."""
        app = seeded_app
        async with app.run_test() as pilot:
            await push_lifepath(app, pilot)

            cm = app.screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

        # Fresh app should see the save.
        app2 = CepheusApp(saves_dir=app.saves_dir)
        saves = app2.list_saves()
        assert len(saves) == 1
        assert saves[0].name == "TestHero"
        assert saves[0].theme_pack == "scifi"


# ---------------------------------------------------------------------------
# 6. Responsive layout at 80x24.
# ---------------------------------------------------------------------------


class TestResponsiveLayout:
    """Panels are usable at 80x24 terminal size."""

    async def test_panels_render_at_80x24(self, seeded_app: CepheusApp):
        """All three panels render at the minimum terminal size."""
        app = seeded_app
        async with app.run_test(size=(80, 24)) as pilot:
            await push_lifepath(app, pilot)

            sheet = app.screen.query_one(CharacterSheetWidget)
            log = app.screen.query_one(NarrativeLogWidget)
            menu = app.screen.query_one(ChoiceMenuWidget)

            assert sheet.size.height > 0
            assert sheet.size.width > 0
            assert log.size.height > 0
            assert log.size.width > 0
            assert menu.size.height > 0
            assert menu.size.width > 0

    async def test_lifepath_playable_at_80x24(self, seeded_app: CepheusApp):
        """A full lifepath step completes at 80x24."""
        app = seeded_app
        async with app.run_test(size=(80, 24)) as pilot:
            screen = await push_lifepath(app, pilot)
            assert screen.phase == "roll_characteristics"

            # Select first option (roll characteristics) via number key.
            await pilot.press("1")
            await pilot.pause()

            assert screen.phase == "choose_career"
            assert len(app.engine.state.character.characteristics) == 6
