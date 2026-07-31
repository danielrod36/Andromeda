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
from src.engine.commands import Engine
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
from src.engine.dice import ForcedRoller
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
        "STR": 7,
        "DEX": 9,
        "END": 6,
        "INT": 8,
        "EDU": 10,
        "SOC": 5,
    }
    return state


def make_engine(
    seed: int = 42,
    death_mode: str = "narrative",
    alive: bool = True,
) -> Engine:
    """Create an Engine wrapping a fresh GameState for defeat testing."""
    state = make_state(seed=seed, death_mode=death_mode, alive=alive)
    return Engine(state, roller=ForcedRoller([]))


# ---------------------------------------------------------------------------
# AE2: Ironman permanent death.
# ---------------------------------------------------------------------------


class TestIronmanStrategy:
    """AE2: Ironman death is permanent; character.alive = False, restart offered."""

    def test_character_alive_set_false(self):
        """Ironman defeat sets character.alive = False."""
        engine = make_engine(death_mode="ironman")
        state = engine.state
        assert state.character.alive is True

        strategy = IronmanStrategy(engine=engine)
        strategy.handle_defeat(state, DefeatContext(reason="pirate ambush"))

        assert state.character.alive is False

    def test_play_does_not_continue(self):
        """Ironman defeat ends play."""
        engine = make_engine(death_mode="ironman")
        strategy = IronmanStrategy(engine=engine)
        result = strategy.handle_defeat(engine.state, DefeatContext())

        assert result.play_continues is False

    def test_restart_offered(self):
        """Ironman defeat offers a new lifepath restart."""
        engine = make_engine(death_mode="ironman")
        strategy = IronmanStrategy(engine=engine)
        result = strategy.handle_defeat(engine.state, DefeatContext())

        assert result.restart_offered is True

    def test_mode_is_ironman(self):
        """The strategy identifies as 'ironman'."""
        assert IronmanStrategy.mode == "ironman"
        engine = make_engine()
        strategy = IronmanStrategy(engine=engine)
        result = strategy.handle_defeat(engine.state, DefeatContext())
        assert result.mode == "ironman"

    def test_message_includes_character_name(self):
        """The defeat message includes the character's name."""
        engine = make_engine(death_mode="ironman")
        engine.state.character.name = "Captain Reyes"
        strategy = IronmanStrategy(engine=engine)
        result = strategy.handle_defeat(engine.state, DefeatContext(reason="disease"))

        assert "Captain Reyes" in result.message

    def test_no_restored_state(self):
        """Ironman does not produce a restored state (death is final)."""
        engine = make_engine(death_mode="ironman")
        strategy = IronmanStrategy(engine=engine)
        result = strategy.handle_defeat(engine.state, DefeatContext())

        assert result.restored_state is None

    def test_ae2_chargen_death_regression(self):
        """AE2 regression: a character who dies stays dead.

        This simulates a chargen death scenario where the character has
        already been marked dead. Ironman mode ensures the death is
        permanent — alive remains False and restart is offered.
        """
        engine = make_engine(death_mode="ironman", alive=False)
        state = engine.state
        assert state.character.alive is False

        strategy = IronmanStrategy(engine=engine)
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

        state.events.append(
            Event(
                seq=0,
                kind=EventKind.STATE_CHANGE,
                command_type="scene_action",
                description="The character fought and lost.",
            )
        )

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
        engine = make_engine(death_mode="narrative")
        state = engine.state
        initial_entity_count = len(state.entities)

        strategy = NarrativeStrategy(engine=engine)
        strategy.handle_defeat(state, DefeatContext(reason="a duel"))

        assert len(state.entities) == initial_entity_count + 1
        injury = state.entities[-1]
        assert isinstance(injury, Injury)
        assert "duel" in injury.name

    def test_injury_is_severe(self):
        """The defeat consequence is a severe injury."""
        engine = make_engine(death_mode="narrative")
        strategy = NarrativeStrategy(engine=engine)
        strategy.handle_defeat(engine.state, DefeatContext(reason="ambush"))

        injury = engine.state.entities[-1]
        assert injury.severity == "severe"

    def test_injury_has_descriptive_text(self):
        """The injury description explains what happened."""
        engine = make_engine(death_mode="narrative")
        strategy = NarrativeStrategy(engine=engine)
        strategy.handle_defeat(engine.state, DefeatContext(reason="a fall"))

        injury = engine.state.entities[-1]
        assert "fall" in injury.description
        assert len(injury.description) > 10

    def test_character_still_alive(self):
        """The character survives a narrative defeat."""
        engine = make_engine(death_mode="narrative")
        strategy = NarrativeStrategy(engine=engine)
        strategy.handle_defeat(engine.state, DefeatContext())

        assert engine.state.character.alive is True

    def test_play_continues(self):
        """Narrative defeat allows continued play."""
        engine = make_engine(death_mode="narrative")
        strategy = NarrativeStrategy(engine=engine)
        result = strategy.handle_defeat(engine.state, DefeatContext())

        assert result.play_continues is True

    def test_no_restored_state(self):
        """Narrative mode does not rewind (no restored state)."""
        engine = make_engine(death_mode="narrative")
        strategy = NarrativeStrategy(engine=engine)
        result = strategy.handle_defeat(engine.state, DefeatContext())

        assert result.restored_state is None

    def test_restart_not_offered(self):
        """Narrative mode does not offer restart."""
        engine = make_engine(death_mode="narrative")
        strategy = NarrativeStrategy(engine=engine)
        result = strategy.handle_defeat(engine.state, DefeatContext())

        assert result.restart_offered is False

    def test_multiple_defeats_accumulate_injuries(self):
        """Each narrative defeat adds a new injury (consequences accumulate)."""
        engine = make_engine(death_mode="narrative")
        strategy = NarrativeStrategy(engine=engine)

        strategy.handle_defeat(engine.state, DefeatContext(reason="first defeat"))
        strategy.handle_defeat(engine.state, DefeatContext(reason="second defeat"))

        injuries = [e for e in engine.state.entities if isinstance(e, Injury)]
        assert len(injuries) == 2

    def test_injury_visible_on_character_sheet(self):
        """AE4: the consequence is visible on the character sheet (entities list).

        The entities list is what the LLM adapter (U5) uses to build the
        character sheet view. An Injury here means it shows up on the sheet.
        """
        engine = make_engine(death_mode="narrative")
        strategy = NarrativeStrategy(engine=engine)
        strategy.handle_defeat(engine.state, DefeatContext(reason="explosion"))

        # The injury is in entities, which feeds the character sheet view.
        injuries = [e for e in engine.state.entities if isinstance(e, Injury)]
        assert len(injuries) == 1
        assert injuries[0].severity == "severe"
        assert "explosion" in injuries[0].name


