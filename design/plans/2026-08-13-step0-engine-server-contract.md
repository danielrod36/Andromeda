# Step 0 — Engine + Server Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: implemented** — merged as PR #41 (merge commit `fe7705d`, 2026-08-13); CI green on `main`. Convention: plan checkboxes record the execution-time checklist and are not retro-ticked after merge — the merged code and its tests are the source of truth.

**Goal:** Close the engine's two pre-client items (B4, G6), give the adventure loop a versioned session contract, add beat narration + story steering, move the LLM key into the OS keychain, and ship the FastAPI sidecar the Godot client will talk to — fully testable with pytest + curl, zero Godot code.

**Architecture:** All work stays inside the existing funnel architecture: every mutation is a `Command` through `Engine.apply`, every roll rides a named RNG stream, the LLM only narrates. The server is a new `src/server/` package (FastAPI, NDJSON streaming) wrapping `ChargenSession` (existing) and `AdventureSession` (new, Task 3), owning autosave and key storage server-side. Spec: `design/2026-08-13-game-client-design.md` §4 (M0.1–M0.7) and §5 (API surface).

**Tech Stack:** Python ≥3.12, pydantic 2, FastAPI + uvicorn (added Task 7), keyring (added Task 6), pytest + pytest-asyncio, ruff.

## Global Constraints

Every task implicitly includes these. They are not optional.

- **Engine invariants (CLAUDE.md):** all mutations through `Engine.apply`; all randomness through a `Roller` on a named stream (`oracle`/`lifepath`/`combat`); `src/engine/` has zero game/LLM imports; `GameState` stays JSON-serializable; the LLM only narrates.
- **Commands run with `uv`:** `uv run pytest tests/ -q`, `uv run ruff check src tests`, `uv run ruff format src tests`. Never pip/venv directly.
- **Dependencies:** add with `uv add <pkg>` (grabs latest stable, re-locks `uv.lock`). Never hand-copy version pins from this plan into `pyproject.toml`.
- **Contract versions:** chargen `CONTRACT_VERSION = 1` (existing, unchanged); adventure `CONTRACT_VERSION = 1` (new, Task 3). Every session API response carries `contract_version`.
- **Error envelope (spec §5):** `{"error": {"code": "<snake_case>", "message": "<engine message verbatim>"}}`; 4xx/422 only. Client renders `message` verbatim in toasts.
- **Narration stream (spec §3):** NDJSON, media type `application/x-ndjson`, one JSON `{"type", "content"}` per line. Block types: `narration | receipt | change | badge | done | error` (existing `src/game/narration.py` `BlockType`).
- **Sidecar lifecycle (spec §3):** bind 127.0.0.1 only; `LISTENING <port>` is the only stdout line the client reads; self-exit after 300 s without a request.
- **Autosave (spec §5):** server writes `{name}.autosave.json` after every beat; checkpoint sidecar `{file}.checkpoint.json` cadence preserved; main-then-sidecar write order; stale-write detection (`GameSession.save`) intact.
- **Key storage (spec D7):** OS keychain via `keyring` (service name `andromeda`); owner-only file (0600) fallback; the settings file on disk never contains the key; the client only ever sees a masked tail (`…last4`).
- **Voice rule (spec §6.6):** player-facing strings come from `src/llm/status.py` canonical constants or engine messages verbatim — no invented copy.
- **Tests:** mirror existing layout (`tests/engine/`, `tests/game/`, `tests/llm/`, new `tests/server/`); every test dir has an `__init__.py`. New code lands with its tests in the same commit.
- **Quality gate per commit:** `uv run ruff check src tests && uv run ruff format src tests && uv run pytest tests/ -q` all green before committing.

## Executor Rules (read first — they prevent failure modes)

1. **Do exactly what the steps say.** Every code block is complete and intended to be applied verbatim. Do not paraphrase, "improve", or add unrequested handling.
2. **Only touch the files a task lists.** If you believe another file needs a change, stop and report instead.
3. **Never skip the failing-test step.** If the test PASSES when the plan says it should FAIL, the implementation already exists or you're in the wrong state — stop and report; do not proceed.
4. **If a command fails differently than the plan's stated expectation, stop and report the exact output.** Do not improvise fixes.
5. **Apply imports exactly as shown.** Where a step says "replace import line X with Y", do that verbatim.
6. **Commit with the exact message given**, after the full gate passes.
7. Run everything from the repo root (`/home/daniel/Andromeda`) with `uv run ...`.

## File Structure

**Created:**

| File | Responsibility |
|------|----------------|
| `src/game/adventure_session.py` | `AdventureSession` — versioned adventure contract (Task 3) |
| `src/game/beats.py` | `build_beat_facts` (events → LLM-safe facts), `NarratorMemory`, `narrator_memory` (Tasks 4–5) |
| `src/llm/keystore.py` | `KeyStore` protocol, `KeyringStore`, `FileKeyStore`, `get_keystore` (Task 6) |
| `src/server/__init__.py` | package docstring + exports |
| `src/server/__main__.py` | `python -m src.server` entry: bind, `LISTENING` handshake, uvicorn, idle watchdog (Task 7) |
| `src/server/app.py` | `create_app` factory, middleware, exception handlers (Task 7) |
| `src/server/errors.py` | `ApiError` + envelope builders (Task 7) |
| `src/server/models.py` | wire DTOs (request/response pydantic models) (Task 7) |
| `src/server/sessions.py` | `SessionRegistry` + `SessionRecord` — session lifecycle, autosave, promote (Task 7) |
| `src/server/routes_meta.py` | `/health`, `/v1/llm/status` (Task 7) |
| `src/server/routes_config.py` | `/v1/config/packs|rulesets|providers` (Task 7) |
| `src/server/routes_sessions.py` | session CRUD + `choose`/`freetext`/`suggest`/`narrate`/`promote`/`name` (Task 8) |
| `src/server/routes_saves.py` | `/v1/saves` CRUD + export/import + manual save (Task 9) |
| `src/server/routes_settings.py` | `/v1/settings/llm` GET/PUT/test (Task 9) |
| `src/server/routes_inspect.py` | `sheet`/`recap`/`memorial`/`audit`/`llm-context`/`odds`/`hash`/`verify` (Task 10) |

**Modified:**

| File | Change |
|------|--------|
| `src/game/adventure.py` | B4 pre-gate at top of `_do_push_for_ending` (Task 1) |
| `src/engine/scene.py` | `NpcReactionRollCommand`, `CreateNpcRecordCommand`; pass `pack=` at the ratify call site (Task 2) |
| `src/engine/retrieval.py` | `ratify_fact_as_npc` gains `pack=`; rolls reaction, creates `NpcRecord` (Task 2) |
| `src/themepacks/base.py` | `NPC_REACTION_DISPOSITIONS` + `npc_reaction_disposition` (Task 2); `LoadedThemePack.theme_tokens`/`intro_text` + manifest parsing (Task 4) |
| `src/engine/checkpoint.py` | public `snapshot` property (Task 3) |
| `src/game/chargen/api.py` | `phase` + `completed` properties on `ChargenSession` (Task 7) |
| `src/game/session.py` | `GameSession.retarget` — autosave follows a manual save's new name (Task 9) |
| `src/llm/prompts.py` | `build_beat_prompt`, `build_world_intro_prompt` (Task 4); memory sections (Task 5) |
| `src/llm/adapter.py` | `narrate_beat`, `narrate_world_intro` (Task 4); memory params (Task 5) |
| `src/engine/commands.py` | `RecordNarrationCommand`, `RecordStoryDirectionCommand` (Task 5) |
| `src/llm/settings.py` | key never persisted; `key_backend` field; resolve/store/delete/mask helpers (Task 6) |
| `src/themepacks/data/scifi/pack.yaml`, `.../fantasy/pack.yaml` | `intro:` + `theme:` blocks (Task 4) |
| `pyproject.toml` (via `uv add`) | `keyring` (Task 6), `fastapi`, `uvicorn` (Task 7) |

---

## Task 1: M0.1 — B4 pre-gate in `_do_push_for_ending`

**The bug:** `AdventureController._do_push_for_ending` (`src/game/adventure.py:425`) resolves a scene check (consuming a combat-stream roll and appending events) before `ResolveMissionCommand.validate` raises `Mission needs 3 scenes before resolution`. An early push must leave state, RNG, and the event log untouched.

**Files:**
- Modify: `src/game/adventure.py:425-431` (gate inserted at the top of `_do_push_for_ending`)
- Test: `tests/game/test_adventure_flow.py` (append a test class at end of file)

**Interfaces:**
- Consumes: `AdventureController.apply_choice("push_for_ending")`; `Mission.scenes_completed`, `Mission.min_scenes` (ints on the in-memory `Mission`).
- Produces: gated early-return contract — early push returns the current view with an explanatory `prompt`, consuming zero rolls and appending zero events. `AdventureSession.choose` (Task 3) relies on this being unreachable-by-construction (it rejects the dimmed option first); the controller gate is the belt.

- [ ] **Step 1: Write the failing test**

Append to `tests/game/test_adventure_flow.py`:

```python
class TestEarlyPushGate:
    """B4: pushing for the ending before min_scenes must not roll or log (M0.1)."""

    def test_early_push_consumes_no_rolls_and_appends_no_events(self):
        # Exactly enough rolls for: 4 hook tables + 2 scene oracle tables.
        # Any further roll attempt raises IndexError (queue exhausted) —
        # so a clean return proves the gate fired before any roll.
        queue = [
            [3, 4], [5, 5], [3, 3], [4, 4],  # mission hook tables
            [5, 5], [4, 4],  # first scene oracle tables
        ]
        engine = _make_engine(queue)
        controller = AdventureController(engine, load_scifi_pack())
        controller.get_view()  # generates + persists the hook
        controller.apply_choice("accept_mission")  # generates the scene; queue now empty
        events_before = len(engine.state.events)

        view = controller.apply_choice("push_for_ending")

        assert len(engine.state.events) == events_before
        assert engine.state.active_mission is not None  # mission NOT resolved
        assert "scene" in view.prompt.lower()

    def test_early_push_prompt_names_remaining_scenes(self):
        queue = [
            [3, 4], [5, 5], [3, 3], [4, 4],
            [5, 5], [4, 4],
        ]
        engine = _make_engine(queue)
        controller = AdventureController(engine, load_scifi_pack())
        controller.get_view()
        controller.apply_choice("accept_mission")

        view = controller.apply_choice("push_for_ending")

        mission = engine.state.active_mission
        remaining = int(mission["min_scenes"]) - int(mission["scenes_completed"])
        assert str(remaining) in view.prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/game/test_adventure_flow.py::TestEarlyPushGate -q`
Expected: FAIL — `IndexError: ForcedRoller queue exhausted` (the current code rolls a scene check before the mission gate rejects).

- [ ] **Step 3: Implement the gate**

In `src/game/adventure.py`, replace the head of `_do_push_for_ending` (currently lines 425-431):

```python
    def _do_push_for_ending(self) -> AdventureView:
        if self._current_mission is None:
            # Defensive: push_for_ending should only be offered with an active
            # mission. Return the current view rather than crashing.
            logger.warning("push_for_ending called with no active mission")
            return self.get_view()
        self._ensure_current_scene()
```

with:

```python
    def _do_push_for_ending(self) -> AdventureView:
        if self._current_mission is None:
            # Defensive: push_for_ending should only be offered with an active
            # mission. Return the current view rather than crashing.
            logger.warning("push_for_ending called with no active mission")
            return self.get_view()
        # B4 (M0.1): gate BEFORE any roll or scene generation. An early push
        # must leave state, RNG streams, and the event log untouched — the
        # old order consumed a scene_check roll and appended events before
        # ResolveMissionCommand.validate rejected the resolution.
        mission = self._current_mission
        if mission.scenes_completed < mission.min_scenes:
            remaining = mission.min_scenes - mission.scenes_completed
            logger.warning(
                "push_for_ending rejected: %d scene(s) short of %d",
                remaining,
                mission.min_scenes,
            )
            view = self.get_view()
            view.prompt = (
                f"The mission needs {remaining} more scene"
                f"{'s' if remaining != 1 else ''} before you can push for the ending."
            )
            return view
        self._ensure_current_scene()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/game/test_adventure_flow.py -q`
Expected: PASS (whole file — including the pre-existing `test_push_for_ending_unlocks_after_min_scenes`, which exercises the ungated path with a populated queue).

- [ ] **Step 5: Full gate + commit**

```bash
uv run ruff check src tests && uv run ruff format src tests && uv run pytest tests/ -q
git add src/game/adventure.py tests/game/test_adventure_flow.py
git commit -m "fix(engine): gate push_for_ending before any roll (B4/M0.1)"
```

---

## Task 2: M0.2 — G6: ratification produces a real `NpcRecord` with a rolled disposition

**The gap:** `NpcRecord` exists in `src/engine/state.py:141` and `build_curated_view_for_scene` already surfaces its disposition to the LLM — but nothing ever creates one. `ratify_fact_as_npc` only annotates the `NarrativeFact` description. After this task, every ratification also rolls the pack's `npc_reaction` oracle table (both shipped packs have one, 2D6: 2 Hostile … 12 Devoted) and appends an `NpcRecord` with the mapped disposition (−2…+2).

**Files:**
- Modify: `src/themepacks/base.py` (keyword map + helper, after the LEGACY maps ~line 72)
- Modify: `src/engine/scene.py` (two new commands after `RatifyFactCommand`, ~line 339; pass `pack=` at the ratify call site, ~line 715)
- Modify: `src/engine/retrieval.py:212-243` (`ratify_fact_as_npc` gains `pack=`, rolls reaction, creates the record)
- Test: `tests/engine/test_retrieval.py` (append)

**Interfaces:**
- Consumes: `LoadedThemePack.oracle_tables` (dict — `"npc_reaction"` key), `lookup_table_result(entries, roll)` from `src/engine/lifepath.py:92`, `RatifyFactCommand` from `src/engine/scene.py:292`.
- Produces:
  - `src.themepacks.base.npc_reaction_disposition(result_text: str) -> int`
  - `src.engine.scene.NpcReactionRollCommand()` — Command, `command_type = "npc_reaction_roll"`, rolls 2D6 on `oracle`; event `changes = {"table_id": "npc_reaction", "roll_total": int}`.
  - `src.engine.scene.CreateNpcRecordCommand(name: str, disposition: int = 0, description: str = "")` — Command, `command_type = "create_npc_record"`; idempotent by name.
  - `ratify_fact_as_npc(fact, engine, ruleset=None, pack=None) -> dict` — new optional `pack`; return value (stats dict) unchanged.

- [ ] **Step 1: Write the failing tests**

First, update the imports in `tests/engine/test_retrieval.py`. Replace line 20 exactly:

```python
from src.engine.scene import RatifyFactCommand, RegisterFactCommand
```

with:

```python
from src.engine.scene import CreateNpcRecordCommand, RatifyFactCommand, RegisterFactCommand
```

Replace line 21 exactly:

```python
from src.engine.state import CampaignConfig, GameState, NarrativeFact
```

with:

```python
from src.engine.state import CampaignConfig, GameState, NarrativeFact, NpcRecord
```

Replace line 23 exactly:

```python
from src.themepacks.base import get_pack
```

with:

```python
from src.engine.audit import EventKind
from src.themepacks.base import get_pack, npc_reaction_disposition
```

(ruff's isort will normalize ordering on `ruff format` — don't hand-sort.)

Then append to `tests/engine/test_retrieval.py` (the existing `pack` fixture at line 30-32 provides the scifi pack; `make_state()` at line 35 provides a fresh state):

```python
class TestNpcRecordProduction:
    """G6 (M0.2): ratification creates a canonical NpcRecord with a rolled disposition."""

    def test_ratify_creates_npc_record_with_rolled_disposition(self, pack):
        state = make_state()
        state.entities.append(NarrativeFact(name="Ila Renn", description="dockmaster"))
        engine = Engine(state, roller=ForcedRoller([[6, 6]]))  # reaction 12 → Devoted

        ratify_fact_as_npc(state.entities[0], engine=engine, pack=pack)

        npcs = [e for e in state.entities if isinstance(e, NpcRecord)]
        assert len(npcs) == 1
        assert npcs[0].name == "Ila Renn"
        assert npcs[0].disposition == 2  # Devoted → allied
        rolls = [
            e
            for e in state.events
            if e.kind == EventKind.ROLL and e.command_type == "npc_reaction_roll"
        ]
        assert len(rolls) == 1
        assert rolls[0].roll.stream == "oracle"

    def test_ratify_without_pack_defaults_neutral_and_rolls_nothing(self):
        state = make_state()
        state.entities.append(NarrativeFact(name="Ila Renn", description="dockmaster"))
        engine = Engine(state, roller=ForcedRoller([]))  # any roll would raise

        ratify_fact_as_npc(state.entities[0], engine=engine)  # no pack → no roll

        npcs = [e for e in state.entities if isinstance(e, NpcRecord)]
        assert len(npcs) == 1
        assert npcs[0].disposition == 0

    def test_create_npc_record_is_idempotent_by_name(self):
        state = make_state()
        engine = Engine(state, roller=ForcedRoller([]))
        engine.apply(CreateNpcRecordCommand(name="Ila Renn", disposition=1))
        engine.apply(CreateNpcRecordCommand(name="Ila Renn", disposition=-2))

        npcs = [e for e in state.entities if isinstance(e, NpcRecord)]
        assert len(npcs) == 1
        assert npcs[0].disposition == 1  # first write wins


class TestNpcReactionDisposition:
    """The keyword map (content layer) maps reaction text to [-2, +2]."""

    def test_keyword_mapping(self):
        assert npc_reaction_disposition("Hostile — immediate attack.") == -2
        assert npc_reaction_disposition("Unfriendly — cold, suspicious.") == -1
        assert npc_reaction_disposition("Wary — cautious and guarded.") == 0
        assert npc_reaction_disposition("Neutral — transactional.") == 0
        assert npc_reaction_disposition("Friendly — warm and cooperative.") == 1
        assert npc_reaction_disposition("Helpful — eager to assist.") == 2
        assert npc_reaction_disposition("Devoted — a loyal ally.") == 2

    def test_unfriendly_beats_friendly_substring(self):
        # "Unfriendly" contains "friendly" — ordering must check it first.
        assert npc_reaction_disposition("Unfriendly") == -1

    def test_unknown_text_defaults_neutral(self):
        assert npc_reaction_disposition("Something entirely alien") == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_retrieval.py -q`
Expected: FAIL — `ImportError`/`TypeError: ratify_fact_as_npc() got an unexpected keyword argument 'pack'`.

- [ ] **Step 3a: Keyword map in the content layer**

In `src/themepacks/base.py`, after `DEFAULT_CURRENCY_UNITS` (~line 72), add:

```python
#: Keyword → mechanical disposition for ``npc_reaction`` table result text (G6).
#: Content-name knowledge lives in the content layer (C-A12 precedent, same as
#: LEGACY_TABLE_ROLES). Ordered: ``unfriendly`` must precede ``friendly``
#: (substring containment).
NPC_REACTION_DISPOSITIONS: tuple[tuple[str, int], ...] = (
    ("hostile", -2),
    ("unfriendly", -1),
    ("wary", 0),
    ("neutral", 0),
    ("friendly", 1),
    ("helpful", 2),
    ("devoted", 2),
)


def npc_reaction_disposition(result_text: str) -> int:
    """Map an ``npc_reaction`` table result string to a disposition in [-2, +2].

    Unknown text defaults to 0 (neutral) so a pack that rewords its reaction
    table degrades to neutral instead of raising.
    """
    text = result_text.lower()
    for keyword, value in NPC_REACTION_DISPOSITIONS:
        if keyword in text:
            return value
    return 0
```

- [ ] **Step 3b: The two commands**

In `src/engine/scene.py`, immediately after `RatifyFactCommand` (ends ~line 339), add:

```python
class NpcReactionRollCommand(Command):
    """Roll 2D6 on the oracle stream for a ratified NPC's reaction (G6).

    Mirrors :class:`src.engine.mission.MissionTableRollCommand`: the roll
    advances the oracle stream and is recorded for audit; the caller looks
    up the pack's ``npc_reaction`` table with the returned total.
    """

    command_type: ClassVar[str] = "npc_reaction_roll"

    def resolve(self, state: GameState, roller: Roller) -> RollResult:
        return roller.roll("oracle", ndice=2, sides=6)

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        assert roll is not None
        return Event(
            kind=EventKind.ROLL,
            command_type=self.command_type,
            description=f"NPC reaction roll (npc_reaction): {roll.total}",
            roll=roll,
            changes={"table_id": "npc_reaction", "roll_total": roll.total},
        )


class CreateNpcRecordCommand(Command):
    """Create the canonical :class:`NpcRecord` for a ratified fact (G6).

    Idempotent by name: a second application for the same NPC records a
    no-op event instead of duplicating the entity (the first write wins).
    """

    command_type: ClassVar[str] = "create_npc_record"

    name: str
    disposition: int = 0  # -2 hostile .. +2 allied
    description: str = ""

    def validate(self, state: GameState) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("NPC name must be non-empty")
        if not -2 <= self.disposition <= 2:
            raise ValueError(f"disposition must be in [-2, +2], got {self.disposition}")

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        existing = next(
            (e for e in state.entities if isinstance(e, NpcRecord) and e.name == self.name),
            None,
        )
        if existing is not None:
            return Event(
                kind=EventKind.STATE_CHANGE,
                command_type=self.command_type,
                description=f"NPC record already exists: {self.name}",
                changes={"name": self.name, "already_existed": True},
            )
        state.entities.append(
            NpcRecord(
                name=self.name.strip(),
                disposition=self.disposition,
                description=self.description,
            )
        )
        return Event(
            kind=EventKind.STATE_CHANGE,
            command_type=self.command_type,
            description=f"NPC record created: {self.name} (disposition {self.disposition:+d})",
            changes={
                "name": self.name.strip(),
                "disposition": self.disposition,
                "description": self.description,
            },
        )
```

`NpcRecord` must be imported in scene.py — extend the existing state import at line 26: `from src.engine.state import GameState, Injury, NarrativeFact, NpcRecord`.

- [ ] **Step 3c: Wire the roll + record into ratification**

In `src/engine/retrieval.py`, replace `ratify_fact_as_npc` (lines 212-243) with:

```python
def ratify_fact_as_npc(
    fact: NarrativeFact,
    engine: Engine,
    ruleset=None,
    pack=None,
) -> dict:
    """Ratify a narrative fact as an NPC with mechanical stats (AE9) and a
    canonical :class:`NpcRecord` with a rolled disposition (G6).

    The fact remains in the entity list; this function returns the generated
    stats and marks the fact as mechanically active by updating its
    description via the command funnel. The engine uses the returned stats
    when checks target this NPC.

    G6: when ``pack`` ships an ``npc_reaction`` oracle table (both shipped
    packs do), the NPC's disposition is rolled on it — 2D6 on the oracle
    stream through the funnel — and a canonical :class:`NpcRecord` is
    appended to ``state.entities`` via :class:`CreateNpcRecordCommand`.
    Without a pack/table the record is created with disposition 0 and no
    roll is consumed (determinism parity with pre-G6 saves).

    The description update is always routed through the command funnel via
    :class:`RatifyFactCommand`, producing an audit event and **logging the
    ratification** (R24/AE9). The ``engine`` parameter is required — there
    is no direct-mutation path.

    Note: stat generation is math-neutral for now. Stats are recorded and
    logged per AE9; opposed-check math using these stats is post-v1.
    """
    from src.engine.lifepath import lookup_table_result
    from src.engine.scene import CreateNpcRecordCommand, NpcReactionRollCommand
    from src.themepacks.base import npc_reaction_disposition

    stats = generate_npc_stats(fact.name, ruleset)
    stats_description = (
        f"[NPC stats: all characteristics {stats['characteristics'].get('STR', 7)}, "
        f"skill level {stats['skill_level']}]"
    )
    engine.apply(
        RatifyFactCommand(
            fact_name=fact.name,
            stats_description=stats_description,
        )
    )

    # G6: roll the reaction table when the pack ships one, then create the
    # canonical record. The NpcRecord is what build_curated_view_for_scene
    # surfaces to the LLM (disposition label) and what the client's NPC
    # chips render.
    disposition = 0
    description = fact.description
    if pack is not None and "npc_reaction" in pack.oracle_tables:
        event = engine.apply(NpcReactionRollCommand())
        table = pack.oracle_tables["npc_reaction"]
        entry = lookup_table_result(table.entries.entries, event.changes["roll_total"])
        disposition = npc_reaction_disposition(entry.result)
        description = entry.result
    engine.apply(
        CreateNpcRecordCommand(
            name=fact.name,
            disposition=disposition,
            description=description,
        )
    )
    return stats
```

- [ ] **Step 3d: Pass the pack at the call site**

In `src/engine/scene.py` `SceneEngine.resolve_scene` (~line 715), change:

```python
            ratify_fact_as_npc(fact, engine=self.engine)
```

to:

```python
            ratify_fact_as_npc(fact, engine=self.engine, pack=self.pack)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/engine/test_retrieval.py tests/engine/test_scene.py -q`
Expected: PASS — including existing ratify tests (they call without `pack=` → the neutral no-roll path, unchanged behavior).

- [ ] **Step 5: Full gate + commit**

```bash
uv run ruff check src tests && uv run ruff format src tests && uv run pytest tests/ -q
git add src/engine/scene.py src/engine/retrieval.py src/themepacks/base.py tests/engine/test_retrieval.py
git commit -m "feat(engine): ratification creates NpcRecord with rolled disposition (G6/M0.2)"
```

---

## Task 3: M0.3 — `AdventureSession` versioned contract

The adventure loop has no session contract (chargen has `ChargenSession`). This task adds the mirror: `create/current_view/choose/submit_freetext/serialize/restore` with `CONTRACT_VERSION = 1`, the checkpoint snapshot riding the serialize envelope so checkpoint-mode rewind survives a session handoff.

**Files:**
- Create: `src/game/adventure_session.py`
- Modify: `src/engine/checkpoint.py` (add public `snapshot` property after `has_snapshot`, ~line 50)
- Test: `tests/game/test_adventure_session.py` (new)

**Interfaces:**
- Consumes: `AdventureController` (`src/game/adventure.py:80`), `Engine`, `CheckpointManager`, `get_pack` (`src/themepacks`), `migrate` (`src/engine/persistence.py:115`).
- Produces:
  - `ADVENTURE_CONTRACT_VERSION: int = 1` (module constant; also re-exported as `CONTRACT_VERSION` for symmetry with chargen)
  - `AdventureStepResult(BaseModel)`: `view: dict`, `phase: str`, `game_over: bool = False`, `contract_version: int = CONTRACT_VERSION`
  - `AdventureSession.wrap(engine: Engine, *, checkpoint_mgr: CheckpointManager | None = None) -> AdventureSession`
  - `AdventureSession.current_view() -> AdventureView` (dataclass, has lazy side effects — see controller note)
  - `AdventureSession.choose(option_id: str) -> AdventureStepResult` — raises `ValueError` on invalid or dimmed option
  - `AdventureSession.submit_freetext(text: str) -> AdventureStepResult` — raises `ValueError` outside `scene_active`; blocking (KTD-9)
  - `AdventureSession.serialize() -> str` / `AdventureSession.restore(data: str) -> AdventureSession`
  - `CheckpointManager.snapshot -> GameState | None` (read-only property)
- The server (Task 7+) imports `AdventureSession`, `AdventureStepResult`, `CONTRACT_VERSION` from `src.game.adventure_session`.

- [ ] **Step 1: Write the failing tests**

Create `tests/game/test_adventure_session.py`:

```python
"""Contract tests for AdventureSession (M0.3).

Mirrors tests/game/test_chargen_session.py's shape: create → view → choose →
serialize → restore, with determinism and validation guarantees locked in.
"""

from __future__ import annotations

import pytest

from src.engine.commands import Engine
from src.engine.dice import ForcedRoller
from src.engine.state import CampaignConfig, GameState
from src.game.adventure_session import CONTRACT_VERSION, AdventureSession
from src.themepacks.cepheus_scifi import load_scifi_pack

# 4 mission hook tables + 2 scene oracle tables + generous scene checks.
_QUEUE = [
    [3, 4], [5, 5], [3, 3], [4, 4],  # hook
    [5, 5], [4, 4],  # scene oracle
    [6, 6],  # scene check 1
    [5, 5], [4, 4],  # scene oracle 2
    [5, 5],  # scene check 2
    [5, 5], [4, 4],  # scene oracle 3
    [5, 5],  # scene check 3
]


def _make_session(queue: list | None = None, death_mode: str = "narrative") -> AdventureSession:
    state = GameState.new(seed=42)
    state.campaign = CampaignConfig(
        resolution_profile="narrative",
        death_mode=death_mode,
        theme_pack="scifi",
    )
    state.character.name = "TestHero"
    state.character.characteristics = {
        "STR": 7, "DEX": 9, "END": 6, "INT": 8, "EDU": 10, "SOC": 5,
    }
    state.character.skills = {"Gun Combat": 1, "Persuade": 0, "Stealth": 2}
    state.character.career = "navy"
    state.character.terms = 2
    state.narrative_log.append("mustered_out=true")
    engine = Engine(state, roller=ForcedRoller(queue or list(_QUEUE)))
    return AdventureSession.wrap(engine)


class TestViewAndChoice:
    def test_initial_view_is_hook_offered(self):
        session = _make_session()
        result_view = session.current_view()
        assert result_view.phase == "hook_offered"

    def test_choose_accepts_mission(self):
        session = _make_session()
        session.current_view()  # generate the hook
        result = session.choose("accept_mission")
        assert result.phase == "scene_active"
        assert result.contract_version == CONTRACT_VERSION
        assert result.view["choices"]  # serialized choices present

    def test_choose_rejects_unknown_option(self):
        session = _make_session()
        session.current_view()
        with pytest.raises(ValueError, match="Invalid option"):
            session.choose("not_a_real_option")

    def test_choose_rejects_dimmed_option(self):
        """push_for_ending is dimmed before min_scenes — not choosable (B4 at the contract layer)."""
        session = _make_session()
        session.current_view()
        session.choose("accept_mission")
        with pytest.raises(ValueError, match="Invalid option"):
            session.choose("push_for_ending")

    def test_submit_freetext_rejected_outside_scene(self):
        session = _make_session()
        session.current_view()  # hook phase
        with pytest.raises(ValueError, match="scene_active"):
            session.submit_freetext("I look around")

    def test_submit_freetext_rejects_empty(self):
        session = _make_session()
        with pytest.raises(ValueError, match="non-empty"):
            session.submit_freetext("   ")


class TestSerializeRestore:
    def test_round_trip_preserves_state_byte_for_byte(self):
        session = _make_session()
        session.current_view()
        session.choose("accept_mission")
        before = session.engine.state.model_dump_json()

        restored = AdventureSession.restore(session.serialize())

        assert restored.engine.state.model_dump_json() == before
        assert restored.current_view().phase == "scene_active"

    def test_restore_rejects_newer_contract_version(self):
        session = _make_session()
        envelope = session.serialize().replace(
            f'"contract_version": {CONTRACT_VERSION}',
            f'"contract_version": {CONTRACT_VERSION + 1}',
            1,
        )
        with pytest.raises(ValueError, match="contract_version"):
            AdventureSession.restore(envelope)

    def test_checkpoint_snapshot_rides_the_envelope(self):
        session = _make_session(death_mode="checkpoint")
        session.current_view()
        session.choose("accept_mission")  # scene start takes the snapshot
        assert session.checkpoint_mgr.has_snapshot

        restored = AdventureSession.restore(session.serialize())

        assert restored.checkpoint_mgr.has_snapshot

    def test_restore_without_checkpoint_has_none(self):
        session = _make_session(death_mode="narrative")
        session.current_view()
        restored = AdventureSession.restore(session.serialize())
        assert not restored.checkpoint_mgr.has_snapshot
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/game/test_adventure_session.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.game.adventure_session'`.

- [ ] **Step 3a: Public snapshot accessor**

In `src/engine/checkpoint.py`, after the `has_snapshot` property (~line 50), add:

```python
    @property
    def snapshot(self) -> GameState | None:
        """The current scene-start snapshot, or None (M0.3 serialize support).

        Read-only: callers never mutate the returned state. Session
        envelopes embed ``snapshot.model_dump()`` so checkpoint-mode rewind
        survives a serialize/restore handoff.
        """
        return self._snapshot
```

- [ ] **Step 3b: The session**

Create `src/game/adventure_session.py`:

```python
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
                f"Invalid option '{option_id}' for phase '{view.phase}'. "
                f"Valid: {sorted(valid_ids)}"
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/game/test_adventure_session.py -q`
Expected: PASS (all 10 tests).

Note on `test_choose_accepts_mission`: after accepting, the controller builds the scene view, whose choices are `option:0..N`, `push_for_ending` (dimmed), `abandon_mission` — `result.phase` is `scene_active`. If a test errors with `IndexError: ForcedRoller queue exhausted`, extend `_QUEUE` with another `[5, 5], [4, 4], [x, y]` triple (complication-table rolls on weak hits vary with forced outcomes).

- [ ] **Step 5: Full gate + commit**

```bash
uv run ruff check src tests && uv run ruff format src tests && uv run pytest tests/ -q
git add src/game/adventure_session.py src/engine/checkpoint.py tests/game/test_adventure_session.py
git commit -m "feat(game): AdventureSession versioned contract (M0.3)"
```

---

## Task 4: M0.4 — Beat facts, narration prompt builders, adapter surfaces, pack `intro:`/`theme:`

The client narrates **beats** (what just happened, per action) and a **world intro** (ceremony). This task adds: the engine-owned facts builder, the prompt builders, two adapter surfaces (scene agent, template fallback, mechanical-claim validation), and the pack manifest fields they draw from.

**Files:**
- Create: `src/game/beats.py`
- Modify: `src/llm/prompts.py` (append builders)
- Modify: `src/llm/adapter.py` (append methods after `narrate_scene_steered`/`_narrate_scene`, ~line 816; import the new builders)
- Modify: `src/themepacks/base.py` (`LoadedThemePack` gains `theme`/`intro`; `validate_pack` parses them)
- Modify: `src/themepacks/data/scifi/pack.yaml`, `src/themepacks/data/fantasy/pack.yaml` (add `intro:` + `theme:`)
- Test: `tests/game/test_beats.py` (new), `tests/llm/test_beat_narration.py` (new), `tests/themepacks/test_pack_load_v2.py` (append one test)

**Interfaces:**
- Consumes: `Event.changes` shapes (per command `mutate` methods), `CuratedView` (`src/llm/state_view.py:67`), `SummaryValidator.validate(text, state) -> ValidationResult(.valid, .error_summary)` (`src/engine/summary.py:84`), `NarrationResult` (`src/llm/adapter.py:168`).
- Produces:
  - `src.game.beats.build_beat_facts(events: list[Event]) -> list[str]`
  - `src.llm.prompts.build_beat_prompt(view: CuratedView, facts: list[str], *, steering_text: str = "", prior_prose: list[str] | None = None, directions: list[str] | None = None) -> str` (memory params are Task 5; include them now, unused-until-Task-5 is fine)
  - `src.llm.prompts.build_world_intro_prompt(view: CuratedView, *, pack_name: str, pack_intro: str) -> str`
  - `LLMAdapter.narrate_beat(view, facts, *, state, steering_text="", prior_prose=(), directions=(), on_attempt=None) -> NarrationResult`
  - `LLMAdapter.narrate_world_intro(view, *, pack_name, pack_intro, state, on_attempt=None) -> NarrationResult`
  - `LoadedThemePack.theme_tokens -> dict`, `LoadedThemePack.intro_text -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/game/test_beats.py`:

```python
"""Tests for build_beat_facts (M0.4) — events to LLM-safe mechanical facts."""

from __future__ import annotations

from src.engine.commands import Engine
from src.engine.dice import ForcedRoller
from src.engine.state import CampaignConfig, GameState
from src.game.adventure import AdventureController
from src.game.beats import build_beat_facts
from src.themepacks.cepheus_scifi import load_scifi_pack


def _play_one_scene() -> tuple[Engine, int]:
    """Accept a mission and resolve one option; return (engine, action_start)."""
    queue = [
        [3, 4], [5, 5], [3, 3], [4, 4],  # hook tables
        [5, 5], [4, 4],  # scene oracle
        [6, 6],  # scene check (12 raw → strong hit at most DMs)
        [3, 3],  # possible npc_reaction/complication follow-ups
    ]
    state = GameState.new(seed=42)
    state.campaign = CampaignConfig(
        resolution_profile="narrative", death_mode="narrative", theme_pack="scifi"
    )
    state.character.name = "TestHero"
    state.character.characteristics = {"STR": 7, "DEX": 9, "END": 6, "INT": 8, "EDU": 10, "SOC": 5}
    state.character.skills = {"Gun Combat": 1, "Persuade": 0}
    state.character.career = "navy"
    state.character.terms = 2
    state.narrative_log.append("mustered_out=true")
    engine = Engine(state, roller=ForcedRoller(queue))
    controller = AdventureController(engine, load_scifi_pack())
    controller.get_view()
    controller.apply_choice("accept_mission")
    action_start = len(engine.state.events)
    controller.apply_choice("option:0")
    return engine, action_start


def test_beat_facts_describe_the_check_without_pips():
    engine, start = _play_one_scene()
    facts = build_beat_facts(engine.state.events[start:])
    assert any("check" in f for f in facts)
    joined = " ".join(facts)
    # No raw pip lists or RNG vocabulary leak into narration facts.
    assert "[" not in joined
    assert "2D6" not in joined


def test_beat_facts_cover_mission_resolution():
    engine, _ = _play_one_scene()
    # Two more scenes (oracle+check each), the pre-push scene generation
    # (oracle), then the push's own check. Exactly 9 forced rolls.
    engine.roller.extend(
        [
            [5, 5], [4, 4], [6, 6],  # scene 2: oracle, oracle, check
            [5, 5], [4, 4], [6, 6],  # scene 3: oracle, oracle, check
            [6, 6], [3, 3],  # scene 4 oracle rolls (from the pre-push get_view)
            [6, 6],  # the push's scene check → strong hit → success
        ]
    )
    controller = AdventureController(engine, load_scifi_pack())
    controller.get_view()
    controller.apply_choice("option:0")
    controller.get_view()
    controller.apply_choice("option:0")
    controller.get_view()
    before = len(engine.state.events)
    controller.apply_choice("push_for_ending")
    facts = build_beat_facts(engine.state.events[before:])
    assert any("mission" in f.lower() and ("success" in f or "ended" in f) for f in facts)


def test_empty_slice_gives_empty_facts():
    assert build_beat_facts([]) == []
```

