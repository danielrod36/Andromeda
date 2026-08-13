"""Session registry — the sidecar's in-memory session table (M0.6).

One record per live session. The registry owns:

- **creation** (chargen from seed, adventure from save, resume by route
  inference via :func:`determine_resume_route`),
- **autosave** — ``{name}.autosave.json`` after every beat, main-then-sidecar
  order, via the record's :class:`GameSession` (stale-write detection intact),
- **manual save** — ``{name}.json`` + checkpoint sidecar, and
- **promotion** — chargen-complete → adventure over the same engine.

Sessions are process-local: the client reconnects by resuming from the
autosave (spec §3: the client holds zero game truth).
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from pathlib import Path

from src.engine.persistence import load
from src.game.adventure_session import AdventureSession
from src.game.chargen.api import ChargenSession
from src.game.saves import determine_resume_route, resolve_save_path
from src.game.session import GameSession
from src.llm.settings import LLMSettings
from src.server.errors import ApiError, SessionNotFoundError

#: Autosave filename suffix (spec §5): "{name}.autosave.json".
AUTOSAVE_SUFFIX = ".autosave"


@dataclass
class SessionRecord:
    """One live session."""

    id: str
    kind: str  # "chargen" | "adventure"
    name: str  # save base name (without .json)
    game: GameSession
    chargen: ChargenSession | None = None
    adventure: AdventureSession | None = None
    #: Event-log watermark for narration beats (M0.4/M0.5).
    last_narrated_seq: int = 0
    #: Start of the last narrated beat — re-tells re-narrate this span.
    last_beat_start: int = 0


class SessionRegistry:
    """Creates, tracks, and persists sessions."""

    def __init__(
        self,
        *,
        saves_dir: Path,
        settings: LLMSettings,
        adapter=None,
        advisor=None,
        translator=None,
    ) -> None:
        self._saves_dir = Path(saves_dir)
        self._settings = settings
        self.adapter = adapter
        self.advisor = advisor
        self.translator = translator
        self._records: dict[str, SessionRecord] = {}

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------

    def create_chargen(
        self,
        *,
        name: str,
        seed: int | None,
        pack_id: str,
        profile: str,
        death_mode: str,
    ) -> SessionRecord:
        """Start a new chronicle in chargen (M0.6)."""
        from src.engine.commands import Engine
        from src.engine.state import CampaignConfig, GameState
        from src.game.lifepath import LifepathController
        from src.themepacks import get_pack

        if seed is None:
            seed = secrets.randbelow(2**31)
        pack = get_pack(pack_id)  # PackLoadError → 422 invalid_config
        config = CampaignConfig(
            ruleset="cepheus",
            theme_pack=pack_id,
            resolution_profile=profile,
            death_mode=death_mode,
        )
        state = GameState.new(seed=seed, campaign=config)
        engine = Engine(state)
        game = GameSession(self._autosave_path(name), settings=self._settings, engine=engine)
        controller = LifepathController(engine, pack)
        chargen = ChargenSession(
            engine, controller, advisor=self.advisor, translator=self.translator
        )
        record = SessionRecord(
            id=uuid.uuid4().hex[:12],
            kind="chargen",
            name=name,
            game=game,
            chargen=chargen,
        )
        self._records[record.id] = record
        self.autosave(record)
        return record

    def create_adventure(self, *, name: str) -> SessionRecord:
        """Open an adventure session over an existing save (M0.6)."""
        path = self._autosave_path(name)
        if not path.exists():
            path = self._main_path(name)
        if not path.exists():
            raise ApiError(404, "save_not_found", f"No save named '{name}'")
        state = load(path)
        return self._open(name, state, kind="adventure")

    def resume(self, *, name: str) -> SessionRecord:
        """Resume a save, inferring the kind from where the story is (M0.6).

        Prefers the autosave when present (it's the newest write). Dead
        characters open as adventure sessions whose view is ``game_over`` —
        the client routes to the memorial screen.
        """
        path = self._autosave_path(name)
        if not path.exists():
            path = self._main_path(name)
        if not path.exists():
            raise ApiError(404, "save_not_found", f"No save named '{name}'")
        state = load(path)
        route = determine_resume_route(state)
        kind = "chargen" if route == "lifepath" else "adventure"
        return self._open(name, state, kind=kind)

    def _open(self, name: str, state, *, kind: str) -> SessionRecord:
        from src.engine.commands import Engine
        from src.game.lifepath import LifepathController
        from src.themepacks import get_pack

        engine = Engine(state)
        game = GameSession(self._autosave_path(name), settings=self._settings, engine=engine)
        record = SessionRecord(id=uuid.uuid4().hex[:12], kind=kind, name=name, game=game)
        if kind == "chargen":
            pack = get_pack(state.campaign.theme_pack)
            record.chargen = ChargenSession(
                engine,
                LifepathController(engine, pack),
                advisor=self.advisor,
                translator=self.translator,
            )
        else:
            record.adventure = AdventureSession.wrap(engine, checkpoint_mgr=game.checkpoint_mgr)
        self._records[record.id] = record
        return record

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    def get(self, session_id: str) -> SessionRecord:
        try:
            return self._records[session_id]
        except KeyError:
            raise SessionNotFoundError(f"No session '{session_id}'") from None

    def list(self) -> list[SessionRecord]:
        return list(self._records.values())

    def delete(self, session_id: str) -> None:
        self.get(session_id)  # raises when unknown
        del self._records[session_id]

    # ------------------------------------------------------------------
    # Promotion (chargen complete → adventure)
    # ------------------------------------------------------------------

    def promote(self, session_id: str) -> SessionRecord:
        """Promote a completed chargen session to adventure (M0.6)."""
        record = self.get(session_id)
        if record.kind != "chargen" or record.chargen is None:
            raise ApiError(422, "invalid_phase", "Only a chargen session can be promoted")
        if not record.chargen.completed:
            raise ApiError(
                422, "invalid_phase", "Chargen is not complete — finish mustering out first"
            )
        record.adventure = AdventureSession.wrap(
            record.game.engine, checkpoint_mgr=record.game.checkpoint_mgr
        )
        record.kind = "adventure"
        record.chargen = None
        self.autosave(record)
        return record

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def autosave(self, record: SessionRecord) -> None:
        """Write the autosave document (spec §5: after every beat)."""
        record.game.save()  # stale-write detection + sidecar cadence inside

    def save_manual(self, record: SessionRecord, name: str) -> None:
        """Write the named manual save, main-then-sidecar (spec §5).

        Retargets the session's autosave to the new base name so subsequent
        beats keep one live document per chronicle. Prior files are left in
        place (they are earlier save points; Chronicles lists them).
        """
        from src.engine.persistence import save

        main = self._main_path(name)
        save(record.game.state, main)
        if record.game.state.campaign.death_mode == "checkpoint":
            record.game.checkpoint_mgr.save_snapshot(main)
        record.game.retarget(self._autosave_path(name))
        record.name = name

    def _main_path(self, name: str) -> Path:
        return resolve_save_path(self._saves_dir, name)

    def _autosave_path(self, name: str) -> Path:
        base = resolve_save_path(self._saves_dir, name)
        return base.with_name(base.stem + AUTOSAVE_SUFFIX + base.suffix)