# ---------------------------------------------------------------------------
# Factory function.
# ---------------------------------------------------------------------------


class TestGetDeathStrategy:
    """Factory returns the correct strategy for each death mode."""

    def test_returns_ironman_strategy(self):
        engine = make_engine()
        strategy = get_death_strategy("ironman", engine=engine)
        assert isinstance(strategy, IronmanStrategy)
        assert strategy.mode == "ironman"

    def test_returns_narrative_strategy(self):
        engine = make_engine()
        strategy = get_death_strategy("narrative", engine=engine)
        assert isinstance(strategy, NarrativeStrategy)
        assert strategy.mode == "narrative"

    def test_returns_checkpoint_strategy(self):
        engine = make_engine()
        mgr = CheckpointManager()
        strategy = get_death_strategy("checkpoint", engine=engine, checkpoint=mgr)
        assert isinstance(strategy, CheckpointStrategy)
        assert strategy.mode == "checkpoint"

    def test_checkpoint_without_manager_raises(self):
        engine = make_engine()
        with pytest.raises(ValueError, match="CheckpointManager"):
            get_death_strategy("checkpoint", engine=engine)

    def test_unknown_mode_raises(self):
        engine = make_engine()
        with pytest.raises(ValueError, match="Unknown death mode"):
            get_death_strategy("permadeath", engine=engine)

    def test_all_death_modes_valid(self):
        """Every mode in DEATH_MODES produces a valid strategy."""
        engine = make_engine()
        mgr = CheckpointManager()
        for mode in DEATH_MODES:
            strategy = get_death_strategy(mode, engine=engine, checkpoint=mgr)
            assert strategy.mode == mode