Create `tests/llm/test_beat_narration.py`:

```python
"""Tests for narrate_beat / narrate_world_intro (M0.4)."""

from __future__ import annotations

from pydantic_ai.models.test import TestModel

from src.engine.state import GameState
from src.llm.adapter import AdapterConfig, LLMAdapter
from src.llm.state_view import build_curated_view


def _view(state: GameState):
    return build_curated_view(state)


class TestNarrateBeat:
    async def test_llm_beat_returns_prose(self):
        state = GameState.new(seed=1)
        adapter = LLMAdapter(AdapterConfig(), test_model=TestModel())
        result = await adapter.narrate_beat(
            _view(state), ["The persuade check succeeded brilliantly (margin +3)."], state=state
        )
        assert result.source == "llm"
        assert result.prose.strip()

    async def test_template_beat_joins_facts(self):
        state = GameState.new(seed=1)
        adapter = LLMAdapter()  # no model → template
        result = await adapter.narrate_beat(
            _view(state), ["Fact one.", "Fact two."], state=state
        )
        assert result.source == "template"
        assert "Fact one." in result.prose and "Fact two." in result.prose

    async def test_steering_text_acknowledged_in_template(self):
        state = GameState.new(seed=1)
        adapter = LLMAdapter()
        result = await adapter.narrate_beat(
            _view(state), ["A thing happened."], state=state, steering_text="make it noir"
        )
        assert "make it noir" in result.prose

    async def test_mechanical_leak_falls_back_to_template(self):
        """Prose that leaks dice notation fails the mechanical-claim guard."""
        state = GameState.new(seed=1)
        # custom_output_args forces the structured output verbatim (pydantic-ai 2.x TestModel).
        adapter = LLMAdapter(
            AdapterConfig(),
            test_model=TestModel(
                custom_output_args={"prose": "You rolled 2D6 and got 11 vs 8."}
            ),
        )
        result = await adapter.narrate_beat(_view(state), ["A check happened."], state=state)
        assert result.source == "template"
        assert result.llm_failed
        assert result.prose == "A check happened."  # the template floor ships


class TestNarrateWorldIntro:
    async def test_template_returns_pack_intro(self):
        state = GameState.new(seed=1)
        adapter = LLMAdapter()
        result = await adapter.narrate_world_intro(
            _view(state), pack_name="Frontier Sci-Fi", pack_intro="The frontier calls.", state=state
        )
        assert result.source == "template"
        assert result.prose == "The frontier calls."

    async def test_template_without_pack_intro_uses_generic_line(self):
        state = GameState.new(seed=1)
        adapter = LLMAdapter()
        result = await adapter.narrate_world_intro(
            _view(state), pack_name="Frontier Sci-Fi", pack_intro="", state=state
        )
        assert result.source == "template"
        assert "Frontier Sci-Fi" in result.prose

    async def test_llm_world_intro(self):
        state = GameState.new(seed=1)
        adapter = LLMAdapter(AdapterConfig(), test_model=TestModel())
        result = await adapter.narrate_world_intro(
            _view(state), pack_name="Frontier Sci-Fi", pack_intro="x", state=state
        )
        assert result.source == "llm"
        assert result.prose.strip()
```

