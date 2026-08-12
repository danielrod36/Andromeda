# Chargen Module — Headless Contract (v1)

A self-contained, UI-agnostic character creation API. Wraps the deterministic
rules engine (`src/engine`) with a clean session interface that the future
Godot client (or any UI) can drive without touching engine internals.

## Quick Start

```bash
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
- `pending_cascades` and per-career muster-out state round-trip through
  `serialize()`/`restore()` identically (save v7).

## Phases (v1 additions)

- `choose_specialization` (C3/C4): surfaced whenever a cascade grant pends
  (`character.pending_cascades`), including mid-term, at basic training, at
  muster-out (duplicate Weapon benefit), and on re-grant with an owned
  specialization (choice every grant). Options are `spec:<skill_id>`.
- Mustering out is per-career (C6): `mustering_out`/`muster_out_allocate` run
  at every career exit, then route to `choose_career_change` unless the
  character is dead or at 7+ terms. The 3-cash-roll cap is lifetime across
  all musters.

CONTRACT_VERSION remains 1: C3/C6 add phases and state fields, but the
envelope shape and method surface are unchanged.

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
