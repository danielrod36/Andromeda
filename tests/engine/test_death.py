"""Tests for the death mode strategy pattern (R8, AE2, AE3, AE4).

Covers:
- AE2: Ironman chargen death is permanent; offers immediate new lifepath.
- AE3: Checkpoint rewind via the strategy restores canonical state.
- AE4: Narrative mode defeat applies lasting consequence (Injury) visible on
  the character sheet; play continues.
- Factory function and strategy protocol conformance.
"""
from __future__ import annotations

import pytest

from src.engine.checkpoint import CheckpointManager
from src.engine.commands import Engine, SetCharacterDeadCommand
from src.engine.dice import ForcedRoller
from src.engine.death import (
    DEATH_MODES,
    CheckpointStrategy,
    DeathStrategy,
    DefeatContext,
    DefeatResult,
    IronmanStrategy,
    NarrativeStrategy,
    get_death_strategy,
)
from src.engine.state import CampaignConfig, GameState, Injury, NarrativeFact


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def make_state(
    seed: int = 42,
    death_mode: str = "narrative",
    alive: bool = True,
) -> GameState:
    """Create a GameState with character data for defeat testing."""
    state = GameState.new(seed=seed)
    state.campaign = CampaignConfig(death_mode=death_mode)
    state.character.name = "Captain Vega"
    state.character.alive = alive
    state.character.age = 34
    state.character.characteristics = {
        "STR": 7, "DEX": 9, "END": 6,
        "INT": 8, "EDU": 10, "SOC": 5,
    }
    return state


# ---------------------------------------------------------------------------
# AE2: Ironman permanent death.
# ---------------------------------------------------------------------------


class TestIronmanStrategy:
    """AE2: Ironman death is permanent; character.alive = False, restart offered."""

    def test_character_alive_set_false(self):
        """Ironman defeat sets character.alive = False."""
        state = make_state(death_mode="ironman")
        assert state.character.alive is True

        strategy = IronmanStrategy()
        result = strategy.handle_defeat(state, DefeatContext(reason="pirate ambush"))

        assert state.character.alive is False

    def test_play_does_not_continue(self):
        """Ironman defeat ends play."""
        state = make_state(death_mode="ironman")
        strategy = IronmanStrategy()
        result = strategy.handle_defeat(state, DefeatContext())

        assert result.play_continues is False

    def test_restart_offered(self):
        """Ironman defeat offers a new lifepath restart."""
        state = make_state(death_mode="ironman")
        strategy = IronmanStrategy()
        result = strategy.handle_defeat(state, DefeatContext())

        assert result.restart_offered is True

    def test_mode_is_ironman(self):
        """The strategy identifies as 'ironman'."""
        assert IronmanStrategy.mode == "ironman"
        state = make_state()
        strategy = IronmanStrategy()
        result = strategy.handle_defeat(state, DefeatContext())
        assert result.mode == "ironman"

    def test_message_includes_character_name(self):
        """The defeat message includes the character's name."""
        state = make_state(death_mode="ironman")
        state.character.name = "Captain Reyes"
        strategy = IronmanStrategy()
        result = strategy.handle_defeat(state, DefeatContext(reason="disease"))

        assert "Captain Reyes" in result.message

    def test_no_restored_state(self):
        """Ironman does not produce a restored state (death is final)."""
        state = make_state(death_mode="ironman")
        strategy = IronmanStrategy()
        result = strategy.handle_defeat(state, DefeatContext())

        assert result.restored_state is None

    def test_ae2_chargen_death_regression(self):
        """AE2 regression: a character who dies stays dead.

        This simulates a chargen death scenario where the character has
        already been marked dead. Ironman mode ensures the death is
        permanent — alive remains False and restart is offered.
        """
        state = make_state(death_mode="ironman", alive=False)
        assert state.character.alive is False

        strategy = IronmanStrategy()
        result = strategy.handle_defeat(state, DefeatContext(reason="chargen mishap"))

        # Death is permanent: alive stays False.
        assert state.character.alive is False
        assert result.restart_offered is True
        assert result.play_continues is False


# ---------------------------------------------------------------------------
# AE3: Checkpoint rewind via the strategy.
# ---------------------------------------------------------------------------


