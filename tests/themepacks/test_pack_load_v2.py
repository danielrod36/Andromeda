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
