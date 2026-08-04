"""Tests for the headless AdventureController (U8).

Mirrors the core scenarios of tests/tui/test_adventure.py headlessly:
hooks, scenes with odds, free-text classify, mission gate, defeat modes.
"""

from __future__ import annotations

from src.engine.commands import Engine
from src.engine.dice import ForcedRoller
from src.engine.state import CampaignConfig, GameState
from src.game.adventure import AdventureController
from src.themepacks.cepheus_scifi import load_scifi_pack


def _make_engine(queue: list | None = None, death_mode: str = "narrative") -> Engine:
    """Create an engine with a mustered-out character ready for adventure."""
    state = GameState.new(seed=42)
    state.campaign = CampaignConfig(
        resolution_profile="narrative",
        death_mode=death_mode,
        theme_pack="scifi",
    )
    state.character.name = "TestHero"
    state.character.characteristics = {
        "STR": 7,
        "DEX": 9,
        "END": 6,
        "INT": 8,
        "EDU": 10,
        "SOC": 5,
    }
    state.character.skills = {"Gun Combat": 1, "Persuade": 0, "Stealth": 2, "Investigate": 1}
    state.character.career = "navy"
    state.character.terms = 2
    state.character.alive = True
    # Mark as mustered out so adventure can start.
    state.narrative_log.append("mustered_out=true")

    roller = ForcedRoller(queue or [])
    return Engine(state, roller=roller)


# Queue: 4 mission hook table rolls + 2 oracle rolls + 1 check per scene.
_DEFAULT_QUEUE = [
    [3, 4],
    [5, 5],
    [3, 3],
    [4, 4],  # mission hook tables
    [5, 5],
    [4, 4],  # scene oracle tables (first scene)
    [6, 6],  # scene check
    [5, 5],
    [4, 4],  # scene oracle tables (second scene)
    [5, 5],  # scene check
    [5, 5],
    [4, 4],  # scene oracle tables (third scene)
]


class TestHookPhase:
    """U8: hook generation and accept/refuse."""

    def test_hook_offered_on_no_active_mission(self):
        engine = _make_engine(_DEFAULT_QUEUE)
        controller = AdventureController(engine, load_scifi_pack())
        view = controller.get_view()
        assert view.phase == "hook_offered"
        assert len(view.choices) == 2  # Accept + Refuse.

    def test_accept_mission_enters_scene(self):
        engine = _make_engine(_DEFAULT_QUEUE)
        controller = AdventureController(engine, load_scifi_pack())
        controller.apply_choice("accept_mission")
        view = controller.get_view()
        assert view.phase == "scene_active"
        assert len(view.choices) >= 2  # Structured options + abandon.

    def test_refuse_mission_stays_in_hook(self):
        engine = _make_engine(_DEFAULT_QUEUE * 2)
        controller = AdventureController(engine, load_scifi_pack())
        controller.apply_choice("refuse_mission")
        view = controller.get_view()
        assert view.phase == "hook_offered"


class TestSceneOptions:
    """U8: scene options carry pre-commit odds."""

    def test_scene_options_have_odds_lines(self):
        engine = _make_engine(_DEFAULT_QUEUE)
        controller = AdventureController(engine, load_scifi_pack())
        controller.apply_choice("accept_mission")
        view = controller.get_view()
        assert view.phase == "scene_active"
        assert len(view.odds_lines) > 0
        # Each odds line should contain a "%" (pre-commit probability).
        for line in view.odds_lines:
            assert "%" in line or "DM" in line

    def test_resolve_option_produces_receipt(self):
        engine = _make_engine(_DEFAULT_QUEUE * 2)
        controller = AdventureController(engine, load_scifi_pack())
        controller.apply_choice("accept_mission")
        view = controller.apply_choice("option:0")
        assert len(view.receipts) > 0
        # Receipt should contain dice notation.
        assert "2D6" in view.receipts[0]


class TestMissionGate:
    """U8: ending push is gated by min_scenes."""

    def test_ending_push_gated_before_min_scenes(self):
        engine = _make_engine(_DEFAULT_QUEUE)
        controller = AdventureController(engine, load_scifi_pack())
        controller.apply_choice("accept_mission")
        view = controller.get_view()
        # U14: push for ending is dimmed-not-hidden — present but gated.
        push_opts = [c for c in view.choices if c.option_id == "push_for_ending"]
        assert len(push_opts) == 1
        assert push_opts[0].dimmed is True
        assert push_opts[0].requirement  # Non-empty requirement text.