class TestCheckpointStrategy:
    """AE3: Checkpoint strategy rewinds canonical state on defeat."""

    def test_restored_state_returned(self):
        """Checkpoint defeat returns a restored state."""
        state = make_state(death_mode="checkpoint")
        mgr = CheckpointManager()
        mgr.take_snapshot(state)

        # Mutate during scene.
        state.character.age = 50
        state.entities.append(NarrativeFact(name="Scene NPC"))

        strategy = CheckpointStrategy(mgr)
        result = strategy.handle_defeat(state, DefeatContext(reason="overwhelmed"))

        assert result.restored_state is not None
        assert result.restored_state.character.age == 34
        assert len(result.restored_state.entities) == 0

    def test_play_continues(self):
        """Checkpoint defeat allows continued play."""
        state = make_state(death_mode="checkpoint")
        mgr = CheckpointManager()
        mgr.take_snapshot(state)

        strategy = CheckpointStrategy(mgr)
        result = strategy.handle_defeat(state, DefeatContext())

        assert result.play_continues is True

    def test_restart_not_offered(self):
        """Checkpoint does not offer restart (play continues)."""
        state = make_state(death_mode="checkpoint")
        mgr = CheckpointManager()
        mgr.take_snapshot(state)

        strategy = CheckpointStrategy(mgr)
        result = strategy.handle_defeat(state, DefeatContext())

        assert result.restart_offered is False

    def test_rewind_applied_in_events(self):
        """The restored state has a REWIND_APPLIED event in the audit log."""
        from src.engine.audit import EventKind

        state = make_state(death_mode="checkpoint")
        mgr = CheckpointManager()
        mgr.take_snapshot(state)

        # Simulate events during the scene.
        from src.engine.audit import Event
        state.events.append(Event(
            seq=0,
            kind=EventKind.STATE_CHANGE,
            command_type="scene_action",
            description="The character fought and lost.",
        ))

        strategy = CheckpointStrategy(mgr)
        result = strategy.handle_defeat(state, DefeatContext())

        assert result.restored_state is not None
        last = result.restored_state.events[-1]
        assert last.kind == EventKind.REWIND_APPLIED

    def test_requires_checkpoint_manager(self):
        """CheckpointStrategy requires a CheckpointManager instance."""
        with pytest.raises(TypeError):
            CheckpointStrategy()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# AE4: Narrative mode lasting consequence.
# ---------------------------------------------------------------------------


class TestNarrativeStrategy:
    """AE4: Narrative defeat applies a lasting Injury; play continues."""

    def test_injury_added_to_entities(self):
        """Narrative defeat adds an Injury entity to the character sheet."""
        state = make_state(death_mode="narrative")
        initial_entity_count = len(state.entities)

        strategy = NarrativeStrategy()
        strategy.handle_defeat(state, DefeatContext(reason="a duel"))

        assert len(state.entities) == initial_entity_count + 1
        injury = state.entities[-1]
        assert isinstance(injury, Injury)
        assert "duel" in injury.name

    def test_injury_is_severe(self):
        """The defeat consequence is a severe injury."""
        state = make_state(death_mode="narrative")
        strategy = NarrativeStrategy()
        strategy.handle_defeat(state, DefeatContext(reason="ambush"))

        injury = state.entities[-1]
        assert injury.severity == "severe"

    def test_injury_has_descriptive_text(self):
        """The injury description explains what happened."""
        state = make_state(death_mode="narrative")
        strategy = NarrativeStrategy()
        strategy.handle_defeat(state, DefeatContext(reason="a fall"))

        injury = state.entities[-1]
        assert "fall" in injury.description
        assert len(injury.description) > 10

    def test_character_still_alive(self):
        """The character survives a narrative defeat."""
        state = make_state(death_mode="narrative")
        strategy = NarrativeStrategy()
        strategy.handle_defeat(state, DefeatContext())

        assert state.character.alive is True

    def test_play_continues(self):
        """Narrative defeat allows continued play."""
        state = make_state(death_mode="narrative")
        strategy = NarrativeStrategy()
        result = strategy.handle_defeat(state, DefeatContext())

        assert result.play_continues is True

    def test_no_restored_state(self):
        """Narrative mode does not rewind (no restored state)."""
        state = make_state(death_mode="narrative")
        strategy = NarrativeStrategy()
        result = strategy.handle_defeat(state, DefeatContext())

        assert result.restored_state is None

    def test_restart_not_offered(self):
        """Narrative mode does not offer restart."""
        state = make_state(death_mode="narrative")
        strategy = NarrativeStrategy()
        result = strategy.handle_defeat(state, DefeatContext())

        assert result.restart_offered is False

    def test_multiple_defeats_accumulate_injuries(self):
        """Each narrative defeat adds a new injury (consequences accumulate)."""
        state = make_state(death_mode="narrative")
        strategy = NarrativeStrategy()

        strategy.handle_defeat(state, DefeatContext(reason="first defeat"))
        strategy.handle_defeat(state, DefeatContext(reason="second defeat"))

        injuries = [e for e in state.entities if isinstance(e, Injury)]
        assert len(injuries) == 2

    def test_injury_visible_on_character_sheet(self):
        """AE4: the consequence is visible on the character sheet (entities list).

        The entities list is what the LLM adapter (U5) uses to build the
        character sheet view. An Injury here means it shows up on the sheet.
        """
        state = make_state(death_mode="narrative")
        strategy = NarrativeStrategy()
        strategy.handle_defeat(state, DefeatContext(reason="explosion"))

        # The injury is in entities, which feeds the character sheet view.
        injuries = [e for e in state.entities if isinstance(e, Injury)]
        assert len(injuries) == 1
        assert injuries[0].severity == "severe"
        assert "explosion" in injuries[0].name


# ---------------------------------------------------------------------------
# Factory function.
# ---------------------------------------------------------------------------


