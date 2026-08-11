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
  5. Option templates (options.yaml) reference real skill ids and the
     canonical Cepheus difficulty ladder.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError

from src.rulesets.base import (
    CareerData,
    CascadeData,
    ComplicationTable,
    MissionTable,
    OracleTable,
    SkillData,
    SkillTableEntry,
    TableRange,
)

# ---------------------------------------------------------------------------
# Errors.
# ---------------------------------------------------------------------------


class PackLoadError(Exception):
    """Raised when a theme pack fails load-time validation."""


# ---------------------------------------------------------------------------
# Option-template models (Task 17, R12/R13/AE10).
# ---------------------------------------------------------------------------


#: Canonical Cepheus difficulty names accepted on OptionTemplate.difficulty.
VALID_DIFFICULTIES: frozenset[str] = frozenset(
    {"easy", "routine", "average", "difficult", "very_difficult", "formidable"}
)


class OptionTemplate(BaseModel):
    """A structured-choice template mapping fiction to an engine-known check.

    Carried in pack data (``options.yaml``); the loader validates that
    ``skill`` references a real pack skill id and ``difficulty`` is one of the
    canonical Cepheus difficulty names. ``SceneEngine.generate_options`` turns
    these into :class:`SceneOption` instances at runtime.
    """

    label: str
    skill: str
    characteristic: str
    difficulty: str
    life_threatening: bool = False


class FreeTextTemplate(OptionTemplate):
    """A free-text keyword mapping for the deterministic classifier fallback.

    Identical to :class:`OptionTemplate` plus a ``keyword`` matched
    case-insensitively as a substring of the player's free-text input. The
    classifier iterates templates in descending keyword-length order so longer
    phrases win over their substrings.
    """

    keyword: str


class ComplicationMap(BaseModel):
    """Focus → table-id mapping for complication/consequence rolls (Task 18, R7).

    Each top-level key (``complication`` for weak hits, ``consequence`` for
    misses) maps a scene-focus keyword (case-insensitive substring match) to
    a table id in ``complication_tables``. A ``default`` entry is used when no
    focus keyword matches. The loader validates that every referenced table id
    exists in the pack.
    """

    complication: dict[str, str] = Field(default_factory=dict)
    consequence: dict[str, str] = Field(default_factory=dict)


class OptionTemplates(BaseModel):
    """Pack-level option data loaded from ``options.yaml`` (Task 17).

    - ``focus_options``: keyed by scene-focus keyword (case-insensitive
      substring match). When no key matches, the engine uses
      ``default_options``.
    - ``default_options``: always-applicable fallback options.
    - ``freetext_keywords``: keyword → check map for the free-text classifier.
    - ``complication_map``: focus → table id map for weak-hit complications
      and miss consequences (Task 18, R7). Each kind dict carries a
      ``default`` entry used when no focus keyword matches.
    """

    focus_options: dict[str, list[OptionTemplate]] = Field(default_factory=dict)
    default_options: list[OptionTemplate] = Field(default_factory=list)
    freetext_keywords: list[FreeTextTemplate] = Field(default_factory=list)
    complication_map: ComplicationMap | None = None


