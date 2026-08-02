# Andromeda

A single-player Choose Your Own Adventure RPG where a **deterministic rules engine** owns dice, state, and outcomes, and an **LLM only narrates**.

Built on Cepheus Engine (2D6 sci-fi TTRPG) mechanics — used under the Open Game License — with an original fantasy theme pack.

## Quick Start

```bash
uv sync
uv run pytest tests/ -v
```

## Play

```bash
# Terminal (TUI):
uv run andromeda

# Web shell (in development):
uv run andromeda-web
# then open http://127.0.0.1:8000
```

## Architecture

- **Engine** (`src/engine/`) — deterministic command funnel, append-only event log, seeded RNG, Pydantic state models, JSON persistence
- **Rule-sets** (`src/rulesets/`) — pluggable resolution mechanics behind a Protocol interface
- **Theme packs** (`src/themepacks/`) — YAML content data (careers, skills, oracle tables)
- **TUI** (`src/tui/`) — Textual rich terminal shell over the engine library
- **Web** (`src/web/`) — FastAPI + Jinja + htmx + SSE web shell (in development)
- **LLM** (`src/llm/`) — Pydantic AI adapter for narration with tool-call-only mutations

## Design Principle

The engine is the trust boundary. Every dice roll, state mutation, and outcome calculation runs in deterministic Python code. The LLM receives outcomes as facts and produces prose — it can never influence mechanics.

## License & Attribution

Andromeda is dual-licensed (see [`NOTICE.md`](NOTICE.md)):

- **Code, tests, and the original fantasy theme pack** — MIT ([`LICENSE`](LICENSE)).
- **Sci-fi theme pack** (`src/themepacks/data/scifi/`) — Open Game License v1.0a ([`LICENSE.OGL`](LICENSE.OGL)), as Open Game Content derived from the Cepheus Engine System Reference Document.

## Status & Trademarks

Andromeda is an independent, unofficial project. "Cepheus Engine" and "Samardan Press" are trademarks of **Jason "Flynn" Kemp**; this project is **not affiliated with or endorsed by** Jason "Flynn" Kemp or Samardan Press. Cepheus Engine SRD content is used under the OGL 1.0a.