# ---------------------------------------------------------------------------
# Strategy protocol conformance.
# ---------------------------------------------------------------------------


class TestStrategyProtocol:
    """All strategies conform to the DeathStrategy protocol."""

    def test_ironman_satisfies_protocol(self):
        engine = make_engine()
        assert isinstance(IronmanStrategy(engine=engine), DeathStrategy)

    def test_checkpoint_satisfies_protocol(self):
        mgr = CheckpointManager()
        assert isinstance(CheckpointStrategy(mgr), DeathStrategy)

    def test_narrative_satisfies_protocol(self):
        engine = make_engine()
        assert isinstance(NarrativeStrategy(engine=engine), DeathStrategy)

    def test_all_strategies_return_defeat_result(self):
        """handle_defeat returns a DefeatResult in all modes."""
        engine = make_engine()
        mgr = CheckpointManager()
        for mode in DEATH_MODES:
            state = make_state(death_mode=mode)
            strategy = get_death_strategy(mode, engine=engine, checkpoint=mgr)
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
    """Death strategies route mutations through Engine.apply."""

    def test_ironman_logs_event(self):
        """Ironman defeat via funnel produces an audit event."""
        engine = make_engine(death_mode="ironman")
        state = engine.state
        initial_events = len(state.events)

        strategy = IronmanStrategy(engine=engine)
        strategy.handle_defeat(state, DefeatContext(reason="pirate ambush"))

        assert state.character.alive is False
        assert len(state.events) == initial_events + 1
        event = state.events[-1]
        assert event.command_type == "set_character_dead"
        assert event.changes["alive"] is False

    def test_narrative_logs_event(self):
        """Narrative defeat via funnel produces an audit event."""
        from src.engine.state import Injury

        engine = make_engine(death_mode="narrative")
        state = engine.state
        initial_events = len(state.events)

        strategy = NarrativeStrategy(engine=engine)
        strategy.handle_defeat(state, DefeatContext(reason="a duel"))

        assert len(state.events) == initial_events + 1
        event = state.events[-1]
        assert event.command_type == "add_injury"
        injury = state.entities[-1]
        assert isinstance(injury, Injury)
        assert "duel" in injury.name

    def test_factory_passes_engine_to_ironman(self):
        """get_death_strategy passes engine to IronmanStrategy."""
        engine = make_engine(death_mode="ironman")
        strategy = get_death_strategy("ironman", engine=engine)
        assert strategy._engine is engine

    def test_factory_passes_engine_to_narrative(self):
        """get_death_strategy passes engine to NarrativeStrategy."""
        engine = make_engine(death_mode="narrative")
        strategy = get_death_strategy("narrative", engine=engine)
        assert strategy._engine is engine

    def test_ironman_requires_engine(self):
        """IronmanStrategy requires an engine (no legacy direct-mutation path)."""
        with pytest.raises(TypeError):
            IronmanStrategy()  # type: ignore[call-arg]

    def test_narrative_requires_engine(self):
        """NarrativeStrategy requires an engine (no legacy direct-mutation path)."""
        with pytest.raises(TypeError):
            NarrativeStrategy()  # type: ignore[call-arg]
