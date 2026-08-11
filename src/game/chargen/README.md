# Chargen Module — Headless Contract (v1)

A self-contained, UI-agnostic character creation API. Wraps the deterministic
rules engine (`src/engine`) with a clean session interface that the future
Godot client (or any UI) can drive without touching engine internals.

## Quick Start

```bash
uv run python scripts/chargen_demo.py           # interactive demo
uv run pytest tests/game/test_chargen_session.py -q  # headless tests
```

## API

| Method | Sync | Returns | Description |
|--------|------|---------|-------------|
| `create(seed, pack_id, *, death_mode, advisor, translator)` | — | `ChargenSession` | New session |
| `current_choice()` | sync | `ChoicePointView` | Current decision + enumerated options |
| `choose(option_id)` | sync | `StepResult` | Apply a selection |
| `suggest()` | async | `SuggestionRecord \| None` | Advisor recommendation (HeuristicAdvisor or LLM); `None` when unavailable |
| `propose(text)` | async | `TranslationRecord` | Free-text to candidate translation |
| `serialize()` | sync | `str` (JSON) | Versioned save envelope |
| `restore(data, *, advisor, translator)` | sync | `ChargenSession` | Resume from save |

## Provenance (A10)

Every choice carries an origin: `"player"` (default), `"advisor"`, or
`"freetext"`. Surfaced in `Event.changes["origin"]`. Replays never re-invoke
the LLM — advice/proposal records are stored as event-log payloads.

## Determinism

- Same seed + same option sequence produces an identical character.
- `serialize()` + `restore()` preserves the RNG stream byte-for-byte.
- Advisor/proposal records live in the event log and replay deterministically.

## Harness Limitations (C4/C6)

- The frozen TUI never surfaces `choose_specialization`: cascade grants queue
  in `character.pending_cascades` and the skill stays unapplied in TUI play.
  The web shell and this headless module surface the choice normally.
- Per-career muster-out (C6): the TUI's own screen machine still musters once
  at chargen end using the last career. Multi-career TUI characters differ
  from engine-correct output (earlier-career benefits never roll). Web +
  headless module are per-career correct.

## Error Model

- `ValueError`: invalid `option_id` for `choose()`.
- `RuntimeError`: `suggest()` without advisor, or `propose()` without translator.
- Engine `validate` errors: impossible action (e.g., can't afford crisis payment).

## Versioning

`CONTRACT_VERSION = 1`. Future versions bump this; `restore()` rejects
envelopes with a higher contract version.

## How a Godot Client Drives This

```gdscript
# Pseudocode — actual HTTP/SSE transport is a future module
var session = ChargenSession.create(seed=42, advisor=LLMAdvisor.new())
while not session.completed:
    var choice = session.current_choice()
    render_scene(choice)
    var selection = await player_input(choice)
    if selection == "suggest":
        var record = await session.suggest()
        show_advisor_panel(record)
    else:
        session.choose(selection)
```
