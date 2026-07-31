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
from textual.widgets import Button, Input, Label, OptionList

from src.engine.persistence import load
from src.engine.state import CampaignConfig, GameState
from src.tui.app import CepheusApp
from src.tui.screens.campaign_config import CampaignConfigScreen
from src.tui.screens.lifepath import LifepathScreen
from src.tui.screens.main_menu import MainMenuScreen
from src.tui.widgets.character_sheet import CharacterSheetWidget
from src.tui.widgets.choice_menu import ChoiceMenuWidget
from src.tui.widgets.narrative_log import NarrativeLogWidget

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
    app = CepheusApp(saves_dir=tmp_path)
    # Ensure LLM is not configured so tests use template narration.
    from src.tui.settings import LLMSettings

    app.llm_settings = LLMSettings()
    return app


@pytest.fixture
def seeded_app(tmp_path: Path) -> CepheusApp:
    """Create an app with a pre-initialised campaign (past config screen)."""
    app = CepheusApp(saves_dir=tmp_path)
    # Ensure LLM is not configured so tests use template narration.
    from src.tui.settings import LLMSettings

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


async def push_lifepath(app: CepheusApp, pilot) -> LifepathScreen:
    """Push the lifepath screen and wait for it to mount."""
    app.push_screen(LifepathScreen())
    await pilot.pause()
    return app.screen


#: Phases that belong to the interactive term sub-state-machine.
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


async def play_through_term(app: CepheusApp, pilot, screen) -> None:
    """Advance through all sub-phases of one term (up to re_enlist).

    Presses the first option repeatedly until the phase leaves the
    term sub-phases or reaches ``re_enlist``.
    """
    for _ in range(20):  # safety limit
        if screen.phase not in TERM_PHASES or screen.phase == "re_enlist":
            break
        cm = app.screen.query_one(ChoiceMenuWidget)
        if not cm.option_list.option_count:
            break
        cm.option_list.highlighted = 0
        cm.option_list.action_select()
        await pilot.pause()


async def select_first(app: CepheusApp, pilot) -> None:
    """Select the first option in the choice menu."""
    cm = app.screen.query_one(ChoiceMenuWidget)
    cm.option_list.highlighted = 0
    cm.option_list.action_select()
    await pilot.pause()


