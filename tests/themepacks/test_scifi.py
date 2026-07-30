"""Tests for the CE SRD sci-fi theme pack (R20, R21).

Covers data validity, referential integrity, pack discovery, career table
completeness, and edge cases for invalid data.
"""

from __future__ import annotations

import pytest

from src.rulesets.base import (
    ThemePack,
)
from src.themepacks.base import (
    PackLoadError,
    discover_packs,
    validate_pack,
)
from src.themepacks.cepheus_scifi import load_scifi_pack

# ---------------------------------------------------------------------------
# Scenario 2: Sci-fi pack data validity — careers have required fields.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def scifi_pack():
    """Load the sci-fi pack once for all tests in this module."""
    return load_scifi_pack()


def test_scifi_pack_satisfies_themepack_protocol(scifi_pack):
    assert isinstance(scifi_pack, ThemePack)


def test_scifi_pack_id(scifi_pack):
    assert scifi_pack.id == "scifi"


def test_scifi_pack_name(scifi_pack):
    assert "Sci" in scifi_pack.name or "sci" in scifi_pack.name.lower()


# ---------------------------------------------------------------------------
# Scenario 5: Career table completeness — 6-8 starter careers with correct structure.
# ---------------------------------------------------------------------------


def test_career_count_between_6_and_8(scifi_pack):
    """The sci-fi pack has between 6 and 8 starter careers."""
    count = len(scifi_pack.careers)
    assert 6 <= count <= 8, f"Expected 6-8 careers, got {count}"


def test_all_expected_careers_present(scifi_pack):
    """All 8 starter careers are present."""
    ids = set(scifi_pack.careers.keys())
    expected = {"navy", "army", "marines", "merchant", "scout", "agent", "noble", "drifter"}
    assert ids == expected, f"Missing: {expected - ids}, Extra: {ids - expected}"


@pytest.mark.parametrize(
    "career_id",
    [
        "navy",
        "army",
        "marines",
        "merchant",
        "scout",
        "agent",
        "noble",
        "drifter",
    ],
)
def test_career_has_required_fields(scifi_pack, career_id):
    """Each career has qualification, survival, advancement, and skill tables."""
    career = scifi_pack.careers[career_id]
    assert career.id == career_id
    assert career.name
    assert career.description
    # Qualification
    assert career.qualification.characteristic in ("STR", "DEX", "END", "INT", "EDU", "SOC")
    # Survival and advancement targets
    assert career.survival.target >= 2
    assert career.advancement.target >= 2
    # Three skill tables
    table_names = {t.name for t in career.skill_tables}
    assert "Personal Development" in table_names
    assert "Service Skills" in table_names
    assert "Advanced Education" in table_names
    assert len(career.skill_tables) == 3


@pytest.mark.parametrize(
    "career_id",
    [
        "navy",
        "army",
        "marines",
        "merchant",
        "scout",
        "agent",
        "noble",
        "drifter",
    ],
)
def test_career_skill_tables_have_contiguous_ranges(scifi_pack, career_id):
    """Every skill table in every career covers 2D6 (2-12) contiguously."""
    career = scifi_pack.careers[career_id]
    for table in career.skill_tables:
        assert table.entries.is_contiguous(), (
            f"Career {career_id} table '{table.name}' has non-contiguous ranges"
        )
        # Must cover full 2-12 range
        assert table.entries.entries[0].min == 2
        assert table.entries.entries[-1].max == 12


def test_career_mustering_out_tables(scifi_pack):
    """Careers have mustering-out benefit tables (cash and material)."""
    navy = scifi_pack.careers["navy"]
    assert navy.mustering_out_cash is not None
    assert navy.mustering_out_material is not None
    # Cash table entries are contiguous
    assert navy.mustering_out_cash.entries.is_contiguous()
    assert navy.mustering_out_material.entries.is_contiguous()


# ---------------------------------------------------------------------------
# Scenario 3: Referential integrity — skills, oracle tables, careers.
# ---------------------------------------------------------------------------


