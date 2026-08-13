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


def test_cascade_ref_in_skill_table_must_exist():
    """A ``cascade:<parent>`` result in a skill table must reference a
    declared cascade parent (C-A1 referential integrity).
    """
    bad = _minimal_pack_dict(
        cascades={
            "gun_combat": {
                "id": "gun_combat",
                "name": "Gun Combat",
                "specializations": ["gun_combat_slug_rifle"],
            }
        },
    )
    bad["careers"] = {
        "test_career": {
            "id": "test_career",
            "name": "Test Career",
            "description": "A test career.",
            "qualification": {"characteristic": "EDU", "target": 6},
            "survival": {"characteristic": "END", "target": 5},
            "advancement": {"characteristic": "EDU", "target": 6},
            "ranks": [],
            "skill_tables": [
                {
                    "name": "Service Skills",
                    "role": "service",
                    "entries": {
                        "num_dice": 1,
                        "die_size": 6,
                        "entries": [
                            {"min": 1, "max": 2, "result": "cascade:nonexistent"},
                            {"min": 3, "max": 3, "result": "cascade:gun_combat"},
                            {"min": 4, "max": 6, "result": "gun_combat_slug_rifle"},
                        ],
                    },
                }
            ],
        }
    }
    with pytest.raises(PackLoadError, match="cascade parent 'nonexistent'"):
        validate_pack(bad)


def test_cascade_ref_in_skill_table_passes_when_valid():
    """A ``cascade:<parent>`` result referencing a declared cascade loads OK."""
    good = _minimal_pack_dict(
        cascades={
            "gun_combat": {
                "id": "gun_combat",
                "name": "Gun Combat",
                "specializations": ["gun_combat_slug_rifle"],
            }
        },
    )
    good["careers"] = {
        "test_career": {
            "id": "test_career",
            "name": "Test Career",
            "description": "A test career.",
            "qualification": {"characteristic": "EDU", "target": 6},
            "survival": {"characteristic": "END", "target": 5},
            "advancement": {"characteristic": "EDU", "target": 6},
            "ranks": [],
            "skill_tables": [
                {
                    "name": "Service Skills",
                    "role": "service",
                    "entries": {
                        "num_dice": 1,
                        "die_size": 6,
                        "entries": [
                            {"min": 1, "max": 3, "result": "cascade:gun_combat"},
                            {"min": 4, "max": 6, "result": "gun_combat_slug_rifle"},
                        ],
                    },
                }
            ],
        }
    }
    pack = validate_pack(good)
    assert "gun_combat" in pack.cascades


# ---------------------------------------------------------------------------
# C5.T4 — pack-declared roles (engine de-hardcoding, C-A12).
# ---------------------------------------------------------------------------


def test_skill_grants_cash_dm_flag_defaults_false():
    """SkillData gains grants_cash_dm, defaulting off (C-A12)."""
    from src.rulesets.base import SkillData

    assert SkillData(id="x", name="X").grants_cash_dm is False
    assert SkillData(id="g", name="G", grants_cash_dm=True).grants_cash_dm is True


def test_skill_table_role_defaults_empty():
    """SkillTable gains role; absent means unroled (C-A12)."""
    from src.rulesets.base import SkillTable, TableRange

    table = SkillTable(
        name="Whatever",
        entries=TableRange(
            num_dice=1,
            die_size=6,
            entries=[{"min": 1, "max": 6, "result": "x"}],
        ),
    )
    assert table.role == ""


def test_loader_infers_legacy_table_roles():
    """Name-based role inference lives in the loader (content layer): packs that
    don't declare roles get 'service'/'advanced_education' from the legacy CE
    table names, so fantasy and old fixtures work unchanged (C-A10/C-A12)."""
    from src.themepacks.fantasy import load_fantasy_pack

    pack = load_fantasy_pack()
    for career in pack.careers.values():
        roles = {t.name: t.role for t in career.skill_tables}
        assert roles.get("Service Skills") == "service"
        if "Advanced Education" in roles:
            assert roles["Advanced Education"] == "advanced_education"


def test_loader_keeps_explicit_roles_for_custom_names():
    """A pack may name tables anything when roles are declared (C-A12)."""
    data = _minimal_pack_dict()
    data["careers"] = {
        "navy": {
            "id": "navy",
            "name": "Navy",
            "description": "t",
            "qualification": {"characteristic": "INT", "target": 5},
            "survival": {"characteristic": "END", "target": 5},
            "has_hierarchy": False,
            "skill_tables": [
                {
                    "name": "Boot Camp",
                    "role": "service",
                    "entries": {
                        "num_dice": 1,
                        "die_size": 6,
                        "entries": [{"min": 1, "max": 6, "result": "gun_combat_slug_rifle"}],
                    },
                },
            ],
            "ranks": [],
        }
    }
    pack = validate_pack(data)
    assert pack.careers["navy"].skill_tables[0].role == "service"


def test_currency_units_default_and_override():
    """Currency flavor is pack-declared; legacy default covers Cr+gold crowns (C-A12)."""
    from src.themepacks.fantasy import load_fantasy_pack

    fantasy = load_fantasy_pack()
    assert "gold crowns" in fantasy.currency_units  # legacy default, no data change
    data = _minimal_pack_dict()
    data["pack"]["currency_units"] = ["credits"]
    assert validate_pack(data).currency_units == ["credits"]


def test_pack_theme_and_intro_defaults_and_overrides():
    """M0.4: packs may ship theme:/intro: in pack.yaml; loader defaults otherwise."""
    pack = validate_pack(_minimal_pack_dict())
    assert pack.theme_tokens == {}
    assert pack.intro_text == ""

    themed = _minimal_pack_dict()
    themed["pack"]["theme"] = {"motif": "✦", "accent": "amber"}
    themed["pack"]["intro"] = "The frontier calls."
    pack2 = validate_pack(themed)
    assert pack2.theme_tokens == {"motif": "✦", "accent": "amber"}
    assert pack2.intro_text == "The frontier calls."
