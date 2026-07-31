"""Tests for skill resolution helpers (Task 16 / FR1).

Covers exact ID match, cascade-parent specialization, the CE SRD untrained
penalty (-3), and the level-0-is-trained rule (basic training/background
skills grant level 0).
"""

from __future__ import annotations

from src.engine.state import Character


def test_exact_id_match():
    from src.engine.skills import skill_level_for

    c = Character(skills={"gun_combat_slug_rifle": 2})
    assert skill_level_for(c, "gun_combat_slug_rifle") == (2, True)


def test_cascade_parent_takes_best_specialization():
    from src.engine.skills import skill_level_for

    c = Character(skills={"gun_combat_slug_rifle": 2, "gun_combat_energy_rifle": 1})
    assert skill_level_for(c, "gun_combat") == (2, True)


def test_untrained_penalty_minus_3():
    from src.engine.skills import skill_level_for

    assert skill_level_for(Character(), "mechanic") == (-3, False)


def test_level_0_is_trained():
    from src.engine.skills import skill_level_for

    assert skill_level_for(Character(skills={"mechanic": 0}), "mechanic") == (0, True)


def test_cascade_parent_untrained_returns_minus_3():
    """Cascade parent with no matching specializations is untrained."""
    from src.engine.skills import skill_level_for

    c = Character(skills={"mechanic": 1})
    # 'gun_combat' prefix matches nothing in {mechanic:1}.
    assert skill_level_for(c, "gun_combat") == (-3, False)


def test_cascade_parent_with_only_zero_level_is_trained():
    """A cascade-parent specialization at level 0 counts as trained."""
    from src.engine.skills import skill_level_for

    c = Character(skills={"gun_combat_slug_rifle": 0})
    assert skill_level_for(c, "gun_combat") == (0, True)


def test_skill_display_name_uses_pack_data():
    from src.engine.skills import skill_display_name
    from src.themepacks.base import get_pack

    pack = get_pack("scifi")
    assert skill_display_name(pack, "gun_combat_slug_rifle") == "Gun Combat (Slug Rifle)"
    assert skill_display_name(pack, "persuade") == "Persuade"


def test_skill_display_name_falls_back_to_title_cased_id():
    from src.engine.skills import skill_display_name
    from src.themepacks.base import get_pack

    pack = get_pack("scifi")
    # 'unknown_skill' is not in the pack: falls back to title-cased ID.
    assert skill_display_name(pack, "unknown_skill_id") == "Unknown Skill Id"