class TestFreeTextClassify:
    """U8: free-text classification flow."""

    def test_classify_keyword_match(self):
        engine = _make_engine(_DEFAULT_QUEUE * 2)
        controller = AdventureController(engine, load_scifi_pack())
        controller.apply_choice("accept_mission")
        view = controller.classify_freetext("I bribe the dock officer")
        # Should produce an interpretation (keyword match) or error message.
        assert view.phase in ("freetext_pending", "scene_active")

    def test_reject_freetext_clears_pending(self):
        engine = _make_engine(_DEFAULT_QUEUE * 2)
        controller = AdventureController(engine, load_scifi_pack())
        controller.apply_choice("accept_mission")
        controller.classify_freetext("I bribe the dock officer")
        # If classify produced a pending state, reject should clear it.
        if controller.state.pending_freetext is not None:
            controller.apply_choice("reject_freetext")
            assert controller.state.pending_freetext is None


def _force_defeat(controller: AdventureController) -> None:
    """Monkey-patch the controller so the next option resolve triggers defeat.

    Tests call this before resolving an option they want to drive through the
    defeat path, so the test is deterministic rather than dependent on a
    life-threatening MISS happening to come up.
    """

    def always_defeat(self, check_result, option, consequences):
        return self._handle_defeat("forced test defeat")

    controller._check_defeat = always_defeat.__get__(controller)


class TestDefeatHandling:
    """U8: defeat triggers the death strategy for each death mode."""

    def test_narrative_defeat_continues(self):
        """In narrative mode, defeat applies a severe injury — play continues."""
        engine = _make_engine(_DEFAULT_QUEUE * 3, death_mode="narrative")
        controller = AdventureController(engine, load_scifi_pack())
        controller.apply_choice("accept_mission")
        _force_defeat(controller)
        view = controller.apply_choice("option:0")
        assert view.defeat == "narrative"
        assert view.phase == "scene_active"

    def test_ironman_defeat_ends_game(self):
        """In ironman mode, defeat sets character.alive=False and ends the game."""
        engine = _make_engine(_DEFAULT_QUEUE * 3, death_mode="ironman")
        controller = AdventureController(engine, load_scifi_pack())
        controller.apply_choice("accept_mission")
        _force_defeat(controller)
        view = controller.apply_choice("option:0")
        assert view.defeat == "ironman"
        assert view.phase == "game_over"
        assert engine.state.character.alive is False

    def test_checkpoint_defeat_rewinds(self):
        """Checkpoint mode rewinds state instead of raising RuntimeError.

        Regression: the headless controller previously instantiated a fresh
        ``CheckpointManager()`` per defeat and never called ``take_snapshot``,
        so ``restore()`` raised ``RuntimeError``.
        """
        engine = _make_engine(_DEFAULT_QUEUE * 3, death_mode="checkpoint")
        controller = AdventureController(engine, load_scifi_pack())
        controller.apply_choice("accept_mission")
        _force_defeat(controller)
        view = controller.apply_choice("option:0")
        assert view.defeat == "checkpoint"
        assert view.phase == "scene_active"  # play continues after rewind


class TestScenesCompletedIncrement:
    """U8: resolving scene options advances the mission progress gate."""

    def test_resolve_option_increments_scenes_completed(self):
        engine = _make_engine(_DEFAULT_QUEUE * 3)
        controller = AdventureController(engine, load_scifi_pack())
        controller.apply_choice("accept_mission")
        before = engine.state.active_mission["scenes_completed"]
        controller.apply_choice("option:0")
        after = engine.state.active_mission["scenes_completed"]
        assert after == before + 1

    def test_push_for_ending_unlocks_after_min_scenes(self):
        """After resolving ``min_scenes`` options, push_for_ending appears."""
        engine = _make_engine(_DEFAULT_QUEUE * 5)
        controller = AdventureController(engine, load_scifi_pack())
        controller.apply_choice("accept_mission")
        min_scenes = engine.state.active_mission["min_scenes"]
        for _ in range(min_scenes):
            controller.apply_choice("option:0")
        view = controller.get_view()
        choice_ids = [c.option_id for c in view.choices]
        assert "push_for_ending" in choice_ids


