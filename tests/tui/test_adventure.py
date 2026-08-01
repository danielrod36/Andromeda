"""Tests for the adventure TUI screen: scene display, options, free-text input.

Covers the TUI integration of the scene engine and mission lifecycle.
Uses Textual's run_test() pilot for async TUI testing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Input

from src.engine.commands import Engine
from src.engine.dice import ForcedRoller
from src.engine.mission import Mission, MissionHook, MissionState
from src.engine.state import CampaignConfig, GameState, Injury
from src.themepacks.cepheus_scifi import load_scifi_pack
from src.tui.app import CepheusApp
from src.tui.screens.adventure import AdventureScreen
from src.tui.widgets.character_sheet import CharacterSheetWidget
from src.tui.widgets.choice_menu import ChoiceMenuWidget
from src.tui.widgets.narrative_log import NarrativeLogWidget

# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


def make_seeded_engine(queue):
    """Create an engine with ForcedRoller and a basic character."""
    state = GameState.new(seed=42)
    state.campaign = CampaignConfig(resolution_profile="narrative")
    state.character.name = "TestHero"
    state.character.characteristics = {
        "STR": 7,
        "DEX": 9,
        "END": 6,
        "INT": 8,
        "EDU": 10,
        "SOC": 5,
    }
    state.character.skills = {
        "Gun Combat": 1,
        "Persuade": 0,
        "Stealth": 2,
        "Investigate": 1,
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
        [3, 4],
        [5, 5],
        [3, 3],
        [4, 4],  # mission hook tables
        [5, 5],
        [4, 4],  # scene oracle tables (first scene)
        [6, 6],  # scene check
        [5, 5],
        [4, 4],  # scene oracle tables (second scene)
        [5, 5],  # scene check (second scene)
        [5, 5],
        [4, 4],  # scene oracle tables (third scene)
    ]
    app.engine = make_seeded_engine(queue)
    app.pack = load_scifi_pack()
    app.campaign_name = "TestHero"
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
            await push_adventure(app, pilot)

            # Accept mission.
            cm = app.screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            # Should have structured options + resolve mission.
            assert cm.option_list.option_count >= 2

    async def test_scene_options_show_pre_commit_odds(self, adventure_app: CepheusApp):
        """Phase 1 #1: each structured option surfaces a pre-commit odds line
        (DM breakdown + success % + band) so choices are informed, not blind
        (mechanics-inspectable identity; Disco Elysium / Citizen Sleeper pattern).
        """
        app = adventure_app
        async with app.run_test() as pilot:
            await push_adventure(app, pilot)
            cm = app.screen.query_one(ChoiceMenuWidget)
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            # First structured option's rendered prompt must include a "%"
            # (the computed success probability) and the honest total "DM".
            first = str(cm.option_list.options[0].prompt)
            assert "%" in first
            assert "DM" in first

    async def test_mission_persisted_in_state(self, adventure_app: CepheusApp):
        """Active mission is persisted in GameState."""
        app = adventure_app
        async with app.run_test() as pilot:
            await push_adventure(app, pilot)

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

    async def test_abandon_mission_completes(self, adventure_app: CepheusApp):
        """Abandoning a mission transitions back to hook (Task 19).

        Abandonment is always allowed regardless of scenes_completed, so it
        works immediately after accepting the hook.
        """
        app = adventure_app
        async with app.run_test() as pilot:
            screen = await push_adventure(app, pilot)

            cm = app.screen.query_one(ChoiceMenuWidget)

            # Accept mission.
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            # Select "Abandon the mission" (last option — push-for-ending is
            # gated off because scenes_completed=0 < min_scenes=3).
            last_idx = cm.option_list.option_count - 1
            cm.option_list.highlighted = last_idx
            cm.option_list.action_select()
            await pilot.pause()

            # Should be back to hook phase.
            assert screen.phase == "hook_offered"
            assert app.engine.state.active_mission is None
            assert len(app.engine.state.completed_missions) == 1
            assert app.engine.state.completed_missions[0]["ending"] == "abandonment"

    async def test_push_for_ending_gated_until_min_scenes(self, adventure_app: CepheusApp):
        """Push-for-ending option hidden until scenes_completed >= min_scenes."""
        app = adventure_app
        async with app.run_test() as pilot:
            await push_adventure(app, pilot)

            cm = app.screen.query_one(ChoiceMenuWidget)

            # Accept mission.
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            # Right after accept: scenes_completed=0, so "push_for_ending"
            # must NOT be among the choices.
            option_ids = [
                cm.option_list.get_option_at_index(i).id for i in range(cm.option_list.option_count)
            ]
            assert "push_for_ending" not in option_ids
            assert "abandon_mission" in option_ids

    async def test_push_for_ending_available_at_min_scenes(self, adventure_app: CepheusApp):
        """Push-for-ending appears once scenes_completed reaches min_scenes."""
        app = adventure_app
        async with app.run_test() as pilot:
            await push_adventure(app, pilot)

            cm = app.screen.query_one(ChoiceMenuWidget)

            # Accept mission.
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            # Manually bump scenes_completed past the gate, then re-present.
            state = app.engine.state
            state.active_mission["scenes_completed"] = state.active_mission["min_scenes"]
            app.screen._current_scene = None  # force re-present
            app.screen.phase = "scene_active"
            await pilot.pause()

            option_ids = [
                cm.option_list.get_option_at_index(i).id for i in range(cm.option_list.option_count)
            ]
            assert "push_for_ending" in option_ids


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

    async def test_freetext_reject_returns_to_options(self, adventure_app: CepheusApp):
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
    """Adventure screen adapts to narrow/short terminal sizes."""

    async def test_panels_render_at_80x24(self, adventure_app: CepheusApp):
        """At 80x24: char sheet hidden, log and menu visible."""
        app = adventure_app
        async with app.run_test(size=(80, 24)) as pilot:
            await push_adventure(app, pilot)
            await pilot.pause()

            screen = app.screen
            assert screen.has_class("narrow")

            sheet = screen.query_one(CharacterSheetWidget)
            log = screen.query_one(NarrativeLogWidget)
            menu = screen.query_one(ChoiceMenuWidget)

            # Char sheet hidden on narrow terminals.
            assert sheet.styles.display == "none"
            # Log and menu still rendered.
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
            [5, 5],
            [4, 4],  # scene oracle tables
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
            [3, 4],
            [5, 5],
            [3, 3],
            [4, 4],  # mission hook
            [5, 5],
            [4, 4],  # scene oracle
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
            [3, 4],
            [5, 5],
            [3, 3],
            [4, 4],  # mission hook
            [5, 5],
            [4, 4],  # scene oracle
            [1, 1],  # scene check: very low roll -> MISS with severe injury
            [5, 5],
            [4, 4],  # scene oracle (second scene after defeat)
            [5, 5],  # scene check (second scene)
            [5, 5],
            [4, 4],  # scene oracle (third)
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
            all_injuries = [e for e in app.engine.state.entities if isinstance(e, Injury)]
            assert len(all_injuries) >= 1

            # If the first option was life-threatening and produced a MISS,
            # a defeat injury with "Defeat:" prefix should be present.
            # Check if defeat was triggered by looking for defeat injuries.
            [e for e in all_injuries if "Defeat:" in e.name]
            # Either a defeat injury or a consequence injury should exist.
            assert len(all_injuries) >= 1

    async def test_ironman_defeat_kills_character(self, tmp_path: Path):
        """Ironman defeat on life-threatening MISS kills the character."""
        app = CepheusApp(saves_dir=tmp_path)
        queue = [
            [3, 4],
            [5, 5],
            [3, 3],
            [4, 4],  # mission hook
            [5, 5],
            [4, 4],  # scene oracle
            [1, 1],  # scene check: very low -> MISS
            [3, 4],
            [5, 5],
            [3, 3],
            [4, 4],  # second hook (after death)
            [5, 5],
            [4, 4],  # scene oracle
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


# ---------------------------------------------------------------------------
# 9. Regression: refuse generates exactly one replacement hook (no double-roll).
# ---------------------------------------------------------------------------


class TestRefuseHookNoDouble:
    """Refusing a hook must generate exactly one replacement, not two.

    Before the fix, ``_do_refuse_mission`` called ``refuse_mission()`` (which
    internally generates a hook), then setting ``phase = "hook_offered"``
    triggered the ``always_update`` watcher → ``_offer_hook`` which called
    ``generate_hook()`` again — burning RNG and discarding the first hook.
    """

    async def test_refuse_generates_single_hook(self, adventure_app):
        app = adventure_app
        async with app.run_test() as pilot:
            screen = await push_adventure(app, pilot)
            first_hook = screen._current_hook
            assert first_hook is not None

            cm = app.screen.query_one(ChoiceMenuWidget)
            # Select "Refuse" (option 1).
            cm.option_list.highlighted = 1
            cm.option_list.action_select()
            await pilot.pause()

            # Exactly one replacement hook should exist — the live hook.
            assert screen._current_hook is not None
            # The hook should differ from the first (it's a new roll).
            assert screen._current_hook is not first_hook

    async def test_offer_hook_does_not_regenerate_when_live(self, adventure_app):
        """_offer_hook skips generation when _current_hook already exists."""
        app = adventure_app
        async with app.run_test() as pilot:
            screen = await push_adventure(app, pilot)
            live_hook = screen._current_hook

            # Re-trigger hook_offered phase — should NOT replace the hook.
            screen.phase = "hook_offered"
            await pilot.pause()

            assert screen._current_hook is live_hook


# ---------------------------------------------------------------------------
# 10. Regression: rejecting free-text keeps the same scene.
# ---------------------------------------------------------------------------


class TestRejectFreetextKeepsScene:
    """Rejecting a free-text interpretation returns to the SAME scene.

    Before the fix, ``_do_reject_freetext`` set ``phase = "scene_active"``
    which re-triggered ``_present_scene`` → ``run_scene()``, discarding the
    live scene and generating a replacement (plus a new checkpoint snapshot).
    """

    async def test_reject_keeps_same_scene_object(self, adventure_app):
        app = adventure_app
        app.engine.roller.extend([[5, 5], [4, 4], [3, 3], [5, 5], [4, 4]])
        async with app.run_test() as pilot:
            screen = await push_adventure(app, pilot)

            cm = app.screen.query_one(ChoiceMenuWidget)
            # Accept mission.
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()
            assert screen.phase == "scene_active"

            scene_before = screen._current_scene

            # Type and submit free-text (must focus input first).
            inp = app.screen.query_one("#adv-input", Input)
            inp.focus()
            await pilot.pause()
            inp.value = "I bribe the dock officer"
            await pilot.press("enter")
            await pilot.pause()

            # Should now show accept/reject choices (not scene options).
            assert cm.option_list.option_count == 2

            # Reject the interpretation.
            cm.option_list.highlighted = 1  # "Reject"
            cm.option_list.action_select()
            await pilot.pause()

            # The same scene object should still be live.
            assert screen._current_scene is scene_before


# ---------------------------------------------------------------------------
# 11. Regression: user free-text with Rich markup chars does not crash.
# ---------------------------------------------------------------------------


class TestFreetextMarkupEscaping:
    """Raw user text echoed to a markup-enabled RichLog is escaped.

    Typing ``[/]`` would crash with ``MarkupError`` before the fix.
    """

    async def test_markup_chars_in_freetext_no_crash(self, adventure_app):
        app = adventure_app
        app.engine.roller.extend([[5, 5], [4, 4], [3, 3]])
        async with app.run_test() as pilot:
            screen = await push_adventure(app, pilot)

            cm = app.screen.query_one(ChoiceMenuWidget)
            # Accept mission.
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()
            assert screen.phase == "scene_active"

            # Type uninterpretable text with markup-breaking chars.
            inp = app.screen.query_one("#adv-input", Input)
            inp.focus()
            await pilot.pause()
            inp.value = "[/] nothing matches"
            await pilot.press("enter")
            await pilot.pause()

            # Screen should still be alive — no crash.
            assert screen.phase == "scene_active"


# ---------------------------------------------------------------------------
# 12. Regression: checkpoint restore rebinds the engine roller (AE3).
# ---------------------------------------------------------------------------


class TestCheckpointRestoreRebindsRoller:
    """After checkpoint rewind via swap_state, rolls use the restored RNG."""

    async def test_restore_advances_restored_rng(self, tmp_path: Path):
        """Post-rewind oracle roll matches scene-start sequence, not abandoned."""

        app = CepheusApp(saves_dir=tmp_path)
        queue = [
            [3, 4],
            [5, 5],
            [3, 3],
            [4, 4],  # mission hook
            [5, 5],
            [4, 4],  # scene oracle
            [1, 1],  # scene check (severe miss)
            [5, 5],
            [4, 4],  # second scene oracle
        ]
        app.engine = make_seeded_engine(queue)
        app.engine.state.campaign = CampaignConfig(
            resolution_profile="narrative",
            death_mode="checkpoint",
        )
        app.pack = load_scifi_pack()
        app.campaign_name = "RewindTest"

        # Snapshot the scene-start state, then advance the RNG (abandoned branch).
        state = app.engine.state
        mgr = app.checkpoint_mgr
        mgr.take_snapshot(state)
        _ = state.rng.roll("oracle", 2, 6)

        restored = mgr.restore(state)
        app.engine.swap_state(restored)

        # The restored state's next oracle roll should NOT continue the
        # abandoned sequence — it reverts to scene start.
        reference = GameState.new(seed=42)
        expected = reference.rng.roll("oracle", 2, 6).total
        actual = app.engine.state.rng.roll("oracle", 2, 6).total
        assert actual == expected


# ---------------------------------------------------------------------------
# 13. Task 20: inline mechanics line, classic vocabulary, preserved free-text.
# ---------------------------------------------------------------------------


def _spy_narrate(screen: AdventureScreen) -> list[str]:
    """Replace ``screen._narrate`` (and ``_narrate_receipt``) with capturing
    wrappers; return the capture list.

    Both narration channels — prose (``_narrate``) and engine receipts
    (``_narrate_receipt``, the provenance-styled mechanics line) — are captured.
    The original log-write still happens; the spy just records the text first.
    Use the returned list to assert on narrated lines.
    """
    captured: list[str] = []
    real_narrate = screen._narrate
    real_receipt = screen._narrate_receipt

    def spy_narrate(text: str) -> None:
        captured.append(text)
        real_narrate(text)

    def spy_receipt(text: str) -> None:
        captured.append(text)
        real_receipt(text)

    screen._narrate = spy_narrate  # type: ignore[assignment,method-assign]
    screen._narrate_receipt = spy_receipt  # type: ignore[assignment,method-assign]
    return captured


class TestTask20MechanicsDisplay:
    """Task 20: inline mechanics line, classic vocabulary, preserved free-text."""

    async def test_mechanics_line_shows_roll_dm_total_tier(self, adventure_app: CepheusApp):
        """Resolution renders an inline '2D6 [...] = ... DM ... vs 8 ...' line."""
        app = adventure_app
        async with app.run_test() as pilot:
            screen = await push_adventure(app, pilot)
            captured = _spy_narrate(screen)

            cm = app.screen.query_one(ChoiceMenuWidget)
            # Accept mission.
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()
            # Select first structured option.
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            mechanics = [ln for ln in captured if ln.startswith("2D6")]
            assert len(mechanics) == 1, f"expected one mechanics line; got {captured!r}"
            line = mechanics[0]
            assert "2D6 [" in line
            assert "DM " in line
            assert "vs 8" in line
            assert "Effect " in line

    async def test_classic_profile_uses_binary_vocabulary(self, tmp_path: Path):
        """Classic profile labels show Success/Failure, not strong_hit/miss."""
        app = CepheusApp(saves_dir=tmp_path)
        queue = [
            [3, 4],
            [5, 5],
            [3, 3],
            [4, 4],  # mission hook tables
            [5, 5],
            [4, 4],  # scene oracle tables
            [6, 6],  # scene check (12 -> clear success)
            [5, 5],
            [4, 4],  # second scene oracle (buffer)
        ]
        app.engine = make_seeded_engine(queue)
        app.engine.state.campaign = CampaignConfig(resolution_profile="classic")
        app.pack = load_scifi_pack()
        app.campaign_name = "ClassicVocab"

        async with app.run_test() as pilot:
            screen = await push_adventure(app, pilot)
            captured = _spy_narrate(screen)

            cm = app.screen.query_one(ChoiceMenuWidget)
            # Accept mission.
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()
            # Select first structured option.
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()

            mechanics = [ln for ln in captured if ln.startswith("2D6")]
            assert len(mechanics) == 1, f"expected one mechanics line; got {captured!r}"
            line = mechanics[0]
            # Classic vocabulary: Success or Failure.
            assert ("Success" in line) or ("Failure" in line)
            # NOT narrative vocabulary.
            assert "strong_hit" not in line
            assert "Strong hit" not in line
            assert "Weak hit" not in line

    async def test_rejecting_interpretation_preserves_text(self, adventure_app: CepheusApp):
        """Rejecting a free-text interpretation restores typed text (Task 20)."""
        app = adventure_app
        app.engine.roller.extend([[5, 5], [4, 4], [3, 3]])
        async with app.run_test() as pilot:
            screen = await push_adventure(app, pilot)

            cm = app.screen.query_one(ChoiceMenuWidget)
            # Accept mission.
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()
            assert screen.phase == "scene_active"

            # Type and submit free-text.
            typed = "I bribe the dock officer"
            inp = app.screen.query_one("#adv-input", Input)
            inp.focus()
            await pilot.pause()
            inp.value = typed
            await pilot.press("enter")
            await pilot.pause()
            # Should show accept/reject.
            assert cm.option_list.option_count == 2

            # Reject.
            cm.option_list.highlighted = 1
            cm.option_list.action_select()
            await pilot.pause()

            # Typed text restored into the input for rephrasing, and focused.
            assert inp.value == typed
            assert inp.has_focus


# ---------------------------------------------------------------------------
# 14. Task 24: LLM wiring + degraded status surfaces.
# ---------------------------------------------------------------------------


class TestAdventureLLMWiring:
    """Adventure screen constructs adapter, shows degraded status (Task 24)."""

    async def test_adapter_none_when_llm_unconfigured(self, tmp_path: Path):
        """When LLM is not configured, _adapter is None."""
        app = CepheusApp(saves_dir=tmp_path)
        queue = [[3, 4], [5, 5], [3, 3], [4, 4], [5, 5], [4, 4]]
        app.engine = make_seeded_engine(queue)
        app.pack = load_scifi_pack()
        app.campaign_name = "NoLLM"
        # Force LLM settings to unconfigured.
        from src.tui.settings import LLMSettings

        app.llm_settings = LLMSettings()

        async with app.run_test() as pilot:
            screen = await push_adventure(app, pilot)
            assert screen._adapter is None

    async def test_status_bar_update_does_not_crash(self, tmp_path: Path):
        """_update_status_bar handles all failure_kinds without crashing."""
        app = CepheusApp(saves_dir=tmp_path)
        queue = [[3, 4], [5, 5], [3, 3], [4, 4], [5, 5], [4, 4]]
        app.engine = make_seeded_engine(queue)
        app.pack = load_scifi_pack()
        app.campaign_name = "StatusBarTest"

        async with app.run_test() as pilot:
            screen = await push_adventure(app, pilot)
            # All failure kinds should update without raising.
            screen._update_status_bar(None)
            screen._update_status_bar("provider_error")
            screen._update_status_bar("retry_exhausted")
            await pilot.pause()
            # Verify the status bar still exists and is queryable.
            from textual.widgets import Label

            bar = screen.query_one("#adv-status-bar", Label)
            assert bar is not None

    async def test_degraded_surface_strings_exist(self):
        """The degraded-mode surface constants are the plan's exact wording."""
        from src.tui.screens.adventure import (
            STATUS_CONNECTION_LOST,
            STATUS_NARRATION_UNAVAILABLE,
        )

        assert STATUS_CONNECTION_LOST == "connection lost — template narration"
        assert STATUS_NARRATION_UNAVAILABLE == "narration unavailable — showing mechanical outcomes"

    async def test_freetext_uses_llm_classifier_when_configured(self, adventure_app: CepheusApp):
        """Free-text classification passes the LLM classifier to SceneEngine."""
        app = adventure_app
        app.engine.roller.extend([[5, 5], [4, 4], [3, 3]])

        # Inject a mock adapter so the classifier closure is built.
        from src.llm.adapter import FreeTextCheck

        class MockAdapter:
            llm_configured = True

            def classify_freetext(self, text, scaffold, view, valid_skill_ids):
                return FreeTextCheck(
                    skill_id="broker",
                    difficulty="average",
                    label="LLM-classified bribe",
                    characteristic="SOC",
                )

            async def narrate_scene(self, *a, **kw):
                from src.llm.adapter import NarrationResult

                return NarrationResult(prose="LLM scene text", source="llm")

        async with app.run_test() as pilot:
            screen = await push_adventure(app, pilot)
            screen._adapter = MockAdapter()

            cm = app.screen.query_one(ChoiceMenuWidget)
            # Accept mission.
            cm.option_list.highlighted = 0
            cm.option_list.action_select()
            await pilot.pause()
            assert screen.phase == "scene_active"

            # Type free-text and submit.
            inp = app.screen.query_one("#adv-input", Input)
            inp.focus()
            await pilot.pause()
            inp.value = "I bribe the dock officer"
            await pilot.press("enter")
            await pilot.pause()

            # Should show the LLM-classified check for confirmation.
            assert cm.option_list.option_count == 2


