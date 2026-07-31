"""Skill resolution helpers: canonical IDs, cascade parents, untrained penalty.

Adventure-loop skill checks (``SceneCheckCommand``) receive a skill *id* —
either an exact pack id (``gun_combat_slug_rifle``) or a cascade parent
(``gun_combat``) that should resolve to the character's best specialization
among ``gun_combat_*``. Lifepath-stored skills always use pack ids, so the
lookup here is the single canonicalization point that lets scene checks
benefit from earned skill levels (FR1).

Level-0 skills count as trained (basic training / background skills grant
level 0). Untrained skill use attracts the CE SRD DM of -3.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.engine.state import Character
    from src.themepacks.base import LoadedThemePack

UNTRAINED_DM = -3  # CE SRD: untrained skill use is DM -3.


def skill_level_for(character: Character, skill_id: str) -> tuple[int, bool]:
    """Return ``(effective_level_or_DM, trained)`` for a skill id.

    Resolution order:
      1. Exact id in ``character.skills`` → ``(level, True)``.
      2. Best level among cascade specializations (``{skill_id}_*``) →
         ``(max_level, True)``.
      3. Otherwise the CE SRD untrained penalty → ``(-3, False)``.

    Level 0 counts as trained (basic training / background skills).
    """
    if skill_id in character.skills:
        return character.skills[skill_id], True
    prefix = skill_id + "_"
    spec_levels = [v for k, v in character.skills.items() if k.startswith(prefix)]
    if spec_levels:
        return max(spec_levels), True
    return UNTRAINED_DM, False


def skill_display_name(pack: LoadedThemePack, skill_id: str) -> str:
    """Human-readable name from pack data, falling back to a title-cased id.

    Pack ``skills.yaml`` maps ids to display names; when the id is unknown
    (e.g. a cascade parent like ``gun_combat`` that has no own entry) the
    fallback renders the id itself in title case.
    """
    skill = pack.skills.get(skill_id)
    if skill is not None:
        return skill.name
    return skill_id.replace("_", " ").title()