class TestResumeDeterminism:
    """U8: serializing and resuming preserves the hook without re-rolling."""

    def test_pending_hook_persisted_across_save_load(self):
        engine = _make_engine(_DEFAULT_QUEUE * 3)
        controller = AdventureController(engine, load_scifi_pack())
        controller.get_view()  # generates + persists the hook
        hook_before = controller._current_hook
        assert hook_before is not None
        assert engine.state.pending_hook is not None

        # Simulate save/load: serialize, deserialize, new controller.
        saved = engine.state.model_dump_json()
        restored_state = GameState.model_validate_json(saved)
        restored_state.rng._hydrate()
        new_engine = Engine(restored_state, roller=ForcedRoller(_DEFAULT_QUEUE * 3))
        new_controller = AdventureController(new_engine, load_scifi_pack())

        # The hook must be restored from state without re-rolling oracle.
        assert new_controller._current_hook is not None
        assert new_controller._current_hook.patron == hook_before.patron, (
            "hook must survive save/load without regeneration"
        )

    def test_hook_resume_does_not_advance_oracle(self):
        """Resuming a hook must not consume oracle-stream rolls.

        Regression: previously, the controller dropped ``_current_hook`` on
        resume and regenerated it via ``_build_hook_view``, advancing the
        oracle stream by 4 rolls and diverging from a no-save session.

        Uses ``LiveRoller`` so oracle-stream advancement is observable.
        """
        from src.engine.dice import LiveRoller

        base = _make_engine().state  # seed=42, deterministic

        # Session A: never save. Generate hook then accept.
        state_a = base.model_copy(deep=True)
        state_a.rng._hydrate()
        engine_a = Engine(state_a, roller=LiveRoller(state_a.rng))
        ctrl_a = AdventureController(engine_a, load_scifi_pack())
        ctrl_a.get_view()
        ctrl_a.apply_choice("accept_mission")
        oracle_a = state_a.rng._live["oracle"].getstate()[1]

        # Session B: save after hook, load, then accept.
        state_b_pre = base.model_copy(deep=True)
        state_b_pre.rng._hydrate()
        engine_b_pre = Engine(state_b_pre, roller=LiveRoller(state_b_pre.rng))
        ctrl_b_pre = AdventureController(engine_b_pre, load_scifi_pack())
        ctrl_b_pre.get_view()
        saved = engine_b_pre.state.model_dump_json()
        state_b_post = GameState.model_validate_json(saved)
        state_b_post.rng._hydrate()
        engine_b_post = Engine(state_b_post, roller=LiveRoller(state_b_post.rng))
        ctrl_b_post = AdventureController(engine_b_post, load_scifi_pack())
        ctrl_b_post.get_view()  # must NOT re-roll oracle (hook is restored)
        ctrl_b_post.apply_choice("accept_mission")
        oracle_b = state_b_post.rng._live["oracle"].getstate()[1]

        assert oracle_a == oracle_b, "oracle stream must not diverge across resume"

    def test_accept_mission_clears_pending_hook(self):
        engine = _make_engine(_DEFAULT_QUEUE * 3)
        controller = AdventureController(engine, load_scifi_pack())
        controller.get_view()
        assert engine.state.pending_hook is not None
        controller.apply_choice("accept_mission")
        assert engine.state.pending_hook is None

    def test_refuse_mission_replaces_pending_hook(self):
        """Refusing generates a new hook, which replaces (not clears) pending_hook."""
        engine = _make_engine(_DEFAULT_QUEUE * 3)
        controller = AdventureController(engine, load_scifi_pack())
        controller.get_view()
        hook_before = engine.state.pending_hook
        assert hook_before is not None
        controller.apply_choice("refuse_mission")
        hook_after = engine.state.pending_hook
        # A new hook is generated and persisted — not cleared.
        assert hook_after is not None
        # The new hook should differ from the old one (different oracle rolls).
        assert (
            hook_after["patron"] != hook_before["patron"]
            or hook_after["objective"] != hook_before["objective"]
        )