class MissionHookEntry(SkillTableEntry):
    """A row of a ``mission_arc`` die table carrying arc metadata (Task 19).

    Packs may ship a ``mission_arc`` table (one row per 2D6 band) whose
    entries declare how many scenes a mission of that band needs before
    it can be resolved, plus pack-supplied prose for each ending. All
    extra fields default so that existing packs (which omit them) degrade
    gracefully: ``min_scenes`` defaults to the Cepheus three-scene arc,
    and ending texts default to empty strings, letting the TUI narrator
    supply a generic line instead of the engine hardcoding one.
    """

    min_scenes: int = 3
    success_text: str = ""
    failure_text: str = ""
    abandonment_text: str = ""


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
        injury_table: TableRange | None = None,
        draft_table: list[str] | None = None,
        option_templates: OptionTemplates | None = None,
        cascades: dict[str, CascadeData] | None = None,
    ) -> None:
        self._id = pack_id
        self._name = name
        self._description = description
        self._careers = careers
        self._skills = skills
        self._oracle_tables = oracle_tables
        self._complication_tables = complication_tables
        self._mission_tables = mission_tables
        self._injury_table = injury_table
        self._draft_table: list[str] = list(draft_table) if draft_table else []
        self._option_templates = option_templates
        self._cascades: dict[str, CascadeData] = dict(cascades) if cascades else {}
        # Pre-compute background skill ids (B10): skills flagged background=true.
        self._background_skills = [sid for sid, s in skills.items() if s.background]

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
    def cascades(self) -> dict[str, CascadeData]:
        """Cascade skill groups (C3); empty when the pack ships no cascades.yaml."""
        return self._cascades

    @property
    def background_skills(self) -> list[str]:
        """Skill ids flagged ``background: true`` (B10 background-skills phase)."""
        return list(self._background_skills)

    @property
    def oracle_tables(self) -> dict[str, OracleTable]:
        return self._oracle_tables

    @property
    def complication_tables(self) -> dict[str, ComplicationTable]:
        return self._complication_tables

    @property
    def mission_tables(self) -> dict[str, MissionTable]:
        return self._mission_tables

    @property
    def injury_table(self) -> TableRange | None:
        return self._injury_table

    @property
    def draft_table(self) -> list[str]:
        """Career ids that compose the pack's draft table (B16).

        Returns a copy so callers can't mutate the loader's list. Empty when
        the pack defines no draft section (the draft fallback is hidden).
        Loader-validated: exactly 6 ids, all present in ``careers``.
        """
        return list(self._draft_table)

    @property
    def option_templates(self) -> OptionTemplates | None:
        """Structured-choice templates from ``options.yaml`` (Task 17).

        ``None`` when the pack ships no options.yaml; the scene engine then
        falls back to deterministic generic options and flags the degraded
        path via :class:`FlagDegradationCommand` (R13).
        """
        return self._option_templates

    @property
    def complication_map(self) -> ComplicationMap | None:
        """Focus → table-id map for complication/consequence rolls (Task 18, R7).

        Delegates to ``option_templates.complication_map``; ``None`` when the
        pack ships no options.yaml or no ``complication_map`` section. The
        scene engine falls back to a ``FlagDegradationCommand`` when ``None``.
        """
        if self._option_templates is None:
            return None
        return self._option_templates.complication_map


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
    oracle_tables = _parse_table_section(data.get("oracle_tables", {}), OracleTable, "oracle")

    # --- Parse complication tables ---
    complication_tables = _parse_table_section(
        data.get("complication_tables", {}), ComplicationTable, "complication"
    )

    # --- Parse mission tables ---
    mission_tables = _parse_table_section(data.get("mission_tables", {}), MissionTable, "mission")

    # --- Parse pack-level injury table (1D6, B13) ---
    raw_injury = data.get("injury_table") or manifest.get("injury_table")
    injury_table: TableRange | None = None
    if raw_injury is not None:
        injury_table = _parse_model(TableRange, raw_injury, "injury table")

    # --- Parse pack-level draft table (1D6, B16) ---
    raw_draft = data.get("draft_table") or manifest.get("draft_table")
    draft_table: list[str] = []
    if raw_draft is not None:
        if not isinstance(raw_draft, list) or not all(isinstance(x, str) for x in raw_draft):
            raise PackLoadError(
                "Pack draft_table must be a list of career id strings; "
                f"got {type(raw_draft).__name__}"
            )
        draft_table = list(raw_draft)

    # --- Parse pack-level option templates (Task 17, options.yaml) ---
    raw_options = data.get("option_templates")
    option_templates: OptionTemplates | None = None
    if raw_options is not None:
        if not isinstance(raw_options, dict):
            raise PackLoadError(
                f"Pack option_templates must be a mapping; got {type(raw_options).__name__}"
            )
        option_templates = _parse_model(OptionTemplates, raw_options, "option_templates")

    # --- Parse cascades (C3, cascades.yaml) ---
    cascades: dict[str, CascadeData] = {}
    raw_cascades = data.get("cascades")
    if raw_cascades is not None:
        if not isinstance(raw_cascades, dict):
            raise PackLoadError(
                f"Pack cascades must be a mapping; got {type(raw_cascades).__name__}"
            )
        for parent_id, entry in raw_cascades.items():
            cascade = _parse_model(CascadeData, entry, f"cascade {parent_id}")
            cascades[cascade.id] = cascade

    # --- Referential integrity checks ---
    _check_referential_integrity(
        careers,
        skills,
        oracle_tables,
        complication_tables,
        mission_tables,
        injury_table,
        draft_table,
        option_templates,
        cascades,
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
        injury_table=injury_table,
        draft_table=draft_table,
        option_templates=option_templates,
        cascades=cascades,
    )


