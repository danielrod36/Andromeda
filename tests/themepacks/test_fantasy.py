"""Tests for the Fantasy theme pack (U9, R21, AE10).

Covers:
- AE10: Fantasy pack works with zero engine code changes — careers, skills,
  oracles, and mission hooks presented through the same engine as sci-fi.
- Pack data validity: all careers have required fields, contiguous ranges.
- Referential integrity: skills reference valid careers.
- Fantasy lifepath runs end-to-end with fantasy careers and skills.
- Fantasy oracle/complication/mission tables produce genre-appropriate content.
- discover_packs() finds the fantasy pack alongside the sci-fi pack.
"""

from __future__ import annotations

import pytest

from src.engine.commands import Engine
from src.engine.dice import ForcedRoller
from src.engine.lifepath import LifepathRunner
from src.engine.state import CampaignConfig, GameState
from src.rulesets.base import ThemePack
from src.themepacks.base import (
    PackLoadError,
    discover_packs,
    validate_pack,
)
from src.themepacks.fantasy import load_fantasy_pack

# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fantasy_pack():
    """Load the fantasy pack once for all tests in this module."""
    return load_fantasy_pack()


FANTASY_CAREER_IDS = {
    "knight",
    "ranger",
    "priest",
    "mage",
    "thief",
    "sailor",
    "scholar",
    "mercenary",
    "bard",
    "healer",
}


# ---------------------------------------------------------------------------
# AE10: Pack satisfies the ThemePack Protocol with zero engine changes.
# ---------------------------------------------------------------------------


class TestAE10FantasyPackProtocol:
    """The fantasy pack satisfies the same ThemePack Protocol as the sci-fi pack."""

    def test_fantasy_pack_satisfies_themepack_protocol(self, fantasy_pack):
        assert isinstance(fantasy_pack, ThemePack)

    def test_fantasy_pack_id(self, fantasy_pack):
        assert fantasy_pack.id == "fantasy"

    def test_fantasy_pack_name(self, fantasy_pack):
        assert "Fantasy" in fantasy_pack.name or "fantasy" in fantasy_pack.name.lower()

    def test_fantasy_pack_has_description(self, fantasy_pack):
        assert len(fantasy_pack.description) > 10


# ---------------------------------------------------------------------------
# Pack data validity — careers.
# ---------------------------------------------------------------------------


class TestCareerValidity:
    """All fantasy careers have required fields and valid structure."""

    def test_career_count_8_to_12(self, fantasy_pack):
        count = len(fantasy_pack.careers)
        assert 8 <= count <= 12, f"Expected 8-12 careers, got {count}"

    def test_all_expected_careers_present(self, fantasy_pack):
        ids = set(fantasy_pack.careers.keys())
        assert ids == FANTASY_CAREER_IDS, (
            f"Missing: {FANTASY_CAREER_IDS - ids}, Extra: {ids - FANTASY_CAREER_IDS}"
        )

    @pytest.mark.parametrize("career_id", sorted(FANTASY_CAREER_IDS))
    def test_career_has_required_fields(self, fantasy_pack, career_id):
        career = fantasy_pack.careers[career_id]
        assert career.id == career_id
        assert career.name
        assert career.description
        assert career.qualification.characteristic in (
            "STR",
            "DEX",
            "END",
            "INT",
            "EDU",
            "SOC",
        )
        assert career.survival.target >= 2
        assert career.advancement.target >= 2

    @pytest.mark.parametrize("career_id", sorted(FANTASY_CAREER_IDS))
    def test_career_has_three_skill_tables(self, fantasy_pack, career_id):
        career = fantasy_pack.careers[career_id]
        assert len(career.skill_tables) == 3
        names = {t.name for t in career.skill_tables}
        assert "Personal Development" in names
        assert "Service Skills" in names
        assert "Advanced Education" in names

    @pytest.mark.parametrize("career_id", sorted(FANTASY_CAREER_IDS))
    def test_career_skill_tables_contiguous_2d6(self, fantasy_pack, career_id):
        career = fantasy_pack.careers[career_id]
        for table in career.skill_tables:
            assert table.entries.is_contiguous(), (
                f"Career {career_id} table '{table.name}' non-contiguous"
            )
            assert table.entries.entries[0].min == 2
            assert table.entries.entries[-1].max == 12

    @pytest.mark.parametrize("career_id", sorted(FANTASY_CAREER_IDS))
    def test_career_has_mustering_out_tables(self, fantasy_pack, career_id):
        career = fantasy_pack.careers[career_id]
        assert career.mustering_out_cash is not None, f"Career '{career_id}' missing cash benefits"
        assert career.mustering_out_material is not None, (
            f"Career '{career_id}' missing material benefits"
        )
        assert career.mustering_out_cash.entries.is_contiguous()
        assert career.mustering_out_material.entries.is_contiguous()