def test_all_career_skills_exist_in_skill_definitions(scifi_pack):
    """Every skill referenced in career tables is defined in skills.yaml."""
    defined_skills = set(scifi_pack.skills.keys())
    for career_id, career in scifi_pack.careers.items():
        for table in career.skill_tables:
            for entry in table.entries.entries:
                result = entry.result
                # Skip characteristic increases (e.g. "+1 STR")
                if result.startswith(("+", "-")):
                    continue
                # Strip level suffixes like "Pilot-1" or "Gunnery (Turrets)"
                skill_key = result.lower().replace(" ", "_").replace("(", "").replace(")", "")
                assert skill_key in defined_skills or result in defined_skills, (
                    f"Career '{career_id}' references skill '{result}' not defined in skills"
                )


def test_oracle_tables_have_contiguous_ranges(scifi_pack):
    """Every oracle table covers its full die range contiguously."""
    for table_id, table in scifi_pack.oracle_tables.items():
        assert table.entries.is_contiguous(), f"Oracle table '{table_id}' has non-contiguous ranges"


def test_complication_tables_have_contiguous_ranges(scifi_pack):
    for table_id, table in scifi_pack.complication_tables.items():
        assert table.entries.is_contiguous(), (
            f"Complication table '{table_id}' has non-contiguous ranges"
        )


def test_mission_tables_have_contiguous_ranges(scifi_pack):
    for table_id, table in scifi_pack.mission_tables.items():
        assert table.entries.is_contiguous(), (
            f"Mission table '{table_id}' has non-contiguous ranges"
        )


def test_skills_reference_valid_careers(scifi_pack):
    """Every skill with a career reference points to an existing career."""
    career_ids = set(scifi_pack.careers.keys())
    for skill_id, skill in scifi_pack.skills.items():
        if skill.career:
            assert skill.career in career_ids, (
                f"Skill '{skill_id}' references career '{skill.career}' which does not exist"
            )


# ---------------------------------------------------------------------------
# Oracle tables content.
# ---------------------------------------------------------------------------


def test_oracle_tables_present(scifi_pack):
    """At least one oracle table exists for scene scaffolding."""
    assert len(scifi_pack.oracle_tables) >= 1


def test_complication_tables_present(scifi_pack):
    """Complication tables exist for Narrative profile weak hits."""
    assert len(scifi_pack.complication_tables) >= 1


def test_mission_tables_present(scifi_pack):
    """Mission hook tables exist."""
    assert len(scifi_pack.mission_tables) >= 1


# ---------------------------------------------------------------------------
# Scenario 4: Pack discovery — theme packs discoverable via directory scan.
# ---------------------------------------------------------------------------


def test_discover_packs_finds_scifi():
    """The directory-scan registry discovers the 'scifi' pack."""
    packs = discover_packs()
    assert "scifi" in packs
    assert isinstance(packs["scifi"], ThemePack)


def test_discover_packs_returns_loaded_packs():
    """discover_packs returns packs that are fully loaded and validated."""
    packs = discover_packs()
    scifi = packs["scifi"]
    assert len(scifi.careers) >= 6
    assert len(scifi.skills) > 0


# ---------------------------------------------------------------------------
# Edge cases — invalid data raises validation errors.
# ---------------------------------------------------------------------------


def test_broken_referential_integrity_raises():
    """Loading a pack where a skill references a non-existent career raises."""
    bad_data = {
        "pack": {"id": "bad", "name": "Bad", "description": "Test"},
        "careers": {
            "navy": {
                "id": "navy",
                "name": "Navy",
                "description": "Test",
                "qualification": {"characteristic": "INT", "target": 5},
                "survival": {"characteristic": "END", "target": 5},
                "advancement": {"characteristic": "EDU", "target": 7},
                "skill_tables": [],
                "ranks": [],
                "mustering_out_cash": None,
                "mustering_out_material": None,
            }
        },
        "skills": {
            "pilot": {
                "id": "pilot",
                "name": "Pilot",
                "description": "Test",
                "career": "nonexistent_career",
            }
        },
        "oracle_tables": {},
        "complication_tables": {},
        "mission_tables": {},
    }
    with pytest.raises(PackLoadError, match="Referential"):
        validate_pack(bad_data)