def _parse_model(model_cls: type, raw: Any, context: str) -> Any:
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
    injury_table: TableRange | None = None,
    draft_table: list[str] | None = None,
    option_templates: OptionTemplates | None = None,
    cascades: dict[str, CascadeData] | None = None,
) -> None:
    """Run all referential-integrity checks across content sections."""
    career_ids = set(careers.keys())
    skill_ids = set(skills.keys())

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
                f"Referential integrity: oracle table '{tid}' has non-contiguous die ranges"
            )

    # 3. Complication tables must have contiguous ranges.
    for tid, table in complication_tables.items():
        if not table.entries.is_contiguous():
            raise PackLoadError(
                f"Referential integrity: complication table '{tid}' has non-contiguous die ranges"
            )

    # 4. Mission tables must have contiguous ranges.
    for tid, table in mission_tables.items():
        if not table.entries.is_contiguous():
            raise PackLoadError(
                f"Referential integrity: mission table '{tid}' has non-contiguous die ranges"
            )

    # 5. Career skill tables and benefit tables must have contiguous ranges.
    for cid, career in careers.items():
        for table in career.skill_tables:
            if not table.entries.is_contiguous():
                raise PackLoadError(
                    f"Referential integrity: career '{cid}' skill table "
                    f"'{table.name}' has non-contiguous die ranges"
                )
        if career.mustering_out_cash is not None and (
            not career.mustering_out_cash.entries.is_contiguous()
        ):
            raise PackLoadError(
                f"Referential integrity: career '{cid}' cash benefits "
                f"table has non-contiguous die ranges"
            )
        if career.mustering_out_material is not None and (
            not career.mustering_out_material.entries.is_contiguous()
        ):
            raise PackLoadError(
                f"Referential integrity: career '{cid}' material benefits "
                f"table has non-contiguous die ranges"
            )
        if career.mishap_table is not None and not career.mishap_table.is_contiguous():
            raise PackLoadError(
                f"Referential integrity: career '{cid}' mishap table has non-contiguous die ranges"
            )

    # 6. Pack-level injury table must have contiguous ranges when present.
    if injury_table is not None and not injury_table.is_contiguous():
        raise PackLoadError(
            "Referential integrity: pack injury table has non-contiguous die ranges"
        )

    # 7. Pack-level draft table (B16): when present, exactly 6 career ids,
    # all of which must reference existing careers. The CE SRD draft table
    # is 1D6 indexed, so 6 entries cover every roll outcome 1-6.
    if draft_table is not None and draft_table:
        if len(draft_table) != 6:
            raise PackLoadError(
                f"Referential integrity: pack draft_table must have exactly 6 "
                f"career ids (1D6); got {len(draft_table)}"
            )
        unknown = [cid for cid in draft_table if cid not in career_ids]
        if unknown:
            raise PackLoadError(
                f"Referential integrity: pack draft_table references unknown "
                f"career ids {unknown}; known careers: {sorted(career_ids)}"
            )

    # 8. Option templates (Task 17): every skill must reference a real pack
    # skill id, and every difficulty must be on the canonical Cepheus ladder.
    # Task 18: complication_map table references must also resolve.
    if option_templates is not None:
        _check_option_templates(
            option_templates,
            skill_ids,
            pack_context="pack",
            complication_table_ids=set(complication_tables.keys()),
        )

    # 9. Cascades (C3, C-A1): parent must not collide with a skill id, members
    # must exist, members must start with '{parent}_', and no member may
    # belong to two cascades.
    if cascades:
        member_owners: dict[str, str] = {}
        for parent_id, cascade in cascades.items():
            if parent_id in skill_ids:
                raise PackLoadError(
                    f"Referential integrity: cascade parent '{parent_id}' collides "
                    "with an existing skill id"
                )
            for member in cascade.specializations:
                if member not in skill_ids:
                    raise PackLoadError(
                        f"Referential integrity: cascade '{parent_id}' member "
                        f"'{member}' is not a known skill. "
                        f"Known: {sorted(skill_ids)}"
                    )
                if not member.startswith(f"{parent_id}_"):
                    raise PackLoadError(
                        f"Referential integrity: cascade member '{member}' violates "
                        f"the prefix rule (must start with '{parent_id}_')"
                    )
                if member in member_owners:
                    raise PackLoadError(
                        f"Referential integrity: skill '{member}' appears in two "
                        f"cascades ('{member_owners[member]}' and '{parent_id}')"
                    )
                member_owners[member] = parent_id


