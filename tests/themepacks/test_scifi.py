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


def test_career_count_is_25(scifi_pack):
    """The sci-fi pack has all 25 CE SRD careers (24 SRD + army as Surface Defense alias)."""
    count = len(scifi_pack.careers)
    assert count == 25, f"Expected 25 careers, got {count}"


_SRD_CAREERS = {
    "aerospace_defense",
    "agent",
    "army",
    "athlete",
    "barbarian",
    "belter",
    "bureaucrat",
    "colonist",
    "diplomat",
    "drifter",
    "entertainer",
    "hunter",
    "maritime_defense",
    "marines",
    "mercenary",
    "merchant",
    "navy",
    "noble",
    "physician",
    "pirate",
    "rogue",
    "scientist",
    "scout",
    "surface_defense",
    "technician",
}
_NON_HIERARCHY = {
    "athlete",
    "barbarian",
    "belter",
    "drifter",
    "entertainer",
    "hunter",
    "scout",
}


def test_all_expected_careers_present(scifi_pack):
    """All 25 CE SRD careers are present."""
    ids = set(scifi_pack.careers.keys())
    assert ids == _SRD_CAREERS, f"Missing: {_SRD_CAREERS - ids}, Extra: {ids - _SRD_CAREERS}"


def test_non_hierarchy_careers_match_srd(scifi_pack):
    """Non-hierarchy careers have has_hierarchy == False (B5)."""
    for cid, career in scifi_pack.careers.items():
        assert career.has_hierarchy == (cid not in _NON_HIERARCHY), cid


def test_all_25_careers_structurally_complete(scifi_pack):
    """Every career has 4 skill tables, a mishap table, and re-enlistment (B14/B20)."""
    for cid in _SRD_CAREERS:
        c = scifi_pack.careers[cid]
        assert len(c.skill_tables) == 4, cid
        assert c.mishap_table is not None, cid
        assert c.re_enlistment is not None, cid


@pytest.mark.parametrize("career_id", sorted(_SRD_CAREERS))
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
    if career.advancement is not None:
        assert career.advancement.target >= 2
    # Four skill tables (B14)
    table_names = {t.name for t in career.skill_tables}
    assert "Personal Development" in table_names
    assert "Service Skills" in table_names
    assert "Specialist Skills" in table_names
    assert "Advanced Education" in table_names
    assert len(career.skill_tables) == 4