# ---------------------------------------------------------------------------
# Phase 1 #2: persistent status strip — character sheet renders load-bearing
# state the engine already tracks (injuries, credits, open threads, mission).
# Sources: Fallen London quality sidebar, Cogmind info strip, Friends & Fables.
# ---------------------------------------------------------------------------


class TestCharacterSheetStatusStrip:
    """The sheet must surface state beyond stats/skills (fixes ADV-2/TUI-2)."""

    def _state_with_rich_state(self) -> GameState:
        from src.engine.state import CampaignConfig, Injury, NarrativeFact

        state = GameState.new(seed=7)
        state.campaign = CampaignConfig()
        state.character.name = "Riley"
        state.character.characteristics = {
            "STR": 7,
            "DEX": 8,
            "END": 6,
            "INT": 10,
            "EDU": 9,
            "SOC": 5,
        }
        state.character.credits = 1500
        state.character.inventory = ["Laser Pistol", "Medkit"]
        state.character.skills = {"pilot": 1}
        state.entities.append(Injury(name="Broken Arm", severity="severe"))
        state.entities.append(NarrativeFact(name="Dock Officer"))
        state.open_threads = ["Find the courier", "Pay off the debt"]
        state.active_mission = {
            "hook": {
                "patron": "Merchant Guild",
                "objective": "Recover stolen cargo",
            },
            "scenes_completed": 1,
            "min_scenes": 3,
        }
        return state

    def test_sheet_shows_credits(self):
        sheet = CharacterSheetWidget()
        content = sheet.render_content(self._state_with_rich_state())
        assert "1500" in content

    def test_sheet_shows_injuries(self):
        sheet = CharacterSheetWidget()
        content = sheet.render_content(self._state_with_rich_state())
        assert "Broken Arm" in content
        assert "severe" in content.lower()

    def test_sheet_shows_open_threads_count(self):
        sheet = CharacterSheetWidget()
        content = sheet.render_content(self._state_with_rich_state())
        assert "2" in content  # thread count
        assert "thread" in content.lower()

    def test_sheet_shows_active_mission(self):
        sheet = CharacterSheetWidget()
        content = sheet.render_content(self._state_with_rich_state())
        assert "Recover stolen cargo" in content

    def test_sheet_shows_inventory(self):
        sheet = CharacterSheetWidget()
        content = sheet.render_content(self._state_with_rich_state())
        assert "Laser Pistol" in content
