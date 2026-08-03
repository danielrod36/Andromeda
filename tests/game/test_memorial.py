"""Tests for the death memorial and obituary (U12, R14, AE4).

Covers:
- Template obituary from a seeded run: career, missions, notable rolls.
- Ironman routing: dead-character save routes to memorial, never into play.
- Checkpoint interstitial: names the rewind point and abandoned events.
- Narrative interstitial: lists the applied injury.
- build_memorial data extraction from canonical state.
"""

from __future__ import annotations

from src.engine.audit import Event, EventKind
from src.engine.dice import RollResult
from src.engine.state import CampaignConfig, GameState, Injury
from src.game.memorial import (
    MemorialData,
    build_memorial,
    build_memorial_lines,
    build_obituary,
)
from src.game.saves import determine_resume_route


def _make_dead_state(
    *,
    death_mode: str = "ironman",
    name: str = "Vex",
    career: str = "navy",
    terms: int = 3,
    age: int = 30,
    death_reason: str = "a failed life-threatening check",
    missions: list[dict] | None = None,
    rolls: list[RollResult] | None = None,
    injuries: list[Injury] | None = None,
    rewind_events: list[Event] | None = None,
    summaries: list[str] | None = None,
) -> GameState:
    """Create a dead-character state for memorial testing."""
    state = GameState.new(seed=42)
    state.campaign = CampaignConfig(theme_pack="scifi", death_mode=death_mode)
    state.character.name = name
    state.character.career = career
    state.character.terms = terms
    state.character.age = age
    state.character.alive = False
    state.narrative_log.append("mustered_out=true")
    state.completed_missions = missions or []
    state.chapter_summaries = summaries or []

    # Death event.
    state.events.append(
        Event(
            seq=1,
            kind=EventKind.STATE_CHANGE,
            command_type="set_character_dead",
            description=f"Character died: {death_reason}",
            changes={"alive": False, "reason": death_reason},
        )
    )

    # Roll events (audit_rolls picks these up).
    seq = 2
    for roll in rolls or []:
        state.events.append(
            Event(
                seq=seq,
                kind=EventKind.ROLL,
                command_type="scene_check",
                description=f"Check roll: {roll.total}",
                roll=roll,
                changes={},
            )
        )
        seq += 1

    # Rewind events for checkpoint mode.
    for event in rewind_events or []:
        state.events.append(event)

    # Injuries.
    if injuries:
        state.entities.extend(injuries)

    return state


class TestBuildMemorial:
    """MemorialData extraction from canonical state (U12)."""

    def test_basic_fields(self):
        state = _make_dead_state()
        data = build_memorial(state)
        assert data.character_name == "Vex"
        assert data.career == "navy"
        assert data.terms == 3
        assert data.age == 30
        assert data.death_mode == "ironman"
        assert data.death_reason  # populated from the set_character_dead event

    def test_death_reason_extracted(self):
        state = _make_dead_state(death_reason="overwhelmed by pirates")
        data = build_memorial(state)
        assert "overwhelmed by pirates" in data.death_reason

    def test_missions_extracted(self):
        missions = [
            {
                "hook": {"objective": "Deliver cargo to Vega", "patron": "Merchant"},
                "ending": "success",
                "scenes_completed": 4,
            },
            {
                "hook": {"objective": "Rescue the diplomat", "patron": "Embassy"},
                "ending": "abandonment",
                "scenes_completed": 2,
            },
        ]
        state = _make_dead_state(missions=missions)
        data = build_memorial(state)
        assert len(data.missions) == 2
        assert data.missions[0].objective == "Deliver cargo to Vega"
        assert data.missions[0].ending == "success"
        assert data.missions[1].ending == "abandonment"

    def test_notable_rolls_critical(self):
        """Natural 12 (6+6 on 2D6) is flagged as critical."""
        rolls = [
            RollResult(
                stream="combat",
                ndice=2,
                sides=6,
                modifiers=0,
                rolls=[6, 6],
                total=12,
            ),
        ]
        state = _make_dead_state(rolls=rolls)
        data = build_memorial(state)
        assert len(data.notable_rolls) == 1
        assert data.notable_rolls[0].roll_type == "critical"

    def test_notable_rolls_fumble(self):
        """Natural 2 (1+1 on 2D6) is flagged as fumble."""
        rolls = [
            RollResult(
                stream="oracle",
                ndice=2,
                sides=6,
                modifiers=0,
                rolls=[1, 1],
                total=2,
            ),
        ]
        state = _make_dead_state(rolls=rolls)
        data = build_memorial(state)
        assert len(data.notable_rolls) == 1
        assert data.notable_rolls[0].roll_type == "fumble"

    def test_non_notable_rolls_excluded(self):
        """A roll of 7 (the most common 2D6 result) is not notable."""
        rolls = [
            RollResult(
                stream="combat",
                ndice=2,
                sides=6,
                modifiers=0,
                rolls=[3, 4],
                total=7,
            ),
        ]
        state = _make_dead_state(rolls=rolls)
        data = build_memorial(state)
        assert len(data.notable_rolls) == 0

    def test_non_2d6_rolls_excluded(self):
        """1D6 or 3D6 rolls are not checked for snake eyes/boxcars."""
        rolls = [
            RollResult(
                stream="lifepath",
                ndice=1,
                sides=6,
                modifiers=0,
                rolls=[6],
                total=6,
            ),
        ]
        state = _make_dead_state(rolls=rolls)
        data = build_memorial(state)
        assert len(data.notable_rolls) == 0

    def test_chapter_summaries_included(self):
        state = _make_dead_state(summaries=["First mission summary.", "Second mission."])
        data = build_memorial(state)
        assert data.chapter_summaries == ["First mission summary.", "Second mission."]

    def test_checkpoint_interstitial(self):
        """Checkpoint mode interstitial names the rewind point."""
        rewind = Event(
            seq=10,
            kind=EventKind.REWIND_APPLIED,
            command_type="rewind_applied",
            description="State rewound to scene start",
            changes={"abandoned_events": 5},
        )
        state = _make_dead_state(
            death_mode="checkpoint",
            rewind_events=[rewind],
        )
        # Checkpoint death doesn't actually kill — simulate for test.
        data = build_memorial(state)
        assert data.interstitial_mode == "checkpoint"
        assert "rewound" in data.interstitial_text.lower()
        assert "5" in data.interstitial_text

    def test_narrative_interstitial(self):
        """Narrative mode interstitial lists the applied injury."""
        injuries = [
            Injury(name="Shattered Ribs", severity="severe", description="From a pirate ambush."),
        ]
        state = _make_dead_state(
            death_mode="narrative",
            injuries=injuries,
        )
        data = build_memorial(state)
        assert data.interstitial_mode == "narrative"
        assert "Shattered Ribs" in data.interstitial_text
        assert "severe" in data.interstitial_text

    def test_narrative_interstitial_no_injuries(self):
        """Narrative mode without injuries still has a message."""
        state = _make_dead_state(death_mode="narrative")
        data = build_memorial(state)
        assert data.interstitial_mode == "narrative"
        assert "lasting consequence" in data.interstitial_text.lower()