class TestGetDeathStrategy:
    """Factory returns the correct strategy for each death mode."""

    def test_returns_ironman_strategy(self):
        strategy = get_death_strategy("ironman")
        assert isinstance(strategy, IronmanStrategy)
        assert strategy.mode == "ironman"

    def test_returns_narrative_strategy(self):
        strategy = get_death_strategy("narrative")
        assert isinstance(strategy, NarrativeStrategy)
        assert strategy.mode == "narrative"

    def test_returns_checkpoint_strategy(self):
        mgr = CheckpointManager()
        strategy = get_death_strategy("checkpoint", checkpoint=mgr)
        assert isinstance(strategy, CheckpointStrategy)
        assert strategy.mode == "checkpoint"

    def test_checkpoint_without_manager_raises(self):
        with pytest.raises(ValueError, match="CheckpointManager"):
            get_death_strategy("checkpoint")

    def test_unknown_mode_raises(self):
        with pytest.raises(ValueError, match="Unknown death mode"):
            get_death_strategy("permadeath")

    def test_all_death_modes_valid(self):
        """Every mode in DEATH_MODES produces a valid strategy."""
        mgr = CheckpointManager()
        for mode in DEATH_MODES:
            strategy = get_death_strategy(mode, checkpoint=mgr)
            assert strategy.mode == mode


# ---------------------------------------------------------------------------
# Strategy protocol conformance.
# ---------------------------------------------------------------------------


class TestStrategyProtocol:
    """All strategies conform to the DeathStrategy protocol."""

    def test_ironman_satisfies_protocol(self):
        assert isinstance(IronmanStrategy(), DeathStrategy)

    def test_checkpoint_satisfies_protocol(self):
        mgr = CheckpointManager()
        assert isinstance(CheckpointStrategy(mgr), DeathStrategy)

    def test_narrative_satisfies_protocol(self):
        assert isinstance(NarrativeStrategy(), DeathStrategy)

    def test_all_strategies_return_defeat_result(self):
        """handle_defeat returns a DefeatResult in all modes."""
        mgr = CheckpointManager()
        for mode in DEATH_MODES:
            state = make_state(death_mode=mode)
            strategy = get_death_strategy(mode, checkpoint=mgr)
            if mode == "checkpoint":
                mgr.take_snapshot(state)
            result = strategy.handle_defeat(state, DefeatContext(reason="test"))
            assert isinstance(result, DefeatResult)
            assert result.mode == mode
            assert len(result.message) > 0


# ---------------------------------------------------------------------------
# Funnel-routed mutations (Fix #2A).
# ---------------------------------------------------------------------------


class TestFunnelRoutedDeathStrategies:
    """Death strategies route mutations through Engine.apply when given an engine."""

    def test_ironman_with_engine_logs_event(self):
        """Ironman defeat via funnel produces an audit event."""
        state = make_state(death_mode="ironman")
        engine = Engine(state, roller=ForcedRoller([]))
        initial_events = len(state.events)

        strategy = IronmanStrategy(engine=engine)
        strategy.handle_defeat(state, DefeatContext(reason="pirate ambush"))

        assert state.character.alive is False
        assert len(state.events) == initial_events + 1
        event = state.events[-1]
        assert event.command_type == "set_character_dead"
        assert event.changes["alive"] is False

    def test_ironman_without_engine_legacy_path(self):
        """Ironman without engine still works (backward-compatible direct mutation)."""
        state = make_state(death_mode="ironman")
        strategy = IronmanStrategy()
        strategy.handle_defeat(state, DefeatContext(reason="test"))

        assert state.character.alive is False

    def test_narrative_with_engine_logs_event(self):
        """Narrative defeat via funnel produces an audit event."""
        from src.engine.state import Injury

        state = make_state(death_mode="narrative")
        engine = Engine(state, roller=ForcedRoller([]))
        initial_events = len(state.events)

        strategy = NarrativeStrategy(engine=engine)
        strategy.handle_defeat(state, DefeatContext(reason="a duel"))

        assert len(state.events) == initial_events + 1
        event = state.events[-1]
        assert event.command_type == "add_injury"
        injury = state.entities[-1]
        assert isinstance(injury, Injury)
        assert "duel" in injury.name

    def test_narrative_without_engine_legacy_path(self):
        """Narrative without engine still works (backward-compatible)."""
        state = make_state(death_mode="narrative")
        strategy = NarrativeStrategy()
        strategy.handle_defeat(state, DefeatContext(reason="test"))

        from src.engine.state import Injury
        assert any(isinstance(e, Injury) for e in state.entities)

    def test_factory_passes_engine_to_ironman(self):
        """get_death_strategy passes engine to IronmanStrategy."""
        state = make_state(death_mode="ironman")
        engine = Engine(state, roller=ForcedRoller([]))
        strategy = get_death_strategy("ironman", engine=engine)
        assert strategy._engine is engine

    def test_factory_passes_engine_to_narrative(self):
        """get_death_strategy passes engine to NarrativeStrategy."""
        state = make_state(death_mode="narrative")
        engine = Engine(state, roller=ForcedRoller([]))
        strategy = get_death_strategy("narrative", engine=engine)
        assert strategy._engine is engine