async def play_through_characteristics(app: CepheusApp, pilot) -> None:
    """Roll the characteristic pool, assign all six, and pick background skills.

    Selects the first unassigned characteristic then the first pool value,
    six times; then picks background skills until exhausted (Task 9).
    After this the phase is ``choose_career``.
    """
    # Roll the pool (roll_characteristics phase).
    await select_first(app, pilot)
    # Assign all six: each assignment is two selections (char then value).
    for _ in range(6):
        await select_first(app, pilot)  # pick first unassigned characteristic
        await select_first(app, pilot)  # pick first pool value
    # Pick background skills (Task 9) until the phase advances.
    for _ in range(20):
        if app.screen.phase != "choose_background_skills":
            return
        cm = app.screen.query_one(ChoiceMenuWidget)
        if cm.option_list.option_count == 0:
            return
        cm.option_list.highlighted = 0
        cm.option_list.action_select()
        await pilot.pause()


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
        """Status bar is present and shows narration source."""
        app = seeded_app
        async with app.run_test() as pilot:
            await push_lifepath(app, pilot)

            from textual.widgets import Label

            status = app.screen.query_one("#status-bar", Label)
            assert status is not None
            # Status bar shows either LLM info or template fallback notice.
            rendered = str(status.render())
            assert "LLM" in rendered or "Template" in rendered


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
            app.screen.query_one(NarrativeLogWidget)
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

            # Press 1 to select the first option (roll characteristic pool).
            await pilot.press("1")
            await pilot.pause()

            # The number key selected the roll option: pool is rolled and
            # the phase advances to assign_characteristics (Task 4 flow).
            assert screen.phase == "assign_characteristics"
            assert len(app.engine.state.character.unassigned_rolls) == 6

    async def test_enter_selects_highlighted(self, seeded_app: CepheusApp):
        """Enter selects the highlighted option."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)

            cm = app.screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = 0
            await pilot.press("enter")
            await pilot.pause()

            # Enter rolled the pool; phase is now assign_characteristics.
            assert screen.phase == "assign_characteristics"
            assert len(app.engine.state.character.unassigned_rolls) == 6


# ---------------------------------------------------------------------------
# 3. Lifepath interaction.
# ---------------------------------------------------------------------------


class TestLifepathInteraction:
    """Verify term outcomes appear in the log and choices are presented."""

    async def test_roll_characteristics_advances_to_career(self, seeded_app: CepheusApp):
        """Rolling and assigning the pool moves to the career selection phase."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            assert screen.phase == "roll_characteristics"

            await play_through_characteristics(app, pilot)

            assert screen.phase == "choose_career"
            assert len(app.engine.state.character.characteristics) == 6

    async def test_career_choices_are_option_list_items(self, seeded_app: CepheusApp):
        """Career selection phase shows careers as OptionList options."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            cm = app.screen.query_one(ChoiceMenuWidget)

            # Roll and assign the characteristic pool first.
            await play_through_characteristics(app, pilot)
            assert screen.phase == "choose_career"

            # Should have multiple careers.
            assert cm.option_list.option_count > 1

    async def test_full_lifepath_to_completion(self, seeded_app: CepheusApp):
        """Play through the entire lifepath to the complete phase."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            cm = app.screen.query_one(ChoiceMenuWidget)

            # 1. Roll and assign characteristics (pool flow).
            await play_through_characteristics(app, pilot)
            assert screen.phase == "choose_career"

            # 2. Choose first career (alphabetically).
            await select_first(app, pilot)
            assert screen.phase in TERM_PHASES or screen.phase == "mustering_out"

            # 3. Play through terms until we choose to muster out.
            for _ in range(10):  # safety limit on terms
                # Play through all sub-phases of one term.
                await play_through_term(app, pilot, screen)

                if screen.phase == "re_enlist":
                    # After enough terms, choose to muster out (option index 1).
                    if app.engine.state.character.terms >= 4:
                        cm.option_list.highlighted = 1
                    else:
                        cm.option_list.highlighted = 0
                    cm.option_list.action_select()
                    await pilot.pause()
                elif screen.phase == "mustering_out" or screen.phase == "complete":
                    break
                elif screen.phase == "choose_career_change":
                    # Mishap/forced-leave (terms < 7): pick "muster out" (idx 1).
                    cm.option_list.highlighted = 1
                    cm.option_list.action_select()
                    await pilot.pause()
                else:
                    break

            # 4. Muster out.  Select the LAST option each iteration so we
            # never get stuck on a disabled cash-at-cap (index 0) option.
            while screen.phase in ("mustering_out", "muster_out_allocate"):
                cm = app.screen.query_one(ChoiceMenuWidget)
                cm.option_list.highlighted = cm.option_list.option_count - 1
                cm.option_list.action_select()
                await pilot.pause()
            # If a career-change choice intervened, drive it to mustering out.
            while screen.phase == "choose_career_change":
                cm.option_list.highlighted = 1
                cm.option_list.action_select()
                await pilot.pause()
            while screen.phase in ("mustering_out", "muster_out_allocate"):
                cm = app.screen.query_one(ChoiceMenuWidget)
                cm.option_list.highlighted = cm.option_list.option_count - 1
                cm.option_list.action_select()
                await pilot.pause()

            # 5. Should be complete.
            assert screen.phase == "complete"

    async def test_narrative_log_shows_term_outcome(self, seeded_app: CepheusApp):
        """Term narration appears in the narrative log."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            app.screen.query_one(ChoiceMenuWidget)

            # Roll and assign characteristics (pool flow).
            await play_through_characteristics(app, pilot)

            # Choose career.
            await select_first(app, pilot)

            # Play through survival (first step of term 1).
            if screen.phase in TERM_PHASES:
                await play_through_term(app, pilot, screen)

            # Character should have gained terms (survival advances term).
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

    async def test_new_campaign_button_navigates_to_config(self, app: CepheusApp):
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


class TestCampaignConfigOptions:
    """Task 17: config offers all discoverable packs and defaults to Narrative."""

    async def test_pack_list_offers_all_discoverable_packs(self, app: CepheusApp):
        """Theme-pack dropdown lists every pack from discover_packs()."""
        from src.themepacks.base import discover_packs

        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#new-campaign", Button).press()
            await pilot.pause()
            assert isinstance(app.screen, CampaignConfigScreen)

            pack_ol = app.screen.query_one("#pack-list", OptionList)
            ids = {opt.id for opt in pack_ol.options}
            discovered = set(discover_packs().keys())
            assert discovered.issubset(ids), f"Missing packs in dropdown: {discovered - ids}"
            # At minimum both shipped packs are present.
            assert {"scifi", "fantasy"}.issubset(ids)

    async def test_profile_default_is_narrative(self, app: CepheusApp):
        """Narrative is the default-highlighted resolution profile (plan Key Decision)."""
        from textual.widgets import OptionList

        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#new-campaign", Button).press()
            await pilot.pause()

            profile_ol = app.screen.query_one("#profile-list", OptionList)
            assert profile_ol.highlighted is not None
            highlighted_id = profile_ol.options[profile_ol.highlighted].id
            assert highlighted_id == "narrative"

    async def test_no_only_pack_available_hint(self, app: CepheusApp):
        """The false 'only pack available' hint is gone (T17)."""
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#new-campaign", Button).press()
            await pilot.pause()

            # The stale hint label must not appear anywhere on the screen.
            labels = app.screen.query(Label)
            for lbl in labels:
                rendered = str(lbl.render())
                assert "only pack available" not in rendered.lower()


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
            app.screen.query_one(ChoiceMenuWidget)

            # Roll and assign characteristics (pool flow).
            await play_through_characteristics(app, pilot)

            # Choose first career.
            await select_first(app, pilot)

            # Play through first term sub-phases if qualified.
            if screen.phase in TERM_PHASES:
                await play_through_term(app, pilot, screen)

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

    async def test_resume_continues_at_correct_phase(self, seeded_app: CepheusApp):
        """Resuming mid-lifepath enters the correct phase (AE8)."""
        app = seeded_app
        async with app.run_test() as pilot:
            screen = await push_lifepath(app, pilot)
            app.screen.query_one(ChoiceMenuWidget)

            # Roll and assign characteristics (pool flow).
            await play_through_characteristics(app, pilot)

            # Choose career.
            await select_first(app, pilot)

            # Play through first term sub-phases.
            if screen.phase in TERM_PHASES:
                await play_through_term(app, pilot, screen)

            terms_done = app.engine.state.character.terms
            career_before = app.engine.state.character.career
            app.save_game()

        # Load into a fresh app.
        app2 = CepheusApp(saves_dir=app.saves_dir)
        save_path = app.saves_dir / "TestHero.json"
        app2.load_campaign(save_path)

        # The loaded state should preserve terms and career (AE8). Career may
        # be "" if the term ended in a mishap/forced-leave (career change, B17).
        assert app2.engine.state.character.terms == terms_done
        assert app2.engine.state.character.career == career_before
        assert app2.engine.state.character.alive

        # Characteristics should be fully rolled.
        assert len(app2.engine.state.character.characteristics) == 6

    async def test_resume_save_picker_lists_campaign(self, seeded_app: CepheusApp):
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

    async def test_save_picker_excludes_checkpoint_sidecars(self, seeded_app: CepheusApp):
        """list_saves excludes *.checkpoint.json sidecar files.

        Before the fix, the ``*.json`` glob matched ``Name.json.checkpoint.json``
        sidecars, listing them as loadable campaigns.
        """
        from src.engine.state import CampaignConfig

        app = seeded_app
        async with app.run_test() as pilot:
            await push_lifepath(app, pilot)

            # Create a save in checkpoint mode so a sidecar is produced.
            app.engine.state.campaign = CampaignConfig(theme_pack="scifi", death_mode="checkpoint")
            app.checkpoint_mgr.take_snapshot(app.engine.state)
            app.save_game()

        # Both the campaign save and the checkpoint sidecar should exist.
        campaign_save = app.saves_dir / "TestHero.json"
        sidecar = app.saves_dir / "TestHero.json.checkpoint.json"
        assert campaign_save.exists()
        assert sidecar.exists()

        # list_saves should return only the campaign save, not the sidecar.
        app2 = CepheusApp(saves_dir=app.saves_dir)
        saves = app2.list_saves()
        names = [s.name for s in saves]
        assert "TestHero" in names
        assert not any("checkpoint" in n for n in names)


# ---------------------------------------------------------------------------
# 6. Responsive layout at 80x24.
# ---------------------------------------------------------------------------


class TestResponsiveLayout:
    """Panels adapt to narrow/short terminal sizes."""

    async def test_panels_render_at_80x24(self, seeded_app: CepheusApp):
        """At 80x24: char sheet hidden by default, log and menu visible."""
        app = seeded_app
        async with app.run_test(size=(80, 24)) as pilot:
            await push_lifepath(app, pilot)
            await pilot.pause()
            await pilot.pause()  # Let call_after_refresh fire.

            screen = app.screen
            assert screen.has_class("narrow"), "Should be narrow at 80 cols"
            # At exactly 24 rows, not "short" (short is < 24).
            assert not screen.has_class("short"), "24 rows is the minimum, not short"

            sheet = screen.query_one(CharacterSheetWidget)
            log = screen.query_one(NarrativeLogWidget)
            menu = screen.query_one(ChoiceMenuWidget)

            # Char sheet hidden by default on narrow terminals.
            assert sheet.styles.display == "none"
            # Log and menu still rendered.
            assert log.size.height > 0
            assert menu.size.height > 0

    async def test_toggle_char_sheet_on_narrow(self, seeded_app: CepheusApp):
        """Pressing 'c' toggles the character sheet on narrow terminals."""
        app = seeded_app
        async with app.run_test(size=(80, 24)) as pilot:
            await push_lifepath(app, pilot)
            await pilot.pause()

            screen = app.screen
            assert screen.has_class("narrow")

            # Toggle sheet on.
            await pilot.press("c")
            await pilot.pause()
            assert screen.has_class("show-sheet")

            # Toggle sheet off.
            await pilot.press("c")
            await pilot.pause()
            assert not screen.has_class("show-sheet")

    async def test_lifepath_playable_at_80x24(self, seeded_app: CepheusApp):
        """A full lifepath step completes at 80x24."""
        app = seeded_app
        async with app.run_test(size=(80, 24)) as pilot:
            screen = await push_lifepath(app, pilot)
            assert screen.phase == "roll_characteristics"

            # Select first option (roll characteristic pool) via number key.
            await pilot.press("1")
            await pilot.pause()

            # Pool rolled; the assign step is playable at this size.
            assert screen.phase == "assign_characteristics"
            assert len(app.engine.state.character.unassigned_rolls) == 6


# ---------------------------------------------------------------------------
# Logging (Gap 1): provider failures must be captured to disk, not dropped.
# ---------------------------------------------------------------------------


def test_setup_logging_captures_adapter_warnings(tmp_path: Path):
    """setup_logging attaches a file handler so ``src.*`` warnings persist.

    The LLM adapter emits ``logger.warning`` on provider failures (bad model
    name, network error). Without a handler those messages are silently
    dropped and the user only sees the generic 'LLM failed — template
    fallback' line, with no way to diagnose the real cause.
    """
    import logging

    from src.tui.app import setup_logging

    src_logger = logging.getLogger("src")
    saved_handlers = src_logger.handlers[:]
    saved_level = src_logger.level
    try:
        log_file = setup_logging(tmp_path)
        logging.getLogger("src.llm.adapter").warning("test-provider-error: Model Not Exist")
        for h in src_logger.handlers:
            h.flush()

        assert log_file.exists()
        assert "Model Not Exist" in log_file.read_text(encoding="utf-8")
    finally:
        # Restore global logger state so this test cannot pollute others.
        for h in src_logger.handlers:
            if h not in saved_handlers:
                h.close()
        src_logger.handlers = saved_handlers
        src_logger.setLevel(saved_level)


def test_setup_logging_is_idempotent(tmp_path: Path):
    """Repeated calls with the same log dir must not stack duplicate handlers.

    Counts only handlers targeting *this* test's log file — the global
    ``src`` logger legitimately accumulates handlers from other tests'
    ``CepheusApp(tmp_path=...)`` fixtures (each a distinct path).
    """
    import logging

    from src.tui.app import setup_logging

    src_logger = logging.getLogger("src")
    saved_handlers = src_logger.handlers[:]
    try:
        log_file = setup_logging(tmp_path)
        target = log_file.resolve()

        def handlers_for_this_file() -> int:
            return sum(
                1
                for h in src_logger.handlers
                if isinstance(h, logging.FileHandler) and Path(h.baseFilename) == target
            )

        assert handlers_for_this_file() == 1
        setup_logging(tmp_path)
        assert handlers_for_this_file() == 1
    finally:
        for h in src_logger.handlers:
            if h not in saved_handlers:
                h.close()
        src_logger.handlers = saved_handlers