class TestBuildObituary:
    """Template obituary assembly (U12, R14)."""

    def test_contains_career_and_name(self):
        data = MemorialData(character_name="Vex", career="navy", terms=3, age=30)
        lines = build_obituary(data)
        joined = " ".join(lines)
        assert "Vex" in joined
        assert "navy" in joined
        assert "3 terms" in joined

    def test_single_term_grammar(self):
        data = MemorialData(character_name="Ace", career="scout", terms=1, age=22)
        lines = build_obituary(data)
        joined = " ".join(lines)
        assert "1 term" in joined
        assert "1 terms" not in joined

    def test_death_reason_included(self):
        data = MemorialData(death_reason="overwhelmed by pirates")
        lines = build_obituary(data)
        joined = " ".join(lines)
        assert "overwhelmed by pirates" in joined

    def test_mission_summary(self):
        from src.game.memorial import MissionRecord

        data = MemorialData(
            missions=[
                MissionRecord(objective="Cargo run", ending="success", scenes=4),
                MissionRecord(objective="Rescue", ending="failure", scenes=3),
                MissionRecord(objective="Scout", ending="abandonment", scenes=1),
            ],
        )
        lines = build_obituary(data)
        joined = " ".join(lines)
        assert "1 completed" in joined
        assert "1 failed" in joined
        assert "1 abandoned" in joined
        assert "Cargo run" in joined

    def test_no_missions_line(self):
        data = MemorialData()
        lines = build_obituary(data)
        joined = " ".join(lines)
        assert "No missions completed" in joined

    def test_notable_rolls_included(self):
        from src.game.memorial import NotableRoll

        data = MemorialData(
            notable_rolls=[
                NotableRoll(
                    seq=1,
                    values=[6, 6],
                    total=12,
                    roll_type="critical",
                    description="Critical shot",
                ),
                NotableRoll(
                    seq=2, values=[1, 1], total=2, roll_type="fumble", description="Bad slip"
                ),
            ],
        )
        lines = build_obituary(data)
        joined = " ".join(lines)
        assert "1 critical" in joined
        assert "1 fumble" in joined

    def test_ironman_epitaph(self):
        data = MemorialData(
            character_name="Vex",
            career="navy",
            terms=3,
            age=30,
            death_mode="ironman",
        )
        lines = build_obituary(data)
        assert "fell" in lines[0]


class TestMemorialLines:
    """Convenience function build_memorial_lines (U12)."""

    def test_full_pipeline(self):
        """build_memorial_lines combines extraction and obituary."""
        state = _make_dead_state(
            missions=[
                {
                    "hook": {"objective": "Deliver cargo"},
                    "ending": "success",
                    "scenes_completed": 3,
                }
            ],
            rolls=[
                RollResult(stream="combat", ndice=2, sides=6, modifiers=0, rolls=[6, 6], total=12),
            ],
        )
        lines = build_memorial_lines(state)
        joined = " ".join(lines)
        assert "Vex" in joined
        assert "navy" in joined
        assert "1 completed" in joined
        assert "1 critical" in joined


class TestResumeRouting:
    """Dead-character saves route to memorial, never into play (AE4)."""

    def test_dead_character_routes_to_memorial(self):
        """determine_resume_route returns 'memorial' for dead characters."""
        state = _make_dead_state()
        route = determine_resume_route(state)
        assert route == "memorial"

    def test_alive_character_does_not_route_to_memorial(self):
        """A living character never routes to memorial."""
        state = _make_dead_state()
        state.character.alive = True
        route = determine_resume_route(state)
        assert route != "memorial"