class TestMechanicsLineFallback:
    """U8: _mechanics_line degrades gracefully on unknown quality values."""

    def test_unknown_quality_does_not_raise(self):
        from src.engine.scene import SceneCheckResult

        engine = _make_engine(_DEFAULT_QUEUE)
        controller = AdventureController(engine, load_scifi_pack())
        weird = SceneCheckResult(
            skill="X",
            difficulty="average",
            raw_roll=7,
            char_dm=0,
            skill_level=0,
            difficulty_dm=0,
            total_dm=0,
            success=False,
            effect=0,
            quality="unknown_tier",
            description="",
            dice=[3, 4],
            trained=True,
        )
        line = controller._mechanics_line(weird)
        assert isinstance(line, str)
        assert "2D6" in line


class TestPushForEndingGuard:
    """U8: _do_push_for_ending handles missing _current_mission gracefully."""

    def test_push_for_ending_with_no_current_mission_returns_view(self):
        engine = _make_engine(_DEFAULT_QUEUE * 3)
        controller = AdventureController(engine, load_scifi_pack())
        controller.apply_choice("accept_mission")
        controller._current_mission = None  # simulate reconstruction failure
        view = controller._do_push_for_ending()
        assert isinstance(view, object)  # did not raise


class TestCheckpointRewindResync:
    """U8: after checkpoint rewind, transient state is re-synced from GameState.

    Regression (kilo-code-bot): ``_handle_defeat`` called ``swap_state`` to
    restore the pre-scene snapshot but never re-synced ``_current_mission``,
    leaving a stale reference that would crash ``_do_push_for_ending`` /
    ``_do_abandon_mission`` with AttributeError.
    """

    def test_current_mission_resynced_after_checkpoint_rewind(self):
        engine = _make_engine(_DEFAULT_QUEUE * 3, death_mode="checkpoint")
        controller = AdventureController(engine, load_scifi_pack())
        controller.apply_choice("accept_mission")
        mission_pre = controller._current_mission
        assert mission_pre is not None

        _force_defeat(controller)
        view = controller.apply_choice("option:0")
        assert view.defeat == "checkpoint"

        # After rewind, _current_mission must be re-synced from the restored
        # state, not left as the stale pre-rewind object.
        assert controller._current_mission is not None
        assert controller._current_mission is not mission_pre

    def test_push_for_ending_works_after_checkpoint_rewind(self):
        """The stale-mission crash scenario the reviewer flagged."""
        engine = _make_engine(_DEFAULT_QUEUE * 5, death_mode="checkpoint")
        controller = AdventureController(engine, load_scifi_pack())
        controller.apply_choice("accept_mission")
        # Trigger a rewind.
        _force_defeat(controller)
        controller.apply_choice("option:0")
        # If _current_mission were stale/None, this would AttributeError.
        # The mission gate may not be open yet, but the call must not crash.
        view = controller._do_push_for_ending()
        assert isinstance(view, object)

    def test_abandon_mission_works_after_checkpoint_rewind(self):
        engine = _make_engine(_DEFAULT_QUEUE * 5, death_mode="checkpoint")
        controller = AdventureController(engine, load_scifi_pack())
        controller.apply_choice("accept_mission")
        _force_defeat(controller)
        controller.apply_choice("option:0")
        # Must not crash with AttributeError on stale mission.
        view = controller.apply_choice("abandon_mission")
        assert view.mission_ending == "abandonment"


class TestOptionIndexBoundsCheck:
    """U8: _do_resolve_option rejects out-of-range option indices."""

    def test_out_of_range_index_returns_current_view(self):
        engine = _make_engine(_DEFAULT_QUEUE * 3)
        controller = AdventureController(engine, load_scifi_pack())
        controller.apply_choice("accept_mission")
        controller.get_view()  # generate the scene
        num_options = len(controller._current_scene.options)
        view = controller.apply_choice(f"option:{num_options}")
        # Should return the current view, not crash with IndexError.
        assert view.phase == "scene_active"

    def test_negative_index_returns_current_view(self):
        engine = _make_engine(_DEFAULT_QUEUE * 3)
        controller = AdventureController(engine, load_scifi_pack())
        controller.apply_choice("accept_mission")
        controller.get_view()
        view = controller._do_resolve_option(-1)
        assert view.phase == "scene_active"
