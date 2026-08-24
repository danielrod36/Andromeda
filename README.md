# Andromeda

A single-player Choose Your Own Adventure RPG where a **deterministic rules engine** owns dice, state, and outcomes, and an **LLM only narrates**.

Built on Cepheus Engine (2D6 sci-fi TTRPG) mechanics — used under the Open Game License — with an original fantasy theme pack.

## Quick Start

```bash
uv sync
uv run pytest tests/ -v

tools/get_godot.sh          # one-time: fetch the pinned Godot 4.7.1
tools/run_client_lint.sh    # gdlint + gdformat over first-party GDScript
tools/run_client_tests.sh   # gdUnit4 headless suite (golden needs a display)
```

See `CLAUDE.md` for the full toolchain (pre-push hook, CI, golden baselines).

## Status

Milestone progress (per `design/2026-08-13-game-client-design.md` §11): **M1** — engine + server contract — and **M2** — the Godot client skeleton — have shipped; Title, Chronicles, New Journey, and Settings run end-to-end against the Python sidecar. Next up: **M3**, the character-creation vertical.

## Architecture

- **Engine** (`src/engine/`) — deterministic command funnel, append-only event log, seeded RNG, Pydantic state models, JSON persistence
- **Rule-sets** (`src/rulesets/`) — pluggable resolution mechanics behind a Protocol interface
- **Theme packs** (`src/themepacks/`) — YAML content data (careers, skills, oracle tables)
- **Game controller** (`src/game/`) — headless controller layer (`LifepathController`, `GameSession`) over the engine
- **LLM** (`src/llm/`) — Pydantic AI adapter for narration with tool-call-only mutations
- **Server** (`src/server/`) — FastAPI sidecar the client spawns locally: session, saves, settings, and inspect routes plus NDJSON narration streaming; owns autosave and keyring-backed key storage
- **Client** (`client/`) — Godot 4.7.1 app; spawns the sidecar, speaks HTTP/NDJSON over 127.0.0.1, renders server view models only (the client holds zero game truth)

## Design Principle

The engine is the trust boundary. Every dice roll, state mutation, and outcome calculation runs in deterministic Python code. The LLM receives outcomes as facts and produces prose — it can never influence mechanics.

## License & Attribution

Andromeda is dual-licensed (see [`NOTICE.md`](NOTICE.md)):

- **Code, tests, and the original fantasy theme pack** — MIT ([`LICENSE`](LICENSE)).
- **Sci-fi theme pack** (`src/themepacks/data/scifi/`) — Open Game License v1.0a ([`LICENSE.OGL`](LICENSE.OGL)), as Open Game Content derived from the Cepheus Engine System Reference Document.

## Trademarks

Andromeda is an independent, unofficial project. "Cepheus Engine" and "Samardan Press" are trademarks of **Jason "Flynn" Kemp**; this project is **not affiliated with or endorsed by** Jason "Flynn" Kemp or Samardan Press. Cepheus Engine SRD content is used under the OGL 1.0a.
