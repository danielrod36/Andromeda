# Cepheus Adventure

A single-player Choose Your Own Adventure RPG where a **deterministic rules engine** owns dice, state, and outcomes, and an **LLM only narrates**.

Built on Cepheus Engine (2D6 sci-fi TTRPG) mechanics with an original fantasy theme pack.

## Quick Start

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -v
```

## Architecture

- **Engine** (`src/engine/`) — deterministic command funnel, append-only event log, seeded RNG, Pydantic state models, JSON persistence
- **Rule-sets** (`src/rulesets/`) — pluggable resolution mechanics behind a Protocol interface
- **Theme packs** (`src/themepacks/`) — YAML/JSON content data (careers, skills, oracle tables)
- **TUI** (`src/tui/`) — Textual rich terminal shell over the engine library
- **LLM** (`src/llm/`) — Pydantic AI adapter for narration with tool-call-only mutations

## Design Principle

The engine is the trust boundary. Every dice roll, state mutation, and outcome calculation runs in deterministic Python code. The LLM receives outcomes as facts and produces prose — it can never influence mechanics.