def test_non_contiguous_range_raises():
    """A table with a gap in its die ranges fails validation."""
    bad_data = {
        "pack": {"id": "bad", "name": "Bad", "description": "Test"},
        "careers": {},
        "skills": {},
        "oracle_tables": {
            "test": {
                "id": "test",
                "name": "Test Oracle",
                "description": "",
                "entries": {
                    "entries": [
                        {"min": 2, "max": 4, "result": "A"},
                        {"min": 6, "max": 12, "result": "B"},
                    ],
                },
            }
        },
        "complication_tables": {},
        "mission_tables": {},
    }
    with pytest.raises(PackLoadError, match="contiguous"):
        validate_pack(bad_data)


def test_missing_required_field_raises():
    """A career missing its survival target fails validation."""
    bad_data = {
        "pack": {"id": "bad", "name": "Bad", "description": "Test"},
        "careers": {
            "broken": {
                "id": "broken",
                "name": "Broken Career",
                "description": "Missing survival",
                # No survival target
                "advancement": {"characteristic": "EDU", "target": 7},
                "skill_tables": [],
                "ranks": [],
                "mustering_out_cash": None,
                "mustering_out_material": None,
            }
        },
        "skills": {},
        "oracle_tables": {},
        "complication_tables": {},
        "mission_tables": {},
    }
    with pytest.raises((PackLoadError, Exception)):
        validate_pack(bad_data)


def test_empty_pack_id_raises():
    """A pack with an empty id fails validation."""
    bad_data = {
        "pack": {"id": "", "name": "Bad", "description": "Test"},
        "careers": {},
        "skills": {},
        "oracle_tables": {},
        "complication_tables": {},
        "mission_tables": {},
    }
    with pytest.raises((PackLoadError, Exception)):
        validate_pack(bad_data)


def test_overlapping_ranges_in_career_skill_table_raises():
    """A career skill table with overlapping ranges fails validation."""
    bad_data = {
        "pack": {"id": "bad", "name": "Bad", "description": "Test"},
        "careers": {
            "navy": {
                "id": "navy",
                "name": "Navy",
                "description": "Test",
                "qualification": {"characteristic": "INT", "target": 5},
                "survival": {"characteristic": "END", "target": 5},
                "advancement": {"characteristic": "EDU", "target": 7},
                "skill_tables": [
                    {
                        "name": "Personal Development",
                        "entries": {
                            "entries": [
                                {"min": 2, "max": 6, "result": "+1 STR"},
                                {"min": 5, "max": 12, "result": "+1 DEX"},
                            ],
                        },
                    },
                ],
                "ranks": [],
                "mustering_out_cash": None,
                "mustering_out_material": None,
            }
        },
        "skills": {},
        "oracle_tables": {},
        "complication_tables": {},
        "mission_tables": {},
    }
    with pytest.raises(PackLoadError, match="contiguous"):
        validate_pack(bad_data)


def test_all_eight_careers_have_skill_table_count(scifi_pack):
    """Every career has exactly three skill tables."""
    for career_id, career in scifi_pack.careers.items():
        assert len(career.skill_tables) == 3, (
            f"Career '{career_id}' has {len(career.skill_tables)} skill tables, expected 3"
        )


def test_all_eight_careers_have_mustering_out(scifi_pack):
    """Every career has both cash and material benefit tables."""
    for career_id, career in scifi_pack.careers.items():
        assert career.mustering_out_cash is not None, (
            f"Career '{career_id}' missing cash benefits table"
        )
        assert career.mustering_out_material is not None, (
            f"Career '{career_id}' missing material benefits table"
        )