# ---------------------------------------------------------------------------
# Referential integrity.
# ---------------------------------------------------------------------------


class TestReferentialIntegrity:
    """Skills reference valid careers; all tables pass validation."""

    def test_skills_reference_valid_careers(self, fantasy_pack):
        career_ids = set(fantasy_pack.careers.keys())
        for skill_id, skill in fantasy_pack.skills.items():
            if skill.career:
                assert skill.career in career_ids, (
                    f"Skill '{skill_id}' references career '{skill.career}' which does not exist"
                )

    def test_oracle_tables_contiguous(self, fantasy_pack):
        for table_id, table in fantasy_pack.oracle_tables.items():
            assert table.entries.is_contiguous(), f"Oracle table '{table_id}' non-contiguous"

    def test_complication_tables_contiguous(self, fantasy_pack):
        for table_id, table in fantasy_pack.complication_tables.items():
            assert table.entries.is_contiguous(), f"Complication table '{table_id}' non-contiguous"

    def test_mission_tables_contiguous(self, fantasy_pack):
        for table_id, table in fantasy_pack.mission_tables.items():
            assert table.entries.is_contiguous(), f"Mission table '{table_id}' non-contiguous"

    def test_skill_count(self, fantasy_pack):
        """The pack defines a rich set of fantasy skills (30+)."""
        assert len(fantasy_pack.skills) >= 30


# ---------------------------------------------------------------------------
# Pack discovery — fantasy pack discoverable alongside sci-fi.
# ---------------------------------------------------------------------------


class TestPackDiscovery:
    """The directory-scan registry discovers the fantasy pack."""

    def test_discover_packs_finds_fantasy(self):
        packs = discover_packs()
        assert "fantasy" in packs
        assert isinstance(packs["fantasy"], ThemePack)

    def test_discover_packs_finds_both_fantasy_and_scifi(self):
        packs = discover_packs()
        assert "fantasy" in packs
        assert "scifi" in packs

    def test_fantasy_and_scifi_are_distinct_packs(self):
        packs = discover_packs()
        assert packs["fantasy"].id != packs["scifi"].id
        assert packs["fantasy"].careers.keys() != packs["scifi"].careers.keys()


# ---------------------------------------------------------------------------
# Fantasy lifepath end-to-end (AE10 — same engine, no code changes).
# ---------------------------------------------------------------------------


def _make_engine(queue, death_mode="narrative", seed=42):
    state = GameState.new(seed=seed)
    state.campaign = CampaignConfig(theme_pack="fantasy", death_mode=death_mode)
    return Engine(state, roller=ForcedRoller(queue))


