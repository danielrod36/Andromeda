"""Config endpoints: packs, rulesets, providers (M0.6, spec §5)."""

from __future__ import annotations

from fastapi import APIRouter

from src.llm.providers import PROVIDER_CONFIGS
from src.rulesets.cepheus import CepheusRuleSet
from src.themepacks import discover_packs

router = APIRouter(prefix="/v1/config")


@router.get("/packs")
async def list_packs() -> dict:
    """Every discovered pack with content stats + theme hints (spec §5)."""
    packs = []
    for pack in discover_packs().values():
        packs.append(
            {
                "id": pack.id,
                "name": pack.name,
                "description": pack.description,
                "career_count": len(pack.careers),
                "skill_count": len(pack.skills),
                "has_cascades": bool(pack.cascades),
                "has_draft": bool(pack.draft_table),
                "theme": pack.theme_tokens,
                "has_intro": bool(pack.intro_text),
            }
        )
    return {"packs": packs}


@router.get("/rulesets")
async def list_rulesets() -> dict:
    """The mechanical resolution systems (v1: Cepheus only)."""
    rs = CepheusRuleSet()
    return {
        "rulesets": [
            {
                "id": rs.id,
                "name": rs.name,
                "characteristics": list(rs.characteristics),
                "difficulty_ladder": rs.difficulty_ladder,
                "resolution_target": rs.resolution_target,
                "resolution_profiles": list(rs.resolution_profiles),
                "death_modes": list(rs.death_modes),
            }
        ]
    }


@router.get("/providers")
async def list_providers() -> dict:
    """LLM provider registry (no secrets — labels, presets, URL defaults)."""
    providers = [
        {
            "id": key,
            "label": cfg["label"],
            "presets": list(cfg.get("presets", [])),
            "default_base_url": cfg["default_base_url"],
            "needs_base_url": not cfg["default_base_url"],
        }
        for key, cfg in PROVIDER_CONFIGS.items()
    ]
    return {"providers": providers}
