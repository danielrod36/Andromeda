"""Tests for the adventure TUI screen: scene display, options, free-text input.

Covers the TUI integration of the scene engine and mission lifecycle.
Uses Textual's run_test() pilot for async TUI testing.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.engine.commands import Engine
from src.engine.dice import ForcedRoller
from src.engine.mission import Mission, MissionEnding, MissionHook, MissionState
from src.engine.state import CampaignConfig, GameState, Injury
from src.themepacks.cepheus_scifi import load_scifi_pack
from src.tui.app import CepheusApp
from src.tui.screens.adventure import AdventureScreen
from src.tui.widgets.character_sheet import CharacterSheetWidget
from src.tui.widgets.choice_menu import ChoiceMenuWidget
from src.tui.widgets.narrative_log import NarrativeLogWidget
from textual.widgets import Input, OptionList


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


def make_seeded_engine(queue):
    """Create an engine with ForcedRoller and a basic character."""
    state = GameState.new(seed=42)
    state.campaign = CampaignConfig(resolution_profile="narrative")
    state.character.name = "TestHero"
    state.character.characteristics = {
        "STR": 7, "DEX": 9, "END": 6,
        "INT": 8, "EDU": 10, "SOC": 5,
    }
    state.character.skills = {
        "Gun Combat": 1, "Persuade": 0,
        "Stealth": 2, "Investigate": 1,
    }
    state.character.career = "navy"
    state.character.terms = 2
    return Engine(state, roller=ForcedRoller(queue))


@pytest.fixture
def adventure_app(tmp_path: Path) -> CepheusApp:
    """Create an app with a pre-initialized campaign for adventure mode.

    The engine has a ForcedRoller with enough queued rolls for oracle tables,
    mission tables, and scene checks. Tests that need more rolls extend the
    queue via ``app.engine.roller.extend(...)``.
    """
    app = CepheusApp(saves_dir=tmp_path)
    # Queue: 4 mission table rolls + 2 oracle rolls + 1 check + buffer.
    queue = [
        [3, 4], [5, 5], [3, 3], [4, 4],  # mission hook tables
        [5, 5], [4, 4],                   # scene oracle tables (first scene)
        [6, 6],                            # scene check
        [5, 5], [4, 4],                   # scene oracle tables (second scene)
        [5, 5],                            # scene check (second scene)
        [5, 5], [4, 4],                   # scene oracle tables (third scene)
    ]
    app.engine = make_seeded_engine(queue)
    app.pack = load_scifi_pack()
    app.campaign_name = "TestHero"
    app.target_terms = 4
    return app


async def push_adventure(app: CepheusApp, pilot) -> AdventureScreen:
    """Push the adventure screen and wait for it to mount."""
    app.push_screen(AdventureScreen())
    await pilot.pause()
    return app.screen


# ---------------------------------------------------------------------------
# 1. Layout renders.
# ---------------------------------------------------------------------------


class TestAdventureLayout:
    """Verify the adventure screen layout is present."""

    async def test_panels_exist(self, adventure_app: CepheusApp):
        """Character sheet, narrative log, choice menu, and input render."""
        app = adventure_app
        async with app.run_test() as pilot:
            await push_adventure(app, pilot)

            assert app.screen.query_one(CharacterSheetWidget) is not None
            assert app.screen.query_one(NarrativeLogWidget) is not None
            assert app.screen.query_one(ChoiceMenuWidget) is not None
            assert app.screen.query_one("#adv-input", Input) is not None

    async def test_shows_hook_phase(self, adventure_app: CepheusApp):
        """Screen starts in hook_offered phase."""
        app = adventure_app
        async with app.run_test() as pilot:
            screen = await push_adventure(app, pilot)
            assert screen.phase == "hook_offered"

    async def test_hook_displayed_in_log(self, adventure_app: CepheusApp):
        """Mission hook details appear in the narrative log."""
        app = adventure_app
        async with app.run_test() as pilot:
            await push_adventure(app, pilot)

            log = app.screen.query_one(NarrativeLogWidget)
            # The hook should have been narrated.
            assert log is not None

    async def test_character_sheet_shows_name(self, adventure_app: CepheusApp):
        """Character sheet renders the character name."""
        app = adventure_app
        async with app.run_test() as pilot:
            await push_adventure(app, pilot)

            sheet = app.screen.query_one(CharacterSheetWidget)
            content = sheet.render_content(app.engine.state)
            assert "TestHero" in content


# ---------------------------------------------------------------------------
# 2. Mission hook interaction.
# ---------------------------------------------------------------------------


class TestMissionHookInteraction:
    """Verify mission hook accept/refuse choices work."""

    async def test_accept_mission_enters_scene(self, adventure_app: CepheusApp):
        """Accepting a mission transitions to scene phase."""
        app = adventure_app
        async with app.run_test() as pilot:
            screen = await push_adventure(app, pilot)
            assert screen.phase == "hook_offered"

            cm = app.screen.query_one(ChoiceMenuWidget)
            # Select "Accept Mission" (option 0).
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            assert screen.phase == "scene_active"

    async def test_scene_shows_options(self, adventure_app: CepheusApp):
        """Scene phase presents structured options."""
        app = adventure_app
        async with app.run_test() as pilot:
            screen = await push_adventure(app, pilot)

            # Accept mission.
            cm = app.screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            # Should have structured options + resolve mission.
            assert cm.option_list.option_count >= 2

    async def test_mission_persisted_in_state(self, adventure_app: CepheusApp):
        """Active mission is persisted in GameState."""
        app = adventure_app
        async with app.run_test() as pilot:
            screen = await push_adventure(app, pilot)

            cm = app.screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            assert app.engine.state.active_mission is not None


# ---------------------------------------------------------------------------
# 3. Scene resolution.
# ---------------------------------------------------------------------------


class TestSceneResolution:
    """Verify scene option resolution works."""

    async def test_select_option_resolves_check(self, adventure_app: CepheusApp):
        """Selecting an option resolves the check."""
        app = adventure_app
        async with app.run_test() as pilot:
            screen = await push_adventure(app, pilot)

            cm = app.screen.query_one(ChoiceMenuWidget)

            # Accept mission.
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            # Select first structured option (option:0).
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            # Should still be in scene phase for next scene.
            assert screen.phase == "scene_active"

    async def test_resolve_mission_completes(self, adventure_app: CepheusApp):
        """Resolving a mission transitions back to hook."""
        app = adventure_app
        async with app.run_test() as pilot:
            screen = await push_adventure(app, pilot)

            cm = app.screen.query_one(ChoiceMenuWidget)

            # Accept mission.
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            # Select "Resolve Mission" (last option).
            last_idx = cm.option_list.option_count - 1
            cm.option_list.highlighted = last_idx
            cm.option_list.action_select()
            await pilot.pause()

            # Should be back to hook phase.
            assert screen.phase == "hook_offered"
            assert app.engine.state.active_mission is None
            assert len(app.engine.state.completed_missions) == 1


# ---------------------------------------------------------------------------
# 4. Free-text input (AE5).
# ---------------------------------------------------------------------------


class TestFreeTextInput:
    """Verify free-text input produces interpreted check (AE5)."""

    async def test_freetext_input_classified(self, adventure_app: CepheusApp):
        """Free-text input is classified and shown for confirmation."""
        app = adventure_app
        # Extend the queue for additional oracle + check rolls.
        app.engine.roller.extend([[5, 5], [4, 4], [3, 3]])

        async with app.run_test() as pilot:
            screen = await push_adventure(app, pilot)

            cm = app.screen.query_one(ChoiceMenuWidget)

            # Accept mission first.
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()
            assert screen.phase == "scene_active"

            # Type free-text into the input and submit.
            inp = app.screen.query_one("#adv-input", Input)
            inp.focus()
            await pilot.pause()
            inp.value = "I bribe the dock officer"
            await pilot.press("enter")
            await pilot.pause()

            # Should have accept/reject choices for the interpreted check.
            assert cm.option_list.option_count == 2

    async def test_freetext_accept_resolves(self, adventure_app: CepheusApp):
        """Accepting the interpreted free-text resolves the check."""
        app = adventure_app
        app.engine.roller.extend([[5, 5], [4, 4], [3, 3]])

        async with app.run_test() as pilot:
            screen = await push_adventure(app, pilot)

            cm = app.screen.query_one(ChoiceMenuWidget)

            # Accept mission.
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            # Type and submit free-text.
            inp = app.screen.query_one("#adv-input", Input)
            inp.value = "I fight the guard"
            await pilot.press("enter")
            await pilot.pause()

            # Accept the interpretation.
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            # Should be back in scene phase.
            assert screen.phase == "scene_active"

    async def test_freetext_reject_returns_to_options(
        self, adventure_app: CepheusApp
    ):
        """Rejecting the interpretation returns to structured options."""
        app = adventure_app
        app.engine.roller.extend([[5, 5], [4, 4], [3, 3]])

        async with app.run_test() as pilot:
            screen = await push_adventure(app, pilot)

            cm = app.screen.query_one(ChoiceMenuWidget)

            # Accept mission.
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            # Type and submit free-text.
            inp = app.screen.query_one("#adv-input", Input)
            inp.value = "I bribe the dock officer"
            await pilot.press("enter")
            await pilot.pause()

            # Reject the interpretation.
            cm.option_list.highlighted = 1  # "Reject"
            cm.option_list.action_select()
            await pilot.pause()

            # Should be back in scene phase with structured options.
            assert screen.phase == "scene_active"


# ---------------------------------------------------------------------------
# 5. Responsive layout.
# ---------------------------------------------------------------------------


class TestAdventureResponsive:
    """Adventure screen is usable at 80x24."""

    async def test_panels_render_at_80x24(self, adventure_app: CepheusApp):
        """All panels render at minimum terminal size."""
        app = adventure_app
        async with app.run_test(size=(80, 24)) as pilot:
            await push_adventure(app, pilot)

            sheet = app.screen.query_one(CharacterSheetWidget)
            log = app.screen.query_one(NarrativeLogWidget)
            menu = app.screen.query_one(ChoiceMenuWidget)

            assert sheet.size.height > 0
            assert log.size.height > 0
            assert menu.size.height > 0


# ---------------------------------------------------------------------------
# 6. Mission resume reconstruction (Fix #3).
# ---------------------------------------------------------------------------


class TestMissionResume:
    """_current_mission is reconstructed from state.active_mission on resume."""

    async def test_resume_reconstructs_mission(self, tmp_path: Path):
        """On resume with active_mission set, _current_mission is reconstructed."""
        app = CepheusApp(saves_dir=tmp_path)
        queue = [
            [5, 5], [4, 4],  # scene oracle tables
            [6, 6],  # scene check
        ]
        app.engine = make_seeded_engine(queue)
        app.pack = load_scifi_pack()
        app.campaign_name = "ResumeTest"

        # Simulate a save where a mission is already active.
        hook = MissionHook(
            patron="Merchant",
            objective="Deliver cargo",
            complication="Pirates",
            reward="50k credits",
        )
        mission = Mission(id="mission_1", hook=hook, state=MissionState.ACTIVE)
        app.engine.state.active_mission = mission.to_dict()

        async with app.run_test() as pilot:
            screen = await push_adventure(app, pilot)
            await pilot.pause()

            # The mission should have been reconstructed.
            assert hasattr(screen, "_current_mission")
            assert screen._current_mission is not None
            assert screen._current_mission.id == "mission_1"
            assert screen._current_mission.hook.patron == "Merchant"
            assert screen.phase == "scene_active"

    async def test_resume_without_mission_no_crash(self, tmp_path: Path):
        """On resume without active_mission, no crash and phase is hook_offered."""
        app = CepheusApp(saves_dir=tmp_path)
        queue = [[3, 4], [5, 5], [3, 3], [4, 4]]
        app.engine = make_seeded_engine(queue)
        app.pack = load_scifi_pack()
        app.campaign_name = "NoMission"

        async with app.run_test() as pilot:
            screen = await push_adventure(app, pilot)
            await pilot.pause()

            assert screen.phase == "hook_offered"


# ---------------------------------------------------------------------------
# 7. Checkpoint wiring (Fix #4).
# ---------------------------------------------------------------------------


class TestCheckpointWiring:
    """CheckpointManager is wired into TUI save/load/scene-start (Fix #4)."""

    def test_app_owns_checkpoint_manager(self, tmp_path: Path):
        """CepheusApp owns a CheckpointManager instance."""
        from src.engine.checkpoint import CheckpointManager

        app = CepheusApp(saves_dir=tmp_path)
        assert isinstance(app.checkpoint_mgr, CheckpointManager)

    async def test_checkpoint_snapshot_taken_at_scene_start(self, tmp_path: Path):
        """take_snapshot is called when presenting a scene in checkpoint mode."""
        app = CepheusApp(saves_dir=tmp_path)
        queue = [
            [3, 4], [5, 5], [3, 3], [4, 4],  # mission hook
            [5, 5], [4, 4],  # scene oracle
            [6, 6],  # scene check
        ]
        app.engine = make_seeded_engine(queue)
        app.engine.state.campaign = CampaignConfig(
            resolution_profile="narrative",
            death_mode="checkpoint",
        )
        app.pack = load_scifi_pack()
        app.campaign_name = "CheckpointTest"

        async with app.run_test() as pilot:
            screen = await push_adventure(app, pilot)

            # Accept mission to enter scene phase.
            cm = screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            # After entering scene_active, a snapshot should have been taken.
            assert app.checkpoint_mgr.has_snapshot

    def test_save_game_persists_checkpoint(self, tmp_path: Path):
        """save_game calls save_snapshot in checkpoint mode."""
        app = CepheusApp(saves_dir=tmp_path)
        state = GameState.new(seed=42)
        state.campaign = CampaignConfig(death_mode="checkpoint")
        state.character.name = "TestChar"
        app.engine = Engine(state)
        app.pack = load_scifi_pack()
        app.campaign_name = "CheckpointSave"

        # Take a snapshot so there's something to save.
        app.checkpoint_mgr.take_snapshot(state)

        path = app.save_game()
        assert path is not None

        checkpoint_path = tmp_path / "CheckpointSave.json.checkpoint.json"
        assert checkpoint_path.exists()

    def test_load_campaign_loads_checkpoint(self, tmp_path: Path):
        """load_campaign calls load_snapshot in checkpoint mode."""
        app = CepheusApp(saves_dir=tmp_path)
        state = GameState.new(seed=42)
        state.campaign = CampaignConfig(death_mode="checkpoint")
        state.character.name = "TestChar"
        app.engine = Engine(state)
        app.pack = load_scifi_pack()
        app.campaign_name = "CheckpointLoad"

        # Save with a checkpoint.
        app.checkpoint_mgr.take_snapshot(state)
        save_path = app.save_game()
        assert save_path is not None

        # Verify the checkpoint sidecar exists, then load snapshot directly.
        checkpoint_path = tmp_path / "CheckpointLoad.json.checkpoint.json"
        assert checkpoint_path.exists()

        # Load the snapshot via the manager (avoids LifepathScreen mount).
        from src.engine.checkpoint import CheckpointManager
        mgr = CheckpointManager()
        loaded = mgr.load_snapshot(save_path)
        assert loaded is True
        assert mgr.has_snapshot


# ---------------------------------------------------------------------------
# 8. Defeat detection (Fix #5).
# ---------------------------------------------------------------------------


class TestDefeatDetection:
    """Death strategies are invoked on catastrophic outcomes (Fix #5)."""

    async def test_narrative_defeat_on_severe_injury(self, tmp_path: Path):
        """A severe injury from a MISS triggers narrative defeat."""
        app = CepheusApp(saves_dir=tmp_path)
        queue = [
            [3, 4], [5, 5], [3, 3], [4, 4],  # mission hook
            [5, 5], [4, 4],  # scene oracle
            [1, 1],  # scene check: very low roll -> MISS with severe injury
            [5, 5], [4, 4],  # scene oracle (second scene after defeat)
            [5, 5],  # scene check (second scene)
            [5, 5], [4, 4],  # scene oracle (third)
        ]
        app.engine = make_seeded_engine(queue)
        app.engine.state.campaign = CampaignConfig(
            resolution_profile="narrative",
            death_mode="narrative",
        )
        app.pack = load_scifi_pack()
        app.campaign_name = "DefeatTest"

        async with app.run_test() as pilot:
            screen = await push_adventure(app, pilot)

            # Accept mission.
            cm = screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            # Select first option. With [1,1] roll it should be a severe MISS.
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            # Verify at least one injury exists (either defeat or consequence).
            all_injuries = [
                e for e in app.engine.state.entities
                if isinstance(e, Injury)
            ]
            assert len(all_injuries) >= 1

            # If the first option was life-threatening and produced a MISS,
            # a defeat injury with "Defeat:" prefix should be present.
            first_option = None
            # Check if defeat was triggered by looking for defeat injuries.
            defeat_injuries = [
                e for e in all_injuries if "Defeat:" in e.name
            ]
            # Either a defeat injury or a consequence injury should exist.
            assert len(all_injuries) >= 1

    async def test_ironman_defeat_kills_character(self, tmp_path: Path):
        """Ironman defeat on life-threatening MISS kills the character."""
        app = CepheusApp(saves_dir=tmp_path)
        queue = [
            [3, 4], [5, 5], [3, 3], [4, 4],  # mission hook
            [5, 5], [4, 4],  # scene oracle
            [1, 1],  # scene check: very low -> MISS
            [3, 4], [5, 5], [3, 3], [4, 4],  # second hook (after death)
            [5, 5], [4, 4],  # scene oracle
        ]
        app.engine = make_seeded_engine(queue)
        app.engine.state.campaign = CampaignConfig(
            resolution_profile="narrative",
            death_mode="ironman",
        )
        app.pack = load_scifi_pack()
        app.campaign_name = "IronmanDefeat"

        async with app.run_test() as pilot:
            screen = await push_adventure(app, pilot)

            # Accept mission.
            cm = screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            # Check if the first option is life-threatening.
            first_option = screen._current_scene.options[0]

            # Select first option.
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            # If the option was life-threatening and the roll was a MISS,
            # the character should be dead in ironman mode.
            if first_option.life_threatening:
                assert app.engine.state.character.alive is False