class TestFantasyLifepath:
    """Fantasy lifepath runs end-to-end using the same LifepathRunner engine."""

    def test_knight_lifepath_two_terms(self, fantasy_pack):
        """Full lifepath for a Knight: chars -> qualification -> 2 terms -> muster out."""
        queue = [
            # Characteristics (6 x 2D6)
            [5, 3],  # STR = 8
            [4, 3],  # DEX = 7
            [5, 3],  # END = 8
            [5, 4],  # INT = 9
            [4, 3],  # EDU = 7
            [4, 2],  # SOC = 6
            # Knight qualification (STR 8, DM +1, target 5)
            [3, 2],  # 5 + 1 = 6 >= 5 -> success
            # Term 1: survival, advancement, 2 skills
            [4, 3],  # Survival: END 8 + DM +1 = 8 >= 5 -> success
            [5, 3],  # Advancement: EDU 7 + DM 0 = 8 >= 7 -> success (rank 1)
            [5, 3],  # Skill (Personal Dev): 8
            [4, 3],  # Skill (Service): 7
            # Term 2
            [3, 3],  # Survival: END 8 + DM +1 = 7 >= 5 -> success
            [4, 4],  # Advancement: EDU 7 + DM 0 = 8 >= 7 -> success (rank 2)
            [6, 3],  # Skill (Personal Dev): 9
            [6, 4],  # Skill (Service): 10
            # Mustering out (2 terms, rank 2)
            # Cash: DM = dm_per_term*2 + dm_per_rank*2
            [1],  # roll 1
            [1],  # roll 1
            # Material: 2 rolls
            [3],  # roll 3
            [5],  # roll 5
        ]
        engine = _make_engine(queue)
        runner = LifepathRunner(engine, fantasy_pack)
        result = runner.run_lifepath("knight", num_terms=2)

        # Qualification succeeded.
        assert result.qualification is not None
        assert result.qualification.success
        assert result.qualification.career_id == "knight"

        # Two terms completed.
        assert result.num_terms == 2
        assert result.terms[0].survival_success
        assert result.terms[0].advancement_success
        assert result.terms[0].rank_after == 1
        assert result.terms[1].rank_after == 2

        # Character alive, career set.
        assert result.character_alive
        char = engine.state.character
        assert char.alive
        assert char.career == "knight"
        assert char.terms == 2
        assert char.rank == 2

        # Mustering out completed.
        assert result.mustering_out is not None
        assert len(result.mustering_out.cash_benefits) == 2
        assert len(result.mustering_out.material_benefits) == 2

    def test_mage_lifepath_one_term(self, fantasy_pack):
        """Mage lifepath: spellcasting career runs through the engine."""
        queue = [
            [4, 3],  # STR = 7
            [4, 3],  # DEX = 7
            [4, 3],  # END = 7
            [5, 4],  # INT = 9
            [5, 3],  # EDU = 8
            [3, 2],  # SOC = 5
            # Mage qualification (INT 9, DM +1, target 6)
            [4, 3],  # 7 + 1 = 8 >= 6 -> success
            # Term 1
            [4, 3],  # Survival: INT 9 + DM +1 = 8 >= 5 -> success
            [5, 4],  # Advancement: INT 9 + DM +1 = 10 >= 7 -> success (rank 1)
            [5, 3],  # Skill 1
            [4, 3],  # Skill 2 (advancement -> extra)
            # Mustering out (1 term, rank 1)
            [1],  # cash
            [2],  # material
        ]
        engine = _make_engine(queue)
        runner = LifepathRunner(engine, fantasy_pack)
        result = runner.run_lifepath("mage", num_terms=1)

        assert result.qualification.success
        assert result.qualification.career_id == "mage"
        assert result.num_terms == 1
        assert result.character_alive
        assert engine.state.character.career == "mage"
        assert len(result.terms[0].skill_gains) == 2

    def test_fantasy_skills_gained_in_lifepath(self, fantasy_pack):
        """Skills gained during lifepath are fantasy skills, not sci-fi skills."""
        queue = [
            [5, 3],
            [4, 3],
            [5, 3],
            [5, 4],
            [4, 3],
            [4, 2],  # chars
            [3, 2],  # qual: Knight STR 8 + 1 = 6 >= 5
            [4, 3],  # survival
            [5, 3],  # advancement
            [4, 3],  # skill 1 -> roll 7
            [3, 3],  # skill 2 -> roll 6 (advancement extra)
            [1],  # cash
            [1],  # material
        ]
        engine = _make_engine(queue)
        runner = LifepathRunner(engine, fantasy_pack)
        result = runner.run_lifepath("knight", num_terms=1)

        # Collect all skill results.
        skill_results = []
        for term in result.terms:
            for gain in term.skill_gains:
                skill_results.append(gain.result_text)

        # None of the skill results should be sci-fi-only skills.
        scifi_only = {
            "pilot_small_craft",
            "astrogation",
            "gun_combat_slug_rifle",
            "electronics_comms",
            "engineer",
            "sensor_ops",
        }
        for s in skill_results:
            if not s.startswith("+"):
                assert s not in scifi_only, f"Sci-fi skill '{s}' appeared in fantasy lifepath"


# ---------------------------------------------------------------------------
# Fantasy oracle tables produce genre-appropriate content.
# ---------------------------------------------------------------------------


class TestFantasyOracles:
    """Oracle tables produce fantasy-appropriate scene scaffolding."""

    def test_oracle_tables_present(self, fantasy_pack):
        assert len(fantasy_pack.oracle_tables) >= 3

    def test_oracle_content_is_fantasy(self, fantasy_pack):
        """Oracle results contain fantasy-genre language, not sci-fi."""
        fantasy_terms = (
            "tavern",
            "dungeon",
            "castle",
            "dragon",
            "guild",
            "kingdom",
            "spell",
            "sword",
            "sorcerer",
            "quest",
            "mage",
            "knight",
            "temple",
            "forest",
            "village",
            "magic",
            "curse",
            "relic",
            "monster",
            "beast",
            "realm",
            "throne",
            "rune",
            "ancient",
            "wilderness",
            "inn",
            "crypt",
            "cursed",
        )
        all_text = ""
        for table in fantasy_pack.oracle_tables.values():
            for entry in table.entries.entries:
                all_text += entry.result.lower() + " "

        # At least some oracle results contain fantasy terminology.
        matches = [term for term in fantasy_terms if term in all_text]
        assert len(matches) >= 3, (
            f"Oracle tables lack fantasy terminology. Found matches: {matches}"
        )

    def test_no_scifi_terms_in_fantasy_oracles(self, fantasy_pack):
        """Oracle results should not contain jarring sci-fi terminology."""
        scifi_terms = (
            "starship",
            "blaster",
            "hyperspace",
            "star system",
            "laser",
            "planet",
            "galaxy",
            "space station",
            "android",
            "cybernetic",
            "terraform",
        )
        for table_id, table in fantasy_pack.oracle_tables.items():
            for entry in table.entries.entries:
                text = entry.result.lower()
                for term in scifi_terms:
                    assert term not in text, (
                        f"Sci-fi term '{term}' in oracle table '{table_id}': {entry.result}"
                    )