Append to `tests/themepacks/test_pack_load_v2.py` (uses the file's own `_minimal_pack_dict()` helper at line 45; `validate_pack` is already imported at line 42):

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/game/test_beats.py tests/llm/test_beat_narration.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.game.beats'`; `AttributeError: narrate_beat`.

- [ ] **Step 3a: `src/game/beats.py`**

```python
"""Beat facts — the engine-owned "what just happened" for narration (M0.4).

After each action, the events it produced are translated into human-readable
mechanical facts. Facts name OUTCOMES (check tiers, injuries, mission
endings) and never expose pips, RNG, or audit internals — the narrator
weaves them into prose but cannot contradict them (the trust boundary made
textual).
"""

from __future__ import annotations

from src.engine.audit import Event

#: Command types that never produce narration facts: flags, pending-state
#: markers, narration/advice records (they are prose/meta, not mechanics).
_SKIP_COMMANDS: frozenset[str] = frozenset(
    {
        "set_flag",
        "set_pending_freetext",
        "set_pending_hook",
        "log_narration",
        "log_mission",
        "record_advice",
        "record_proposal",
        "record_narration",
        "record_story_direction",
        "flag_degradation",
        "next_mission_id",
        "oracle_roll",
        "mission_table_roll",
    }
)

_TIER_PHRASES: dict[str, str] = {
    "strong_hit": "succeeded brilliantly",
    "weak_hit": "succeeded, but with a complication",
    "miss": "failed",
}


def build_beat_facts(events: list[Event]) -> list[str]:
    """Translate an event slice into LLM-safe mechanical facts (M0.4).

    One fact per meaningful event, in order. Empty slice → empty list.
    """
    facts: list[str] = []
    for event in events:
        ct = event.command_type
        c = event.changes
        if ct in _SKIP_COMMANDS:
            continue
        if ct == "scene_check":
            tier = _TIER_PHRASES.get(c.get("quality", ""), c.get("quality", "resolved"))
            facts.append(f"The {c.get('skill', 'unknown')} check {tier} (margin {c.get('effect', 0):+d}).")
        elif ct == "complication_roll":
            facts.append(f"The situation shifted: {c.get('result_text', '')}")
        elif ct == "npc_reaction_roll":
            continue  # the disposition lands on the NPC record; no prose fact
        elif ct == "create_npc_record":
            if not c.get("already_existed"):
                facts.append(f"{c.get('name', 'Someone')} stepped out of the background — the story can now test them.")
        elif ct == "add_injury":
            facts.append(f"You suffered {c.get('name', 'an injury')} ({c.get('severity', 'moderate')}).")
        elif ct == "register_fact":
            facts.append(f"New element in the story: {c.get('name', '')}.")
        elif ct == "ratify_fact":
            continue  # paired with create_npc_record; one fact is enough
        elif ct == "resolve_mission":
            facts.append(f"The mission ended in {c.get('ending', 'unknown')}.")
        elif ct == "set_mission_state":
            mission = c.get("mission_data") or {}
            hook = mission.get("hook") or {}
            if hook.get("objective"):
                facts.append(
                    f"You took the job: {hook.get('objective')} "
                    f"(patron: {hook.get('patron', 'unknown')}; reward: {hook.get('reward', 'unknown')})."
                )
        elif ct == "set_character_dead":
            reason = c.get("reason") or "your injuries"
            facts.append(f"You died — {reason}.")
        elif ct == "add_open_thread":
            facts.append(f"A new thread opened: {c.get('thread', '')}.")
        elif ct == "remove_open_thread":
            facts.append(f"A thread closed: {c.get('thread', '')}.")
        # Unknown command types produce no fact — beats stay honest about
        # what the engine actually did rather than guessing.
    return facts
```

- [ ] **Step 3b: Prompt builders**

Append to `src/llm/prompts.py`:

```python
# ---------------------------------------------------------------------------
# Beat narration + world intro prompts (M0.4, M0.5).
# ---------------------------------------------------------------------------


def build_beat_prompt(
    view: CuratedView,
    facts: list[str],
    *,
    steering_text: str = "",
    prior_prose: list[str] | None = None,
    directions: list[str] | None = None,
) -> str:
    """Build the user-turn prompt for beat narration (M0.4).

    ``facts`` are the engine-owned outcomes of the beat (locked). Memory
    (M0.5) carries continuity: recent shipped prose (do not repeat) and
    standing player story directions. ``steering_text`` is the player's
    one-off direction for THIS re-telling.
    """
    view_json = json.dumps(view.model_dump(), indent=2)
    facts_block = "\n".join(f"  - {f}" for f in facts) or "  - (a quiet moment — no mechanical events)"

    memory_block = ""
    if prior_prose:
        prose_lines = "\n".join(f'  - "{p}"' for p in prior_prose)
        memory_block += (
            f"\n## Recent Narration (continuity — stay consistent, do not repeat verbatim)\n"
            f"{prose_lines}\n"
        )
    if directions:
        direction_lines = "\n".join(f'  - "{d}"' for d in directions)
        memory_block += f"\n## Standing Player Story Directions\n{direction_lines}\n"

    prompt = (
        f"## Character State\n{view_json}\n"
        f"{memory_block}\n"
        f"## What Just Happened (mechanical facts — locked)\n{facts_block}\n\n"
        f"Write engaging second-person narration (2-4 sentences) for this beat. "
        f"Faithfully reflect every fact above. Do not mention dice or game mechanics."
    )
    if steering_text:
        prompt += (
            f"\n\n## Player Steering Direction\n\"{steering_text}\"\n\n"
            f"Incorporate the player's direction for tone, focus, or style. "
            f"The facts are locked — only the prose changes."
        )
    return prompt


def build_world_intro_prompt(
    view: CuratedView,
    *,
    pack_name: str,
    pack_intro: str,
) -> str:
    """Build the user-turn prompt for the ceremony world introduction (M0.4).

    The pack's own ``intro:`` text is the canonical floor — the LLM expands
    it into the opening passage, it never replaces its facts.
    """
    view_json = json.dumps(view.model_dump(), indent=2)
    intro_block = pack_intro or (
        "(the pack ships no introduction — establish the world from its name "
        "and the character sheet)"
    )
    return (
        f"## The World\nTheme pack: {pack_name}\n"
        f"Pack introduction (canonical):\n{intro_block}\n\n"
        f"## Character State\n{view_json}\n\n"
        f"Write the opening passage of the story: 3-5 sentences of second-person "
        f"prose introducing the world and the character's place in it. Epic but "
        f"grounded. Do not mention dice or game mechanics."
    )
```

- [ ] **Step 3c: Adapter surfaces**

In `src/llm/adapter.py`, extend the prompts import (line 43-53) with `build_beat_prompt` and `build_world_intro_prompt`, then append after `_narrate_scene` (~line 816):

```python
    # ------------------------------------------------------------------
    # Beat narration + world intro (M0.4, M0.5).
    # ------------------------------------------------------------------

    async def narrate_beat(
        self,
        view: CuratedView,
        facts: list[str],
        *,
        state: GameState,
        steering_text: str = "",
        prior_prose: tuple[str, ...] | list[str] = (),
        directions: tuple[str, ...] | list[str] = (),
        on_attempt: AttemptCallback | None = None,
    ) -> NarrationResult:
        """Narrate one beat from engine-owned facts (M0.4).

        The facts are locked outcomes; only prose varies. ``state`` is
        required so the mechanical-claim guard
        (:class:`src.engine.summary.SummaryValidator`) can validate the
        prose before it ships — a leak falls back to template narration.
        Never raises.
        """
        if not self.llm_configured:
            return NarrationResult(
                prose=self._template_beat(facts, steering_text=steering_text),
                source="template",
            )
        prompt = build_beat_prompt(
            view,
            facts,
            steering_text=steering_text,
            prior_prose=list(prior_prose),
            directions=list(directions),
        )
        return await self._run_beat_agent(
            prompt,
            state,
            template=lambda: self._template_beat(facts, steering_text=steering_text),
            on_attempt=on_attempt,
        )

    async def narrate_world_intro(
        self,
        view: CuratedView,
        *,
        pack_name: str,
        pack_intro: str,
        state: GameState,
        on_attempt: AttemptCallback | None = None,
    ) -> NarrationResult:
        """Narrate the ceremony world introduction (M0.4).

        Template fallback is the pack's own ``intro:`` text (or a generic
        line), so the ceremony always has canonical prose. Never raises.
        """
        template = pack_intro.strip() or f"The world of {pack_name} awaits."
        if not self.llm_configured:
            return NarrationResult(prose=template, source="template")
        prompt = build_world_intro_prompt(view, pack_name=pack_name, pack_intro=pack_intro)
        return await self._run_beat_agent(
            prompt,
            state,
            template=lambda: template,
            on_attempt=on_attempt,
        )

    async def _run_beat_agent(
        self,
        prompt: str,
        state: GameState,
        *,
        template,
        on_attempt: AttemptCallback | None = None,
    ) -> NarrationResult:
        """Shared core for beat/world-intro narration (M0.4).

        Runs the read-only scene agent, validates the prose with the
        mechanical-claim guard, and falls back to ``template()`` on LLM
        failure or validation rejection. Never raises.
        """
        from src.engine.summary import SummaryValidator

        deps = ToolDeps(engine=None, state=None)
        try:
            result = await self._run_agent(
                self._scene_agent, prompt, deps=deps, on_attempt=on_attempt
            )
            prose = result.output.prose
            check = SummaryValidator().validate(prose, state)
            if not check.valid:
                logger.warning(
                    "Beat narration failed mechanical-claim validation; shipping template: %s",
                    check.error_summary,
                )
                return NarrationResult(
                    prose=template(),
                    source="template",
                    llm_failed=True,
                    failure_kind="validation_rejected",
                )
            return NarrationResult(prose=prose, source="llm")
        except Exception as exc:
            failure_kind = self._classify_failure(exc)
            logger.warning(
                "LLM beat narration failed (%s), falling back to template: %s",
                failure_kind,
                exc,
            )
            return NarrationResult(
                prose=template(),
                source="template",
                llm_failed=True,
                failure_kind=failure_kind,
            )

    @staticmethod
    def _template_beat(facts: list[str], *, steering_text: str = "") -> str:
        """Template (fallback) beat narration: the facts themselves, in order."""
        lines = [f for f in facts if f and f.strip()]
        if steering_text:
            lines.append(f"(Direction: {steering_text})")
        return " ".join(lines) or "The story continues."
```

- [ ] **Step 3d: Pack manifest fields**

In `src/themepacks/base.py`:

1. `LoadedThemePack.__init__` — add two keyword params at the end of the signature: `theme: dict | None = None, intro: str = "",` and two lines in the body:

```python
        self._theme: dict = dict(theme) if theme else {}
        self._intro: str = intro or ""
```

2. Add properties after `complication_map` (~line 325):

```python
    @property
    def theme_tokens(self) -> dict:
        """Pack-supplied UI theme hints from ``pack.yaml:theme`` (M0.4).

        A free-form dict (motif glyph, accent name, ambience list). Empty
        when the pack ships no ``theme:`` block — the client's built-in
        token sets are the default.
        """
        return dict(self._theme)

    @property
    def intro_text(self) -> str:
        """Pack-supplied world introduction from ``pack.yaml:intro`` (M0.4).

        The canonical floor for the ceremony world intro; empty when the
        pack ships none (the template fallback then uses a generic line).
        """
        return self._intro
```

3. In `validate_pack`, after the currency-units block (~line 371), add:

```python
    # --- Pack-declared UI theme hints + world intro (M0.4) ---
    raw_theme = manifest.get("theme")
    if raw_theme is not None and not isinstance(raw_theme, dict):
        raise PackLoadError(
            f"Pack theme must be a mapping; got {type(raw_theme).__name__}"
        )
    raw_intro = manifest.get("intro", "")
    if not isinstance(raw_intro, str):
        raise PackLoadError(
            f"Pack intro must be a string; got {type(raw_intro).__name__}"
        )
```

4. In `validate_pack`'s `LoadedThemePack(...)` call (~line 462), add `theme=raw_theme, intro=raw_intro,` to the kwargs.

- [ ] **Step 3e: Ship `intro:` + `theme:` in both packs**

Both `pack.yaml` files use top-level manifest keys (`id`, `name`, `description`, `injury_table`, ...) — the loader treats the whole file as the manifest. Append the following at the END of each file, at column 0 (top level, no indentation).

Append to `src/themepacks/data/scifi/pack.yaml`:

```yaml
intro: >-
  The frontier stretches out past the last chartered routes — a scatter of
  jump lanes, free ports, and debts that outlive their debtors. Ships are
  expensive, fuel is honest, and a traveler's word is the only collateral
  that compounds. You have a name, a history, and a ticket off-world.

theme:
  motif: "✦"
  accent: amber
  ambience: [meteors, birds]
```

Append to `src/themepacks/data/fantasy/pack.yaml`:

```yaml
intro: >-
  The old roads still remember the names of kings, though the kings are
  gone. Between the walled towns the wild keeps its own ledger — of ruins,
  omens, and bargains struck at crossroads. You carry what you own, and a
  reputation that walks a day ahead of you.

theme:
  motif: "❧"
  accent: gold
  ambience: [fireflies, leaves]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/game/test_beats.py tests/llm/test_beat_narration.py tests/themepacks/ -q`
Expected: PASS (all). The forced-output test relies on pydantic-ai 2.x `TestModel(custom_output_args=...)`, verified against the installed pydantic-ai 2.20.0 — no subclassing needed.

- [ ] **Step 5: Full gate + commit**

```bash
uv run ruff check src tests && uv run ruff format src tests && uv run pytest tests/ -q
git add src/game/beats.py src/llm/prompts.py src/llm/adapter.py src/themepacks/base.py src/themepacks/data/scifi/pack.yaml src/themepacks/data/fantasy/pack.yaml tests/game/test_beats.py tests/llm/test_beat_narration.py tests/themepacks/test_pack_load_v2.py
git commit -m "feat(llm): beat narration + world intro + pack intro/theme (M0.4)"
```

---

## Task 5: M0.5 — `RecordNarrationCommand`, `RecordStoryDirectionCommand`, narrator memory

Steering rule (spec §2 D6): "The past is written. The present can be re-told. The future is steered." Shipped prose is funneled into canonical state (replay never re-calls the LLM); player directions are canonical events that condition future narration.

**Files:**
- Modify: `src/engine/commands.py` (append two commands after `RecordProposalCommand`, end of file)
- Modify: `src/game/beats.py` (add `NarratorMemory` + `narrator_memory`)
- Test: `tests/engine/test_commands.py` (append), `tests/game/test_beats.py` (append)

**Interfaces:**
- Consumes: `Command`/`Engine` (`src/engine/commands.py`), `Event`/`EventKind`.
- Produces:
  - `RecordNarrationCommand(text: str, beat: str = "", source: str = "llm")` — `command_type = "record_narration"`; appends prose to `state.narrative_log`; event kind `SYSTEM`; `changes = {"text", "beat", "source"}`.
  - `RecordStoryDirectionCommand(text: str, beat: str = "")` — `command_type = "record_story_direction"`; appends `story_direction=<text>` to `narrative_log`; event kind `SYSTEM`; `changes = {"text", "beat"}`.
  - `src.game.beats.NarratorMemory` dataclass: `prose: list[str]`, `directions: list[str]`.
  - `src.game.beats.narrator_memory(events: list[Event], *, prose_limit: int = 6, direction_limit: int = 3) -> NarratorMemory`
- The server (Task 8) applies these commands around every `/narrate` call and feeds `narrator_memory` into `narrate_beat`.

- [ ] **Step 1: Write the failing tests**

In `tests/engine/test_commands.py`, replace the existing commands import block (lines 12-18) exactly:

```python
from src.engine.commands import (
    Engine,
    RecordAdviceCommand,
    RecordProposalCommand,
    RollCharacteristicCommand,
    SetFlagCommand,
)
```

with:

```python
from src.engine.commands import (
    Engine,
    RecordAdviceCommand,
    RecordNarrationCommand,
    RecordProposalCommand,
    RecordStoryDirectionCommand,
    RollCharacteristicCommand,
    SetFlagCommand,
)
```

Then append to `tests/engine/test_commands.py`:

```python
class TestNarrationRecordCommands:
    """M0.5: shipped prose and story directions are canonical funnel events."""

    def test_record_narration_appends_prose_and_event(self):
        state = GameState.new(seed=1)
        engine = Engine(state)
        event = engine.apply(
            RecordNarrationCommand(text="The rain on Pad 9 isn't rain.", beat="scene", source="llm")
        )
        assert state.narrative_log[-1] == "The rain on Pad 9 isn't rain."
        assert event.changes == {
            "text": "The rain on Pad 9 isn't rain.",
            "beat": "scene",
            "source": "llm",
        }

    def test_record_narration_rejects_empty(self):
        state = GameState.new(seed=1)
        engine = Engine(state)
        with pytest.raises(ValueError, match="non-empty"):
            engine.apply(RecordNarrationCommand(text="  "))
        assert state.narrative_log == []  # validate fired before any mutation

    def test_record_story_direction_uses_scannable_prefix(self):
        state = GameState.new(seed=1)
        engine = Engine(state)
        engine.apply(RecordStoryDirectionCommand(text="more paranoia, less heroics", beat="scene"))
        assert state.narrative_log[-1] == "story_direction=more paranoia, less heroics"

    def test_record_story_direction_rejects_empty(self):
        engine = Engine(GameState.new(seed=1))
        with pytest.raises(ValueError, match="non-empty"):
            engine.apply(RecordStoryDirectionCommand(text=""))
```

Append to `tests/game/test_beats.py`:

```python
class TestNarratorMemory:
    """M0.5: memory derives from the event log, capped and ordered."""

    def test_memory_collects_prose_and_directions(self):
        from src.engine.commands import (
            Engine,
            RecordNarrationCommand,
            RecordStoryDirectionCommand,
        )
        from src.engine.state import GameState
        from src.game.beats import narrator_memory

        engine = Engine(GameState.new(seed=1))
        engine.apply(RecordNarrationCommand(text="First prose.", beat="a"))
        engine.apply(RecordStoryDirectionCommand(text="darker", beat="a"))
        engine.apply(RecordNarrationCommand(text="Second prose.", beat="b"))

        memory = narrator_memory(engine.state.events)
        assert memory.prose == ["First prose.", "Second prose."]
        assert memory.directions == ["darker"]

    def test_memory_caps_at_limits(self):
        from src.engine.commands import Engine, RecordNarrationCommand
        from src.engine.state import GameState
        from src.game.beats import narrator_memory

        engine = Engine(GameState.new(seed=1))
        for i in range(10):
            engine.apply(RecordNarrationCommand(text=f"Prose {i}.", beat="x"))

        memory = narrator_memory(engine.state.events, prose_limit=3)
        assert memory.prose == ["Prose 7.", "Prose 8.", "Prose 9."]

    def test_memory_ignores_other_events(self):
        from src.engine.commands import Engine, SetFlagCommand
        from src.engine.state import GameState
        from src.game.beats import narrator_memory

        engine = Engine(GameState.new(seed=1))
        engine.apply(SetFlagCommand(key="k", value="v"))
        memory = narrator_memory(engine.state.events)
        assert memory.prose == [] and memory.directions == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_commands.py::TestNarrationRecordCommands tests/game/test_beats.py::TestNarratorMemory -q`
Expected: FAIL — `ImportError: cannot import name 'RecordNarrationCommand'`.

- [ ] **Step 3a: The commands**

Append to `src/engine/commands.py`:

```python
class RecordNarrationCommand(Command):
    """Funnel shipped narration prose into canonical state (M0.5, D6).

    The prose that actually shipped to the player — LLM or template — is
    appended to ``state.narrative_log`` and recorded as a ``SYSTEM`` event.
    Replay re-reads this record; it never re-calls the LLM (the same
    guarantee :class:`RecordAdviceCommand` makes for advice).
    """

    command_type: ClassVar[str] = "record_narration"

    text: str
    beat: str = ""
    source: str = "llm"  # "llm" | "template"

    def validate(self, state: GameState) -> None:
        if not self.text or not self.text.strip():
            raise ValueError("narration text must be non-empty")
        if len(self.text) > 4000:
            raise ValueError("narration text must be 4000 characters or fewer")

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        state.narrative_log.append(self.text.strip())
        return Event(
            kind=EventKind.SYSTEM,
            command_type=self.command_type,
            description=f"Narration shipped ({self.beat or 'beat'}, {self.source})",
            changes={"text": self.text.strip(), "beat": self.beat, "source": self.source},
        )


class RecordStoryDirectionCommand(Command):
    """Record a player story direction for future narration conditioning (M0.5, D6).

    Directions are appended to ``narrative_log`` with the scannable
    ``story_direction=`` prefix (the same flag-channel convention as
    ``crisis_cost=``/``term_phase=``) and recorded as a ``SYSTEM`` event.
    Prompt builders surface recent directions so future prose is steered
    without ever touching mechanics.
    """

    command_type: ClassVar[str] = "record_story_direction"

    text: str
    beat: str = ""

    def validate(self, state: GameState) -> None:
        if not self.text or not self.text.strip():
            raise ValueError("story direction must be non-empty")
        if len(self.text) > 1000:
            raise ValueError("story direction must be 1000 characters or fewer")

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        state.narrative_log.append(f"story_direction={self.text.strip()}")
        return Event(
            kind=EventKind.SYSTEM,
            command_type=self.command_type,
            description="Story direction recorded",
            changes={"text": self.text.strip(), "beat": self.beat},
        )
```

- [ ] **Step 3b: Narrator memory**

In `src/game/beats.py`, add `from dataclasses import dataclass, field` to the imports and append:

```python
# ---------------------------------------------------------------------------
# Narrator memory (M0.5).
# ---------------------------------------------------------------------------


@dataclass
class NarratorMemory:
    """Recent shipped prose + standing player directions (M0.5).

    Derived from the event log (never from a side channel), so a restored
    session remembers exactly what a never-saved session would.
    """

    prose: list[str] = field(default_factory=list)
    directions: list[str] = field(default_factory=list)


def narrator_memory(
    events: list[Event],
    *,
    prose_limit: int = 6,
    direction_limit: int = 3,
) -> NarratorMemory:
    """Scan the event log for narration records and story directions (M0.5).

    Returns the most recent ``prose_limit`` shipped-prose texts and
    ``direction_limit`` player directions, oldest-first within each list.
    """
    prose = [e.changes["text"] for e in events if e.command_type == "record_narration"]
    directions = [
        e.changes["text"] for e in events if e.command_type == "record_story_direction"
    ]
    return NarratorMemory(
        prose=prose[-prose_limit:],
        directions=directions[-direction_limit:],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/engine/test_commands.py tests/game/test_beats.py -q`
Expected: PASS.

- [ ] **Step 5: Full gate + commit**

```bash
uv run ruff check src tests && uv run ruff format src tests && uv run pytest tests/ -q
git add src/engine/commands.py src/game/beats.py tests/engine/test_commands.py tests/game/test_beats.py
git commit -m "feat(engine): narration + story-direction funnel commands, narrator memory (M0.5)"
```

---

## Task 6: M0.7 — Keyring storage for the LLM key

The settings file currently holds the API key in plaintext (0600). After this task: the key lives in the OS keychain (`keyring`, service `andromeda`); a 0600 JSON file is the fallback when no keyring backend exists (headless Linux CI); the on-disk settings file never contains the key; legacy plaintext files migrate on first load.

**Files:**
- Create: `src/llm/keystore.py`
- Modify: `src/llm/settings.py` (load/save resolve the key through the store; add `key_backend`; add resolve/store/delete/mask helpers)
- Modify: `pyproject.toml` via `uv add keyring`
- Test: `tests/llm/test_keystore.py` (new), `tests/llm/test_settings.py` (update if it exists — check; otherwise fold settings tests into test_keystore.py)

**Interfaces:**
- Consumes: existing `LLMSettings`, `load_settings`, `save_settings`, `create_llm_adapter` shapes.
- Produces:
  - `src.llm.keystore.KeyStore` (Protocol): `get(account) -> str`, `set(account, secret) -> None`, `delete(account) -> None`, `backend_name -> str`
  - `KeyringStore()` / `KeyringStore.available() -> bool` / `FileKeyStore(settings_dir)`
  - `get_keystore(settings_dir) -> KeyStore`
  - `LLMSettings.key_backend: str = ""` (persisted; `"keyring" | "file" | ""`)
  - `resolve_api_key(settings, settings_dir) -> str`
  - `store_api_key(settings, api_key, settings_dir) -> LLMSettings`
  - `delete_api_key(settings, settings_dir) -> LLMSettings`
  - `masked_key_tail(settings, settings_dir) -> str` (`"…ab12"` or `""`)
- **Preserved contract:** `LLMSettings.api_key` remains a field, populated at load time (runtime-only; never written to disk). `is_configured`, `env_overrides`, `create_llm_adapter` keep working unchanged.

- [ ] **Step 1: Add the dependency**

```bash
uv add keyring
```

Expected: `uv.lock` updated; `keyring` in `[project.dependencies]`.

- [ ] **Step 2: Write the failing tests**

Create `tests/llm/test_keystore.py`:

```python
"""Key storage tests (M0.7): keychain primary, owner-only file fallback."""

from __future__ import annotations

import json

from src.llm.keystore import FileKeyStore, get_keystore, masked_tail
from src.llm.settings import (
    LLMSettings,
    load_settings,
    save_settings,
)


class TestFileKeyStore:
    def test_round_trip_and_permissions(self, tmp_path):
        store = FileKeyStore(tmp_path)
        store.set("anthropic", "sk-ant-secret1234")
        assert store.get("anthropic") == "sk-ant-secret1234"
        mode = (tmp_path / "llm.keys.json").stat().st_mode & 0o777
        assert mode == 0o600

    def test_missing_key_returns_empty(self, tmp_path):
        assert FileKeyStore(tmp_path).get("anthropic") == ""

    def test_delete(self, tmp_path):
        store = FileKeyStore(tmp_path)
        store.set("openai", "sk-x")
        store.delete("openai")
        assert store.get("openai") == ""

    def test_backend_name(self, tmp_path):
        assert FileKeyStore(tmp_path).backend_name == "file"


class TestMaskedTail:
    def test_mask_shows_last_four_only(self):
        assert masked_tail("sk-ant-secret1234") == "…1234"

    def test_short_key_masks_fully(self):
        assert masked_tail("abc") == "…"

    def test_empty(self):
        assert masked_tail("") == ""


class TestSettingsIntegration:
    def test_saved_file_never_contains_key(self, tmp_path):
        settings = LLMSettings(provider="anthropic", model="claude-sonnet-5", api_key="sk-ant-9999")
        save_settings(settings, tmp_path)
        raw = json.loads((tmp_path / "llm.json").read_text())
        assert "api_key" not in raw or not raw["api_key"]
        assert raw["key_backend"] in ("file", "keyring")

    def test_load_resolves_key_back(self, tmp_path):
        settings = LLMSettings(provider="anthropic", model="claude-sonnet-5", api_key="sk-ant-9999")
        save_settings(settings, tmp_path)
        loaded = load_settings(tmp_path)
        assert loaded.api_key == "sk-ant-9999"
        assert loaded.is_configured

    def test_legacy_plaintext_migrates_on_load(self, tmp_path):
        # A v0.1 file: key in plaintext, no key_backend.
        (tmp_path / "llm.json").write_text(
            json.dumps({"provider": "anthropic", "model": "m", "api_key": "sk-legacy-777"})
        )
        loaded = load_settings(tmp_path)
        assert loaded.api_key == "sk-legacy-777"
        # The file was rewritten without the key.
        raw = json.loads((tmp_path / "llm.json").read_text())
        assert not raw.get("api_key")
        assert raw.get("key_backend") in ("file", "keyring")

    def test_get_keystore_returns_a_working_store(self, tmp_path):
        store = get_keystore(tmp_path)
        store.set("p", "s3cr3t")
        assert store.get("p") == "s3cr3t"
        assert store.backend_name in ("file", "keyring")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/llm/test_keystore.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.llm.keystore'`.

- [ ] **Step 4a: `src/llm/keystore.py`**

```python
"""API-key storage: OS keychain primary, owner-only file fallback (M0.7, D7).

The LLM API key never lives in the settings file. It is stored in the OS
keychain via ``keyring`` (service ``andromeda``); on systems without a
keyring backend (headless Linux, CI), it falls back to an owner-only
(0600) JSON file next to the settings. The client only ever sees a masked
tail (``…1234``) via :func:`masked_tail`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol

#: Keychain service name (shown in OS keychain UIs).
SERVICE_NAME = "andromeda"

#: Fallback file name inside the settings directory.
KEYS_FILENAME = "llm.keys.json"


class KeyStore(Protocol):
    """Secret storage backend."""

    def get(self, account: str) -> str:
        """Return the stored secret for ``account``, or "" when absent."""
        ...

    def set(self, account: str, secret: str) -> None:
        """Store ``secret`` for ``account``."""
        ...

    def delete(self, account: str) -> None:
        """Remove any secret for ``account``."""
        ...

    @property
    def backend_name(self) -> str:
        """``"keyring"`` or ``"file"`` — surfaced in Settings (D7 visible status)."""
        ...


class KeyringStore:
    """OS keychain backend via the ``keyring`` package."""

    def __init__(self) -> None:
        import keyring

        self._keyring = keyring

    @classmethod
    def available(cls) -> bool:
        """True when a real keyring backend is usable on this system."""
        try:
            import keyring
            from keyring.backends.fail import Keyring as FailKeyring

            backend = keyring.get_keyring()
            return not isinstance(backend, FailKeyring)
        except Exception:
            return False

    def get(self, account: str) -> str:
        return self._keyring.get_password(SERVICE_NAME, account) or ""

    def set(self, account: str, secret: str) -> None:
        self._keyring.set_password(SERVICE_NAME, account, secret)

    def delete(self, account: str) -> None:
        try:
            self._keyring.delete_password(SERVICE_NAME, account)
        except Exception:
            pass  # deleting an absent key is a no-op

    @property
    def backend_name(self) -> str:
        return "keyring"


class FileKeyStore:
    """Owner-only JSON file fallback (headless systems without a keychain)."""

    def __init__(self, settings_dir: str | Path) -> None:
        self._path = Path(settings_dir) / KEYS_FILENAME

    def _read(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _write(self, data: dict[str, str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self._path)
        os.chmod(self._path, 0o600)

    def get(self, account: str) -> str:
        return self._read().get(account, "")

    def set(self, account: str, secret: str) -> None:
        data = self._read()
        data[account] = secret
        self._write(data)

    def delete(self, account: str) -> None:
        data = self._read()
        if account in data:
            del data[account]
            self._write(data)

    @property
    def backend_name(self) -> str:
        return "file"


def get_keystore(settings_dir: str | Path) -> KeyStore:
    """Return the OS keychain when usable, else the owner-only file store."""
    if KeyringStore.available():
        return KeyringStore()
    return FileKeyStore(settings_dir)


def masked_tail(secret: str) -> str:
    """The only key material the client ever sees: ``…last4`` (D7)."""
    if not secret:
        return ""
    if len(secret) <= 4:
        return "…"
    return f"…{secret[-4:]}"
```

- [ ] **Step 4b: settings.py integration**

In `src/llm/settings.py`:

1. Add to `LLMSettings` after `api_key` (keep `api_key` — it becomes runtime-only):

```python
    key_backend: str = ""
    """Where the API key is stored: ``"keyring"`` | ``"file"`` | ``""`` (no key).
    The key itself is never persisted in this file (M0.7, D7)."""
```

2. Replace `load_settings` and `save_settings` with:

```python
def load_settings(settings_dir: str | Path = DEFAULT_SETTINGS_DIR) -> LLMSettings:
    """Load LLM settings from disk and resolve the API key from the store.

    The on-disk file never contains the key (M0.7): the key is read from
    the OS keychain (or the 0600 fallback file) into the runtime-only
    ``api_key`` field. Legacy files that still hold a plaintext key are
    migrated: the key moves into the store and the file is rewritten
    scrubbed.
    """
    from src.llm.keystore import get_keystore

    path = settings_path(settings_dir)
    if not path.exists():
        return LLMSettings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        settings = LLMSettings.model_validate(data)
    except (json.JSONDecodeError, ValueError):
        return LLMSettings()

    store = get_keystore(settings_dir)
    legacy_key = settings.api_key  # present only in pre-M0.7 files
    if legacy_key:
        store.set(settings.provider, legacy_key)
        settings.key_backend = store.backend_name
        # Rewrite scrubbed — the file must not keep the key.
        scrubbed = settings.model_copy(update={"api_key": ""})
        _write_settings_file(scrubbed, settings_dir)
    elif settings.key_backend:
        settings.api_key = store.get(settings.provider)
    return settings


def save_settings(settings: LLMSettings, settings_dir: str | Path = DEFAULT_SETTINGS_DIR) -> Path:
    """Persist LLM settings atomically; the API key goes to the store (M0.7).

    When ``settings.api_key`` is set, it is written to the OS keychain (or
    the 0600 fallback file) and ``key_backend`` records which. The JSON
    file is written without the key, with owner-only permissions.
    """
    from src.llm.keystore import get_keystore

    store = get_keystore(settings_dir)
    to_persist = settings.model_copy(update={"api_key": ""})
    if settings.api_key:
        store.set(settings.provider, settings.api_key)
        to_persist.key_backend = store.backend_name
    return _write_settings_file(to_persist, settings_dir)


def _write_settings_file(settings: LLMSettings, settings_dir: str | Path) -> Path:
    """Write the settings JSON (never contains the key) with 0600 perms."""
    path = settings_path(settings_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    payload = settings.model_dump()
    payload.pop("api_key", None)  # belt: the key never lands on disk here
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)
    os.chmod(path, 0o600)
    return path


def resolve_api_key(settings: LLMSettings, settings_dir: str | Path = DEFAULT_SETTINGS_DIR) -> str:
    """Return the stored API key for the settings' provider ("" when none)."""
    from src.llm.keystore import get_keystore

    if settings.api_key:  # already resolved (runtime)
        return settings.api_key
    return get_keystore(settings_dir).get(settings.provider)


def delete_api_key(settings: LLMSettings, settings_dir: str | Path = DEFAULT_SETTINGS_DIR) -> LLMSettings:
    """Remove the stored key and return updated (persisted) settings."""
    from src.llm.keystore import get_keystore

    get_keystore(settings_dir).delete(settings.provider)
    updated = settings.model_copy(update={"api_key": "", "key_backend": ""})
    _write_settings_file(updated, settings_dir)
    return updated


def masked_key_tail(settings: LLMSettings, settings_dir: str | Path = DEFAULT_SETTINGS_DIR) -> str:
    """The masked tail shown in the UI (``…1234``), or "" when no key."""
    from src.llm.keystore import masked_tail

    return masked_tail(resolve_api_key(settings, settings_dir))
```

3. Update the module docstring's second paragraph:

```python
Settings are stored as JSON in a settings directory so they persist across
sessions. The API key is NOT stored in this file (M0.7, D7): it lives in the
OS keychain via ``keyring`` (service ``andromeda``), with an owner-only
(0600) fallback file on systems without a keychain. The ``api_key`` field
on :class:`LLMSettings` is runtime-only, resolved at load.
```

(Delete the old `save_settings` docstring's "plaintext" remark. `create_llm_adapter` and `apply_llm_env` need no changes — they read the runtime `api_key` field that `load_settings` now resolves.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/llm/ -q`
Expected: PASS. If a pre-existing settings test asserts the key IS in the file, update that test to the new contract (key in store, `key_backend` in file) — that inversion is the point of the task.

- [ ] **Step 6: Full gate + commit**

```bash
uv run ruff check src tests && uv run ruff format src tests && uv run pytest tests/ -q
git add src/llm/keystore.py src/llm/settings.py pyproject.toml uv.lock tests/llm/test_keystore.py
git commit -m "feat(llm): API key moves to OS keychain with 0600 fallback (M0.7/D7)"
```

---

## Task 7: M0.6a — Server package: app factory, session registry, lifecycle, meta + config routes

The sidecar skeleton: `create_app` with the error envelope and activity middleware, the in-memory `SessionRegistry` with autosave, the `__main__` entry with the `LISTENING` handshake and idle watchdog, and the meta/config endpoints. Gameplay endpoints land in Task 8; saves/settings in Task 9; introspection in Task 10.

**Files:**
- Create: `src/server/__init__.py`, `src/server/__main__.py`, `src/server/app.py`, `src/server/errors.py`, `src/server/models.py`, `src/server/sessions.py`, `src/server/routes_meta.py`, `src/server/routes_config.py`
- Modify: `pyproject.toml` via `uv add fastapi uvicorn`
- Test: `tests/server/__init__.py` (empty), `tests/server/conftest.py`, `tests/server/test_meta_config.py`

**Interfaces:**
- Consumes: `GameSession` (`src/game/session.py:46`), `ChargenSession.create`, `AdventureSession.wrap` (Task 3), `discover_packs`/`get_pack`, `CepheusRuleSet`, `PROVIDER_CONFIGS`/`provider_labels`, `load_settings`, `create_llm_adapter`, `determine_resume_route` (`src/game/saves.py:114`).
- Produces:
  - `create_app(*, saves_dir: Path, settings_dir: Path, adapter=None, advisor=None, translator=None) -> FastAPI` — app.state carries `registry`, `settings`, `adapter`, `advisor`, `translator`, `last_request_at`.
  - `src.server.errors.ApiError(status_code: int, code: str, message: str)`; handlers map: `ApiError` → its status/code; `ValueError` → 422 `invalid_choice`; `StaleWriteError` → 409 `save_conflict`; `SessionNotFoundError` → 404 `session_not_found`; `ActionInFlightError` → 409 `action_in_flight`; `PackLoadError` → 422 `invalid_config`.
  - `SessionRegistry.create_chargen(name, seed, pack_id, profile, death_mode) -> SessionRecord`; `.create_adventure(name) -> SessionRecord` (loads save `name`); `.resume(name) -> SessionRecord` (route-inferred kind); `.get(id)`, `.list()`, `.delete(id)`, `.promote(id)`, `.autosave(record)`, `.save_manual(record, name)`.
  - `SessionRecord` dataclass: `id: str`, `kind: str`, `name: str`, `game: GameSession`, `chargen: ChargenSession | None`, `adventure: AdventureSession | None`, `last_narrated_seq: int = 0`, `last_beat_start: int = 0`.
  - Endpoints: `GET /health`, `GET /v1/llm/status`, `GET /v1/config/packs`, `GET /v1/config/rulesets`, `GET /v1/config/providers`.

- [ ] **Step 1: Add dependencies**

```bash
uv add fastapi uvicorn
```

- [ ] **Step 2: Write the failing tests**

Create `tests/server/__init__.py` (empty file) and `tests/server/conftest.py`:

```python
"""Server test fixtures (M0.6)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.server.app import create_app


@pytest.fixture()
def client(tmp_path):
    app = create_app(saves_dir=tmp_path / "saves", settings_dir=tmp_path / "settings")
    with TestClient(app) as test_client:
        yield test_client
```

Create `tests/server/test_meta_config.py`:

```python
"""Meta + config endpoint contract tests (M0.6a)."""

from __future__ import annotations


class TestHealth:
    def test_health_shape(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["contract_versions"] == {"chargen": 1, "adventure": 1}


class TestErrorEnvelope:
    def test_unknown_route_uses_envelope(self, client):
        resp = client.get("/v1/sessions/nope")
        assert resp.status_code == 404
        body = resp.json()
        assert "error" in body and "code" in body["error"] and "message" in body["error"]
        # Task 8 adds GET /v1/sessions/{id}; unknown ids then return the
        # precise code "session_not_found".


class TestLlmStatus:
    def test_unconfigured_by_default(self, client):
        resp = client.get("/v1/llm/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["configured"] is False
        assert body["model"] is None
        assert body["key_backend"] in ("", "file", "keyring")


class TestConfig:
    def test_packs(self, client):
        resp = client.get("/v1/config/packs")
        assert resp.status_code == 200
        packs = {p["id"]: p for p in resp.json()["packs"]}
        assert "scifi" in packs and "fantasy" in packs
        scifi = packs["scifi"]
        assert scifi["career_count"] == 25
        assert scifi["has_cascades"] is True
        assert scifi["theme"] == {"motif": "✦", "accent": "amber", "ambience": ["meteors", "birds"]}
        assert scifi["has_intro"] is True

    def test_rulesets(self, client):
        resp = client.get("/v1/config/rulesets")
        assert resp.status_code == 200
        rulesets = resp.json()["rulesets"]
        cepheus = next(r for r in rulesets if r["id"] == "cepheus")
        assert cepheus["resolution_profiles"] == ["classic", "narrative"]
        assert sorted(cepheus["death_modes"]) == ["checkpoint", "ironman", "narrative"]
        assert "average" in cepheus["difficulty_ladder"]

    def test_providers(self, client):
        resp = client.get("/v1/config/providers")
        assert resp.status_code == 200
        providers = {p["id"]: p for p in resp.json()["providers"]}
        assert "anthropic" in providers
        assert providers["anthropic"]["label"] == "Anthropic"
        assert "claude-sonnet-5" in providers["anthropic"]["presets"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/server/ -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.server'`.

- [ ] **Step 4a: errors.py**

Create `src/server/errors.py`:

```python
"""API error envelope (spec §5): {"error": {"code", "message"}}."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.game.session import StaleWriteError
from src.themepacks.base import PackLoadError


class ApiError(Exception):
    """An error with a stable machine code and a client-renderable message."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class SessionNotFoundError(Exception):
    """Unknown session id."""


class ActionInFlightError(Exception):
    """A beat is already in flight for this session (KTD-9 gate)."""


def envelope(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def register_error_handlers(app: FastAPI) -> None:
    """Map exceptions onto the error envelope (spec §5: engine messages verbatim)."""

    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=envelope(exc.code, exc.message))

    @app.exception_handler(SessionNotFoundError)
    async def _not_found(_request: Request, exc: SessionNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content=envelope("session_not_found", str(exc)))

    @app.exception_handler(ActionInFlightError)
    async def _in_flight(_request: Request, exc: ActionInFlightError) -> JSONResponse:
        return JSONResponse(status_code=409, content=envelope("action_in_flight", str(exc)))

    @app.exception_handler(StaleWriteError)
    async def _stale(_request: Request, exc: StaleWriteError) -> JSONResponse:
        return JSONResponse(status_code=409, content=envelope("save_conflict", str(exc)))

    @app.exception_handler(PackLoadError)
    async def _pack(_request: Request, exc: PackLoadError) -> JSONResponse:
        return JSONResponse(status_code=422, content=envelope("invalid_config", str(exc)))

    @app.exception_handler(ValueError)
    async def _value(_request: Request, exc: ValueError) -> JSONResponse:
        # Engine/controller validation messages ship verbatim — the client
        # renders them in toasts (spec §5).
        return JSONResponse(status_code=422, content=envelope("invalid_choice", str(exc)))
```

- [ ] **Step 4b: models.py**

Create `src/server/models.py`:

```python
"""Wire DTOs for the v1 API (M0.6). Request/response pydantic models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    """POST /v1/sessions body."""

    kind: Literal["chargen", "adventure"] = "chargen"
    name: str = Field(min_length=1, max_length=80)
    seed: int | None = None  # None → server picks one (client's REROLL sends an int)
    pack_id: str = "scifi"
    profile: Literal["narrative", "classic"] = "narrative"
    death_mode: Literal["narrative", "ironman", "checkpoint"] = "narrative"
    from_save: str | None = None  # adventure kind: save name to load/resume


class ChooseRequest(BaseModel):
    option_id: str
    origin: Literal["player", "advisor", "freetext"] = "player"


class FreetextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class NarrateRequest(BaseModel):
    beat: str = "scene"  # "world_intro" | "scene" | "chargen_beat" | "chargen_close"
    steering: str = ""


class NameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class SaveRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class DuplicateSaveRequest(BaseModel):
    new_name: str = Field(min_length=1, max_length=80)


class ImportSaveRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    document: dict  # the full GameState JSON document


class LlmSettingsRequest(BaseModel):
    """PUT /v1/settings/llm body. ``api_key=None`` leaves the stored key untouched."""

    provider: str = "anthropic"
    model: str = ""
    api_key: str | None = None
    base_url: str = ""
    max_retries: int = 3


class OddsRequest(BaseModel):
    skill: str
    characteristic: str
    difficulty: str
```

- [ ] **Step 4c: sessions.py — the registry**

Create `src/server/sessions.py`:

```python
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
        game = GameSession(
            self._autosave_path(name), settings=self._settings, engine=engine
        )
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
        state = load(self._main_path(name))
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
        record = SessionRecord(
            id=uuid.uuid4().hex[:12], kind=kind, name=name, game=game
        )
        if kind == "chargen":
            pack = get_pack(state.campaign.theme_pack)
            record.chargen = ChargenSession(
                engine,
                LifepathController(engine, pack),
                advisor=self.advisor,
                translator=self.translator,
            )
        else:
            record.adventure = AdventureSession.wrap(
                engine, checkpoint_mgr=game.checkpoint_mgr
            )
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

        Retargets the session's base name so subsequent autosaves follow
        the new name. Prior files are left in place (they are earlier save
        points; Chronicles lists them).
        """
        from src.engine.persistence import save

        main = self._main_path(name)
        save(record.game.state, main)
        if record.game.state.campaign.death_mode == "checkpoint":
            record.game.checkpoint_mgr.save_snapshot(main)
        record.name = name

    def _main_path(self, name: str) -> Path:
        return resolve_save_path(self._saves_dir, name)

    def _autosave_path(self, name: str) -> Path:
        base = resolve_save_path(self._saves_dir, name)
        return base.with_name(base.stem + AUTOSAVE_SUFFIX + base.suffix)
```

- [ ] **Step 4d: ChargenSession `phase` + `completed` properties**

The registry's `promote` (Step 4c) and Task 8's session envelope need these. In `src/game/chargen/api.py`, after the `current_choice` method (~line 108), add:

```python
    @property
    def phase(self) -> str:
        """The controller's current phase identifier (M0.6 server surface)."""
        return self._controller.determine_phase()

    @property
    def completed(self) -> bool:
        """True when chargen has run to completion (mustered out or died)."""
        return self._controller.determine_phase() == "complete"
```

- [ ] **Step 4e: app.py**

Create `src/server/app.py`:

```python
"""FastAPI app factory for the Andromeda sidecar (M0.6).

The app owns: settings (with keyring-resolved key), the LLM trio (adapter /
advisor / translator — ``None`` when unconfigured, template mode), the
session registry, and the activity timestamp the idle watchdog reads.
"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI

from src.llm.settings import LLMSettings, create_llm_adapter, load_settings
from src.server.errors import register_error_handlers
from src.server.sessions import SessionRegistry


class ActivityMiddleware:
    """Stamp ``last_request_at`` on every HTTP request (idle watchdog feed).

    Pure ASGI — deliberately NOT ``@app.middleware("http")``:
    BaseHTTPMiddleware buffers response bodies on some Starlette versions,
    which would break the Task 8 NDJSON stream.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            scope["app"].state.last_request_at = time.monotonic()
        await self.app(scope, receive, send)


def create_app(
    *,
    saves_dir: Path = Path("saves"),
    settings_dir: Path = Path("settings"),
    settings: LLMSettings | None = None,
    adapter=None,
    advisor=None,
    translator=None,
) -> FastAPI:
    """Build the sidecar application.

    ``adapter``/``advisor``/``translator`` are injectable for tests (a
    ``TestModel``-backed adapter makes narration deterministic). When
    ``None`` and settings are complete, real ones are built.
    """
    app = FastAPI(title="andromeda-sidecar", docs_url=None, redoc_url=None)

    settings = settings if settings is not None else load_settings(settings_dir)
    if adapter is None:
        adapter = create_llm_adapter(settings)
    if advisor is None and settings.is_configured:
        from src.llm.advisor import Advisor, AdvisorConfig

        advisor = Advisor(AdvisorConfig(model=settings.model_string))
    if translator is None and settings.is_configured:
        from src.llm.translator import Translator
        from src.llm.adapter import AdapterConfig

        translator = Translator(AdapterConfig(model=settings.model_string))

    app.state.settings = settings
    app.state.settings_dir = Path(settings_dir)
    app.state.saves_dir = Path(saves_dir)
    app.state.adapter = adapter
    app.state.advisor = advisor
    app.state.translator = translator
    app.state.last_request_at = time.monotonic()
    app.state.registry = SessionRegistry(
        saves_dir=Path(saves_dir),
        settings=settings,
        adapter=adapter,
        advisor=advisor,
        translator=translator,
    )

    app.add_middleware(ActivityMiddleware)
    register_error_handlers(app)

    from src.server.routes_config import router as config_router
    from src.server.routes_meta import router as meta_router

    app.include_router(meta_router)
    app.include_router(config_router)

    # Gameplay/saves/settings/inspect routers land in Tasks 8–10 and are
    # included unconditionally — they exist by the time this ships.
    from src.server.routes_inspect import router as inspect_router
    from src.server.routes_saves import router as saves_router
    from src.server.routes_sessions import router as sessions_router
    from src.server.routes_settings import router as settings_router

    app.include_router(sessions_router)
    app.include_router(saves_router)
    app.include_router(settings_router)
    app.include_router(inspect_router)

    return app
```

- [ ] **Step 4f: routes_meta.py + routes_config.py**

Create `src/server/routes_meta.py`:

```python
"""Meta endpoints: /health and /v1/llm/status (M0.6)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from src.game.chargen.api import CONTRACT_VERSION as CHARGEN_CONTRACT
from src.game.adventure_session import CONTRACT_VERSION as ADVENTURE_CONTRACT
from src.llm.status import STATUS_NARRATION_UNAVAILABLE

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "contract_versions": {"chargen": CHARGEN_CONTRACT, "adventure": ADVENTURE_CONTRACT},
    }


@router.get("/v1/llm/status")
async def llm_status(request: Request) -> dict:
    """Narrator status for the status strip (spec §9: canonical strings only)."""
    settings = request.app.state.settings
    adapter = request.app.state.adapter
    configured = bool(adapter is not None and adapter.llm_configured)
    return {
        "configured": configured,
        "model": settings.model_string if configured else None,
        "key_backend": settings.key_backend,
        # Shown when narration degrades; canonical string, never invented copy.
        "degraded_line": None if configured else STATUS_NARRATION_UNAVAILABLE,
    }
```

Create `src/server/routes_config.py`:

```python
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
```

- [ ] **Step 4g: __init__.py + __main__.py**

Create `src/server/__init__.py`:

```python
"""Andromeda sidecar server — FastAPI over 127.0.0.1, NDJSON streaming (M0.6).

The server wraps the engine's session contracts and owns autosave, key
storage, and the LLM adapter. The Godot client holds zero game truth.
"""
```

Create `src/server/__main__.py`:

```python
"""Sidecar entry point: ``python -m src.server [--port N]`` (M0.6, spec §3).

Binds 127.0.0.1 (random port by default), prints exactly one stdout line —
``LISTENING <port>`` — for the spawning client, then serves until the
client kills the process or the idle watchdog fires (300 s without a
request → self-exit, so orphans never linger).
"""

from __future__ import annotations

import argparse
import asyncio
import socket
import time
from pathlib import Path

import uvicorn

from src.server.app import create_app

#: Self-exit after this many seconds without a request (spec §3).
DEFAULT_IDLE_TIMEOUT = 300


async def _watchdog(server: uvicorn.Server, state, idle_timeout: int) -> None:
    """Flip ``should_exit`` when the app has been idle too long."""
    while True:
        await asyncio.sleep(15)
        if time.monotonic() - state.last_request_at > idle_timeout:
            server.should_exit = True
            return


async def _serve(server: uvicorn.Server, sock: socket.socket, state, idle_timeout: int) -> None:
    watcher = asyncio.create_task(_watchdog(server, state, idle_timeout))
    try:
        await server.serve(sockets=[sock])
    finally:
        watcher.cancel()


def main() -> None:
    parser = argparse.ArgumentParser(prog="andromeda-server")
    parser.add_argument("--port", type=int, default=0, help="0 = pick a free port")
    parser.add_argument("--saves-dir", type=Path, default=Path("saves"))
    parser.add_argument("--settings-dir", type=Path, default=Path("settings"))
    parser.add_argument("--idle-timeout", type=int, default=DEFAULT_IDLE_TIMEOUT)
    args = parser.parse_args()

    app = create_app(saves_dir=args.saves_dir, settings_dir=args.settings_dir)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", args.port))
    sock.listen()
    port = sock.getsockname()[1]
    # The ONLY stdout line the client reads (spec §3 handshake).
    print(f"LISTENING {port}", flush=True)

    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    asyncio.run(_serve(server, sock, app.state, args.idle_timeout))


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Verify (tests for the routes that exist so far)**

The config/meta tests can't pass until Task 8–10 routers exist (app.py imports them). To keep this task independently landable, create the four remaining router modules as minimal stubs NOW (they get their real endpoints in Tasks 8–10):

`src/server/routes_sessions.py`:

```python
"""Session gameplay endpoints (M0.6b — implemented in Task 8)."""

from fastapi import APIRouter

router = APIRouter(prefix="/v1/sessions")
```

`src/server/routes_saves.py`:

```python
"""Save management endpoints (M0.6c — implemented in Task 9)."""

from fastapi import APIRouter

router = APIRouter(prefix="/v1")
```

`src/server/routes_settings.py`:

```python
"""LLM settings endpoints (M0.6c — implemented in Task 9)."""

from fastapi import APIRouter

router = APIRouter(prefix="/v1/settings")
```

`src/server/routes_inspect.py`:

```python
"""Introspection endpoints (M0.6c — implemented in Task 10)."""

from fastapi import APIRouter

router = APIRouter(prefix="/v1/sessions")
```

Then run: `uv run pytest tests/server/ -q`
Expected: PASS (all meta/config tests; the 404 envelope test passes because `/v1/sessions/nope` hits the sessions router with no matching route → 404 from FastAPI… **careful**: FastAPI's default 404 body is `{"detail": "Not Found"}`, not our envelope. Add a catch-all override in `register_error_handlers` (errors.py):

```python
    from starlette.exceptions import HTTPException as StarletteHTTPException

    @app.exception_handler(StarletteHTTPException)
    async def _http(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return JSONResponse(
                status_code=404, content=envelope("not_found", "Unknown endpoint")
            )
        return JSONResponse(
            status_code=exc.status_code,
            content=envelope("http_error", str(exc.detail)),
        )
```

Note: the `StarletteHTTPException` import must come from `starlette.exceptions` (as shown), not `fastapi.exceptions`. The activity middleware is already pure ASGI (see app.py), so NDJSON streaming in Task 8 is unaffected by response buffering.

- [ ] **Step 6: Full gate + commit**

```bash
uv run ruff check src tests && uv run ruff format src tests && uv run pytest tests/ -q
git add src/server/ tests/server/ pyproject.toml uv.lock
git commit -m "feat(server): sidecar skeleton — app, registry, lifecycle, meta+config (M0.6a)"
```

---

## Task 8: M0.6b — Session gameplay routes (choose / freetext / suggest / narrate / promote / name)

The heart of the API. Every mutation flows: endpoint → session contract → engine funnel → autosave → view response carrying the **structured new events** (so the client renders roll readouts from data, not text parsing — spec D5). `/narrate` streams NDJSON blocks; all mutations happen **before** streaming starts (the trust boundary made temporal — mechanics and shipped prose are canonical before the client sees a word).

**Files:**
- Modify: `src/server/sessions.py` (save-existence pre-checks in `create_adventure`/`resume`)
- Modify: `src/server/routes_sessions.py` (replace the Task 7 stub)
- Test: `tests/server/test_sessions.py` (new)

**Interfaces:**
- Consumes: everything from Tasks 1–7; `derive_recent_change_lines(events, since_seq=...)` (`src/game/change_lines.py:271`); `record_advice(engine, record)` (`src/game/advice.py:26`); `ChoicePointView`/`ChoiceOptionView` (`src/engine/lifepath_choices.py`); `SetCharacterNameCommand` (`src/engine/commands.py:276`); `STATUS_NARRATION_UNAVAILABLE`, `STATUS_CONNECTION_LOST` (`src/llm/status.py`).
- Produces (all under `/v1/sessions`):
  - `POST ""` (201) → `{"session": <SessionEnvelope>}`
  - `GET ""` → `{"sessions": [<SessionSummary>]}`; `GET /{id}` → `{"session": <SessionEnvelope>}`; `DELETE /{id}` → 204
  - `POST /{id}/choose` → `{"session": ..., "result": <StepResult dict>, "events": [<Event dict>]}`
  - `POST /{id}/freetext` → chargen: `{"record": <TranslationRecord dict>}`; adventure: same envelope as choose
  - `POST /{id}/suggest` → `{"record": <SuggestionRecord dict> | null}`
  - `POST /{id}/name` → `{"session": ...}`
  - `POST /{id}/promote` → `{"session": ...}` (kind now `"adventure"`)
  - `POST /{id}/narrate` → NDJSON stream of `{"type", "content"}` lines
  - `<SessionEnvelope>` = `{"id", "name", "kind", "phase", "view": <dict|null>, "contract_version": int}`

- [ ] **Step 1: Write the failing tests**

Create `tests/server/test_sessions.py`:

```python
"""Gameplay endpoint contract tests (M0.6b)."""

from __future__ import annotations

import json


def _create(client, name="The Ruuth Run", **overrides):
    body = {"kind": "chargen", "name": name, "seed": 42, "pack_id": "scifi"}
    body.update(overrides)
    resp = client.post("/v1/sessions", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["session"]


class TestCreateAndView:
    def test_create_chargen(self, client):
        session = _create(client)
        assert session["kind"] == "chargen"
        assert session["phase"] == "roll_characteristics"
        assert session["contract_version"] == 1
        assert session["view"]["options"][0]["option_id"] == "roll_pool"

    def test_create_writes_autosave(self, client, tmp_path):
        _create(client)
        assert (tmp_path / "saves" / "The_Ruuth_Run.autosave.json").exists()

    def test_list_and_get(self, client):
        session = _create(client)
        listing = client.get("/v1/sessions").json()["sessions"]
        assert [s["id"] for s in listing] == [session["id"]]
        fetched = client.get(f"/v1/sessions/{session['id']}").json()["session"]
        assert fetched["phase"] == "roll_characteristics"

    def test_delete(self, client):
        session = _create(client)
        assert client.delete(f"/v1/sessions/{session['id']}").status_code == 204
        resp = client.get(f"/v1/sessions/{session['id']}")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "session_not_found"


class TestChoose:
    def test_choose_returns_structured_events(self, client):
        session = _create(client)
        resp = client.post(
            f"/v1/sessions/{session['id']}/choose", json={"option_id": "roll_pool"}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["result"]["contract_version"] == 1
        # Structured roll events power the client's graphical readouts (D5).
        rolls = [e for e in body["events"] if e["kind"] == "roll"]
        assert rolls, "expected roll events in the choose response"
        assert rolls[0]["roll"]["rolls"]  # pip values present
        assert rolls[0]["roll"]["stream"] == "lifepath"

    def test_choose_invalid_option_is_422_verbatim(self, client):
        session = _create(client)
        resp = client.post(
            f"/v1/sessions/{session['id']}/choose", json={"option_id": "nope"}
        )
        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "invalid_choice"
        assert "nope" in body["error"]["message"]  # engine message verbatim


class TestName:
    def test_set_name(self, client):
        session = _create(client)
        resp = client.post(
            f"/v1/sessions/{session['id']}/name", json={"name": "Mara Voss"}
        )
        assert resp.status_code == 200
        state_resp = client.get(f"/v1/sessions/{session['id']}/sheet")
        assert state_resp.json()["character"]["name"] == "Mara Voss"


class TestNarrate:
    @staticmethod
    def _blocks(resp) -> list[dict]:
        return [json.loads(line) for line in resp.text.splitlines() if line.strip()]

    def test_world_intro_template_streams_blocks(self, client):
        session = _create(client)
        resp = client.post(
            f"/v1/sessions/{session['id']}/narrate", json={"beat": "world_intro"}
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/x-ndjson")
        blocks = self._blocks(resp)
        assert blocks[-1]["type"] == "done"
        narration = " ".join(b["content"] for b in blocks if b["type"] == "narration")
        assert "frontier" in narration.lower()  # the scifi pack intro text

    def test_world_intro_replays_without_recalling(self, client):
        session = _create(client)
        first = self._blocks(
            client.post(f"/v1/sessions/{session['id']}/narrate", json={"beat": "world_intro"})
        )
        second = self._blocks(
            client.post(f"/v1/sessions/{session['id']}/narrate", json={"beat": "world_intro"})
        )
        first_text = [b["content"] for b in first if b["type"] == "narration"]
        second_text = [b["content"] for b in second if b["type"] == "narration"]
        assert first_text == second_text  # replayed record, byte-identical

    def test_steering_is_recorded(self, client, tmp_path):
        session = _create(client)
        client.post(f"/v1/sessions/{session['id']}/narrate", json={"beat": "world_intro"})
        resp = client.post(
            f"/v1/sessions/{session['id']}/narrate",
            json={"beat": "world_intro", "steering": "lean into the loneliness"},
        )
        assert resp.status_code == 200
        # Steering and shipped prose are canonical funnel events — visible in
        # the autosave document (the /audit endpoint lands in Task 10).
        auto = json.loads((tmp_path / "saves" / "The_Ruuth_Run.autosave.json").read_text())
        kinds = {e["command_type"] for e in auto["events"]}
        assert "record_story_direction" in kinds
        assert "record_narration" in kinds

    def test_scene_beat_after_choose(self, client):
        session = _create(client)
        client.post(f"/v1/sessions/{session['id']}/choose", json={"option_id": "roll_pool"})
        resp = client.post(
            f"/v1/sessions/{session['id']}/narrate", json={"beat": "chargen_beat"}
        )
        assert resp.status_code == 200
        blocks = self._blocks(resp)
        assert blocks[-1]["type"] == "done"


class TestSuggest:
    def test_suggest_without_advisor_is_422(self, client):
        session = _create(client)
        resp = client.post(f"/v1/sessions/{session['id']}/suggest")
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "advisor_unavailable"


class TestPromote:
    def test_promote_before_completion_is_422(self, client):
        session = _create(client)
        resp = client.post(f"/v1/sessions/{session['id']}/promote")
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "invalid_phase"

    def test_promote_non_chargen_is_422(self, client, tmp_path):
        from tests.server.conftest import write_save

        write_save(tmp_path / "saves", "Mara")
        created = _create(client, name="x", kind="adventure", from_save="Mara")
        assert created["kind"] == "adventure"
        resp = client.post(f"/v1/sessions/{created['id']}/promote")
        assert resp.status_code == 422


class TestAdventureFlow:
    def test_resume_adventure_and_play_a_scene(self, client, tmp_path):
        from tests.server.conftest import write_save

        write_save(tmp_path / "saves", "Mara")
        session = _create(client, name="x", kind="adventure", from_save="Mara")
        assert session["kind"] == "adventure"
        assert session["phase"] == "hook_offered"

        resp = client.post(
            f"/v1/sessions/{session['id']}/choose", json={"option_id": "accept_mission"}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["session"]["phase"] == "scene_active"

        # B4 through the wire: the dimmed push is a 422, not a crash.
        resp = client.post(
            f"/v1/sessions/{session['id']}/choose", json={"option_id": "push_for_ending"}
        )
        assert resp.status_code == 422

    def test_freetext_outside_scene_is_422(self, client, tmp_path):
        from tests.server.conftest import write_save

        write_save(tmp_path / "saves", "Mara")
        session = _create(client, name="x", kind="adventure", from_save="Mara")
        resp = client.post(
            f"/v1/sessions/{session['id']}/freetext", json={"text": "I look around"}
        )
        assert resp.status_code == 422  # hook phase — no scaffold to interpret
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/server/test_sessions.py -q`
Expected: FAIL — 404s everywhere (router is a stub), plus `write_save` missing from conftest.

- [ ] **Step 3a: `write_save` fixture helper**

Append to `tests/server/conftest.py`:

```python
def write_save(saves_dir, name: str, *, death_mode: str = "narrative", seed: int = 42):
    """Write a mustered-out, adventure-ready save document (M0.6 tests)."""
    from src.engine.persistence import save
    from src.engine.state import CampaignConfig, GameState

    state = GameState.new(seed=seed)
    state.campaign = CampaignConfig(
        resolution_profile="narrative", death_mode=death_mode, theme_pack="scifi"
    )
    state.character.name = "TestHero"
    state.character.characteristics = {
        "STR": 7, "DEX": 9, "END": 6, "INT": 8, "EDU": 10, "SOC": 5,
    }
    state.character.skills = {"Gun Combat": 1, "Persuade": 0}
    state.character.career = "navy"
    state.character.terms = 2
    state.narrative_log.append("mustered_out=true")
    saves_dir.mkdir(parents=True, exist_ok=True)
    return save(state, saves_dir / f"{name}.json")
```

- [ ] **Step 3b: Confirm the ChargenSession properties exist**

`ChargenSession.phase` and `ChargenSession.completed` were added in Task 7 (Step 4d) — the registry's `promote` and this task's `_session_payload` consume them. Verify with `uv run python -c "from src.game.chargen.api import ChargenSession; print(ChargenSession.phase, ChargenSession.completed)"`. If Task 7 landed without them, add them now (the code is in Task 7, Step 4d).

- [ ] **Step 3c: Registry save-existence pre-checks**

In `src/server/sessions.py`, replace `create_adventure` and `resume`'s path handling:

```python
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
```

(The old `create_adventure` loaded only the main path; preferring the autosave keeps resume semantics identical for both entry points.)

- [ ] **Step 3d: routes_sessions.py (full replacement of the stub)**

```python
"""Session gameplay endpoints (M0.6b, spec §5).

Every mutation endpoint follows the same pipeline: gate (one in-flight
beat per session) → session contract → engine funnel → autosave → response
carrying the structured new events (the client's roll readouts render from
these, never from parsed text — spec D5).

``/narrate`` is the NDJSON stream. All mutations (steering record, shipped
prose record, autosave, watermarks) happen BEFORE streaming starts: the
trust boundary made temporal.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from src.engine.commands import (
    RecordNarrationCommand,
    RecordStoryDirectionCommand,
    SetCharacterNameCommand,
)
from src.engine.lifepath_choices import ChoiceOptionView, ChoicePointView
from src.game.adventure_session import CONTRACT_VERSION as ADVENTURE_CONTRACT
from src.game.advice import record_advice
from src.game.beats import build_beat_facts, narrator_memory
from src.game.change_lines import derive_recent_change_lines
from src.game.chargen.api import CONTRACT_VERSION as CHARGEN_CONTRACT
from src.llm.adapter import LLMAdapter, NarrationResult
from src.llm.status import STATUS_CONNECTION_LOST, STATUS_NARRATION_UNAVAILABLE
from src.server.errors import ActionInFlightError, ApiError
from src.server.models import (
    ChooseRequest,
    CreateSessionRequest,
    FreetextRequest,
    NameRequest,
    NarrateRequest,
)
from src.server.sessions import SessionRecord
from src.themepacks import get_pack

router = APIRouter(prefix="/v1/sessions")


# ---------------------------------------------------------------------------
# Envelope helpers.
# ---------------------------------------------------------------------------


def _session_payload(record: SessionRecord) -> dict:
    """The SessionEnvelope — everything the client needs to render."""
    if record.kind == "chargen":
        session = record.chargen
        contract = CHARGEN_CONTRACT
        if session.completed:
            phase, view = "complete", None
        else:
            phase = session.phase
            view = session.current_choice().model_dump(mode="json")
    else:
        contract = ADVENTURE_CONTRACT
        adv_view = record.adventure.current_view()
        phase = adv_view.phase
        view = dataclasses.asdict(adv_view)
    return {
        "id": record.id,
        "name": record.name,
        "kind": record.kind,
        "phase": phase,
        "view": view,
        "contract_version": contract,
    }


def _summary(record: SessionRecord) -> dict:
    return {"id": record.id, "name": record.name, "kind": record.kind}


def _record(request: Request, session_id: str) -> SessionRecord:
    return request.app.state.registry.get(session_id)


def _new_events_since(record: SessionRecord, start: int) -> list[dict]:
    return [
        e.model_dump(mode="json") for e in record.game.state.events[start:]
    ]


# ---------------------------------------------------------------------------
# Session CRUD.
# ---------------------------------------------------------------------------


@router.post("", status_code=201)
async def create_session(req: CreateSessionRequest, request: Request) -> dict:
    registry = request.app.state.registry
    if req.from_save is not None:
        # Opening a save: kind is inferred from where the story is.
        record = registry.resume(name=req.from_save)
    elif req.kind == "chargen":
        record = registry.create_chargen(
            name=req.name,
            seed=req.seed,
            pack_id=req.pack_id,
            profile=req.profile,
            death_mode=req.death_mode,
        )
    else:
        raise ApiError(
            422,
            "invalid_config",
            "Adventure sessions start from a completed chargen — "
            "promote a chargen session or open a save (from_save).",
        )
    return {"session": _session_payload(record)}


@router.get("")
async def list_sessions(request: Request) -> dict:
    return {"sessions": [_summary(r) for r in request.app.state.registry.list()]}


@router.get("/{session_id}")
async def get_session(session_id: str, request: Request) -> dict:
    return {"session": _session_payload(_record(request, session_id))}


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str, request: Request) -> None:
    request.app.state.registry.delete(session_id)


# ---------------------------------------------------------------------------
# Mutations.
# ---------------------------------------------------------------------------


@router.post("/{session_id}/choose")
async def choose(session_id: str, req: ChooseRequest, request: Request) -> dict:
    record = _record(request, session_id)
    if not record.game.begin_action():
        raise ActionInFlightError("A beat is already in flight for this session")
    try:
        before = len(record.game.state.events)
        if record.kind == "chargen":
            result = record.chargen.choose(req.option_id, origin=req.origin)
        else:
            result = record.adventure.choose(req.option_id)
        request.app.state.registry.autosave(record)
        return {
            "session": _session_payload(record),
            "result": result.model_dump(mode="json"),
            "events": _new_events_since(record, before),
        }
    finally:
        record.game.end_action()


@router.post("/{session_id}/freetext")
async def freetext(session_id: str, req: FreetextRequest, request: Request) -> dict:
    record = _record(request, session_id)
    if not record.game.begin_action():
        raise ActionInFlightError("A beat is already in flight for this session")
    try:
        before = len(record.game.state.events)
        if record.kind == "chargen":
            if request.app.state.translator is None:
                raise ApiError(
                    422,
                    "translator_unavailable",
                    "No translator configured — set the narrator model in Settings",
                )
            translation = await record.chargen.propose(req.text)
            request.app.state.registry.autosave(record)
            return {
                "session": _session_payload(record),
                "record": translation.model_dump(mode="json"),
                "events": _new_events_since(record, before),
            }
        # Adventure: classify is sync + blocking (KTD-9) — threadpool it.
        result = await run_in_threadpool(record.adventure.submit_freetext, req.text)
        request.app.state.registry.autosave(record)
        return {
            "session": _session_payload(record),
            "result": result.model_dump(mode="json"),
            "events": _new_events_since(record, before),
        }
    finally:
        record.game.end_action()


@router.post("/{session_id}/suggest")
async def suggest(session_id: str, request: Request) -> dict:
    record = _record(request, session_id)
    advisor = request.app.state.advisor
    if advisor is None:
        raise ApiError(
            422,
            "advisor_unavailable",
            "No advisor configured — set the narrator model in Settings",
        )
    if not record.game.begin_action():
        raise ActionInFlightError("A beat is already in flight for this session")
    try:
        if record.kind == "chargen":
            suggestion = await record.chargen.suggest()  # records internally
        else:
            view = record.adventure.current_view()
            choice = ChoicePointView(
                choice_id=f"adventure_{view.phase}",
                phase=view.phase,
                prompt=view.prompt or "Choose your action:",
                options=[
                    ChoiceOptionView(
                        option_id=c.option_id,
                        label=c.label,
                        description=c.description,
                        odds_line=c.description or None,
                        dimmed=c.dimmed,
                        requirement=c.requirement or None,
                    )
                    for c in view.choices
                ],
                allows_advisor=True,
                allows_freetext=True,
            )
            rules_summary = view.scaffold_text or "\n".join(view.odds_lines) or "Scene options."
            suggestion = await advisor.suggest(choice, rules_summary)
            if suggestion is not None:
                record_advice(record.game.engine, suggestion)
        if suggestion is not None:
            request.app.state.registry.autosave(record)
        return {"record": suggestion.model_dump(mode="json") if suggestion else None}
    finally:
        record.game.end_action()


@router.post("/{session_id}/name")
async def set_name(session_id: str, req: NameRequest, request: Request) -> dict:
    record = _record(request, session_id)
    if not record.game.begin_action():
        raise ActionInFlightError("A beat is already in flight for this session")
    try:
        record.game.engine.apply(SetCharacterNameCommand(name=req.name))
        request.app.state.registry.autosave(record)
        return {"session": _session_payload(record)}
    finally:
        record.game.end_action()


@router.post("/{session_id}/promote")
async def promote(session_id: str, request: Request) -> dict:
    record = request.app.state.registry.promote(session_id)
    return {"session": _session_payload(record)}


# ---------------------------------------------------------------------------
# Narration stream (NDJSON).
# ---------------------------------------------------------------------------


def _sentences(prose: str) -> list[str]:
    """Split prose into typewriter chunks on sentence-ending punctuation."""
    chunks: list[str] = []
    current = ""
    for char in prose.strip():
        current += char
        if char in ".!?":
            stripped = current.strip()
            if stripped:
                chunks.append(stripped)
            current = ""
    if current.strip():
        chunks.append(current.strip())
    return chunks or ([prose.strip()] if prose.strip() else [])


def _ndjson(block_type: str, content: str) -> str:
    return json.dumps({"type": block_type, "content": content}) + "\n"


@router.post("/{session_id}/narrate")
async def narrate(session_id: str, req: NarrateRequest, request: Request):
    """Stream one narration beat as NDJSON blocks (M0.4/M0.5, spec §3/§5).

    Beat kinds: ``world_intro`` (ceremony; replays its record without
    re-calling the LLM unless steered), ``scene`` / ``chargen_beat`` /
    ``chargen_close`` (facts from the events since the last beat; steering
    re-tells the SAME beat — the past is written, the present can be
    re-told, the future is steered).
    """
    record = _record(request, session_id)
    if not record.game.begin_action():
        raise ActionInFlightError("A beat is already in flight for this session")
    try:
        registry = request.app.state.registry
        engine = record.game.engine
        state = engine.state

        # 1. Beat span: new events, or the last beat's span for a re-tell.
        if record.last_narrated_seq < len(state.events):
            span = (record.last_narrated_seq, len(state.events))
        else:
            span = (record.last_beat_start, record.last_narrated_seq)

        # 2. Steering lands FIRST — it conditions this telling and the next.
        steering = req.steering.strip()
        if steering:
            engine.apply(RecordStoryDirectionCommand(text=steering, beat=req.beat))

        # 3. Facts + memory + curated view (engine-owned; the LLM sees only these).
        facts = build_beat_facts(state.events[span[0] : span[1]])
        memory = narrator_memory(state.events)
        adapter = request.app.state.adapter or LLMAdapter()  # template when unconfigured
        from src.llm.state_view import build_curated_view

        view = build_curated_view(state)

        # 4. Prose — world intro replays its record; everything else narrates.
        if req.beat == "world_intro":
            existing = [
                e
                for e in state.events
                if e.command_type == "record_narration"
                and e.changes.get("beat") == "world_intro"
            ]
            if existing and not steering:
                prose = existing[-1].changes["text"]
                result = NarrationResult(
                    prose=prose, source=existing[-1].changes.get("source", "template")
                )
            else:
                pack = get_pack(state.campaign.theme_pack)
                result = await adapter.narrate_world_intro(
                    view,
                    pack_name=pack.name,
                    pack_intro=pack.intro_text,
                    state=state,
                )
        else:
            result = await adapter.narrate_beat(
                view,
                facts,
                state=state,
                steering_text=steering,
                prior_prose=memory.prose,
                directions=memory.directions,
            )

        # 5. Shipped prose is canonical BEFORE the client sees a word.
        engine.apply(
            RecordNarrationCommand(text=result.prose, beat=req.beat, source=result.source)
        )
        registry.autosave(record)
        record.last_beat_start = span[0]
        record.last_narrated_seq = len(state.events)

        # 6. Stream: narration sentences → change lines → degradation badge → done.
        change_lines = derive_recent_change_lines(state.events, since_seq=span[0] - 1)
        badge = None
        if result.llm_failed:
            badge = (
                STATUS_CONNECTION_LOST
                if result.failure_kind == "provider_error"
                else STATUS_NARRATION_UNAVAILABLE
            )

        async def _stream() -> AsyncIterator[str]:
            for sentence in _sentences(result.prose):
                yield _ndjson("narration", sentence)
            for line in change_lines:
                yield _ndjson("change", line.text)
            if badge is not None:
                yield _ndjson("badge", badge)
            yield _ndjson("done", "")

        return StreamingResponse(_stream(), media_type="application/x-ndjson")
    finally:
        record.game.end_action()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/server/ -q`
Expected: PASS. Two likely adjustments:
- If `test_world_intro_template_streams_blocks` finds no "frontier", the pack intro YAML from Task 4 didn't land at the manifest top level — check `pack.intro_text` in a REPL (`uv run python -c "from src.themepacks import get_pack; print(get_pack('scifi').intro_text)"`).
- If the scene beat's `_sentences` chunking splits "…Pad 9." oddly, that's cosmetic — assertions only check block types.

- [ ] **Step 5: Full gate + commit**

```bash
uv run ruff check src tests && uv run ruff format src tests && uv run pytest tests/ -q
git add src/server/sessions.py src/server/routes_sessions.py tests/server/
git commit -m "feat(server): session gameplay routes + NDJSON narration stream (M0.6b)"
```

---

## Task 9: M0.6c (part 1) — Saves + settings routes

**Files:**
- Modify: `src/server/routes_saves.py` (replace stub)
- Modify: `src/server/routes_settings.py` (replace stub)
- Modify: `src/game/session.py` (add `retarget` method — manual save retargets the autosave path)
- Modify: `src/server/sessions.py` (`save_manual` retargets the GameSession)
- Test: `tests/server/test_saves.py`, `tests/server/test_settings.py` (new)

**Interfaces:**
- Consumes: `discover_saves`/`resolve_save_path`/`safe_save_name` (`src/game/saves.py`), `persistence.save`/`load`/`migrate`, `fetch_available_models` (`src/llm/providers.py:139`), Task 6 settings helpers (`resolve_api_key`, `delete_api_key`, `masked_key_tail`).
- Produces:
  - `GET /v1/saves` → `{"saves": [{name, base_name, autosave, theme_pack, character_name, terms, career, alive, mtime}]}`
  - `POST /v1/sessions/{id}/save {name}` → `{"session": ...}` (writes `{name}.json` + sidecar; retargets autosave base)
  - `DELETE /v1/saves/{name}` → `{"deleted": [filenames]}` (main + autosave + both sidecars)
  - `POST /v1/saves/{name}/duplicate {new_name}` → 201 `{"saves": [created filenames]}`
  - `GET /v1/saves/{name}/export` → the save JSON document (main preferred, autosave fallback)
  - `POST /v1/saves/import {name, document}` → 201 `{"name": ...}`; invalid document → 422 `invalid_save`
  - `GET /v1/settings/llm` → `{provider, model, base_url, max_retries, is_configured, key_backend, key_tail}`
  - `PUT /v1/settings/llm` → same shape (key via store; `api_key: null` keeps the stored key; `api_key: ""` deletes it)
  - `POST /v1/settings/llm/test` → `{"ok": bool, "models": [...]}` or `{"ok": false, "error": str}` — never raises

- [ ] **Step 1: Write the failing tests**

Create `tests/server/test_saves.py`:

```python
"""Save endpoint contract tests (M0.6c)."""

from __future__ import annotations

from tests.server.conftest import write_save


def _create(client, name="The Ruuth Run"):
    resp = client.post(
        "/v1/sessions", json={"kind": "chargen", "name": name, "seed": 42, "pack_id": "scifi"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["session"]


class TestListSaves:
    def test_autosave_flagged_with_base_name(self, client, tmp_path):
        _create(client)
        saves = client.get("/v1/saves").json()["saves"]
        auto = next(s for s in saves if s["autosave"])
        assert auto["base_name"] == "The_Ruuth_Run"
        assert auto["theme_pack"] == "scifi"

    def test_empty_when_no_saves(self, client):
        assert client.get("/v1/saves").json()["saves"] == []


class TestManualSave:
    def test_save_writes_main_file_and_retargets(self, client, tmp_path):
        session = _create(client)
        resp = client.post(f"/v1/sessions/{session['id']}/save", json={"name": "Mara Voss"})
        assert resp.status_code == 200, resp.text
        assert (tmp_path / "saves" / "Mara_Voss.json").exists()
        # Subsequent beats autosave under the new name.
        client.post(f"/v1/sessions/{session['id']}/choose", json={"option_id": "roll_pool"})
        assert (tmp_path / "saves" / "Mara_Voss.autosave.json").exists()


class TestDuplicateDeleteExportImport:
    def test_duplicate(self, client, tmp_path):
        write_save(tmp_path / "saves", "Mara")
        resp = client.post("/v1/saves/Mara/duplicate", json={"new_name": "Mara Copy"})
        assert resp.status_code == 201, resp.text
        assert (tmp_path / "saves" / "Mara_Copy.json").exists()

    def test_delete_removes_main_autosave_and_sidecars(self, client, tmp_path):
        write_save(tmp_path / "saves", "Mara")
        write_save(tmp_path / "saves", "Mara.autosave")
        resp = client.delete("/v1/saves/Mara")
        assert resp.status_code == 200
        assert not list((tmp_path / "saves").glob("Mara*"))

    def test_export_returns_document(self, client, tmp_path):
        write_save(tmp_path / "saves", "Mara")
        resp = client.get("/v1/saves/Mara/export")
        assert resp.status_code == 200
        assert resp.json()["character"]["name"] == "TestHero"

    def test_import_round_trip(self, client, tmp_path):
        write_save(tmp_path / "saves", "Mara")
        document = client.get("/v1/saves/Mara/export").json()
        resp = client.post(
            "/v1/saves/import", json={"name": "Imported", "document": document}
        )
        assert resp.status_code == 201, resp.text
        assert (tmp_path / "saves" / "Imported.json").exists()

    def test_import_invalid_document_is_422(self, client):
        resp = client.post(
            "/v1/saves/import", json={"name": "Bad", "document": {"not": "a save"}}
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "invalid_save"

    def test_path_traversal_rejected(self, client):
        resp = client.get("/v1/saves/..%2F..%2Fetc/export")
        assert resp.status_code in (404, 422)
```

Create `tests/server/test_settings.py`:

```python
"""Settings endpoint contract tests (M0.6c + M0.7)."""

from __future__ import annotations

import json


class TestGetSettings:
    def test_defaults(self, client):
        body = client.get("/v1/settings/llm").json()
        assert body["provider"] == "anthropic"
        assert body["is_configured"] is False
        assert body["key_tail"] == ""
        assert body["key_backend"] in ("", "file", "keyring")


class TestPutSettings:
    def test_put_stores_key_outside_the_file(self, client, tmp_path):
        resp = client.put(
            "/v1/settings/llm",
            json={
                "provider": "anthropic",
                "model": "claude-sonnet-5",
                "api_key": "sk-ant-testkey99",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["is_configured"] is True
        assert body["key_tail"] == "…ey99"
        assert body["key_backend"] in ("file", "keyring")
        # The settings file on disk never contains the key (M0.7).
        raw = json.loads((tmp_path / "settings" / "llm.json").read_text())
        assert not raw.get("api_key")
        # And the response never echoes the key.
        assert "sk-ant-testkey99" not in resp.text

    def test_put_without_key_keeps_stored_key(self, client):
        client.put(
            "/v1/settings/llm",
            json={"provider": "anthropic", "model": "m", "api_key": "sk-keepme1"},
        )
        body = client.put(
            "/v1/settings/llm", json={"provider": "anthropic", "model": "m2"}
        ).json()
        assert body["key_tail"] == "…pme1"

    def test_put_empty_key_deletes(self, client):
        client.put(
            "/v1/settings/llm",
            json={"provider": "anthropic", "model": "m", "api_key": "sk-deleteme1"},
        )
        body = client.put(
            "/v1/settings/llm", json={"provider": "anthropic", "model": "m", "api_key": ""}
        ).json()
        assert body["key_tail"] == ""
        assert body["is_configured"] is False

    def test_bad_base_url_is_422(self, client):
        resp = client.put("/v1/settings/llm", json={"base_url": "ftp://nope"})
        assert resp.status_code == 422


class TestTestEndpoint:
    def test_no_key_returns_ok_false(self, client):
        body = client.post("/v1/settings/llm/test").json()
        assert body["ok"] is False
        assert body["error"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/server/test_saves.py tests/server/test_settings.py -q`
Expected: FAIL — 404/405 on every route (stubs).

- [ ] **Step 3a: `GameSession.retarget` + registry wiring**

In `src/game/session.py`, after the `save` method (~line 178), add:

```python
    def retarget(self, save_path: Path) -> None:
        """Point the session's autosave at a new path (M0.6 manual save).

        Resets stale-write detection against the new location (the file may
        not exist yet — a ``None`` hash disables the next check, same as a
        fresh session). The checkpoint manager and its in-memory snapshot
        are untouched.
        """
        self._save_path = Path(save_path)
        self._last_write_hash = self._compute_disk_hash()
```

In `src/server/sessions.py`, replace `save_manual`'s tail (`record.name = name`) so the autosave follows the new name:

```python
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
```

- [ ] **Step 3b: routes_saves.py (full replacement)**

```python
"""Save management endpoints (M0.6c, spec §5).

Files per chronicle: ``{name}.json`` (last manual save), ``{name}.autosave.json``
(live beat autosave), and ``*.checkpoint.json`` sidecars. Path safety goes
through :func:`resolve_save_path` (traversal-proof).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi import APIRouter, Request

from src.engine.persistence import migrate, save
from src.engine.state import GameState
from src.game.saves import discover_saves, resolve_save_path
from src.server.errors import ApiError
from src.server.models import DuplicateSaveRequest, ImportSaveRequest, SaveRequest
from src.server.routes_sessions import _record, _session_payload
from src.server.sessions import AUTOSAVE_SUFFIX

router = APIRouter(prefix="/v1")


def _files_for(saves_dir: Path, name: str) -> list[Path]:
    """All files belonging to a chronicle: main, autosave, and sidecars."""
    base = resolve_save_path(saves_dir, name)
    auto = base.with_name(base.stem + AUTOSAVE_SUFFIX + base.suffix)
    candidates = [base, auto]
    files = [p for p in candidates if p.exists()]
    files += [Path(str(p) + ".checkpoint.json") for p in candidates if Path(str(p) + ".checkpoint.json").exists()]
    return files


@router.get("/saves")
async def list_saves(request: Request) -> dict:
    saves = []
    for info in discover_saves(request.app.state.saves_dir):
        autosave = info.name.endswith(AUTOSAVE_SUFFIX)
        base_name = info.name[: -len(AUTOSAVE_SUFFIX)] if autosave else info.name
        saves.append(
            {
                "name": info.name,
                "base_name": base_name,
                "autosave": autosave,
                "theme_pack": info.theme_pack,
                "character_name": info.character_name,
                "terms": info.terms,
                "career": info.career,
                "alive": info.alive,
                "mtime": info.mtime,
            }
        )
    return {"saves": saves}


@router.post("/sessions/{session_id}/save")
async def save_session(session_id: str, req: SaveRequest, request: Request) -> dict:
    """Manual save: write ``{name}.json`` + sidecar; retarget autosave base."""
    record = _record(request, session_id)
    request.app.state.registry.save_manual(record, req.name)
    return {"session": _session_payload(record)}


@router.delete("/saves/{name}")
async def delete_save(name: str, request: Request) -> dict:
    files = _files_for(request.app.state.saves_dir, name)
    if not files:
        raise ApiError(404, "save_not_found", f"No save named '{name}'")
    deleted = [p.name for p in files]
    for path in files:
        path.unlink()
    return {"deleted": deleted}


@router.post("/saves/{name}/duplicate", status_code=201)
async def duplicate_save(name: str, req: DuplicateSaveRequest, request: Request) -> dict:
    saves_dir = request.app.state.saves_dir
    files = _files_for(saves_dir, name)
    if not files:
        raise ApiError(404, "save_not_found", f"No save named '{name}'")
    target_base = resolve_save_path(saves_dir, req.new_name)
    if target_base.exists():
        raise ApiError(409, "save_conflict", f"A save named '{req.new_name}' already exists")
    created: list[str] = []
    for path in files:
        # Rename the base portion, preserving .autosave/.checkpoint suffixes.
        suffix_tail = path.name[len(resolve_save_path(saves_dir, name).stem):]
        target = target_base.with_name(target_base.stem + suffix_tail)
        shutil.copy2(path, target)
        created.append(target.name)
    return {"created": created}


@router.get("/saves/{name}/export")
async def export_save(name: str, request: Request) -> dict:
    files = _files_for(request.app.state.saves_dir, name)
    if not files:
        raise ApiError(404, "save_not_found", f"No save named '{name}'")
    # Prefer the main document; fall back to the autosave.
    main = resolve_save_path(request.app.state.saves_dir, name)
    source = main if main.exists() else files[0]
    return json.loads(source.read_text(encoding="utf-8"))


@router.post("/saves/import", status_code=201)
async def import_save(req: ImportSaveRequest, request: Request) -> dict:
    try:
        data = migrate(dict(req.document), from_version=int(req.document.get("save_version", 1)))
        state = GameState.model_validate(data)
    except Exception as exc:
        raise ApiError(422, "invalid_save", f"Not a valid save document: {exc}") from exc
    target = resolve_save_path(request.app.state.saves_dir, req.name)
    if target.exists():
        raise ApiError(409, "save_conflict", f"A save named '{req.name}' already exists")
    save(state, target)
    return {"name": target.stem}
```

- [ ] **Step 3c: routes_settings.py (full replacement)**

```python
"""LLM settings endpoints (M0.6c + M0.7, spec §5/D7).

The API key moves through the key store only: PUT accepts it, stores it,
and never echoes it back; GET reports the masked tail and the backend.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from src.llm.providers import fetch_available_models
from src.llm.settings import (
    LLMSettings,
    delete_api_key,
    masked_key_tail,
    resolve_api_key,
    save_settings,
)
from src.server.models import LlmSettingsRequest

router = APIRouter(prefix="/v1/settings")


def _payload(request: Request) -> dict:
    settings: LLMSettings = request.app.state.settings
    settings_dir = request.app.state.settings_dir
    return {
        "provider": settings.provider,
        "model": settings.model,
        "base_url": settings.base_url,
        "max_retries": settings.max_retries,
        "is_configured": settings.is_configured,
        "key_backend": settings.key_backend,
        "key_tail": masked_key_tail(settings, settings_dir),
    }


def _rebuild_llm_trio(request: Request) -> None:
    """Rebuild adapter/advisor/translator after a settings change.

    Live sessions keep the trio they were constructed with (their session
    contracts captured the references); sessions created or resumed after
    the change get the new one.
    """
    from src.llm.adapter import AdapterConfig
    from src.llm.advisor import Advisor, AdvisorConfig
    from src.llm.settings import create_llm_adapter
    from src.llm.translator import Translator

    settings: LLMSettings = request.app.state.settings
    request.app.state.adapter = create_llm_adapter(settings)
    if settings.is_configured:
        request.app.state.advisor = Advisor(AdvisorConfig(model=settings.model_string))
        request.app.state.translator = Translator(AdapterConfig(model=settings.model_string))
    else:
        request.app.state.advisor = None
        request.app.state.translator = None
    registry = request.app.state.registry
    registry.adapter = request.app.state.adapter
    registry.advisor = request.app.state.advisor
    registry.translator = request.app.state.translator


@router.get("/llm")
async def get_llm_settings(request: Request) -> dict:
    return _payload(request)


@router.put("/llm")
async def put_llm_settings(req: LlmSettingsRequest, request: Request) -> dict:
    settings_dir = request.app.state.settings_dir
    current: LLMSettings = request.app.state.settings
    updated = LLMSettings(
        provider=req.provider,
        model=req.model,
        base_url=req.base_url,  # pydantic validator rejects non-http(s)
        max_retries=req.max_retries,
        key_backend=current.key_backend,
    )
    if req.api_key is None:
        # Keep the stored key; carry it at runtime so save can re-affirm it.
        updated.api_key = resolve_api_key(current, settings_dir)
    elif req.api_key == "":
        current.api_key = resolve_api_key(current, settings_dir)
        delete_api_key(current, settings_dir)
        updated.key_backend = ""
    else:
        updated.api_key = req.api_key
    save_settings(updated, settings_dir)
    request.app.state.settings = updated
    _rebuild_llm_trio(request)
    return _payload(request)


@router.post("/llm/test")
async def test_llm_settings(request: Request) -> dict:
    """Live connectivity test — never raises; the client renders the error."""
    settings: LLMSettings = request.app.state.settings
    api_key = resolve_api_key(settings, request.app.state.settings_dir)
    if not api_key:
        return {"ok": False, "error": "No API key stored"}
    try:
        models = await fetch_available_models(
            settings.provider, api_key, settings.base_url or None
        )
        return {"ok": True, "models": models}
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/server/ -q`
Expected: PASS. Calibration note: `test_put_stores_key_outside_the_file` asserts `key_tail == "…ey99"` because the stored key is the literal `"sk-ant-testkey99"` — `masked_tail` keeps the last four characters and prefixes `…`.

- [ ] **Step 5: Full gate + commit**

```bash
uv run ruff check src tests && uv run ruff format src tests && uv run pytest tests/ -q
git add src/game/session.py src/server/sessions.py src/server/routes_saves.py src/server/routes_settings.py tests/server/test_saves.py tests/server/test_settings.py tests/server/conftest.py
git commit -m "feat(server): saves + settings routes with keyring-backed key handling (M0.6c)"
```

---

## Task 10: M0.6c (part 2) — Introspection routes + autosave/stale-write contract tests

**Files:**
- Modify: `src/server/routes_inspect.py` (replace stub)
- Test: `tests/server/test_inspect.py`, `tests/server/test_persistence_contract.py` (new)

**Interfaces:**
- Consumes: `build_audit_view`/`filter_from_params` (`src/game/audit_view.py`), `build_recap` (`src/game/recap.py:157`), `build_memorial`/`build_obituary` (`src/game/memorial.py`), `compute_check_odds`/`format_odds_line` (`src/engine/odds.py`), `build_curated_view`/`build_curated_view_for_scene`/`PROHIBITED_KEYS` (`src/llm/state_view.py`), `CepheusRuleSet.characteristic_dm`, `skill_display_name` (`src/engine/skills.py`).
- Produces (all under `/v1/sessions/{id}`):
  - `GET /sheet` → `{"character": <full dump>, "characteristic_dms": {STR: int, ...}, "skill_names": {id: display}}`
  - `GET /recap` → `{"lines": [...], "source": "template"|"llm"}`
  - `GET /memorial` → `{"data": <MemorialData dict>, "obituary": [lines]}`
  - `GET /audit?kind=&stream=&since=&page=&per_page=` → `<AuditView dict>` (`since` maps to `seq_min`)
  - `GET /llm-context` → `{"view": <CuratedView dict>, "never_includes": [...], "note": str}`
  - `POST /odds {skill, characteristic, difficulty}` → `<CheckOdds dict> + {"odds_line": str}`
  - `GET /hash` → `{"sha256": str}`
  - `POST /verify` → 501 `not_implemented`

- [ ] **Step 1: Write the failing tests**

Create `tests/server/test_inspect.py`:

```python
"""Introspection endpoint contract tests (M0.6c)."""

from __future__ import annotations

from tests.server.conftest import write_save


def _create(client, name="The Ruuth Run"):
    resp = client.post(
        "/v1/sessions", json={"kind": "chargen", "name": name, "seed": 42, "pack_id": "scifi"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["session"]


class TestSheet:
    def test_sheet_carries_dms_and_display_names(self, client, tmp_path):
        write_save(tmp_path / "saves", "Mara")
        session = client.post(
            "/v1/sessions", json={"kind": "adventure", "name": "x", "from_save": "Mara"}
        ).json()["session"]
        body = client.get(f"/v1/sessions/{session['id']}/sheet").json()
        assert body["character"]["name"] == "TestHero"
        assert set(body["characteristic_dms"]) == {"STR", "DEX", "END", "INT", "EDU", "SOC"}
        assert body["characteristic_dms"]["DEX"] == 1  # DEX 9 → DM +1
        assert "Gun Combat" in body["skill_names"]


class TestRecap:
    def test_recap_shape(self, client):
        session = _create(client)
        body = client.get(f"/v1/sessions/{session['id']}/recap").json()
        assert body["source"] == "template"
        assert isinstance(body["lines"], list)


class TestAudit:
    def test_audit_rows_and_filters(self, client):
        session = _create(client)
        client.post(f"/v1/sessions/{session['id']}/choose", json={"option_id": "roll_pool"})
        body = client.get(f"/v1/sessions/{session['id']}/audit").json()
        assert body["total_events"] > 0
        roll_rows = [r for r in body["rows"] if r["kind"] == "roll"]
        assert roll_rows and roll_rows[0]["stream"] == "lifepath"
        # Stream filter.
        filtered = client.get(
            f"/v1/sessions/{session['id']}/audit", params={"stream": "oracle"}
        ).json()
        assert all(r["stream"] == "oracle" for r in filtered["rows"] if r["kind"] == "roll")

    def test_since_filter(self, client):
        session = _create(client)
        client.post(f"/v1/sessions/{session['id']}/choose", json={"option_id": "roll_pool"})
        total = client.get(f"/v1/sessions/{session['id']}/audit").json()["total_events"]
        # seq is 0-based and assigned at append time, so `since = total - 1`
        # matches exactly the last event.
        filtered = client.get(
            f"/v1/sessions/{session['id']}/audit", params={"since": total - 1}
        ).json()
        assert filtered["filtered_count"] == 1


class TestLlmContext:
    def test_no_prohibited_keys(self, client):
        session = _create(client)
        client.post(f"/v1/sessions/{session['id']}/choose", json={"option_id": "roll_pool"})
        body = client.get(f"/v1/sessions/{session['id']}/llm-context").json()
        assert "view" in body and "never_includes" in body
        import json

        raw = json.dumps(body["view"])
        for key in ("roll", "rolls", "rng", "seed", "events", "stream"):
            assert f'"{key}"' not in raw


class TestOdds:
    def test_narrative_profile_tiers(self, client, tmp_path):
        write_save(tmp_path / "saves", "Mara")
        resp = client.post(
            "/v1/sessions",
            json={"kind": "adventure", "name": "x", "from_save": "Mara"},
        )
        session = resp.json()["session"]
        body = client.post(
            f"/v1/sessions/{session['id']}/odds",
            json={"skill": "Gun Combat", "characteristic": "DEX", "difficulty": "average"},
        ).json()
        assert body["profile"] == "narrative"
        assert body["strong_hit_probability"] is not None
        assert body["odds_line"]
        total = body["strong_hit_probability"] + body["weak_hit_probability"] + body["miss_probability"]
        assert abs(total - 1.0) < 1e-9


class TestHash:
    def test_hash_stable_then_changes(self, client):
        session = _create(client)
        first = client.get(f"/v1/sessions/{session['id']}/hash").json()["sha256"]
        assert first == client.get(f"/v1/sessions/{session['id']}/hash").json()["sha256"]
        client.post(f"/v1/sessions/{session['id']}/choose", json={"option_id": "roll_pool"})
        assert client.get(f"/v1/sessions/{session['id']}/hash").json()["sha256"] != first


class TestVerify:
    def test_verify_is_501(self, client):
        session = _create(client)
        resp = client.post(f"/v1/sessions/{session['id']}/verify")
        assert resp.status_code == 501
        assert resp.json()["error"]["code"] == "not_implemented"


class TestMemorial:
    def test_memorial_for_dead_character(self, client, tmp_path):
        from src.engine.commands import Engine, SetCharacterDeadCommand
        from src.engine.persistence import load, save

        # Author a dead-character ironman save through the funnel.
        write_save(tmp_path / "saves", "Dead", death_mode="ironman")
        state = load(tmp_path / "saves" / "Dead.json")
        engine = Engine(state)
        engine.apply(SetCharacterDeadCommand(reason="a failed life-threatening check"))
        save(engine.state, tmp_path / "saves" / "Dead.json")

        dead = client.post(
            "/v1/sessions", json={"kind": "adventure", "name": "y", "from_save": "Dead"}
        ).json()["session"]
        assert dead["phase"] == "game_over"
        body = client.get(f"/v1/sessions/{dead['id']}/memorial").json()
        assert body["data"]["character_name"] == "TestHero"
        assert any("In memoriam" in line for line in body["obituary"])
```

Create `tests/server/test_persistence_contract.py`:

```python
"""Autosave cadence + stale-write contract tests (M0.6c, spec §5)."""

from __future__ import annotations

from tests.server.conftest import write_save


def _create(client, name="The Ruuth Run"):
    resp = client.post(
        "/v1/sessions", json={"kind": "chargen", "name": name, "seed": 42, "pack_id": "scifi"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["session"]


class TestAutosaveCadence:
    def test_every_beat_updates_the_autosave(self, client, tmp_path):
        session = _create(client)
        import json

        auto = tmp_path / "saves" / "The_Ruuth_Run.autosave.json"
        before = json.loads(auto.read_text())
        events_before = len(before["events"])

        client.post(f"/v1/sessions/{session['id']}/choose", json={"option_id": "roll_pool"})

        after = json.loads(auto.read_text())
        assert len(after["events"]) > events_before

    def test_checkpoint_mode_writes_sidecar(self, client, tmp_path):
        write_save(tmp_path / "saves", "Mara", death_mode="checkpoint")
        session = client.post(
            "/v1/sessions",
            json={"kind": "adventure", "name": "x", "from_save": "Mara"},
        ).json()["session"]
        client.post(
            f"/v1/sessions/{session['id']}/choose", json={"option_id": "accept_mission"}
        )
        # Scene start takes the snapshot; autosave persists it as sidecar.
        sidecar = tmp_path / "saves" / "Mara.autosave.json.checkpoint.json"
        assert sidecar.exists()


class TestStaleWrite:
    def test_external_modification_conflicts(self, client, tmp_path):
        # Create writes the autosave (registry.create_chargen autosaves).
        session = _create(client)
        auto = tmp_path / "saves" / "The_Ruuth_Run.autosave.json"
        # Another "session" writes to the file — the session's stored hash
        # no longer matches the disk.
        auto.write_text(auto.read_text() + "\n")

        # roll_pool is still the first (unused) choice, so the choice itself
        # is valid; the conflict must surface at autosave time, after the
        # mutation — proving stale-write detection guards every beat.
        resp = client.post(
            f"/v1/sessions/{session['id']}/choose", json={"option_id": "roll_pool"}
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "save_conflict"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/server/test_inspect.py tests/server/test_persistence_contract.py -q`
Expected: FAIL — inspect routes are stubs (404s).

- [ ] **Step 3: routes_inspect.py (full replacement)**

```python
"""Introspection endpoints (M0.6c, spec §5): sheet, recap, memorial, audit,
llm-context, odds, hash, verify.

All read-only views over canonical state. ``verify`` ships disabled — it
needs the engine replay walker (spec §12).
"""

from __future__ import annotations

import dataclasses
import hashlib

from fastapi import APIRouter, Query, Request

from src.engine.odds import compute_check_odds, format_odds_line
from src.game.audit_view import build_audit_view, filter_from_params
from src.game.memorial import build_memorial, build_obituary
from src.game.recap import build_recap
from src.llm.state_view import (
    PROHIBITED_KEYS,
    build_curated_view,
    build_curated_view_for_scene,
)
from src.rulesets.cepheus import CepheusRuleSet
from src.server.errors import ApiError
from src.server.models import OddsRequest
from src.server.routes_sessions import _record
from src.themepacks import get_pack

router = APIRouter(prefix="/v1/sessions")


@router.get("/{session_id}/sheet")
async def sheet(session_id: str, request: Request) -> dict:
    """The full character sheet + server-computed DMs (no client-side math)."""
    record = _record(request, session_id)
    state = record.game.state
    ruleset = CepheusRuleSet()
    pack = get_pack(state.campaign.theme_pack)
    from src.engine.skills import skill_display_name

    return {
        "character": state.character.model_dump(mode="json"),
        "characteristic_dms": {
            char: ruleset.characteristic_dm(value)
            for char, value in state.character.characteristics.items()
        },
        "skill_names": {
            skill_id: skill_display_name(pack, skill_id)
            for skill_id in state.character.skills
        },
    }


@router.get("/{session_id}/recap")
async def recap(session_id: str, request: Request) -> dict:
    record = _record(request, session_id)
    result = build_recap(record.game.state, adapter=request.app.state.adapter)
    return {"lines": result.lines, "source": result.source}


@router.get("/{session_id}/memorial")
async def memorial(session_id: str, request: Request) -> dict:
    record = _record(request, session_id)
    data = build_memorial(record.game.state)
    return {
        "data": dataclasses.asdict(data),
        "obituary": build_obituary(data),
    }


@router.get("/{session_id}/audit")
async def audit(
    session_id: str,
    request: Request,
    kind: str | None = Query(default=None),
    stream: str | None = Query(default=None),
    since: int | None = Query(default=None),
    page: int = Query(default=1),
    per_page: int = Query(default=50),
) -> dict:
    """The proof log: paginated, filterable event rows (spec §5)."""
    record = _record(request, session_id)
    audit_filter = filter_from_params(
        kind=kind,
        stream=stream,
        seq_min=str(since) if since is not None else None,
    )
    view = build_audit_view(
        record.game.state, audit_filter=audit_filter, page=page, per_page=per_page
    )
    return dataclasses.asdict(view)


@router.get("/{session_id}/llm-context")
async def llm_context(session_id: str, request: Request) -> dict:
    """What the narrator sees — and the never-includes strip (spec §7.12)."""
    record = _record(request, session_id)
    state = record.game.state
    if record.kind == "adventure":
        view = build_curated_view_for_scene(state, [])
    else:
        view = build_curated_view(state)
    return {
        "view": view.model_dump(mode="json"),
        "never_includes": sorted(PROHIBITED_KEYS),
        "note": "Raw rolls, RNG state, off-scene NPC stats, unoffered hooks, and full event history never leave the server.",
    }


@router.post("/{session_id}/odds")
async def odds(session_id: str, req: OddsRequest, request: Request) -> dict:
    """Pre-commit odds for a prospective check — no roll (spec §5)."""
    record = _record(request, session_id)
    state = record.game.state
    result = compute_check_odds(
        state.character,
        skill=req.skill,
        characteristic=req.characteristic,
        difficulty=req.difficulty,
        profile=state.campaign.resolution_profile,
    )
    return {**dataclasses.asdict(result), "odds_line": format_odds_line(result)}


@router.get("/{session_id}/hash")
async def state_hash(session_id: str, request: Request) -> dict:
    """Determinism fingerprint: sha256 of the canonical state document."""
    record = _record(request, session_id)
    digest = hashlib.sha256(record.game.state.model_dump_json().encode()).hexdigest()
    return {"sha256": digest}


@router.post("/{session_id}/verify")
async def verify(session_id: str, request: Request) -> None:
    """Replay verification — ships disabled (spec §5/§12)."""
    _record(request, session_id)  # 404s on unknown sessions, consistently
    raise ApiError(
        501,
        "not_implemented",
        "Replay verification needs the engine replay walker — it ships in a later milestone.",
    )
```

The `kind` query param is passed through to `filter_from_params` as a comma-separated string of `EventKind` values (e.g. `?kind=roll,state_change`); no `EventKind` import is needed in this module.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/server/ -q`
Expected: PASS. One calibration note: `test_since_filter` asserts `filtered_count == 1` — that is exact, not approximate: `seq` is assigned as `len(events)` at append time (0-based), so `since = total - 1` matches exactly the last appended event.

- [ ] **Step 5: Full gate + commit**

```bash
uv run ruff check src tests && uv run ruff format src tests && uv run pytest tests/ -q
git add src/server/routes_inspect.py tests/server/test_inspect.py tests/server/test_persistence_contract.py
git commit -m "feat(server): introspection routes + autosave/stale-write contracts (M0.6c)"
```

---

## Step 0 definition of done

- `uv run pytest tests/ -q` green (existing suite + all new tests).
- `uv run ruff check src tests && uv run ruff format --check src tests` clean.
- Manual smoke: `uv run python -m src.server --port 0` prints `LISTENING <port>`; `curl http://127.0.0.1:<port>/health` → `{"status":"ok",...}`; a curl-driven chargen → narrate → adventure-promotion walk works end to end; Ctrl-C leaves no orphan.
- The API surface in spec §5 is implemented except `/verify` (501 by design) and a stdio transport (deferred per D2).

## What Step 0 deliberately does NOT include

- Godot client code (M1+ — the client plan is a separate document, written after this lands, per the writing-plans scope rule).
- The `/verify` replay walker (spec §12 out of scope).
- Adventure-side `Advisor` prompt tuning (the choice-point adapter in Task 8 is mechanical; prompt quality is client-milestone polish).
- Packaging/installers (spec §12).
