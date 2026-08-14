# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Andromeda — a single-player CYOA RPG where a **deterministic rules engine** owns dice, state, and outcomes, and an **LLM only narrates**. Built on Cepheus Engine (2D6 sci-fi TTRPG) mechanics with pluggable theme packs.

## Commands

This project uses **uv** (not pip/venv directly), despite the README's pip instructions. A `uv.lock` and `.venv` are committed-ish; use `uv run` so the environment stays in sync.

```bash
uv run pytest tests/ -q              # full suite
uv run pytest tests/engine/test_dice.py -q          # one file
uv run pytest tests/engine/test_dice.py::test_name  # single test
uv run pytest -k "lifepath" -q       # by keyword
uv run pytest -m "not slow"          # skip slow markers
```

Tests run sync + async (`asyncio_mode = "auto"`); `pythonpath = ["."]` is set in pyproject, so imports are `from src.engine...`. The package is literally named `src` — pyproject's `[tool.setuptools.packages.find]` is configured for this; don't rename it without updating the setuptools config.

## Quality gate (lint + pre-push hook + CI)

```bash
uv run ruff check src tests          # lint
uv run ruff format --check src tests # format check (apply with `ruff format`)
uv run ruff check --fix src tests    # auto-fix lint errors
```

**Pre-push hook** (`.githooks/pre-push`): runs `ruff check`, `ruff format --check`, and the **full** pytest suite before a push is accepted — any failure aborts the push so broken code never reaches the remote. It's the tracked, shared hook (via `core.hooksPath`); new clones need one line: `git config core.hooksPath .githooks`. Bypass in a genuine emergency with `git push --no-verify`.

**CI** (`.github/workflows/ci.yml`): on every PR and push to `main`, runs ruff (lint + format) and the full pytest suite across Python 3.12, 3.13, and 3.14. Deps install with `uv sync --frozen`, so keep `uv.lock` committed and re-run `uv lock` after any dependency change — a stale lockfile fails CI.

### Client (Godot)

```bash
tools/get_godot.sh               # one-time: pinned Godot 4.7.1 into tools/godot/
tools/run_client_lint.sh         # gdlint + gdformat over first-party GDScript
tools/run_client_tests.sh        # gdUnit4 headless (golden suites self-skip)
ANDROMEDA_DISPLAY=1 tools/run_client_tests.sh                  # with a display: incl. golden
GOLDEN_UPDATE=1 ANDROMEDA_DISPLAY=1 tools/run_client_tests.sh  # regen golden baselines
```

The Godot project lives in `client/` (UI built in GDScript code; the only scene is `client/app/main.tscn`). GDScript changes are gated by gdlint + gdformat + gdUnit4 in the pre-push hook and CI; golden baselines compare only under a real renderer (CI's xvfb job).

## Architecture: The Engine Is the Trust Boundary

The central design principle: **the LLM can never influence mechanics.** Every dice roll, state mutation, and outcome runs in deterministic Python; the LLM receives outcomes as facts and produces prose.

### The command funnel — sole mutation path

All state changes (player actions, LLM tool calls, oracle rolls) are `Command` objects passed through `Engine.apply(cmd)`, which runs:

```
validate → resolve (dice) → mutate → append event
```

- `validate` may raise and leaves state untouched.
- `resolve` rolls dice via an injected `Roller`.
- `mutate` applies the change and returns an `Event`.
- The funnel assigns a sequence number and appends to the append-only event log.

**Never mutate `GameState` outside `Engine.apply`.** To add behavior, write a new `Command` subclass (see `src/engine/commands.py`). This is what preserves determinism, audit, and checkpoint guarantees.

### Seeded RNG streams (`src/engine/dice.py`)

One `random.Random` per subsystem (`oracle`, `lifepath`, `combat`) so rolls in one stream never shift another's sequence. State is stored as JSON-serializable `RngSnapshot`s inside `GameState` and rehydrated on load.

- Production: `LiveRoller` bound to `GameState.rng`.
- Tests: `ForcedRoller` with a FIFO queue of forced die values (`ForcedRoller([[3,5], [2,4]])`).
- **Never use module-level `random`.** Always go through a `Roller` on a named stream, so rolls are recorded and replayable.

### Rulesets and theme packs are Protocol-based plugins (`src/rulesets/base.py`)

- `RuleSet` (Protocol): the mechanical resolution system — characteristics, difficulty ladder, characteristic DMs, resolution profiles (`classic`/`narrative`), death modes, `resolve_check`. Concrete: `src/rulesets/cepheus.py`.
- `ThemePack` (Protocol): pure content data — careers, skills, oracle/complication/mission tables loaded from YAML in `src/themepacks/data/<pack>/`. Packs satisfy the Protocol by shape (no engine imports). Die tables are validated for contiguous 2D6 ranges at load time.

### LLM adapter — narration only (`src/llm/adapter.py`, `src/llm/tools.py`)

The adapter is the single integration point with the LLM (Pydantic AI). It enforces the trust boundary:

- **Structured output** — narration comes back as a `BaseModel` with only a `prose` field (no fields that could alter mechanics); invalid output triggers `ModelRetry`.
- **Curated view** — the LLM never sees full state; it gets `build_curated_view(state)`.
- **Tool-call-only mutations** — LLM tools (`src/llm/tools.py`) are thin wrappers that construct a `Command` and apply it through `Engine.apply`. The LLM never mutates state directly.
- **Template fallback** — when no LLM is configured or retries exhaust, the adapter delegates to `Narrator` (deterministic templates) and never raises.

### Persistence (`src/engine/persistence.py`)

Single JSON documents, atomic writes (temp file + `os.replace`). Schema versioning via `save_version` + a stepwise migration chain (`_MIGRATIONS`). No pickle, no SQLite.

### Game controller (`src/game/`)

Headless controller layer over the engine. `LifepathController` drives chargen phases, `GameSession` manages the adventure loop. Client surfaces (TUI, web) have been removed; the controller is the API that future client surfaces will build on. The engine package has **zero game imports** — keep it that way.

## Key Invariants (don't break these)

1. **All mutations go through `Engine.apply`.** Direct `GameState` field writes break determinism, audit, and replay.
2. **All randomness goes through a `Roller` on a named stream** — never `random` at module level.
3. **The engine has no game or LLM imports** — it's a plain sync package. The game controller and LLM adapter are clients.
4. **The LLM only narrates** — its only state influence is through tool calls that route Commands through the funnel.
5. **`GameState` must stay JSON-serializable** — every field round-trips through `model_dump_json` (note: RNG live instances are `PrivateAttr`, rebuilt from snapshots on load).

## Branches & history

Work happens on feature branches off `main`. Commits reference plan/audit codes (U1–U8 = units, R1–R24 = requirements, AE1–AE13 = acceptance/edge cases); these appear in docstrings and test names.
