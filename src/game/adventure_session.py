"""AdventureSession — the headless, versioned adventure contract (M0.3).

CONTRACT_VERSION 1 (2026-08-13):
  wrap / current_view / choose / submit_freetext / serialize / restore

Mirrors :class:`src.game.chargen.api.ChargenSession`: the client drives the
adventure loop through this surface without touching controllers, engines,
or GameState. Determinism: serialize+restore preserves the RNG streams
byte-for-byte, and the checkpoint snapshot rides the envelope so
checkpoint-mode rewind survives a session handoff. The LLM is never
re-invoked on restore.
"""

from __future__ import annotations

import dataclasses
import json

from pydantic import BaseModel

from src.engine.checkpoint import CheckpointManager
from src.engine.commands import Engine
from src.game.adventure import AdventureController, AdventureView
from src.themepacks import get_pack

CONTRACT_VERSION: int = 1
#: Alias for consumers that import both sessions and need to disambiguate.
ADVENTURE_CONTRACT_VERSION: int = CONTRACT_VERSION


class AdventureStepResult(BaseModel):
    """Result of a choose/submit_freetext call (M0.3).

    ``view`` is the :class:`AdventureView` serialized via
    :func:`dataclasses.asdict` — the wire shape is the view model's field
    names (phase, prompt, choices[{label, option_id, description, dimmed,
    requirement}], receipts, odds_lines, ...). Every response carries
    ``contract_version`` so a client can reject incompatible envelopes.
    """

    view: dict
    phase: str
    game_over: bool = False
    contract_version: int = CONTRACT_VERSION


class AdventureSession:
    """Headless adventure session (M0.3).

    Wraps ``Engine`` + ``AdventureController`` and exposes the versioned
    surface. The checkpoint manager is shared with the controller (and, in
    the server, with the owning GameSession) so scene-start snapshots
    persist through the same object everywhere.
    """

    def __init__(self, engine: Engine, controller: AdventureController) -> None:
        self._engine = engine
        self._controller = controller

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def wrap(
        cls,
        engine: Engine,
        *,
        checkpoint_mgr: CheckpointManager | None = None,
    ) -> AdventureSession:
        """Wrap an existing engine (chargen-complete or restored) (M0.3).

        The theme pack is read from ``state.campaign.theme_pack`` — the
        pack is baked into the save, so a session can never resume into a
        different world.
        """
        pack = get_pack(engine.state.campaign.theme_pack)
        controller = AdventureController(engine, pack, checkpoint_mgr=checkpoint_mgr)
        return cls(engine, controller)

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def engine(self) -> Engine:
        return self._engine

    @property
    def controller(self) -> AdventureController:
        return self._controller

    @property
    def checkpoint_mgr(self) -> CheckpointManager:
        return self._controller.checkpoint_mgr

    # ------------------------------------------------------------------
    # Read current state
    # ------------------------------------------------------------------

    def current_view(self) -> AdventureView:
        """Return the current adventure view.

        .. note::

            First call in a phase lazily generates the hook/scene via
            ``Engine.apply`` (oracle rolls) — treat this as a refresh, not
            a pure query (mirrors the controller's documented semantics).
        """
        return self._controller.get_view()

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def choose(self, option_id: str) -> AdventureStepResult:
        """Apply a player choice (M0.3).

        Raises ``ValueError`` if the option is not offered or is dimmed
        (rule-gated) in the current view — the contract-layer gate that
        makes B4 unreachable through any session consumer.
        """
        view = self.current_view()
        valid_ids = {c.option_id for c in view.choices if not c.dimmed}
        if option_id not in valid_ids:
            raise ValueError(
                f"Invalid option '{option_id}' for phase '{view.phase}'. Valid: {sorted(valid_ids)}"
            )
        new_view = self._controller.apply_choice(option_id)
        return self._step_result(new_view)

    def submit_freetext(self, text: str) -> AdventureStepResult:
        """Classify free-text input into a pending interpretation (M0.3).

        Only valid in ``scene_active`` (free text outside a scene has no
        scaffold to interpret against). Blocking — the classify surface is
        synchronous; the server runs this in a threadpool (KTD-9).
        """
        if not text or not text.strip():
            raise ValueError("free text must be non-empty")
        if self._controller.determine_phase() != "scene_active":
            raise ValueError(
                "free text is only available during an active scene "
                f"(phase is '{self._controller.determine_phase()}')"
            )
        view = self._controller.classify_freetext(text.strip())
        return self._step_result(view)

    # ------------------------------------------------------------------
    # Serialize / Restore
    # ------------------------------------------------------------------

    def serialize(self) -> str:
        """Serialize to a versioned JSON envelope (M0.3).

        Envelope shape::

            {
              "contract_version": 1,
              "save_version": 7,
              "state": <GameState.model_dump()>,
              "checkpoint": <GameState.model_dump()> | null,
            }
        """
        snap = self._controller.checkpoint_mgr.snapshot
        return json.dumps(
            {
                "contract_version": CONTRACT_VERSION,
                "save_version": self._engine.state.save_version,
                "state": self._engine.state.model_dump(),
                "checkpoint": snap.model_dump() if snap is not None else None,
            }
        )

    @classmethod
    def restore(cls, data: str) -> AdventureSession:
        """Restore from a serialized envelope (M0.3).

        Runs save migrations on both documents. Rejects future contract
        versions. Never re-invokes the LLM.
        """
        from src.engine.persistence import migrate
        from src.engine.state import GameState

        envelope = json.loads(data)
        cv = envelope.get("contract_version", 0)
        if cv > CONTRACT_VERSION:
            raise ValueError(
                f"Envelope contract_version {cv} is newer than "
                f"supported {CONTRACT_VERSION}. Upgrade the client."
            )

        state_data = envelope.get("state")
        if state_data is None:
            raise ValueError("Envelope missing required 'state' field.")
        state_data = migrate(state_data, from_version=state_data.get("save_version", 1))
        state = GameState.model_validate(state_data)

        mgr = CheckpointManager()
        snap_data = envelope.get("checkpoint")
        if snap_data is not None:
            snap_data = migrate(snap_data, from_version=snap_data.get("save_version", 1))
            # take_snapshot deep-copies and rehydrates the RNG streams —
            # exactly what restore needs.
            mgr.take_snapshot(GameState.model_validate(snap_data))

        return cls.wrap(Engine(state), checkpoint_mgr=mgr)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _step_result(view: AdventureView) -> AdventureStepResult:
        return AdventureStepResult(
            view=dataclasses.asdict(view),
            phase=view.phase,
            game_over=view.phase == "game_over",
        )
