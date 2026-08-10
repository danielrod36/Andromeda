"""P3.T1 — pack schema v2 additive fields default away (A6)."""

from src.rulesets.base import RankEntry, SkillTableEntry


def test_rank_entry_defaults_no_bonus_skills():
    """RankEntry without bonus_skills still validates."""
    entry = RankEntry(rank=1, title="Midshipman")
    assert entry.bonus_skills == []


def test_rank_entry_with_bonus_skills():
    entry = RankEntry(
        rank=4,
        title="Commander",
        bonus_skills=[{"skill": "leadership", "level": 1}],
    )
    assert entry.bonus_skills == [{"skill": "leadership", "level": 1}]


def test_skill_table_entry_defaults():
    entry = SkillTableEntry(min=3, max=3, result="Weapon")
    assert entry.effects is None
    assert entry.once is False
    assert entry.on_duplicate is None


def test_fantasy_pack_loads_unchanged():
    """Fantasy pack has no v2 fields and must load without error (A6)."""
    from src.themepacks.fantasy import load_fantasy_pack

    pack = load_fantasy_pack()
    assert pack.id == "fantasy"


# ---------------------------------------------------------------------------
# C3 — cascade schema (cascades.yaml, C-A1).
# ---------------------------------------------------------------------------

import pytest  # noqa: E402

from src.themepacks.base import PackLoadError, validate_pack  # noqa: E402


def _minimal_pack_dict(cascades=None, skills=None):
    """Smallest valid pack dict; mirrors test_scifi.py's synthetic pattern."""
    return {
        "pack": {"id": "t", "name": "T", "description": "t"},
        "careers": {},
        "skills": skills
        or {
            "gun_combat_slug_rifle": {
                "id": "gun_combat_slug_rifle",
                "name": "Gun Combat (Slug Rifle)",
            },
            "gun_combat_slug_pistol": {
                "id": "gun_combat_slug_pistol",
                "name": "Gun Combat (Slug Pistol)",
            },
        },
        "oracle_tables": {},
        "complication_tables": {},
        "mission_tables": {},
        **({"cascades": cascades} if cascades is not None else {}),
    }


def test_cascades_optional_absent():
    """Packs without cascades load with an empty cascade map (C-A1/A6)."""
    pack = validate_pack(_minimal_pack_dict())
    assert pack.cascades == {}


def test_cascades_parse():
    pack = validate_pack(
        _minimal_pack_dict(
            cascades={
                "gun_combat": {
                    "id": "gun_combat",
                    "name": "Gun Combat",
                    "specializations": ["gun_combat_slug_rifle", "gun_combat_slug_pistol"],
                }
            }
        )
    )
    assert pack.cascades["gun_combat"].name == "Gun Combat"
    assert len(pack.cascades["gun_combat"].specializations) == 2


def test_cascade_member_must_exist():
    bad = _minimal_pack_dict(
        cascades={
            "gun_combat": {
                "id": "gun_combat",
                "name": "Gun Combat",
                "specializations": ["gun_combat_slug_rifle", "gun_combat_energy_rifle"],
            }
        }
    )
    with pytest.raises(PackLoadError, match="Referential"):
        validate_pack(bad)


def test_cascade_member_prefix_rule():
    """Members must start with '{parent}_' so prefix resolution aligns (C-A1)."""
    bad = _minimal_pack_dict(
        skills={
            "gun_combat_slug_rifle": {"id": "gun_combat_slug_rifle", "name": "R"},
            "melee_blade": {"id": "melee_blade", "name": "B"},
        },
        cascades={
            "gun_combat": {
                "id": "gun_combat",
                "name": "Gun Combat",
                "specializations": ["gun_combat_slug_rifle", "melee_blade"],
            }
        },
    )
    with pytest.raises(PackLoadError, match="prefix"):
        validate_pack(bad)


def test_cascade_parent_not_a_skill():
    bad = _minimal_pack_dict(
        cascades={
            "gun_combat_slug_rifle": {  # parent collides with a skill id
                "id": "gun_combat_slug_rifle",
                "name": "Bad",
                "specializations": ["gun_combat_slug_rifle"],
            }
        }
    )
    with pytest.raises(PackLoadError, match="Referential"):
        validate_pack(bad)


def test_cascade_no_double_membership():
    bad = _minimal_pack_dict(
        cascades={
            "gun_combat": {
                "id": "gun_combat",
                "name": "Gun Combat",
                "specializations": ["gun_combat_slug_rifle"],
            },
            "gun": {
                "id": "gun",
                "name": "Guns",
                "specializations": ["gun_combat_slug_rifle"],
            },
        },
    )
    with pytest.raises(PackLoadError, match="two cascades"):
        validate_pack(bad)
