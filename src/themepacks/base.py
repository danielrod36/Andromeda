"""Theme-pack loader, validation, and directory-scan registry (R20).

Theme packs are pure data: YAML files validated into Pydantic models at load
time. This module provides:

- :class:`LoadedThemePack` — satisfies the :class:`ThemePack` Protocol by shape.
- :class:`ThemePackLoader` — reads a pack directory, parses YAML, runs
  referential-integrity checks.
- :func:`validate_pack` — validates an already-parsed pack dict (used by tests
  and by the loader).
- :func:`discover_packs` — scans ``src/themepacks/data/`` for pack directories.

Referential integrity checks:
  1. Every skill with a ``career`` field references an existing career id.
  2. Every oracle/complication/mission table has contiguous die ranges (2–12).
  3. Every career's skill table has contiguous die ranges.
  4. Required fields present on all models (enforced by Pydantic).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from src.rulesets.base import (
    BenefitsTable,
    CareerData,
    ComplicationTable,
    MissionTable,
    OracleTable,
    SkillData,
    SkillTable,
    TableRange,
)


# ---------------------------------------------------------------------------
# Errors.
# ---------------------------------------------------------------------------


class PackLoadError(Exception):
    """Raised when a theme pack fails load-time validation."""


# ---------------------------------------------------------------------------
# Loaded pack object (satisfies ThemePack Protocol by shape).
# ---------------------------------------------------------------------------


class LoadedThemePack:
    """A fully loaded and validated theme pack.

    Constructed by :class:`ThemePackLoader` after all YAML files are parsed and
    referential integrity passes. Exposes the ThemePack Protocol's properties.

    Not a Pydantic model — the contents are already-validated model instances.
    """

    def __init__(
        self,
        pack_id: str,
        name: str,
        description: str,
        careers: dict[str, CareerData],
        skills: dict[str, SkillData],
        oracle_tables: dict[str, OracleTable],
        complication_tables: dict[str, ComplicationTable],
        mission_tables: dict[str, MissionTable],
    ) -> None:
        self._id = pack_id
        self._name = name
        self._description = description
        self._careers = careers
        self._skills = skills
        self._oracle_tables = oracle_tables
        self._complication_tables = complication_tables
        self._mission_tables = mission_tables

    @property
    def id(self) -> str:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def careers(self) -> dict[str, CareerData]:
        return self._careers

    @property
    def skills(self) -> dict[str, SkillData]:
        return self._skills

    @property
    def oracle_tables(self) -> dict[str, OracleTable]:
        return self._oracle_tables

    @property
    def complication_tables(self) -> dict[str, ComplicationTable]:
        return self._complication_tables

    @property
    def mission_tables(self) -> dict[str, MissionTable]:
        return self._mission_tables


# ---------------------------------------------------------------------------
# Data directory location.
# ---------------------------------------------------------------------------

#: Root directory containing theme-pack subdirectories.
DATA_ROOT = Path(__file__).parent / "data"


# ---------------------------------------------------------------------------
# Raw-dict validation (used by loader and tests).
# ---------------------------------------------------------------------------


def validate_pack(data: dict[str, Any]) -> LoadedThemePack:
    """Validate a parsed pack dict and return a :class:`LoadedThemePack`.

    Runs Pydantic model validation on each content section, then performs
    referential-integrity checks across sections.

    Raises :class:`PackLoadError` on any validation failure.
    """
    # --- Manifest ---
    manifest = data.get("pack", {})
    pack_id = manifest.get("id", "")
    if not pack_id:
        raise PackLoadError("Pack manifest missing 'id'")
    pack_name = manifest.get("name", pack_id)
    pack_description = manifest.get("description", "")

    # --- Parse careers ---
    careers: dict[str, CareerData] = {}
    raw_careers = data.get("careers", {})
    if isinstance(raw_careers, list):
        # List format: [{id: ...}, ...]
        for entry in raw_careers:
            career = _parse_model(CareerData, entry, f"career {entry.get('id', '?')}")
            careers[career.id] = career
    elif isinstance(raw_careers, dict):
        # Dict format: {id: {...}, ...}
        for cid, entry in raw_careers.items():
            career = _parse_model(CareerData, entry, f"career {cid}")
            careers[career.id] = career

    # --- Parse skills ---
    skills: dict[str, SkillData] = {}
    raw_skills = data.get("skills", {})
    if isinstance(raw_skills, list):
        for entry in raw_skills:
            skill = _parse_model(SkillData, entry, f"skill {entry.get('id', '?')}")
            skills[skill.id] = skill
    elif isinstance(raw_skills, dict):
        for sid, entry in raw_skills.items():
            skill = _parse_model(SkillData, entry, f"skill {sid}")
            skills[skill.id] = skill

    # --- Parse oracle tables ---
    oracle_tables = _parse_table_section(
        data.get("oracle_tables", {}), OracleTable, "oracle"
    )

    # --- Parse complication tables ---
    complication_tables = _parse_table_section(
        data.get("complication_tables", {}), ComplicationTable, "complication"
    )

    # --- Parse mission tables ---
    mission_tables = _parse_table_section(
        data.get("mission_tables", {}), MissionTable, "mission"
    )

    # --- Referential integrity checks ---
    _check_referential_integrity(
        careers, skills, oracle_tables, complication_tables, mission_tables
    )

    return LoadedThemePack(
        pack_id=pack_id,
        name=pack_name,
        description=pack_description,
        careers=careers,
        skills=skills,
        oracle_tables=oracle_tables,
        complication_tables=complication_tables,
        mission_tables=mission_tables,
    )


def _parse_model(
    model_cls: type, raw: Any, context: str
) -> Any:
    """Parse a raw dict into a Pydantic model, wrapping errors in PackLoadError."""
    try:
        return model_cls.model_validate(raw)
    except ValidationError as exc:
        raise PackLoadError(f"Validation error in {context}: {exc}") from exc


def _parse_table_section(
    raw: dict[str, Any] | list[Any],
    model_cls: type,
    section_name: str,
) -> dict[str, Any]:
    """Parse a section of tables (oracle/complication/mission) into a dict."""
    tables: dict[str, Any] = {}
    if isinstance(raw, list):
        for entry in raw:
            table = _parse_model(model_cls, entry, f"{section_name} table {entry.get('id', '?')}")
            tables[table.id] = table
    elif isinstance(raw, dict):
        for tid, entry in raw.items():
            table = _parse_model(model_cls, entry, f"{section_name} table {tid}")
            tables[table.id] = table
    return tables


def _check_referential_integrity(
    careers: dict[str, CareerData],
    skills: dict[str, SkillData],
    oracle_tables: dict[str, OracleTable],
    complication_tables: dict[str, ComplicationTable],
    mission_tables: dict[str, MissionTable],
) -> None:
    """Run all referential-integrity checks across content sections."""
    career_ids = set(careers.keys())

    # 1. Skills → careers: every skill.career must reference an existing career.
    for skill_id, skill in skills.items():
        if skill.career and skill.career not in career_ids:
            raise PackLoadError(
                f"Referential integrity: skill '{skill_id}' references "
                f"career '{skill.career}' which does not exist. "
                f"Known careers: {sorted(career_ids)}"
            )

    # 2. Oracle tables must have contiguous ranges.
    for tid, table in oracle_tables.items():
        if not table.entries.is_contiguous():
            raise PackLoadError(
                f"Referential integrity: oracle table '{tid}' has "
                f"non-contiguous die ranges"
            )

    # 3. Complication tables must have contiguous ranges.
    for tid, table in complication_tables.items():
        if not table.entries.is_contiguous():
            raise PackLoadError(
                f"Referential integrity: complication table '{tid}' has "
                f"non-contiguous die ranges"
            )

    # 4. Mission tables must have contiguous ranges.
    for tid, table in mission_tables.items():
        if not table.entries.is_contiguous():
            raise PackLoadError(
                f"Referential integrity: mission table '{tid}' has "
                f"non-contiguous die ranges"
            )

    # 5. Career skill tables and benefit tables must have contiguous ranges.
    for cid, career in careers.items():
        for table in career.skill_tables:
            if not table.entries.is_contiguous():
                raise PackLoadError(
                    f"Referential integrity: career '{cid}' skill table "
                    f"'{table.name}' has non-contiguous die ranges"
                )
        if career.mustering_out_cash is not None:
            if not career.mustering_out_cash.entries.is_contiguous():
                raise PackLoadError(
                    f"Referential integrity: career '{cid}' cash benefits "
                    f"table has non-contiguous die ranges"
                )
        if career.mustering_out_material is not None:
            if not career.mustering_out_material.entries.is_contiguous():
                raise PackLoadError(
                    f"Referential integrity: career '{cid}' material benefits "
                    f"table has non-contiguous die ranges"
                )


# ---------------------------------------------------------------------------
# Directory-scan loader.
# ---------------------------------------------------------------------------


class ThemePackLoader:
    """Load a theme pack from a directory on disk.

    Reads the pack manifest (``pack.yaml``) and all content YAML files
    (``careers.yaml``, ``skills.yaml``, ``oracles.yaml``, ``complications.yaml``,
    ``missions.yaml``), merges them into a single dict, and validates.
    """

    #: Filenames to load, in order.
    CONTENT_FILES = (
        "careers.yaml",
        "skills.yaml",
        "oracles.yaml",
        "complications.yaml",
        "missions.yaml",
    )

    def __init__(self, pack_dir: str | Path) -> None:
        self.pack_dir = Path(pack_dir)

    def load(self) -> LoadedThemePack:
        """Load and validate the pack, returning a :class:`LoadedThemePack`."""
        if not self.pack_dir.is_dir():
            raise PackLoadError(f"Pack directory not found: {self.pack_dir}")

        manifest_path = self.pack_dir / "pack.yaml"
        if not manifest_path.exists():
            raise PackLoadError(f"No pack.yaml manifest in {self.pack_dir}")

        data: dict[str, Any] = {}

        # Load manifest.
        with manifest_path.open("r", encoding="utf-8") as f:
            manifest = yaml.safe_load(f) or {}
        data["pack"] = manifest

        # Load content files if they exist.
        for filename in self.CONTENT_FILES:
            path = self.pack_dir / filename
            if path.exists():
                section_name = filename.replace(".yaml", "")
                section_map = {
                    "careers": "careers",
                    "skills": "skills",
                    "oracles": "oracle_tables",
                    "complications": "complication_tables",
                    "missions": "mission_tables",
                }
                key = section_map.get(section_name, section_name)
                with path.open("r", encoding="utf-8") as f:
                    data[key] = yaml.safe_load(f) or {}

        return validate_pack(data)


# ---------------------------------------------------------------------------
# Directory-scan registry.
# ---------------------------------------------------------------------------

#: Cache of discovered packs (id → LoadedThemePack).
_pack_cache: dict[str, LoadedThemePack] | None = None


def discover_packs(data_root: Path | None = None) -> dict[str, LoadedThemePack]:
    """Discover and load all theme packs under ``data_root`` (default: DATA_ROOT).

    Scans for subdirectories containing ``pack.yaml``, loads each pack, and
    returns a dict keyed by pack id. Results are cached for the process.

    Entry-point-based discovery (importlib.metadata) is the post-v1 graduation
    step; this in-repo scan is the pre-v1 mechanism.
    """
    global _pack_cache
    if _pack_cache is not None and data_root is None:
        return dict(_pack_cache)

    root = data_root if data_root is not None else DATA_ROOT
    packs: dict[str, LoadedThemePack] = {}

    if root.is_dir():
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            manifest = entry / "pack.yaml"
            if not manifest.exists():
                continue
            try:
                pack = ThemePackLoader(entry).load()
                packs[pack.id] = pack
            except PackLoadError:
                raise
            except Exception as exc:
                raise PackLoadError(
                    f"Failed to load pack from {entry}: {exc}"
                ) from exc

    if data_root is None:
        _pack_cache = dict(packs)

    return packs


def get_pack(pack_id: str) -> LoadedThemePack:
    """Return a loaded pack by id, loading if necessary."""
    packs = discover_packs()
    if pack_id not in packs:
        raise PackLoadError(
            f"Theme pack '{pack_id}' not found. "
            f"Available: {sorted(packs.keys())}"
        )
    return packs[pack_id]