# ---------------------------------------------------------------------------
# Fantasy complication tables.
# ---------------------------------------------------------------------------


class TestFantasyComplications:
    """Complication tables produce fantasy-appropriate outcomes."""

    def test_complication_tables_present(self, fantasy_pack):
        assert len(fantasy_pack.complication_tables) >= 3

    def test_complication_content_is_fantasy(self, fantasy_pack):
        """Complication results reference fantasy elements."""
        fantasy_terms = (
            "sword",
            "spell",
            "armor",
            "potion",
            "curse",
            "guild",
            "monster",
            "beast",
            "dragon",
            "guard",
            "tavern",
            "inn",
            "castle",
            "dungeon",
            "temple",
            "arrow",
            "bow",
            "mount",
            "horse",
            "rune",
            "relic",
            "king",
            "lord",
            "mage",
            "wand",
            "scroll",
            "blow",
            "wound",
            "weapon",
        )
        all_text = ""
        for table in fantasy_pack.complication_tables.values():
            for entry in table.entries.entries:
                all_text += entry.result.lower() + " "

        matches = [term for term in fantasy_terms if term in all_text]
        assert len(matches) >= 2, f"Complication tables lack fantasy terminology. Found: {matches}"


# ---------------------------------------------------------------------------
# Fantasy mission tables.
# ---------------------------------------------------------------------------


class TestFantasyMissions:
    """Mission tables produce fantasy-appropriate adventure hooks."""

    def test_mission_tables_present(self, fantasy_pack):
        assert len(fantasy_pack.mission_tables) >= 3

    def test_mission_content_is_fantasy(self, fantasy_pack):
        """Mission hooks reference fantasy patrons and objectives."""
        fantasy_terms = (
            "guild",
            "noble",
            "wizard",
            "dragon",
            "temple",
            "king",
            "queen",
            "lord",
            "castle",
            "dungeon",
            "relic",
            "artifact",
            "spell",
            "curse",
            "beast",
            "monster",
            "rescue",
            "kingdom",
            "throne",
            "quest",
            "treasure",
            "tome",
            "amulet",
            "quest",
            "baron",
            "count",
            "duke",
            "witch",
            "warlock",
            "sage",
            "village",
            "farm",
            "crop",
            "blight",
        )
        all_text = ""
        for table in fantasy_pack.mission_tables.values():
            for entry in table.entries.entries:
                all_text += entry.result.lower() + " "

        matches = [term for term in fantasy_terms if term in all_text]
        assert len(matches) >= 3, f"Mission tables lack fantasy terminology. Found: {matches}"

    def test_mission_reward_uses_fantasy_currency(self, fantasy_pack):
        """Mission rewards use gold/silver instead of Credits."""
        reward_table = None
        for table in fantasy_pack.mission_tables.values():
            if "reward" in table.id.lower():
                reward_table = table
                break
        if reward_table is None:
            for table in fantasy_pack.mission_tables.values():
                if "reward" in table.name.lower():
                    reward_table = table
                    break

        assert reward_table is not None, "No reward table found"
        all_text = " ".join(e.result.lower() for e in reward_table.entries.entries)
        assert "gold" in all_text or "silver" in all_text or "crown" in all_text, (
            f"Reward table lacks fantasy currency: {all_text}"
        )


# ---------------------------------------------------------------------------
# Edge cases — invalid data raises.
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Invalid fantasy pack data raises validation errors."""

    def test_broken_referential_integrity_raises(self):
        bad_data = {
            "pack": {"id": "bad", "name": "Bad", "description": "Test"},
            "careers": {
                "knight": {
                    "id": "knight",
                    "name": "Knight",
                    "description": "Test",
                    "qualification": {"characteristic": "STR", "target": 5},
                    "survival": {"characteristic": "END", "target": 5},
                    "advancement": {"characteristic": "EDU", "target": 7},
                    "skill_tables": [],
                    "ranks": [],
                    "mustering_out_cash": None,
                    "mustering_out_material": None,
                }
            },
            "skills": {
                "sword": {
                    "id": "sword",
                    "name": "Sword",
                    "description": "Test",
                    "career": "nonexistent",
                }
            },
            "oracle_tables": {},
            "complication_tables": {},
            "mission_tables": {},
        }
        with pytest.raises(PackLoadError, match="Referential"):
            validate_pack(bad_data)