# ---------------------------------------------------------------------------
# Directory-scan loader.
# ---------------------------------------------------------------------------


def _check_option_templates(
    templates: OptionTemplates,
    skill_ids: set[str],
    pack_context: str = "pack",
    complication_table_ids: set[str] | None = None,
) -> None:
    """Validate option templates reference real skills and valid difficulties.

    Runs at pack-load time so a typo in ``options.yaml`` fails loudly rather
    than surfacing at runtime as an untrained skill check. Also validates
    ``complication_map`` references when present (Task 18, R7).
    """
    if not skill_ids:
        # No skills declared (test fixture): skip rather than reject every id.
        return

    def _check_one(template: OptionTemplate, where: str) -> None:
        if template.skill not in skill_ids:
            raise PackLoadError(
                f"Referential integrity: option template {where} references "
                f"skill {template.skill!r} which does not exist. "
                f"Known skills: {sorted(skill_ids)}"
            )
        if template.difficulty not in VALID_DIFFICULTIES:
            raise PackLoadError(
                f"Referential integrity: option template {where} has "
                f"difficulty {template.difficulty!r}; valid: "
                f"{sorted(VALID_DIFFICULTIES)}"
            )

    for focus, opts in templates.focus_options.items():
        for i, opt in enumerate(opts):
            _check_one(opt, f"focus_options[{focus!r}][{i}]")
    for i, opt in enumerate(templates.default_options):
        _check_one(opt, f"default_options[{i}]")
    for i, kw in enumerate(templates.freetext_keywords):
        _check_one(kw, f"freetext_keywords[{i}]")

    # Task 18: complication_map table references must resolve.
    if templates.complication_map is not None and complication_table_ids:
        for kind in ("complication", "consequence"):
            for focus, table_id in (getattr(templates.complication_map, kind, {}) or {}).items():
                if table_id not in complication_table_ids:
                    raise PackLoadError(
                        f"Referential integrity: complication_map.{kind}[{focus!r}] "
                        f"references table {table_id!r} which does not exist. "
                        f"Known complication tables: {sorted(complication_table_ids)}"
                    )


class ThemePackLoader:
    """Load a theme pack from a directory on disk.

    Reads the pack manifest (``pack.yaml``) and all content YAML files
    (``careers.yaml``, ``skills.yaml``, ``oracles.yaml``, ``complications.yaml``,
    ``missions.yaml``, ``options.yaml``), merges them into a single dict, and
    validates.
    """

    #: Filenames to load, in order.
    CONTENT_FILES = (
        "careers.yaml",
        "skills.yaml",
        "oracles.yaml",
        "complications.yaml",
        "missions.yaml",
        "options.yaml",
        "cascades.yaml",
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
                    "options": "option_templates",
                    "cascades": "cascades",
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
                raise PackLoadError(f"Failed to load pack from {entry}: {exc}") from exc

    if data_root is None:
        _pack_cache = dict(packs)

    return packs


def get_pack(pack_id: str) -> LoadedThemePack:
    """Return a loaded pack by id, loading if necessary."""
    packs = discover_packs()
    if pack_id not in packs:
        raise PackLoadError(f"Theme pack '{pack_id}' not found. Available: {sorted(packs.keys())}")
    return packs[pack_id]