@pytest.mark.parametrize("career_id", sorted(_SRD_CAREERS))
def test_career_skill_tables_have_contiguous_ranges(scifi_pack, career_id):
    """Every skill table in every career covers 1D6 (1-6) contiguously."""
    career = scifi_pack.careers[career_id]
    for table in career.skill_tables:
        assert table.entries.is_contiguous(), (
            f"Career {career_id} table '{table.name}' has non-contiguous ranges"
        )
        # Must cover full 1-6 range (1D6)
        assert table.entries.entries[0].min == 1
        assert table.entries.entries[-1].max == 6


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
    """Every career has exactly four skill tables (B14)."""
    for career_id, career in scifi_pack.careers.items():
        assert len(career.skill_tables) == 4, (
            f"Career '{career_id}' has {len(career.skill_tables)} skill tables, expected 4"
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


# ---------------------------------------------------------------------------
# Task 3: 1D6 skill tables, SRD-verified careers, non-hierarchy flags (B3/B5/B6).
# ---------------------------------------------------------------------------


def test_all_skill_tables_are_1d6(scifi_pack):
    for career in scifi_pack.careers.values():
        for table in career.skill_tables:
            assert table.entries.num_dice == 1, f"{career.id}/{table.name}"
            assert table.entries.entries[0].min == 1
            assert table.entries.entries[-1].max == 6


def test_non_hierarchy_careers_have_no_advancement(scifi_pack):
    for cid in _NON_HIERARCHY:
        assert scifi_pack.careers[cid].has_hierarchy is False
        assert scifi_pack.careers[cid].advancement is None


def test_agent_career_matches_srd(scifi_pack):
    agent = scifi_pack.careers["agent"]
    assert (agent.qualification.characteristic, agent.qualification.target) == ("SOC", 6)
    assert (agent.survival.characteristic, agent.survival.target) == ("INT", 6)
    assert (agent.commission.characteristic, agent.commission.target) == ("EDU", 7)
    assert (agent.advancement.characteristic, agent.advancement.target) == ("EDU", 6)
    assert agent.re_enlistment == 6


# ---------------------------------------------------------------------------
# Task 5: Pack injury table + per-career mishap tables (B13).
# ---------------------------------------------------------------------------


def test_scifi_pack_has_injury_table(scifi_pack):
    """The sci-fi pack has a 1D6 injury table loaded from pack.yaml."""
    assert scifi_pack.injury_table is not None
    assert scifi_pack.injury_table.is_contiguous()
    assert scifi_pack.injury_table.num_dice == 1
    assert scifi_pack.injury_table.entries[0].min == 1
    assert scifi_pack.injury_table.entries[-1].max == 6
    assert len(scifi_pack.injury_table.entries) == 6


@pytest.mark.parametrize("career_id", sorted(_SRD_CAREERS))
def test_every_scifi_career_has_mishap_table(scifi_pack, career_id):
    """Every sci-fi career has a 1D6 (6-row) mishap table (B13)."""
    career = scifi_pack.careers[career_id]
    assert career.mishap_table is not None, f"Career '{career_id}' missing mishap_table"
    assert career.mishap_table.is_contiguous()
    assert career.mishap_table.num_dice == 1
    assert career.mishap_table.entries[0].min == 1
    assert career.mishap_table.entries[-1].max == 6
    assert len(career.mishap_table.entries) == 6


# ---------------------------------------------------------------------------
# Task 9: Background skills — SkillData.background flag and pack exposure.
# ---------------------------------------------------------------------------


def test_scifi_pack_exposes_background_skills(scifi_pack):
    """``pack.background_skills`` is a non-empty list of skill ids flagged
    ``background: true`` in skills.yaml (B10).
    """
    assert isinstance(scifi_pack.background_skills, list)
    assert len(scifi_pack.background_skills) >= 6
    # Every id must exist in skills.
    for sid in scifi_pack.background_skills:
        assert sid in scifi_pack.skills, f"Background skill {sid!r} not in pack.skills"
        assert scifi_pack.skills[sid].background is True


def test_scifi_background_skills_match_srd_education_list(scifi_pack):
    """The background-flagged skills match a CE-SRD-consistent education list.

    The SRD lets characters pick from a background/education skill list before
    careers — drive, electronics, gun combat, etc. We verify a representative
    subset is flagged.
    """
    # Representative SRD background skills (any-character education list).
    expected_subset = {
        "drive_ground_vehicle",
        "electronics_comms",
        "gun_combat_slug_rifle",
        "mechanic",
        "vacc_suit",
        "athletics",
    }
    flagged = set(scifi_pack.background_skills)
    missing = expected_subset - flagged
    assert not missing, f"Expected SRD background skills missing: {sorted(missing)}"


def test_default_skill_background_flag_false():
    """Skills without an explicit ``background:`` field default to False."""
    from src.rulesets.base import SkillData

    skill = SkillData(id="x", name="X")
    assert skill.background is False


# ---------------------------------------------------------------------------
# Task 13: Specialist Skills tables, mishap verification, 7-row benefits (B14).
# ---------------------------------------------------------------------------


def test_every_career_has_four_skill_tables(scifi_pack):
    """Every career has exactly four skill tables in SRD order (B14)."""
    for career in scifi_pack.careers.values():
        names = [t.name for t in career.skill_tables]
        assert names == [
            "Personal Development",
            "Service Skills",
            "Specialist Skills",
            "Advanced Education",
        ], career.id


def test_every_career_has_mishap_table(scifi_pack):
    """Every career has a contiguous mishap table (B13)."""
    for career in scifi_pack.careers.values():
        assert career.mishap_table is not None, career.id
        assert career.mishap_table.is_contiguous()


def test_benefit_tables_have_seven_rows_with_extension(scifi_pack):
    """Cash and material benefit tables have 7 rows with max_extension >= 1 (B15)."""
    for career in scifi_pack.careers.values():
        for table in (career.mustering_out_cash, career.mustering_out_material):
            if table is not None:
                assert table.entries.max_extension >= 1
                assert table.entries.entries[-1].max == 7
