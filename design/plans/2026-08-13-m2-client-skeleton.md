# M2 — Client Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Godot 4.7.1 client skeleton — sidecar lifecycle, EngineClient + StreamPump, ScreenStack, token-driven theme — with Title, Chronicles, New Journey, and Settings working end-to-end against the real Python sidecar, per `design/2026-08-13-m2-client-skeleton-design.md` (the spec) and the mocks in `design/mockups/final/`.

**Architecture:** Monorepo: a new `client/` Godot project alongside `src/`. Godot spawns the FastAPI sidecar (`uv run python -m src.server --port 0`, cwd = repo root), reads one `LISTENING <port>` line from a log-file redirect, then speaks HTTP/NDJSON over 127.0.0.1. All UI is constructed in GDScript code (no hand-authored `.tscn` layouts beyond a minimal `main.tscn`); theme comes from code-built `PackTheme` resources matching `design/mockups/final/tokens.css` byte-for-byte. The client holds zero game truth — every render comes from server view models.

**Tech Stack:** Godot 4.7.1 (GDScript 2.0, static typing), gdUnit4 v6.2.0 (tests), gdtoolkit (gdlint + gdformat) via uv, Python sidecar from Step 0 (unchanged).

**Spec:** `design/2026-08-13-m2-client-skeleton-design.md` — its §12 detail standard governs this plan: two sources of truth (the mocks and the server code), no shape guessing, no name guessing, every task ends in an executable check.

---

## Global Constraints

Every task implicitly includes these. Do not violate them; do not re-derive them.

- **Godot version:** exactly `4.7.1-stable`, downloaded by `tools/get_godot.sh` into `tools/godot/` (gitignored). Never use a system Godot.
- **GDScript style:** static typing on every variable/parameter/return; tabs for indentation (gdformat default); `class_name` on every non-autoload class; autoload scripts have **no** `class_name`. Run `uv run gdformat client/` before every commit; `uv run gdlint client/` must pass.
- **Trust boundary:** the client never mutates game state, never computes mechanics, never stores game truth between server calls. All rendering is from server payloads. (Spec §4.)
- **Copy rule:** player-facing strings come from the mocks (verbatim) or from server payloads (verbatim). Never invent copy. Cockpit-voice strings used in this plan are quoted exactly where used. (Spec §6.6 of the parent spec.)
- **Errors:** server errors arrive as `{"error":{"code","message"}}`; `EngineClient` parses them once; screens show `message` verbatim via `OverlayLayer.toast(..., "bad")`. (errors.py:32-33.)
- **Contract check:** every `SessionEnvelope` carries `contract_version`; the client compares it against the version from `/health` for that `kind` and shows the mismatch card on divergence (Task 6 pins the card).
- **Commits:** each task ends with the listed commit(s). Commit message prefixes: `feat(client):` for new capability, `test(client):`, `chore(client):`, `docs:`.
- **Quality gate (must pass at the end of every task):**
  ```bash
  uv run ruff check . && uv run ruff format --check .
  uv run pytest tests/ -q
  uv run gdlint client/
  uv run gdformat --check client/
  tools/godot/Godot_v4.7.1-stable_linux.x86_64 --headless --path client \
    -s res://addons/gdUnit4/bin/GdUnitCmdTool.gd -a res://tests -c -rd /tmp/gdunit-reports
  ```
  gdUnit4 exit codes: `0` = pass, `100` = test failures, `101` = warnings-only (accept 0 and 101). Golden suites self-skip under the headless display server (Task 11).
- **Godot binary env var:** test scripts and the pre-push hook use `GODOT_BIN` if set, else `tools/godot/Godot_v4.7.1-stable_linux.x86_64`.
- **No placeholders:** if a step here is ambiguous, the plan is broken — stop and ask; do not improvise.

---

## API Reference — inlined shapes (the zero-gap backbone)

Every payload the client touches, with the server code that defines it. Tasks cite these as `§A<n>`. Field names here are authoritative — copy them exactly.

### A1. Error envelope — `src/server/errors.py:32-33`

```json
{"error": {"code": "session_not_found", "message": "..."}}
```

Codes the client may receive (all rendered as verbatim-message toasts):

| code | HTTP | raised at |
|------|------|-----------|
| `session_not_found` | 404 | errors.py:43-45 |
| `save_not_found` | 404 | routes_saves.py:75, 110 |
| `action_in_flight` | 409 | errors.py:47-49 |
| `save_conflict` | 409 | errors.py:51-53, routes_saves.py:94, 133 |
| `bad_json` | 400 | errors.py:55-57 |
| `invalid_request` | 422 | errors.py:82-84 (pydantic validation) |
| `invalid_choice` | 422 | errors.py:63-67 |
| `invalid_config` | 422 | errors.py:59-61, routes_sessions.py:112-118 |
| `invalid_name` | 422 | routes_saves.py:89-92, 128-131 |
| `invalid_save` | 422 | routes_saves.py:113-117, 124-126 |
| `translator_unavailable` | 422 | routes_sessions.py:177-182 |
| `advisor_unavailable` | 422 | routes_sessions.py:208-213 |
| `not_implemented` | 501 | routes_inspect.py:140-144 |
| `not_found` | 404 | errors.py:71-74 (unknown endpoint) |
| `http_error` | * | errors.py:75-78 |
| `server_error` | 500 | errors.py:86-90 |

### A2. Meta

- `GET /health` → `{"status": "ok", "contract_versions": {"chargen": 1, "adventure": 1}}` (routes_meta.py:14-19).
- `GET /v1/llm/status` → `{"configured": bool, "model": str|null, "key_backend": str, "degraded_line": str|null}` (routes_meta.py:22-34). `degraded_line` is `"narration unavailable — showing mechanical outcomes"` when unconfigured, else `null` (src/llm/status.py).

### A3. Sessions — routes_sessions.py

`SessionEnvelope` (routes_sessions.py:56-78) — the return of create/get/resume/choose/name/promote:

```json
{"id": "ab12cd34ef56", "name": "The Ruuth Run", "kind": "chargen",
 "phase": "homeworld", "view": { ... }, "contract_version": 1}
```

- `kind` is `"chargen"` or `"adventure"`. `contract_version` is `1` for both (src/game/chargen/api.py, src/game/adventure_session.py — `CONTRACT_VERSION = 1`).
- Chargen: `phase` = `session.phase`, or `"complete"` with `view: null` when finished (routes_sessions.py:61-65). Non-complete `view` is a `ChoicePointView` (src/engine/lifepath_choices.py:37-46):
  ```json
  {"choice_id": "...", "phase": "...", "prompt": "...",
   "options": [{"option_id": "...", "label": "...", "description": "",
                "preview": [], "odds_line": null, "dimmed": false, "requirement": null}],
   "allows_advisor": true, "allows_freetext": false, "freetext_hint": ""}
  ```
- Adventure: `view` is `dataclasses.asdict(adv_view)`; it always includes `phase: str` and `game_over: bool` (`game_over` is `true` iff `phase == "game_over"`, adventure_session.py:224-225), plus `prompt`, `choices`, `odds_lines`, `scaffold_text`. **The client detects a dead save by `view.game_over == true`** (spec §7.5).
- `POST /v1/sessions` — body `CreateSessionRequest` (models.py:12-31):
  ```json
  {"kind": "chargen", "name": "1-80 chars", "seed": 482991, "pack_id": "scifi",
   "profile": "narrative", "death_mode": "narrative", "from_save": null}
  ```
  Defaults: `kind="chargen"`, `seed=null` (server picks), `pack_id="scifi"`, `profile="narrative"`, `death_mode="narrative"`. `seed` is any JSON int; the client's REROLL sends one (Task 10 pins `randi_range(100000, 999999)`). If `from_save` is set, all other fields are ignored and the kind is inferred (routes_sessions.py:101-103). Adventure without `from_save` → 422 `invalid_config` (112-118). Success → `201 {"session": SessionEnvelope}`.
- `GET /v1/sessions` → `{"sessions": [{"id", "name", "kind"}]}` (routes_sessions.py:81-82, 122-124).
- `GET /v1/sessions/{id}` → `{"session": SessionEnvelope}` (127-134). Unknown id → 404 `session_not_found`.
- `DELETE /v1/sessions/{id}` → 204, empty body (137-139).
- `POST /v1/sessions/{id}/choose` — body `{"option_id": str, "origin": "player"|"advisor"|"freetext"}` (models.py:34-36) → `{"session", "result": {...}, "events": [Event, ...]}` (147-166).
- `POST /v1/sessions/{id}/freetext` — body `{"text": "1-2000 chars"}` → chargen: `{"session", "record", "events"}`; adventure: `{"session", "result", "events"}`; 422 `translator_unavailable` when no LLM configured (169-201).
- `POST /v1/sessions/{id}/suggest` → `{"record": {...}|null}`; 422 `advisor_unavailable` (204-246).
- `POST /v1/sessions/{id}/name` — body `{"name": str}` → `{"session"}` (249-260).
- `POST /v1/sessions/{id}/promote` → `{"session"}` (263-268). M2 ships the wrapper only — integration-testing it needs a completed chargen (M3).
- `Event` (src/engine/audit.py:39-54): `{"seq": int, "kind": "roll"|"state_change"|"system"|"rewind_applied", "command_type": str, "description": str, "roll": RollResult|null, "changes": {}}`. `RollResult` (src/engine/dice.py:36-48): `{"stream": str, "ndice": int, "sides": int, "modifiers": int, "rolls": [int], "total": int}`.

### A4. Narration stream — routes_sessions.py:292-398

`POST /v1/sessions/{id}/narrate` — body `{"beat": "world_intro"|"scene"|"chargen_beat"|"chargen_close", "steering": ""}` (models.py:43-45; defaults `beat="scene"`, `steering=""`). Response: `application/x-ndjson`, one JSON object per line (routes_sessions.py:292-294):

```json
{"type": "narration", "content": "One sentence of prose."}
```

**The complete block-type set is exactly four:** `narration` (≥0, prose sentences), `change` (≥0, one change-line string each), `badge` (0 or 1, a degradation string), `done` (exactly 1, always last, empty content) — from the generator at routes_sessions.py:387-394. There is no `receipt` or `error` block on the wire (the parent spec's §3 list predates the shipped code). Badge content is one of (src/llm/status.py): `"narration unavailable — showing mechanical outcomes"` or `"connection lost — template narration"`. Errors before streaming start arrive as the normal HTTP error envelope (e.g. 409 `action_in_flight`); the stream itself carries no error block.

### A5. Saves — routes_saves.py

- `GET /v1/saves` → `{"saves": [SaveEntry]}` (41-60). `SaveEntry`:
  ```json
  {"name": "mara", "base_name": "mara", "autosave": true, "theme_pack": "scifi",
   "character_name": "Mara Voss", "terms": 4, "career": "Scout", "alive": true,
   "mtime": 1755094800.0}
  ```
  `name` includes the `.autosave` suffix for autosave entries; `base_name` never does. `mtime` is a Unix epoch float.
- `POST /v1/sessions/{id}/save` — body `{"name": str}` → `{"session"}` (63-68). Wrapper only in M2.
- `DELETE /v1/saves/{name}` → `{"deleted": ["mara.json", ...]}`; 404 `save_not_found` (71-79).
- `POST /v1/saves/{name}/duplicate` — body `{"new_name": str}` → `201 {"created": [...]}`; 404/409 `save_conflict`/422 `invalid_name` (82-103).
- `GET /v1/saves/{name}/export` → the raw save JSON document (any JSON object; the client writes it to disk verbatim) (106-117).
- `POST /v1/saves/import` — body `{"name": str, "document": {…full save JSON…}}` → `201 {"name": "<stem>"}`; 409 `save_conflict`, 422 `invalid_save`/`invalid_name` (120-135).

### A6. Config — routes_config.py

- `GET /v1/config/packs` → `{"packs": [PackInfo]}` (14-32). `PackInfo`:
  ```json
  {"id": "scifi", "name": "Frontier Sci-Fi", "description": "...",
   "career_count": 25, "skill_count": 57, "has_cascades": true,
   "has_draft": false, "theme": {"motif": "✦", "accent": "amber",
   "ambience": ["meteors", "birds"]}, "has_intro": true}
  ```
  Shipped pack ids: `scifi`, `fantasy` (test_meta_config.py:41-50). Fantasy theme: `{"motif": "❧", "accent": "gold", "ambience": ["fireflies", "leaves"]}` (src/themepacks/data/fantasy/pack.yaml:47-50). Tolerate a missing/null `theme` (fall back to neutral motif `◆`).
- `GET /v1/config/rulesets` → `{"rulesets": [{"id": "cepheus", "name": ..., "characteristics": [...], "difficulty_ladder": {...}, "resolution_target": 8, "resolution_profiles": ["classic", "narrative"], "death_modes": ["checkpoint", "ironman", "narrative"]}]}` (35-51; ordering per test_meta_config.py:52-59).
- `GET /v1/config/providers` → `{"providers": [{"id": "anthropic", "label": "Anthropic", "presets": ["claude-sonnet-5", ...], "default_base_url": "https://api.anthropic.com", "needs_base_url": false}]}` (54-67).

### A7. Settings — routes_settings.py

- `GET /v1/settings/llm` → `{"provider": "anthropic", "model": "claude-sonnet-5", "base_url": "", "max_retries": 3, "is_configured": false, "key_backend": "", "key_tail": ""}` (25-36). `key_backend` ∈ `"" | "file" | "keyring"`.
- `PUT /v1/settings/llm` — body `{"provider": str, "model": str, "api_key": str|null, "base_url": str, "max_retries": int}` (models.py:65-81). Key semantics (routes_settings.py:70-105): `api_key: null` keeps the stored key; `api_key: ""` **deletes** it; a provider switch deletes the old provider's key. Response = the GET payload, reloaded from disk.
- `POST /v1/settings/llm/test` → `{"ok": true, "models": [...]}` or `{"ok": false, "error": "..."}` (108-119). Never raises.

### A8. Inspect (M2 uses recap only; the rest ship as untested wrappers for M4)

- `GET /v1/sessions/{id}/recap` → `{"lines": ["...", "..."], "source": "..."}` (routes_inspect.py:55-61).
- Wrappers only (integration-tested in M4): `GET .../sheet`, `GET .../memorial`, `GET .../audit?kind=&stream=&since=&page=&per_page=`, `GET .../llm-context`, `POST .../odds` (body `{"skill","characteristic","difficulty"}`, models.py:84-87), `GET .../hash`, `POST .../verify` (501).

---

## GDScript conventions used throughout

- **UI-in-code:** screens and components are `class_name X extends Control` classes that build their node tree in `_ready()` via a `_build()` method. No `.tscn` files except `client/app/main.tscn` (Task 6). Nodes that need per-frame work implement `_process`/`_unhandled_input`.
- **Autoloads (registered in Task 6, no `class_name`):** `PackThemes` (theme/pack_themes.gd, Task 2), `ClientSettings` (app/client_settings.gd, Task 6), `SessionStore` (engine/session_store.gd, Task 4), `Services` (app/services.gd, Task 6 — holds `sidecar` and `client`). Before Task 6 registers them, tests instantiate the scripts directly: `var pt: PackThemesImpl = preload("res://theme/pack_themes.gd").new()` — the scripts take no `_init` args.
- **Async:** all EngineClient methods are `async` via `await` on signals; callers write `var res: EngineResult = await Services.client.list_saves()`.
- **Result type** (Task 4): `EngineResult` (RefCounted) — `ok: bool`, `status: int`, `data: Dictionary`, `error_code: String`, `error_message: String`.
- **Naming:** files `snake_case.gd`; classes `PascalCase`; signals `snake_case`; constants `UPPER_SNAKE`.
- **Tests:** `client/tests/<area>/test_<thing>.gd`, `extends GdUnitTestSuite`, methods `func test_x() -> void:`. Node-creating tests wrap instances in `auto_free(...)`. Golden suites live in `client/tests/golden/` and self-skip when `DisplayServer.get_name() == "headless"`.

## File structure map

```
client/
  project.godot                     # Task 1 (autoloads appended in Task 6)
  .gdignore                         # (none needed)
  addons/gdUnit4/                   # Task 1 (committed, v6.2.0)
  assets/fonts/                     # Task 1 (5 OFL families + OFL.txt each)
  engine/
    paths.gd                        # Task 3 — class_name Paths (repo-root resolution)
    sidecar_process.gd              # Task 3 — class_name SidecarProcess extends Node
    engine_result.gd                # Task 4 — class_name EngineResult extends RefCounted
    engine_client.gd                # Task 4 — class_name EngineClient extends Node
    stream_pump.gd                  # Task 5 — class_name StreamPump extends Node
    session_store.gd                # Task 4 — autoload SessionStore (no class_name)
  theme/
    pack_theme.gd                   # Task 2 — class_name PackTheme extends Resource
    pack_themes.gd                  # Task 2 — autoload PackThemes (no class_name)
    fonts.gd                        # Task 2 — class_name Fonts (statics)
    stepped_frame.gd                # Task 2 — class_name SteppedFrame extends Control
    dither.gd                       # Task 2 — class_name Dither (static texture factory)
    scene_backdrop.gd               # Task 2 — class_name SceneBackdrop extends Control
  app/
    main.tscn + main.gd             # Task 6 — boot flow, root layout
    services.gd                     # Task 6 — autoload Services
    client_settings.gd              # Task 6 — autoload ClientSettings
    screen_stack.gd                 # Task 6 — class_name ScreenStack extends Control
    base_screen.gd                  # Task 6 — class_name BaseScreen extends Control
    overlay_layer.gd                # Task 6 — class_name OverlayLayer extends CanvasLayer
    status_strip.gd                 # Task 6 — class_name StatusStrip extends Control
  components/
    kit.gd                          # Task 6 — class_name Kit (statics: btn, ghost, microlink,
                                  #   card, docket, data_field, toggle, slider, segmented)
    toast.gd                        # Task 6 — class_name Toast extends Control
  screens/
    title_screen.gd                 # Task 7  — class_name TitleScreen extends BaseScreen
    settings_screen.gd              # Task 8  — class_name SettingsScreen extends BaseScreen
    chronicles_screen.gd            # Task 9  — class_name ChroniclesScreen extends BaseScreen
    new_journey_screen.gd           # Task 10 — class_name NewJourneyScreen extends BaseScreen
    stub_screen.gd                  # Task 10 — class_name StubScreen extends BaseScreen
  tests/
    test_smoke.gd                   # Task 1
    theme/test_pack_themes.gd       # Task 2 (tokens.css conformance)
    theme/test_stepped_frame.gd     # Task 2
    engine/test_sidecar_process.gd  # Task 3 (integration)
    engine/test_engine_client.gd    # Task 4 (integration, real sidecar)
    engine/test_stream_pump.gd      # Task 5 (integration)
    engine/fake_engine_client.gd    # Task 6 — FakeEngineClient extends Node (test double)
    app/test_screen_stack.gd        # Task 6
    app/test_client_settings.gd     # Task 6
    screens/test_title_screen.gd    # Task 7
    screens/test_settings_screen.gd # Task 8
    screens/test_chronicles_screen.gd   # Task 9
    screens/test_new_journey_screen.gd  # Task 10
    golden/golden_assert.gd         # Task 11 — class_name GoldenAssert (statics)
    golden/test_golden_screens.gd   # Task 11
tools/
  get_godot.sh                      # Task 1
  get_fonts.sh                      # Task 1
  get_gdunit4.sh                    # Task 1
  run_client_tests.sh               # Task 1 — one-command gate entry
```

## Task 1 (M2.1): Scaffold + toolchain

**Files:**
- Create: `tools/get_godot.sh`, `tools/get_gdunit4.sh`, `tools/get_fonts.sh`, `tools/run_client_tests.sh`, `tools/run_client_lint.sh`
- Create: `client/project.godot`, `client/app/main.tscn`, `client/app/main.gd`, `client/tests/test_smoke.gd`
- Create: empty dirs `client/engine client/theme client/components client/screens client/tests/theme client/tests/engine client/tests/app client/tests/screens client/tests/golden`
- Modify: `.gitignore` (append), `.githooks/pre-push` (insert block), `.github/workflows/ci.yml` (append job)
- Modify: `pyproject.toml` + `uv.lock` via `uv add --dev gdtoolkit`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `tools/run_client_tests.sh` (gate entry, used by pre-push + CI + every later task); `tools/run_client_lint.sh`; the Godot binary at `tools/godot/Godot_v4.7.1-stable_linux.x86_64`; committed fonts under `client/assets/fonts/`; committed gdUnit4 under `client/addons/gdUnit4/`.

- [ ] **Step 1: `tools/get_godot.sh`** — create exactly:

```bash
#!/usr/bin/env bash
# Download the pinned Godot build (spec M2-D3). Idempotent: skips if present.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

GODOT_VERSION="4.7.1-stable"
GODOT_ZIP="Godot_v${GODOT_VERSION}_linux.x86_64.zip"
GODOT_BIN="tools/godot/Godot_v${GODOT_VERSION}_linux.x86_64"

if [ -x "$GODOT_BIN" ]; then
  echo "Godot ${GODOT_VERSION} already present at ${GODOT_BIN}"
  exit 0
fi

mkdir -p tools/godot
tmp="$(mktemp -d)"
curl -fSL "https://github.com/godotengine/godot/releases/download/${GODOT_VERSION}/${GODOT_ZIP}" -o "$tmp/godot.zip"
unzip -q "$tmp/godot.zip" -d tools/godot/
chmod +x "$GODOT_BIN"
rm -rf "$tmp"
"$GODOT_BIN" --version
```

Run: `chmod +x tools/get_godot.sh && tools/get_godot.sh`
Expected: last line prints `4.7.1.stable.official.<hex>` (any hex suffix).

- [ ] **Step 2: `tools/get_gdunit4.sh`** — create exactly (release v6.2.0 has no zip asset; the source tarball carries `addons/gdUnit4`):

```bash
#!/usr/bin/env bash
# Install gdUnit4 v6.2.0 into the client project (spec M2-D4). Idempotent.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

if [ -d client/addons/gdUnit4 ]; then
  echo "gdUnit4 already present at client/addons/gdUnit4"
  exit 0
fi

tmp="$(mktemp -d)"
curl -fSL "https://github.com/godot-gdunit-labs/gdUnit4/archive/refs/tags/v6.2.0.tar.gz" -o "$tmp/gdunit4.tar.gz"
tar -xzf "$tmp/gdunit4.tar.gz" -C "$tmp"
mkdir -p client/addons
cp -r "$tmp/gdUnit4-6.2.0/addons/gdUnit4" client/addons/gdUnit4
rm -rf "$tmp"
echo "gdUnit4 v6.2.0 installed to client/addons/gdUnit4"
```

Run: `chmod +x tools/get_gdunit4.sh && tools/get_gdunit4.sh`
Expected: `gdUnit4 v6.2.0 installed to client/addons/gdUnit4`; `ls client/addons/gdUnit4/bin/GdUnitCmdTool.gd` exists.

- [ ] **Step 3: `tools/get_fonts.sh`** — create exactly (URLs verified 200 on 2026-08-13; spec M2-D10):

```bash
#!/usr/bin/env bash
# Download the five OFL font families (tokens.css type system) into
# client/assets/fonts/. Idempotent: re-downloads everything when run.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

BASE="https://raw.githubusercontent.com/google/fonts/main/ofl"

fetch() { # fetch <url-path> <dest-relative-to-client/assets/fonts>
  mkdir -p "client/assets/fonts/$(dirname "$2")"
  curl -fSL "$BASE/$1" -o "client/assets/fonts/$2"
}

fetch "spacegrotesk/SpaceGrotesk%5Bwght%5D.ttf"        "spacegrotesk/SpaceGrotesk-Variable.ttf"
fetch "spacegrotesk/OFL.txt"                          "spacegrotesk/OFL.txt"

fetch "chakrapetch/ChakraPetch-Medium.ttf"            "chakrapetch/ChakraPetch-Medium.ttf"
fetch "chakrapetch/ChakraPetch-SemiBold.ttf"          "chakrapetch/ChakraPetch-SemiBold.ttf"
fetch "chakrapetch/ChakraPetch-Bold.ttf"              "chakrapetch/ChakraPetch-Bold.ttf"
fetch "chakrapetch/OFL.txt"                           "chakrapetch/OFL.txt"

fetch "atkinsonhyperlegible/AtkinsonHyperlegible-Regular.ttf" "atkinsonhyperlegible/AtkinsonHyperlegible-Regular.ttf"
fetch "atkinsonhyperlegible/AtkinsonHyperlegible-Bold.ttf"    "atkinsonhyperlegible/AtkinsonHyperlegible-Bold.ttf"
fetch "atkinsonhyperlegible/AtkinsonHyperlegible-Italic.ttf"  "atkinsonhyperlegible/AtkinsonHyperlegible-Italic.ttf"
fetch "atkinsonhyperlegible/OFL.txt"                          "atkinsonhyperlegible/OFL.txt"

fetch "ibmplexmono/IBMPlexMono-Regular.ttf"           "ibmplexmono/IBMPlexMono-Regular.ttf"
fetch "ibmplexmono/IBMPlexMono-Medium.ttf"            "ibmplexmono/IBMPlexMono-Medium.ttf"
fetch "ibmplexmono/IBMPlexMono-SemiBold.ttf"          "ibmplexmono/IBMPlexMono-SemiBold.ttf"
fetch "ibmplexmono/OFL.txt"                           "ibmplexmono/OFL.txt"

fetch "vt323/VT323-Regular.ttf"                       "vt323/VT323-Regular.ttf"
fetch "vt323/OFL.txt"                                 "vt323/OFL.txt"

echo "fonts installed under client/assets/fonts/"
```

Run: `chmod +x tools/get_fonts.sh && tools/get_fonts.sh`
Expected: `fonts installed under client/assets/fonts/`; `find client/assets/fonts -name '*.ttf' | wc -l` prints `10`.

- [ ] **Step 4: `client/project.godot`** — create exactly (gl_compatibility so xvfb/WSLg software GL works; fixed 1280×720 per spec §8; nearest texture filter for the pixel idiom):

```
config_version=5

[application]

config/name="Andromeda"
run/main_scene="res://app/main.tscn"
config/features=PackedStringArray("4.7", "GL Compatibility")

[display]

window/size/viewport_width=1280
window/size/viewport_height=720
window/size/resizable=false

[rendering]

renderer/rendering_method="gl_compatibility"
textures/canvas_textures/default_texture_filter=0
```

Create `client/app/main.tscn` exactly (placeholder; Task 6 replaces both files):

```
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://app/main.gd" id="1"]

[node name="Main" type="Control"]
layout_mode = 3
anchors_preset = 15
script = ExtResource("1")
```

Create `client/app/main.gd` exactly (placeholder):

```gdscript
extends Control
## Boot root. Replaced by the real app shell in Task 6.
```

Create the remaining directories: `mkdir -p client/engine client/theme client/components client/screens client/tests/theme client/tests/engine client/tests/app client/tests/screens client/tests/golden`

- [ ] **Step 5: `client/tests/test_smoke.gd`** — create exactly:

```gdscript
extends GdUnitTestSuite
## Scaffold smoke test (M2.1): right engine, fonts on disk.

func test_godot_version_is_4_7_1() -> void:
	assert_str(str(Engine.get_version_info()["string"])).contains("4.7.1")


func test_fonts_are_on_disk() -> void:
	var fonts := [
		"res://assets/fonts/spacegrotesk/SpaceGrotesk-Variable.ttf",
		"res://assets/fonts/chakrapetch/ChakraPetch-SemiBold.ttf",
		"res://assets/fonts/atkinsonhyperlegible/AtkinsonHyperlegible-Regular.ttf",
		"res://assets/fonts/ibmplexmono/IBMPlexMono-Medium.ttf",
		"res://assets/fonts/vt323/VT323-Regular.ttf",
	]
	for path: String in fonts:
		assert_bool(FileAccess.file_exists(path)).is_true()
```

- [ ] **Step 6: test runner scripts** — create `tools/run_client_tests.sh` exactly:

```bash
#!/usr/bin/env bash
# One-command gdUnit4 entry (gate + local). Exit 0 on pass or warnings-only.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

GODOT_BIN="${GODOT_BIN:-tools/godot/Godot_v4.7.1-stable_linux.x86_64}"
if [ ! -x "$GODOT_BIN" ]; then
  echo "Godot binary not found at $GODOT_BIN — run tools/get_godot.sh first" >&2
  exit 1
fi

# First run needs an import pass to build .godot/ (fonts etc.).
if [ ! -d client/.godot ]; then
  "$GODOT_BIN" --headless --path client --import
fi

set +e
"$GODOT_BIN" --headless --path client \
  -s res://addons/gdUnit4/bin/GdUnitCmdTool.gd \
  -a res://tests -c -rd /tmp/gdunit-reports
code=$?
set -e

# gdUnit4 exit codes: 0 = pass, 100 = failures, 101 = warnings-only.
if [ "$code" -eq 0 ] || [ "$code" -eq 101 ]; then
  exit 0
fi
exit "$code"
```

Create `tools/run_client_lint.sh` exactly (explicit dir list — `client/addons/` is third-party and must NOT be linted/formatted):

```bash
#!/usr/bin/env bash
# gdlint + gdformat over first-party GDScript only (never client/addons/).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

DIRS="client/app client/components client/engine client/screens client/tests client/theme"

printf '▶ gdlint\n'
uv run gdlint $DIRS

printf '▶ gdformat --check\n'
uv run gdformat --check $DIRS
```

Run: `chmod +x tools/run_client_tests.sh tools/run_client_lint.sh`

- [ ] **Step 7: gdtoolkit dev dependency**

Run: `uv add --dev gdtoolkit && uv lock`
Verify: `uv run gdlint --version` prints a version; `uv run gdformat --version` prints a version.
(If `uv add` fails to find the package, stop — the gate depends on it.)

- [ ] **Step 8: `.gitignore`** — append exactly:

```
# Godot client (M2)
client/.godot/
tools/godot/
```

- [ ] **Step 9: run the client gate** — `tools/run_client_tests.sh`
Expected: gdUnit4 reports 2 passed tests, exit code 0.

- [ ] **Step 10: run the lint gate** — `tools/run_client_lint.sh`
Expected: gdlint and gdformat both pass (only `client/app/main.gd` + the smoke test exist so far).

- [ ] **Step 11: pre-push hook** — in `.githooks/pre-push`, replace this block:

```bash
printf '▶ pre-push: pytest (full suite)\n'
uv run pytest tests/ -q

printf '✓ pre-push checks passed\n'
```

with exactly:

```bash
printf '▶ pre-push: pytest (full suite)\n'
uv run pytest tests/ -q

printf '▶ pre-push: client lint (gdlint + gdformat)\n'
tools/run_client_lint.sh

printf '▶ pre-push: client tests (gdUnit4 headless)\n'
tools/run_client_tests.sh

printf '✓ pre-push checks passed\n'
```

- [ ] **Step 12: CI job** — append to `jobs:` in `.github/workflows/ci.yml` (same indentation as `lint:`/`test:`):

```yaml
  client:
    name: Client (gdlint + gdformat + gdUnit4)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7.0.1
      - uses: astral-sh/setup-uv@v9.0.0
        with:
          enable-cache: true
      - name: Install dependencies
        run: uv sync --frozen
      - name: Cache Godot
        uses: actions/cache@v4
        with:
          path: tools/godot
          key: godot-4.7.1-stable-linux-x86_64
      - name: Download Godot (skip on cache hit)
        run: tools/get_godot.sh
      - name: Install xvfb (golden screenshots need a real renderer)
        run: sudo apt-get update && sudo apt-get install -y xvfb
      - name: Client lint
        run: tools/run_client_lint.sh
      - name: Client tests
        run: xvfb-run -a tools/run_client_tests.sh
```

- [ ] **Step 13: full quality gate** — run every line of the Global Constraints gate block (ruff, pytest, lint script, tests script).
Expected: all pass. (`uv lock` in Step 7 keeps `uv sync --frozen` honest.)

- [ ] **Step 14: Commit**

```bash
git add tools/ client/ .gitignore .githooks/pre-push .github/workflows/ci.yml pyproject.toml uv.lock
git commit -m "chore(client): M2.1 scaffold — Godot 4.7.1 project, gdUnit4, fonts, gate wiring"
```

---

## Task 2 (M2.2): Theme foundations

**Files:**
- Create: `client/theme/pack_theme.gd`, `client/theme/pack_themes.gd`, `client/theme/fonts.gd`, `client/theme/dither.gd`, `client/theme/stepped_frame.gd`, `client/theme/scene_backdrop.gd`
- Test: `client/tests/theme/test_pack_themes.gd`, `client/tests/theme/test_stepped_frame.gd`

**Interfaces:**
- Consumes: Task 1 fonts on disk.
- Produces (later tasks rely on these exact names):
  - `PackTheme` (Resource): `id, bg, panel, line, ink, muted, accent, ok, danger: Color`; `motif: String`; `ambience: PackedStringArray`.
  - `PackThemes` (autoload script, **no class_name**; extends Node): static `_build_sets() -> Dictionary`; `get_theme(id: String) -> PackTheme` (unknown → neutral); `has_pack(id) -> bool`; `apply(id: String)`, `apply_hint(pack_id: String, hint: Dictionary)`; `var current: PackTheme`; `signal pack_changed(theme: PackTheme)`.
  - `Fonts` (statics): `title() inter() prose() prose_bold() data() data_semibold() micro() micro_tracked() -> Font`; `label(text: String, font: Font, size: int, color: Color) -> Label`.
  - `Dither` (statics): `texture() -> Texture2D`; `overlay() -> TextureRect`.
  - `SteppedFrame` (Control): `ring_color`, `fill_color: Color`; `add_content(node: Control)`; `set_content_margins(l, t, r, b: int)`; `apply_theme(t: PackTheme, ring := "accent", fill := "panel")`; static `_stepped(r: Rect2, s1: float, s2: float) -> PackedVector2Array` (20 points).
  - `SceneBackdrop` (Control): `scene_id: String`, `kicker_text: String`, `footer_text: String`, `show_planet := true`, `show_horizon := true`, `theme: PackTheme`; `const GRADIENTS: Dictionary`; `const NIGHT_STARS: Array`.

**Theming model (pin — do not improvise):** there is no implicit theme propagation. Every component receives its `PackTheme` explicitly (`apply_theme(t)` / property assignment) from its parent screen. Per-widget tinting is required (mock 02 shows scifi/fantasy/dead dockets on one screen). `PackThemes.current` + `pack_changed` exist only for shell-level repaint (Title tint-on-return, Task 7).

- [ ] **Step 1: failing tests** — create `client/tests/theme/test_pack_themes.gd` exactly:

```gdscript
extends GdUnitTestSuite
## tokens.css conformance (spec M2-D6): the four pack token sets must match
## design/mockups/final/tokens.css lines 24-27 byte-for-byte.

const PackThemesImpl := preload("res://theme/pack_themes.gd")

# id -> [bg, panel, line, ink, muted, accent, ok, danger, motif, ambience]
const EXPECTED := {
	"scifi": ["0A0F1E", "101830", "27345C", "E6EBF7", "7C88A8", "F5A623", "46C48A", "E5484D", "✦", ["meteors", "birds"]],
	"fantasy": ["17120C", "221A10", "4A3A22", "F2E9D8", "9C8D76", "D9A02B", "7FA85C", "C24A52", "❧", ["fireflies", "leaves"]],
	"neutral": ["13161D", "1A1F2A", "2C3444", "E9EDF5", "7E8899", "8FA3C8", "5FC98E", "E5606C", "◆", []],
	"dead": ["180F12", "221418", "4A2830", "E9DCD8", "96787E", "8E3A46", "7FA85C", "E5606C", "✝", []],
}


func test_four_token_sets_match_tokens_css() -> void:
	var sets: Dictionary = PackThemesImpl._build_sets()
	assert_that(sets.size()).is_equal(4)
	for id: String in EXPECTED:
		var e: Array = EXPECTED[id]
		var t: PackTheme = sets[id]
		assert_that(t.bg).is_equal(Color(e[0]))
		assert_that(t.panel).is_equal(Color(e[1]))
		assert_that(t.line).is_equal(Color(e[2]))
		assert_that(t.ink).is_equal(Color(e[3]))
		assert_that(t.muted).is_equal(Color(e[4]))
		assert_that(t.accent).is_equal(Color(e[5]))
		assert_that(t.ok).is_equal(Color(e[6]))
		assert_that(t.danger).is_equal(Color(e[7]))
		assert_that(t.motif).is_equal(e[8])
		assert_that(Array(t.ambience)).is_equal(e[9])


func test_get_theme_falls_back_to_neutral() -> void:
	var sets: Dictionary = PackThemesImpl._build_sets()
	var pt: Node = PackThemesImpl.new()
	pt._sets = sets
	assert_that(pt.get_theme("scifi").id).is_equal("scifi")
	assert_that(pt.get_theme("nonexistent").id).is_equal("neutral")
	pt.free()
```

Create `client/tests/theme/test_stepped_frame.gd` exactly:

```gdscript
extends GdUnitTestSuite
## SteppedFrame geometry: the tokens.css clip-path polygons, converted.

func test_outer_polygon_matches_px_clip_path() -> void:
	# tokens.css .px: (0,8)(4,8)(4,4)(8,4)(8,0) then mirrored — 20 points.
	var pts := SteppedFrame._stepped(Rect2(0, 0, 100, 100), 4.0, 8.0)
	assert_that(pts.size()).is_equal(20)
	assert_that(pts[0]).is_equal(Vector2(0, 8))
	assert_that(pts[1]).is_equal(Vector2(4, 8))
	assert_that(pts[2]).is_equal(Vector2(4, 4))
	assert_that(pts[3]).is_equal(Vector2(8, 4))
	assert_that(pts[4]).is_equal(Vector2(8, 0))
	assert_that(pts[5]).is_equal(Vector2(92, 0))
	assert_that(pts[10]).is_equal(Vector2(100, 92))


func test_inner_polygon_matches_px_in_clip_path() -> void:
	# tokens.css .px-in: (0,6)(3,6)(3,3)(6,3)(6,0) then mirrored.
	var pts := SteppedFrame._stepped(Rect2(2, 2, 98, 98), 3.0, 6.0)
	assert_that(pts[0]).is_equal(Vector2(2, 8))
	assert_that(pts[4]).is_equal(Vector2(8, 2))


func test_apply_theme_sets_colors() -> void:
	var frame: SteppedFrame = auto_free(SteppedFrame.new())
	var t := PackTheme.new()
	t.accent = Color("F5A623")
	t.panel = Color("101830")
	frame.apply_theme(t)
	assert_that(frame.ring_color).is_equal(Color("F5A623"))
	assert_that(frame.fill_color).is_equal(Color("101830"))
```

- [ ] **Step 2: run tests, verify failure**

Run: `tools/run_client_tests.sh`
Expected: FAIL — `PackTheme`/`SteppedFrame` don't exist (parse errors in the test suite).

- [ ] **Step 3: `client/theme/pack_theme.gd`** — create exactly:

```gdscript
class_name PackTheme
extends Resource
## One pack's token set: the eight colors + motif glyph + ambience list
## (design/mockups/final/tokens.css, .t-* blocks).

var id: String = ""
var bg: Color = Color.BLACK
var panel: Color = Color.BLACK
var line: Color = Color.BLACK
var ink: Color = Color.WHITE
var muted: Color = Color.GRAY
var accent: Color = Color.WHITE
var ok: Color = Color.GREEN
var danger: Color = Color.RED
var motif: String = "◆"
var ambience: PackedStringArray = PackedStringArray()
```

- [ ] **Step 4: `client/theme/pack_themes.gd`** — create exactly (**no class_name** — it becomes the `PackThemes` autoload in Task 6; tests instantiate it directly):

```gdscript
extends Node
## Autoload: PackThemes. Builds the four token sets as a mechanical
## translation of tokens.css (never reinterpreted — spec §5) and applies
## server theme hints (symbolic only: motif + ambience; §A6).

signal pack_changed(theme: PackTheme)

const NEUTRAL := "neutral"

var current: PackTheme
var _sets: Dictionary = {}


func _ready() -> void:
	_sets = _build_sets()
	current = _sets[NEUTRAL]


static func _build_sets() -> Dictionary:
	return {
		"scifi": _make("scifi", "0A0F1E", "101830", "27345C", "E6EBF7", "7C88A8", "F5A623", "46C48A", "E5484D", "✦", ["meteors", "birds"]),
		"fantasy": _make("fantasy", "17120C", "221A10", "4A3A22", "F2E9D8", "9C8D76", "D9A02B", "7FA85C", "C24A52", "❧", ["fireflies", "leaves"]),
		"neutral": _make("neutral", "13161D", "1A1F2A", "2C3444", "E9EDF5", "7E8899", "8FA3C8", "5FC98E", "E5606C", "◆", []),
		"dead": _make("dead", "180F12", "221418", "4A2830", "E9DCD8", "96787E", "8E3A46", "7FA85C", "E5606C", "✝", []),
	}


static func _make(
	id: String,
	bg: String,
	panel: String,
	line: String,
	ink: String,
	muted: String,
	accent: String,
	ok: String,
	danger: String,
	motif: String,
	ambience: Array
) -> PackTheme:
	var t := PackTheme.new()
	t.id = id
	t.bg = Color(bg)
	t.panel = Color(panel)
	t.line = Color(line)
	t.ink = Color(ink)
	t.muted = Color(muted)
	t.accent = Color(accent)
	t.ok = Color(ok)
	t.danger = Color(danger)
	t.motif = motif
	t.ambience = PackedStringArray(ambience)
	return t


func has_pack(id: String) -> bool:
	return _sets.has(id)


## Unknown ids fall back to neutral (spec §5).
func get_theme(id: String) -> PackTheme:
	return _sets.get(id, _sets[NEUTRAL])


func apply(id: String) -> void:
	current = get_theme(id)
	pack_changed.emit(current)


## Applies a server `theme` hint (§A6) over the built-in set: motif and
## ambience are adopted when present; the named accent is symbolic and never
## overrides the tokens.css hexes. Sets `current` and emits pack_changed.
func apply_hint(pack_id: String, hint: Dictionary) -> void:
	var base: PackTheme = get_theme(pack_id)
	var t := PackTheme.new()
	t.id = base.id
	t.bg = base.bg
	t.panel = base.panel
	t.line = base.line
	t.ink = base.ink
	t.muted = base.muted
	t.accent = base.accent
	t.ok = base.ok
	t.danger = base.danger
	t.motif = base.motif
	t.ambience = base.ambience
	if str(hint.get("motif", "")) != "":
		t.motif = str(hint["motif"])
	var amb: Variant = hint.get("ambience", null)
	if amb is Array and not amb.is_empty():
		t.ambience = PackedStringArray(amb)
	current = t
	pack_changed.emit(current)
```

- [ ] **Step 5: `client/theme/fonts.gd`** — create exactly. Role mapping per tokens.css: title = Space Grotesk 700, int = Chakra Petch 600 (SemiBold), prose = Atkinson 400, data = IBM Plex Mono 500 (Medium), micro = VT323. Space Grotesk ships as a variable font, so weight 700 comes from an OpenType variation coordinate. `micro_tracked` adds +2px glyph spacing (the mocks' `.2em` micro tracking at 12px).

```gdscript
class_name Fonts
extends RefCounted
## tokens.css type system. Statics only — never instantiate.
## Roles: title / int(eractive) / prose / data / micro.

const _SPACE_GROTESK := "res://assets/fonts/spacegrotesk/SpaceGrotesk-Variable.ttf"
const _CHAKRA_SEMIBOLD := "res://assets/fonts/chakrapetch/ChakraPetch-SemiBold.ttf"
const _CHAKRA_MEDIUM := "res://assets/fonts/chakrapetch/ChakraPetch-Medium.ttf"
const _ATKINSON := "res://assets/fonts/atkinsonhyperlegible/AtkinsonHyperlegible-Regular.ttf"
const _ATKINSON_BOLD := "res://assets/fonts/atkinsonhyperlegible/AtkinsonHyperlegible-Bold.ttf"
const _PLEX_MEDIUM := "res://assets/fonts/ibmplexmono/IBMPlexMono-Medium.ttf"
const _PLEX_SEMIBOLD := "res://assets/fonts/ibmplexmono/IBMPlexMono-SemiBold.ttf"
const _VT323 := "res://assets/fonts/vt323/VT323-Regular.ttf"

static var _cache: Dictionary = {}


static func _load(path: String) -> Font:
	if not _cache.has(path):
		_cache[path] = ResourceLoader.load(path) as Font
	return _cache[path]


## Space Grotesk 700 (screen titles, big numbers).
static func title() -> Font:
	if not _cache.has("title"):
		var v := FontVariation.new()
		v.base_font = _load(_SPACE_GROTESK)
		v.variation_opentype = {"wght": 700}
		_cache["title"] = v
	return _cache["title"]


## Chakra Petch 600 (interactive titles: menus, choices, buttons).
static func inter() -> Font:
	return _load(_CHAKRA_SEMIBOLD)


## Chakra Petch 500.
static func inter_medium() -> Font:
	return _load(_CHAKRA_MEDIUM)


## Atkinson Hyperlegible 400 (prose).
static func prose() -> Font:
	return _load(_ATKINSON)


## Atkinson Hyperlegible 700.
static func prose_bold() -> Font:
	return _load(_ATKINSON_BOLD)


## IBM Plex Mono 500 (data: dockets, odds, receipts).
static func data() -> Font:
	return _load(_PLEX_MEDIUM)


## IBM Plex Mono 600.
static func data_semibold() -> Font:
	return _load(_PLEX_SEMIBOLD)


## VT323 (micro-labels: kickers, pack tags, SEQ stamps — never main content).
static func micro() -> Font:
	return _load(_VT323)


## VT323 with +2px glyph tracking (the mocks' .2em micro tracking at 12px).
static func micro_tracked() -> Font:
	if not _cache.has("micro_tracked"):
		var v := FontVariation.new()
		v.base_font = _load(_VT323)
		v.spacing_glyph = 2
		_cache["micro_tracked"] = v
	return _cache["micro_tracked"]


## Builds a Label with the role font/size/color applied as overrides.
static func label(text: String, font: Font, size: int, color: Color) -> Label:
	var l := Label.new()
	l.text = text
	l.add_theme_font_override("font", font)
	l.add_theme_font_size_override("font_size", size)
	l.add_theme_color_override("font_color", color)
	return l
```

- [ ] **Step 6: `client/theme/dither.gd`** — create exactly (4px tile, half the cells white at 6% alpha ≈ 3% average — tokens.css "4px dither overlay ~3%"):

```gdscript
class_name Dither
extends RefCounted
## 4px dither overlay at ~3% (tokens.css §6.3). Statics only.

static var _texture: Texture2D


static func texture() -> Texture2D:
	if _texture == null:
		var img := Image.create(4, 4, false, Image.FORMAT_RGBA8)
		for y: int in 4:
			for x: int in 4:
				var on: bool = (x + y) % 2 == 0
				img.set_pixel(x, y, Color(1, 1, 1, 0.06) if on else Color(0, 0, 0, 0))
		_texture = ImageTexture.create_from_image(img)
	return _texture


## A full-rect tiled overlay; ignores mouse; add as the last child of a panel.
static func overlay() -> TextureRect:
	var tr := TextureRect.new()
	tr.texture = texture()
	tr.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	tr.stretch_mode = TextureRect.STRETCH_TILE
	tr.mouse_filter = Control.MOUSE_FILTER_IGNORE
	tr.set_anchors_preset(Control.PRESET_FULL_RECT)
	return tr
```

- [ ] **Step 7: `client/theme/stepped_frame.gd`** — create exactly (geometry from tokens.css `.px`/`.px-in`; test Step 1 pins the polygon points):

```gdscript
class_name SteppedFrame
extends Control
## tokens.css .px frame: 2px accent ring with 2px-stepped pixel corners
## (outer steps 4/8px, inner steps 3/6px) over a panel fill.

@export var ring_color: Color = Color.WHITE:
	set(v):
		ring_color = v
		queue_redraw()
@export var fill_color: Color = Color.BLACK:
	set(v):
		fill_color = v
		queue_redraw()

var _content := MarginContainer.new()


func _ready() -> void:
	_content.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(_content)


## Themed content container; margins default to 2 (the ring) until
## set_content_margins is called.
func add_content(node: Control) -> void:
	_content.add_child(node)


func set_content_margins(l: int, t: int, r: int, b: int) -> void:
	_content.add_theme_constant_override("margin_left", l)
	_content.add_theme_constant_override("margin_top", t)
	_content.add_theme_constant_override("margin_right", r)
	_content.add_theme_constant_override("margin_bottom", b)


func apply_theme(t: PackTheme, ring := "accent", fill := "panel") -> void:
	ring_color = t.get(ring)
	fill_color = t.get(fill)


## The stepped-corner polygon: (0,s2)(s1,s2)(s1,s1)(s2,s1)(s2,0) mirrored on
## all four corners. 20 points. s1/s2 are 4/8 (outer) or 3/6 (inner).
static func _stepped(r: Rect2, s1: float, s2: float) -> PackedVector2Array:
	var x0 := r.position.x
	var y0 := r.position.y
	var x1 := r.end.x
	var y1 := r.end.y
	return PackedVector2Array(
		[
			Vector2(x0, y0 + s2),
			Vector2(x0 + s1, y0 + s2),
			Vector2(x0 + s1, y0 + s1),
			Vector2(x0 + s2, y0 + s1),
			Vector2(x0 + s2, y0),
			Vector2(x1 - s2, y0),
			Vector2(x1 - s2, y0 + s1),
			Vector2(x1 - s1, y0 + s1),
			Vector2(x1 - s1, y0 + s2),
			Vector2(x1, y0 + s2),
			Vector2(x1, y1 - s2),
			Vector2(x1 - s1, y1 - s2),
			Vector2(x1 - s1, y1 - s1),
			Vector2(x1 - s2, y1 - s1),
			Vector2(x1 - s2, y1),
			Vector2(x0 + s2, y1),
			Vector2(x0 + s2, y1 - s1),
			Vector2(x0 + s1, y1 - s1),
			Vector2(x0 + s1, y1 - s2),
			Vector2(x0, y1 - s2),
		]
	)


func _draw() -> void:
	var r := Rect2(Vector2.ZERO, size)
	draw_colored_polygon(_stepped(r, 4.0, 8.0), ring_color)
	draw_colored_polygon(_stepped(r.grow_individual(-2, -2, -2, -2), 3.0, 6.0), fill_color)
```

- [ ] **Step 8: `client/theme/scene_backdrop.gd`** — create exactly. Gradient stops are tokens.css `.sc-*` lines 53-92; star specks are the `.sc-night` radial-gradient specks (position %, px size, alpha); the horizon is the tokens.css `clip-path` polygon (26% bottom band); veil = `.veil-cinema`. Static in M2 (spec M2-D7).

```gdscript
class_name SceneBackdrop
extends Control
## Cinematic scene backdrop (tokens.css §cinematic scene system).
## Static in M2: gradient + fixed star specks + planet + horizon + veil.
## Ambient motion (twinkle, drift, beacon, meteor, birds) is M5.

@export var scene_id := "night":
	set(v):
		scene_id = v
		queue_redraw()
@export var kicker_text := "":
	set(v):
		kicker_text = v
		queue_redraw()
@export var footer_text := "":
	set(v):
		footer_text = v
		queue_redraw()
@export var show_planet := true:
	set(v):
		show_planet = v
		queue_redraw()
@export var show_horizon := true:
	set(v):
		show_horizon = v
		queue_redraw()

var theme: PackTheme:
	set(v):
		theme = v
		queue_redraw()

## tokens.css .sc-* linear-gradient stops (top → bottom).
const GRADIENTS := {
	"night": [[0.0, "0B0E17"], [0.52, "141B31"], [0.78, "1E2A4D"], [1.0, "2A3A66"]],
	"dawn": [[0.0, "0B0E17"], [0.45, "181E38"], [0.75, "41365C"], [1.0, "8A5A3A"]],
	"dusk": [[0.0, "0B0E17"], [0.55, "241E3C"], [0.85, "5C3A4E"], [1.0, "7C4A44"]],
	"flare": [[0.0, "0B0E17"], [0.55, "2E1524"], [0.85, "571E28"], [1.0, "7A2830"]],
	"gold": [[0.0, "0B0E17"], [0.5, "1E2438"], [0.8, "4A3A22"], [1.0, "8A6428"]],
	"noon": [[0.0, "0B0E17"], [0.4, "1A2440"], [0.7, "3A4A7C"], [1.0, "C97B4A"]],
	"port": [[0.0, "0B0E17"], [0.45, "1A2030"], [0.75, "3A3230"], [1.0, "5C4630"]],
	"dead": [[0.0, "120A0D"], [0.55, "1E1216"], [1.0, "331A20"]],
}

## tokens.css .sc-night star specks: [x%, y%, px size, alpha], color E9EDF5.
const NIGHT_STARS := [
	[12.0, 18.0, 1.5, 0.8],
	[28.0, 8.0, 1.0, 0.5],
	[45.0, 22.0, 1.0, 0.4],
	[63.0, 10.0, 2.0, 0.7],
	[78.0, 26.0, 1.0, 0.45],
	[90.0, 12.0, 1.5, 0.6],
	[8.0, 40.0, 1.0, 0.3],
]

## tokens.css .horizon clip-path polygon, as [x%, y%] within the bottom band.
const HORIZON_POINTS := [
	[0, 62], [6, 62], [6, 54], [12, 54], [12, 66], [20, 66], [20, 40], [26, 40],
	[26, 30], [30, 30], [30, 40], [36, 40], [36, 58], [44, 58], [44, 46],
	[52, 46], [52, 24], [55, 24], [55, 12], [58, 12], [58, 24], [62, 24],
	[62, 52], [70, 52], [70, 62], [78, 62], [78, 44], [86, 44], [86, 58],
	[100, 58], [100, 100], [0, 100],
]

const _STAR_INK := "E9EDF5"
const _HORIZON_FILL := "080A10"
const _HORIZON_BAND := 0.26  # bottom 26%
const _PLANET_STOPS := [[0.0, "C97B4A"], [0.42, "A8542E"], [0.78, "6E3319"], [1.0, "4A2212"]]


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE


func _draw() -> void:
	var r := Rect2(Vector2.ZERO, size)
	_draw_gradient(r)
	if scene_id != "flat":
		_draw_stars(r)
		if show_planet:
			_draw_planet(r)
		if show_horizon:
			_draw_horizon(r)
		_draw_veil(r)
	_draw_labels(r)


func _draw_gradient(r: Rect2) -> void:
	var stops: Array = GRADIENTS.get(scene_id, [])
	if stops.is_empty():
		# .sc-flat — the pack bg.
		draw_rect(r, theme.bg if theme != null else Color("13161D"))
		return
	var prev_offset: float = stops[0][0]
	var prev_color := Color(stops[0][1])
	draw_rect(Rect2(r.position, Vector2(r.size.x, 1)), prev_color)
	for i: int in range(1, stops.size()):
		var offset: float = stops[i][0]
		var color := Color(stops[i][1])
		# Vertical strip interpolation in N slices keeps the gradient smooth.
		var y_from := r.size.y * prev_offset
		var y_to := r.size.y * offset
		const SLICES := 24
		for s: int in SLICES:
			var t0 := float(s) / SLICES
			var t1 := float(s + 1) / SLICES
			var strip := Rect2(0, y_from + (y_to - y_from) * t0, r.size.x, (y_to - y_from) * (t1 - t0) + 1)
			draw_rect(strip, prev_color.lerp(color, (t0 + t1) * 0.5))
		prev_offset = offset
		prev_color = color


func _draw_stars(r: Rect2) -> void:
	for speck: Array in NIGHT_STARS:
		var pos := Vector2(r.size.x * speck[0] / 100.0, r.size.y * speck[1] / 100.0)
		var side: float = speck[2]
		var c := Color(_STAR_INK)
		c.a = speck[3]
		draw_rect(Rect2(pos - Vector2(side, side) * 0.5, Vector2(side, side)), c)


func _draw_planet(r: Rect2) -> void:
	# 130px radial-gradient circle, top 8% right 10% (tokens.css .planet),
	# with a 44px glow halo behind it.
	var center := Vector2(r.size.x * 0.90 - 65.0, r.size.y * 0.08 + 65.0)
	_draw_radial(center, 87.0, [[0.0, Color("C97B4A"), 0.35], [1.0, Color("C97B4A"), 0.0]])
	_draw_radial(center, 65.0, [[0.0, Color("C97B4A"), 1.0], [0.42, Color("A8542E"), 1.0], [0.78, Color("6E3319"), 1.0], [1.0, Color("4A2212"), 1.0]])


func _draw_radial(center: Vector2, radius: float, stops: Array) -> void:
	# Concentric-ring approximation of a radial gradient (48 rings).
	const RINGS := 48
	for i: int in range(RINGS, 0, -1):
		var t := float(i) / RINGS
		var color: Color = _radial_color(stops, t)
		draw_circle(center, radius * t, color)


static func _radial_color(stops: Array, t: float) -> Color:
	# stops: [offset, hex, alpha?] — alpha defaults to 1.
	if t <= stops[0][0]:
		var c0: Color = Color(stops[0][1])
		c0.a = stops[0][2] if stops[0].size() > 2 else 1.0
		return c0
	var prev: Array = stops[0]
	for i: int in range(1, stops.size()):
		var cur: Array = stops[i]
		if t <= cur[0]:
			var span: float = cur[0] - prev[0]
			var k := (t - prev[0]) / span if span > 0.0 else 1.0
			var a0: float = prev[2] if prev.size() > 2 else 1.0
			var a1: float = cur[2] if cur.size() > 2 else 1.0
			var c: Color = Color(prev[1]).lerp(Color(cur[1]), k)
			c.a = lerpf(a0, a1, k)
			return c
		prev = cur
	var cl: Color = Color(stops[-1][1])
	cl.a = stops[-1][2] if stops[-1].size() > 2 else 1.0
	return cl


func _draw_horizon(r: Rect2) -> void:
	var band_top := r.size.y * (1.0 - _HORIZON_BAND)
	var pts := PackedVector2Array()
	for p: Array in HORIZON_POINTS:
		pts.append(Vector2(r.size.x * p[0] / 100.0, band_top + r.size.y * _HORIZON_BAND * p[1] / 100.0))
	draw_colored_polygon(pts, Color(_HORIZON_FILL))


func _draw_veil(r: Rect2) -> void:
	# .veil-cinema: rgba(8,10,16,.34) → .55 at 60% → .78 at 100%.
	var c := Color("080A10")
	var bands := [[0.0, 0.6, 0.34, 0.55], [0.6, 1.0, 0.55, 0.78]]
	for band: Array in bands:
		var y_from := r.size.y * band[0]
		var y_to := r.size.y * band[1]
		const SLICES := 16
		for s: int in SLICES:
			var t0 := float(s) / SLICES
			var t1 := float(s + 1) / SLICES
			var a := lerpf(band[2], band[3], (t0 + t1) * 0.5)
			var strip := Rect2(0, y_from + (y_to - y_from) * t0, r.size.x, (y_to - y_from) * (t1 - t0) + 1)
			var col := c
			col.a = a
			draw_rect(strip, col)


func _draw_labels(r: Rect2) -> void:
	var accent := theme.accent if theme != null else Color("8FA3C8")
	var muted := theme.muted if theme != null else Color("7E8899")
	if kicker_text != "":
		draw_string(Fonts.micro_tracked(), Vector2(18, 14 + 12), kicker_text, HORIZONTAL_ALIGNMENT_LEFT, -1, 12, accent)
	if footer_text != "":
		draw_string(Fonts.micro_tracked(), Vector2(22, r.size.y - 12), footer_text, HORIZONTAL_ALIGNMENT_LEFT, -1, 12, muted)
```

- [ ] **Step 9: run the theme tests**

Run: `tools/run_client_tests.sh`
Expected: PASS — 5 tests (2 smoke + 3 new), exit 0. (SceneBackdrop has no unit test — its correctness is visual; Task 11's golden baseline covers it. Do not invent one.)

- [ ] **Step 10: lint + format**

Run: `uv run gdformat client/theme client/tests && tools/run_client_lint.sh`
Expected: format rewrites nothing meaningful / lint passes. Re-run tests if gdformat changed files.

- [ ] **Step 11: Commit**

```bash
git add client/theme client/tests/theme
git commit -m "feat(client): M2.2 theme foundations — PackTheme sets, Fonts, SteppedFrame, Dither, SceneBackdrop"
```

---

## Task 3 (M2.3): SidecarProcess — sidecar lifecycle

**Files:**
- Create: `client/engine/paths.gd`, `client/engine/sidecar_process.gd`
- Test: `client/tests/engine/test_sidecar_process.gd` (integration — boots the real server)

**Interfaces:**
- Consumes: Task 1 scaffold; the Step 0 server (`src/server/__main__.py` prints `LISTENING <port>` on stdout, then serves).
- Produces:
  - `Paths.repo_root() -> String` — the repo root (parent of `client/`), globalized.
  - `SidecarProcess` (Node): `spawn()`, `kill()`; signals `booted(base_url: String, port: int)`, `boot_failed(reason: String)`; vars `pid: int`, `port: int`, `base_url: String`, `attached_external: bool`, `log_path: String`.

**Why a log file, not stdio pipes:** parent spec D2 — Godot's `execute_with_pipe` is demonstrably unmaintained upstream (godot#102340, #97423, #111029). The spawn redirects stdout to a log file via `bash -c`; the client polls the file for the `LISTENING <port>` line. The file doubles as the debug log when boot fails.

- [ ] **Step 1: failing test** — create `client/tests/engine/test_sidecar_process.gd` exactly:

```gdscript
extends GdUnitTestSuite
## Integration: boot the real Python sidecar end-to-end (spec §4).
## Each test is self-contained; the server self-exits after 5 idle minutes
## even if a failing assert skips kill().


func test_repo_root_has_pyproject() -> void:
	assert_bool(FileAccess.file_exists(Paths.repo_root().path_join("pyproject.toml"))).is_true()


func test_spawn_listen_health_kill() -> void:
	var sp: SidecarProcess = auto_free(SidecarProcess.new())
	add_child(sp)
	var outcome := {"ok": false, "reason": ""}
	sp.booted.connect(func(_url: String, _p: int) -> void: outcome["ok"] = true)
	sp.boot_failed.connect(func(reason: String) -> void: outcome["reason"] = reason)
	sp.spawn()
	var waited := 0.0
	while not outcome["ok"] and outcome["reason"] == "" and waited < 20.0:
		await get_tree().create_timer(0.1).timeout
		waited += 0.1
	assert_str(outcome["reason"]).is_empty()
	assert_bool(outcome["ok"]).is_true()
	assert_that(sp.port).is_greater(0)
	assert_str(sp.base_url).begins_with("http://127.0.0.1:")
	sp.kill()
	assert_that(sp.pid).is_equal(-1)


func test_env_override_attaches_without_spawning() -> void:
	var first: SidecarProcess = auto_free(SidecarProcess.new())
	add_child(first)
	var outcome := {"ok": false}
	first.booted.connect(func(_url: String, _p: int) -> void: outcome["ok"] = true)
	first.spawn()
	var waited := 0.0
	while not outcome["ok"] and waited < 20.0:
		await get_tree().create_timer(0.1).timeout
		waited += 0.1
	assert_bool(outcome["ok"]).is_true()

	OS.set_environment("ANDROMEDA_SIDECAR_URL", first.base_url)
	var second: SidecarProcess = auto_free(SidecarProcess.new())
	add_child(second)
	var attached := {"ok": false}
	second.booted.connect(func(_url: String, _p: int) -> void: attached["ok"] = true)
	second.spawn()
	waited = 0.0
	while not attached["ok"] and waited < 5.0:
		await get_tree().create_timer(0.1).timeout
		waited += 0.1
	OS.set_environment("ANDROMEDA_SIDECAR_URL", "")
	assert_bool(attached["ok"]).is_true()
	assert_bool(second.attached_external).is_true()
	assert_that(second.pid).is_equal(-1)
	first.kill()
```

- [ ] **Step 2: run tests, verify failure**

Run: `tools/run_client_tests.sh`
Expected: FAIL — `Paths`/`SidecarProcess` unknown.

- [ ] **Step 3: `client/engine/paths.gd`** — create exactly:

```gdscript
class_name Paths
extends RefCounted
## Repo layout (spec §3): client/ is the Godot project; the repo root — where
## `uv run python -m src.server` runs — is its parent directory.


static func repo_root() -> String:
	return ProjectSettings.globalize_path("res://").path_join("..").simplify_path()
```

- [ ] **Step 4: `client/engine/sidecar_process.gd`** — create exactly:

```gdscript
class_name SidecarProcess
extends Node
## Owns the Python sidecar lifecycle (spec §4).
##
## Spawn: `bash -c "cd <repo> && exec uv run python -m src.server --port 0
## > <log> 2>&1"` — the `exec` keeps the returned PID pointed at the server,
## and the log redirect avoids Godot's unmaintained stdio-pipe path (parent
## spec D2). Boot completes when the log prints `LISTENING <port>` and a
## GET /health returns {"status": "ok"} (§A2).
##
## Dev override: ANDROMEDA_SIDECAR_URL=http://127.0.0.1:<port> attaches to an
## already-running server instead of spawning (screen iteration without
## respawn). The server self-exits after 5 idle minutes, so a crashed client
## never leaves a permanent orphan.

signal booted(base_url: String, port: int)
signal boot_failed(reason: String)

const BOOT_TIMEOUT_SEC := 15.0

var pid := -1
var port := 0
var base_url := ""
var attached_external := false
var log_path := ""

var _polling := false
var _elapsed := 0.0
var _health_request: HTTPRequest


func spawn() -> void:
	var override := OS.get_environment("ANDROMEDA_SIDECAR_URL").strip_edges()
	if override != "":
		attached_external = true
		base_url = override.rstrip("/")
		port = int(base_url.get_slice(":", base_url.get_slice_count(":") - 1))
		_health_check()
		return
	log_path = OS.get_cache_dir().path_join("andromeda-sidecar.log")
	var log_file := FileAccess.open(log_path, FileAccess.WRITE)
	if log_file != null:
		log_file.store_string("")
		log_file.close()
	var cmd := "cd %s && exec uv run python -m src.server --port 0 > %s 2>&1" % [
		_sh_quote(Paths.repo_root()), _sh_quote(log_path)
	]
	pid = OS.create_process("bash", ["-c", cmd])
	if pid == -1:
		boot_failed.emit("could not spawn bash — is bash on PATH?")
		return
	_polling = true
	_elapsed = 0.0


func kill() -> void:
	if pid > 0 and not attached_external:
		OS.kill(pid)
	pid = -1


func _exit_tree() -> void:
	kill()


func _process(delta: float) -> void:
	if not _polling:
		return
	_elapsed += delta
	if _elapsed >= BOOT_TIMEOUT_SEC:
		_polling = false
		kill()
		boot_failed.emit(
			"sidecar did not print LISTENING within %ds — see %s" % [BOOT_TIMEOUT_SEC, log_path]
		)
		return
	if not FileAccess.file_exists(log_path):
		return
	var f := FileAccess.open(log_path, FileAccess.READ)
	if f == null:
		return
	var text := f.get_as_text()
	f.close()
	for line: String in text.split("\n"):
		if line.begins_with("LISTENING "):
			var parsed_port := int(line.trim_prefix("LISTENING ").strip_edges())
			if parsed_port > 0:
				port = parsed_port
				base_url = "http://127.0.0.1:%d" % port
				_polling = false
				_health_check()
			return


func _health_check() -> void:
	_health_request = HTTPRequest.new()
	add_child(_health_request)
	_health_request.request_completed.connect(_on_health_completed)
	var err := _health_request.request(base_url + "/health")
	if err != OK:
		_health_request.queue_free()
		boot_failed.emit("health request failed to start: %s" % error_string(err))


func _on_health_completed(result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	_health_request.queue_free()
	if result != HTTPRequest.RESULT_SUCCESS or code != 200:
		boot_failed.emit("health check failed (HTTP %d) at %s — is the sidecar up?" % [code, base_url])
		return
	var parsed: Variant = JSON.parse_string(body.get_string_from_utf8())
	if not (parsed is Dictionary) or parsed.get("status") != "ok":
		boot_failed.emit("health check returned an unexpected body at %s" % base_url)
		return
	booted.emit(base_url, port)


static func _sh_quote(s: String) -> String:
	return "'" + s.replace("'", "'\\''") + "'"
```

- [ ] **Step 5: run tests, verify pass**

Run: `tools/run_client_tests.sh`
Expected: PASS — the two integration tests boot the real server (each takes ~2-5s; total suite now 7 tests).

- [ ] **Step 6: lint, format, commit**

Run: `uv run gdformat client/engine client/tests && tools/run_client_lint.sh && tools/run_client_tests.sh`
Expected: all pass.

```bash
git add client/engine client/tests/engine
git commit -m "feat(client): M2.3 SidecarProcess — spawn/handshake/health/kill + env override"
```

---

## Task 4 (M2.4): EngineClient — typed v1 API client + SessionStore

**Files:**
- Create: `client/engine/engine_result.gd`, `client/engine/engine_client.gd`, `client/engine/session_store.gd`
- Test: `client/tests/engine/test_engine_client.gd` (integration — real sidecar, one boot per suite)

**Interfaces:**
- Consumes: Task 3 `SidecarProcess`; §A1–A8 shapes.
- Produces:
  - `EngineResult` (RefCounted): `ok: bool`, `status: int`, `data: Dictionary`, `error_code: String`, `error_message: String`; statics `ok_result(status, data)`, `err_result(status, code, message)`.
  - `EngineClient` (Node): `setup(base_url: String)`, `refresh_contracts() -> EngineResult`, `contract_matches(session: Dictionary) -> bool`, `contract_chargen: int`, `contract_adventure: int`; one async method per route (full list below), each `-> EngineResult`.
  - `SessionStore` (autoload script, **no class_name**): `current: Dictionary`, `has_session()`, `set_current(session)`, `clear()`, `session_id() -> String`; `signal session_changed(session: Dictionary)`.

**Method surface (pin — every route from §A2–A8):**

| group | methods |
|-------|---------|
| meta | `health()` · `llm_status()` |
| config | `list_packs()` · `list_rulesets()` · `list_providers()` |
| settings | `get_settings()` · `put_settings(payload: Dictionary)` · `test_settings()` |
| saves | `list_saves()` · `delete_save(name)` · `duplicate_save(name, new_name)` · `export_save(name)` · `import_save(name, document: Dictionary)` |
| sessions | `create_session(payload: Dictionary)` · `resume_session(from_save)` · `list_sessions()` · `get_session(id)` · `delete_session(id)` · `choose(id, option_id, origin := "player")` · `freetext(id, text)` · `suggest(id)` · `set_name(id, name)` · `promote(id)` · `save_session(id, name)` |
| inspect | `recap(id)` — the rest (`sheet`/`memorial`/`audit`/`llm_context`/`odds`/`state_hash`/`verify`) are thin wrappers for M4, integration-tested there (spec §4 note) |

Per-call `HTTPRequest` allocation (create → await → free), not a pool: the client issues at most a few requests per second and pooling buys nothing but lifecycle bugs. This refines spec §4's "small pool" wording — same guarantee, simpler code.

- [ ] **Step 1: failing integration test** — create `client/tests/engine/test_engine_client.gd` exactly:

```gdscript
extends GdUnitTestSuite
## EngineClient integration against the real sidecar (one boot per suite).
##
## SAFETY: never send `provider` or `api_key` changes from tests — a provider
## switch deletes the stored key server-side (§A7). The settings roundtrip
## below touches max_retries only.

var _sidecar: SidecarProcess
var _client: EngineClient


func before_all() -> void:
	_sidecar = SidecarProcess.new()
	add_child(_sidecar)
	var outcome := {"ok": false, "reason": ""}
	_sidecar.booted.connect(func(_url: String, _p: int) -> void: outcome["ok"] = true)
	_sidecar.boot_failed.connect(func(reason: String) -> void: outcome["reason"] = reason)
	_sidecar.spawn()
	var waited := 0.0
	while not outcome["ok"] and outcome["reason"] == "" and waited < 20.0:
		await get_tree().create_timer(0.1).timeout
		waited += 0.1
	if outcome["reason"] != "":
		push_error("sidecar boot failed: " + outcome["reason"])
	_client = EngineClient.new()
	add_child(_client)
	_client.setup(_sidecar.base_url)


func after_all() -> void:
	_sidecar.kill()


func _unique_name() -> String:
	return "m2-itest-%d" % int(Time.get_unix_time_from_system() * 1000.0)


func test_health_and_contracts() -> void:
	var res: EngineResult = await _client.refresh_contracts()
	assert_bool(res.ok).is_true()
	assert_str(str(res.data.get("status"))).is_equal("ok")
	assert_that(_client.contract_chargen).is_equal(1)
	assert_that(_client.contract_adventure).is_equal(1)


func test_llm_status_shape() -> void:
	var res: EngineResult = await _client.llm_status()
	assert_bool(res.ok).is_true()
	# configured depends on the machine's key store — assert shape, not value.
	assert_bool(res.data.has("configured")).is_true()
	assert_bool(res.data.has("key_backend")).is_true()
	if not bool(res.data["configured"]):
		assert_str(str(res.data["degraded_line"])).is_equal(
			"narration unavailable — showing mechanical outcomes"
		)


func test_config_packs() -> void:
	var res: EngineResult = await _client.list_packs()
	assert_bool(res.ok).is_true()
	var by_id := {}
	for pack: Dictionary in res.data["packs"]:
		by_id[pack["id"]] = pack
	assert_bool(by_id.has("scifi")).is_true()
	assert_bool(by_id.has("fantasy")).is_true()
	var scifi: Dictionary = by_id["scifi"]
	assert_that(int(scifi["career_count"])).is_equal(25)
	assert_bool(bool(scifi["has_cascades"])).is_true()
	assert_str(str(scifi["theme"]["motif"])).is_equal("✦")
	assert_str(str(scifi["theme"]["accent"])).is_equal("amber")
	assert_that(Array(scifi["theme"]["ambience"])).is_equal(["meteors", "birds"])


func test_config_rulesets_and_providers() -> void:
	var rules: EngineResult = await _client.list_rulesets()
	assert_bool(rules.ok).is_true()
	var cepheus: Dictionary = rules.data["rulesets"][0]
	assert_that(Array(cepheus["resolution_profiles"])).is_equal(["classic", "narrative"])
	var death_modes := Array(cepheus["death_modes"])
	death_modes.sort()
	assert_that(death_modes).is_equal(["checkpoint", "ironman", "narrative"])

	var providers: EngineResult = await _client.list_providers()
	assert_bool(providers.ok).is_true()
	var by_id := {}
	for p: Dictionary in providers.data["providers"]:
		by_id[p["id"]] = p
	assert_str(str(by_id["anthropic"]["label"])).is_equal("Anthropic")
	assert_bool(Array(by_id["anthropic"]["presets"]).has("claude-sonnet-5")).is_true()


func test_settings_roundtrip_max_retries_only() -> void:
	var before: EngineResult = await _client.get_settings()
	assert_bool(before.ok).is_true()
	var original := int(before.data["max_retries"])
	var payload := before.data.duplicate()
	payload["max_retries"] = original + 1
	payload.erase("is_configured")
	payload.erase("key_backend")
	payload.erase("key_tail")
	payload["api_key"] = null  # keep the stored key (§A7)
	var put: EngineResult = await _client.put_settings(payload)
	assert_bool(put.ok).is_true()
	assert_that(int(put.data["max_retries"])).is_equal(original + 1)
	payload["max_retries"] = original
	var restored: EngineResult = await _client.put_settings(payload)
	assert_bool(restored.ok).is_true()
	assert_that(int(restored.data["max_retries"])).is_equal(original)


func test_settings_test_endpoint_never_raises() -> void:
	var res: EngineResult = await _client.test_settings()
	assert_bool(res.ok).is_true()  # transport ok; body carries ok:true/false
	assert_bool(res.data.has("ok")).is_true()
	if not bool(res.data["ok"]):
		assert_str(str(res.data["error"])).is_not_empty()


func test_session_lifecycle_and_envelope() -> void:
	var name := _unique_name()
	var created: EngineResult = await _client.create_session(
		{"kind": "chargen", "name": name, "seed": 482991, "pack_id": "scifi"}
	)
	assert_bool(created.ok).is_true()
	var session: Dictionary = created.data["session"]
	for key: String in ["id", "name", "kind", "phase", "view", "contract_version"]:
		assert_bool(session.has(key)).is_true()
	assert_str(session["kind"]).is_equal("chargen")
	assert_that(int(session["contract_version"])).is_equal(1)
	assert_bool(_client.contract_matches(session)).is_true()
	# §A3: chargen view is a ChoicePointView.
	var view: Dictionary = session["view"]
	assert_bool(view.has("choice_id")).is_true()
	assert_bool(view.has("options")).is_true()
	assert_bool(not Array(view["options"]).is_empty()).is_true()

	var fetched: EngineResult = await _client.get_session(session["id"])
	assert_bool(fetched.ok).is_true()
	var deleted: EngineResult = await _client.delete_session(session["id"])
	assert_bool(deleted.ok).is_true()
	var gone: EngineResult = await _client.get_session(session["id"])
	assert_bool(gone.ok).is_false()
	assert_that(gone.status).is_equal(404)
	assert_str(gone.error_code).is_equal("session_not_found")
	assert_str(gone.error_message).is_not_empty()


func test_saves_crud_cycle() -> void:
	var name := _unique_name()
	var created: EngineResult = await _client.create_session({"kind": "chargen", "name": name})
	assert_bool(created.ok).is_true()
	var session_id := str(created.data["session"]["id"])
	# GET forces the autosave to disk (routes_sessions.py:133).
	await _client.get_session(session_id)

	var saves: EngineResult = await _client.list_saves()
	assert_bool(saves.ok).is_true()
	var entry := {}
	for s: Dictionary in saves.data["saves"]:
		if s["base_name"] == name:
			entry = s
	assert_bool(not entry.is_empty()).is_true()
	assert_bool(bool(entry["autosave"])).is_true()
	assert_str(str(entry["theme_pack"])).is_equal("scifi")
	assert_bool(bool(entry["alive"])).is_true()

	var dup: EngineResult = await _client.duplicate_save(name, name + "-copy")
	assert_bool(dup.ok).is_true()
	assert_bool(not Array(dup.data["created"]).is_empty()).is_true()

	var exported: EngineResult = await _client.export_save(name)
	assert_bool(exported.ok).is_true()
	assert_bool(int(exported.data.get("save_version", 0)) >= 1).is_true()

	var imported: EngineResult = await _client.import_save(name + "-imp", exported.data)
	assert_bool(imported.ok).is_true()
	assert_str(str(imported.data["name"])).is_equal(name + "-imp")

	var conflict: EngineResult = await _client.import_save(name + "-imp", exported.data)
	assert_bool(conflict.ok).is_false()
	assert_str(conflict.error_code).is_equal("save_conflict")

	assert_bool((await _client.delete_save(name + "-imp")).ok).is_true()
	assert_bool((await _client.delete_save(name + "-copy")).ok).is_true()
	assert_bool((await _client.delete_save(name)).ok).is_true()
	var missing: EngineResult = await _client.delete_save(name)
	assert_bool(missing.ok).is_false()
	assert_str(missing.error_code).is_equal("save_not_found")
	await _client.delete_session(session_id)


func test_resume_infers_kind() -> void:
	var name := _unique_name()
	var created: EngineResult = await _client.create_session({"kind": "chargen", "name": name})
	assert_bool(created.ok).is_true()
	await _client.get_session(created.data["session"]["id"])  # autosave
	var resumed: EngineResult = await _client.resume_session(name)
	assert_bool(resumed.ok).is_true()
	assert_str(str(resumed.data["session"]["kind"])).is_equal("chargen")
	await _client.delete_session(resumed.data["session"]["id"])
	await _client.delete_session(created.data["session"]["id"])
	await _client.delete_save(name)


func test_choose_returns_events() -> void:
	var name := _unique_name()
	var created: EngineResult = await _client.create_session({"kind": "chargen", "name": name, "seed": 7})
	assert_bool(created.ok).is_true()
	var session: Dictionary = created.data["session"]
	var options: Array = session["view"]["options"]
	var option_id := str(options[0]["option_id"])
	var chosen: EngineResult = await _client.choose(session["id"], option_id)
	assert_bool(chosen.ok).is_true()
	assert_bool(chosen.data.has("session")).is_true()
	assert_bool(chosen.data.has("result")).is_true()
	assert_bool(chosen.data.has("events")).is_true()
	for e: Dictionary in chosen.data["events"]:
		for key: String in ["seq", "kind", "command_type", "description", "changes"]:
			assert_bool(e.has(key)).is_true()
	await _client.delete_session(session["id"])
	await _client.delete_save(name)


func test_freetext_and_suggest_envelopes() -> void:
	var name := _unique_name()
	var created: EngineResult = await _client.create_session({"kind": "chargen", "name": name})
	var session_id := str(created.data["session"]["id"])
	var ft: EngineResult = await _client.freetext(session_id, "a wandering scout")
	# Without a configured translator: 422 translator_unavailable. With one:
	# ok. Accept either; assert the envelope is well-formed.
	if not ft.ok:
		assert_str(ft.error_code).is_equal("translator_unavailable")
		assert_str(ft.error_message).is_not_empty()
	var sg: EngineResult = await _client.suggest(session_id)
	if not sg.ok:
		assert_str(sg.error_code).is_equal("advisor_unavailable")
		assert_str(sg.error_message).is_not_empty()
	await _client.delete_session(session_id)
	await _client.delete_save(name)
```

- [ ] **Step 2: run tests, verify failure**

Run: `tools/run_client_tests.sh`
Expected: FAIL — `EngineClient`/`EngineResult` unknown (parse error in the suite).

- [ ] **Step 3: `client/engine/engine_result.gd`** — create exactly:

```gdscript
class_name EngineResult
extends RefCounted
## The result of one EngineClient call. On HTTP success: ok=true, data = the
## parsed body. On any failure: ok=false with the server's error envelope
## (§A1) parsed into error_code/error_message — transport failures use
## error_code "transport_error" and a fixed cockpit-voice message.

var ok := false
var status := 0
var data: Dictionary = {}
var error_code := ""
var error_message := ""


static func ok_result(p_status: int, p_data: Dictionary) -> EngineResult:
	var r := EngineResult.new()
	r.ok = true
	r.status = p_status
	r.data = p_data
	return r


static func err_result(p_status: int, p_code: String, p_message: String) -> EngineResult:
	var r := EngineResult.new()
	r.ok = false
	r.status = p_status
	r.error_code = p_code
	r.error_message = p_message
	return r
```

- [ ] **Step 4: `client/engine/engine_client.gd`** — create exactly:

```gdscript
class_name EngineClient
extends Node
## Typed async client for the v1 sidecar API (§A1–A8). One method per route;
## every method returns an EngineResult. The error envelope is parsed exactly
## once, in _request. One HTTPRequest node per call — a few requests/second
## never justifies pool lifecycle risk.

var base_url := ""
var contract_chargen := 0
var contract_adventure := 0
## Round-trip time of the last request, for the settings latency line.
var last_rtt_ms := 0


func setup(p_base_url: String) -> void:
	base_url = p_base_url


# --- core ------------------------------------------------------------------


func _request(method: HTTPClient.Method, path: String, body: Variant = null) -> EngineResult:
	var req := HTTPRequest.new()
	add_child(req)
	var headers := PackedStringArray()
	var payload := ""
	if body != null:
		headers.append("Content-Type: application/json")
		payload = JSON.stringify(body)
	var start := Time.get_ticks_msec()
	var err := req.request(base_url + path, headers, method, payload)
	if err != OK:
		req.queue_free()
		return EngineResult.err_result(
			0, "transport_error", "could not reach the referee — is the sidecar running?"
		)
	var completed: Array = await req.request_completed
	req.queue_free()
	last_rtt_ms = Time.get_ticks_msec() - start
	var result: int = completed[0]
	var code: int = completed[1]
	var raw: PackedByteArray = completed[3]
	if result != HTTPRequest.RESULT_SUCCESS:
		return EngineResult.err_result(
			0, "transport_error", "could not reach the referee — is the sidecar running?"
		)
	if code == 204:
		return EngineResult.ok_result(code, {})
	var text := raw.get_string_from_utf8()
	var parsed: Variant = JSON.parse_string(text)
	if parsed == null:
		return EngineResult.err_result(
			code, "bad_response", "the referee answered with something unreadable"
		)
	if code >= 400:
		if parsed is Dictionary and parsed.has("error"):
			var envelope: Dictionary = parsed["error"]
			return EngineResult.err_result(
				code, str(envelope.get("code", "unknown")), str(envelope.get("message", ""))
			)
		return EngineResult.err_result(code, "http_%d" % code, text)
	if parsed is Dictionary:
		return EngineResult.ok_result(code, parsed)
	return EngineResult.ok_result(code, {"value": parsed})


func _enc(value: String) -> String:
	return value.uri_encode()


# --- contract ---------------------------------------------------------------


func refresh_contracts() -> EngineResult:
	var res: EngineResult = await health()
	if res.ok:
		var versions: Dictionary = res.data.get("contract_versions", {})
		contract_chargen = int(versions.get("chargen", 0))
		contract_adventure = int(versions.get("adventure", 0))
	return res


## True when the SessionEnvelope's contract_version matches /health (§A2/A3).
func contract_matches(session: Dictionary) -> bool:
	var version := int(session.get("contract_version", -1))
	match str(session.get("kind", "")):
		"chargen":
			return version == contract_chargen
		"adventure":
			return version == contract_adventure
	return false


# --- meta (§A2) -------------------------------------------------------------


func health() -> EngineResult:
	return await _request(HTTPClient.METHOD_GET, "/health")


func llm_status() -> EngineResult:
	return await _request(HTTPClient.METHOD_GET, "/v1/llm/status")


# --- config (§A6) -----------------------------------------------------------


func list_packs() -> EngineResult:
	return await _request(HTTPClient.METHOD_GET, "/v1/config/packs")


func list_rulesets() -> EngineResult:
	return await _request(HTTPClient.METHOD_GET, "/v1/config/rulesets")


func list_providers() -> EngineResult:
	return await _request(HTTPClient.METHOD_GET, "/v1/config/providers")


# --- settings (§A7) ---------------------------------------------------------


func get_settings() -> EngineResult:
	return await _request(HTTPClient.METHOD_GET, "/v1/settings/llm")


func put_settings(payload: Dictionary) -> EngineResult:
	return await _request(HTTPClient.METHOD_PUT, "/v1/settings/llm", payload)


func test_settings() -> EngineResult:
	return await _request(HTTPClient.METHOD_POST, "/v1/settings/llm/test", {})


# --- saves (§A5) ------------------------------------------------------------


func list_saves() -> EngineResult:
	return await _request(HTTPClient.METHOD_GET, "/v1/saves")


func delete_save(save_name: String) -> EngineResult:
	return await _request(HTTPClient.METHOD_DELETE, "/v1/saves/" + _enc(save_name))


func duplicate_save(save_name: String, new_name: String) -> EngineResult:
	return await _request(
		HTTPClient.METHOD_POST, "/v1/saves/" + _enc(save_name) + "/duplicate", {"new_name": new_name}
	)


func export_save(save_name: String) -> EngineResult:
	return await _request(HTTPClient.METHOD_GET, "/v1/saves/" + _enc(save_name) + "/export")


func import_save(save_name: String, document: Dictionary) -> EngineResult:
	return await _request(
		HTTPClient.METHOD_POST, "/v1/saves/import", {"name": save_name, "document": document}
	)


# --- sessions (§A3) ---------------------------------------------------------


func create_session(payload: Dictionary) -> EngineResult:
	return await _request(HTTPClient.METHOD_POST, "/v1/sessions", payload)


func resume_session(from_save: String) -> EngineResult:
	return await _request(HTTPClient.METHOD_POST, "/v1/sessions", {"from_save": from_save})


func list_sessions() -> EngineResult:
	return await _request(HTTPClient.METHOD_GET, "/v1/sessions")


func get_session(id: String) -> EngineResult:
	return await _request(HTTPClient.METHOD_GET, "/v1/sessions/" + _enc(id))


func delete_session(id: String) -> EngineResult:
	return await _request(HTTPClient.METHOD_DELETE, "/v1/sessions/" + _enc(id))


func choose(id: String, option_id: String, origin := "player") -> EngineResult:
	return await _request(
		HTTPClient.METHOD_POST,
		"/v1/sessions/" + _enc(id) + "/choose",
		{"option_id": option_id, "origin": origin}
	)


func freetext(id: String, text: String) -> EngineResult:
	return await _request(
		HTTPClient.METHOD_POST, "/v1/sessions/" + _enc(id) + "/freetext", {"text": text}
	)


func suggest(id: String) -> EngineResult:
	return await _request(HTTPClient.METHOD_POST, "/v1/sessions/" + _enc(id) + "/suggest", {})


func set_name(id: String, char_name: String) -> EngineResult:
	return await _request(
		HTTPClient.METHOD_POST, "/v1/sessions/" + _enc(id) + "/name", {"name": char_name}
	)


func promote(id: String) -> EngineResult:
	return await _request(HTTPClient.METHOD_POST, "/v1/sessions/" + _enc(id) + "/promote", {})


func save_session(id: String, save_name: String) -> EngineResult:
	return await _request(
		HTTPClient.METHOD_POST, "/v1/sessions/" + _enc(id) + "/save", {"name": save_name}
	)


# --- inspect (§A8) ----------------------------------------------------------


func recap(id: String) -> EngineResult:
	return await _request(HTTPClient.METHOD_GET, "/v1/sessions/" + _enc(id) + "/recap")


func sheet(id: String) -> EngineResult:
	return await _request(HTTPClient.METHOD_GET, "/v1/sessions/" + _enc(id) + "/sheet")


func memorial(id: String) -> EngineResult:
	return await _request(HTTPClient.METHOD_GET, "/v1/sessions/" + _enc(id) + "/memorial")


func audit(id: String, params: Dictionary) -> EngineResult:
	var query := PackedStringArray()
	for key: String in ["kind", "stream", "since", "page", "per_page"]:
		if params.has(key) and str(params[key]) != "":
			query.append("%s=%s" % [key, str(params[key]).uri_encode()])
	var path := "/v1/sessions/" + _enc(id) + "/audit"
	if not query.is_empty():
		path += "?" + "&".join(query)
	return await _request(HTTPClient.METHOD_GET, path)


func llm_context(id: String) -> EngineResult:
	return await _request(HTTPClient.METHOD_GET, "/v1/sessions/" + _enc(id) + "/llm-context")


func odds(id: String, skill: String, characteristic: String, difficulty: String) -> EngineResult:
	return await _request(
		HTTPClient.METHOD_POST,
		"/v1/sessions/" + _enc(id) + "/odds",
		{"skill": skill, "characteristic": characteristic, "difficulty": difficulty}
	)


func state_hash(id: String) -> EngineResult:
	return await _request(HTTPClient.METHOD_GET, "/v1/sessions/" + _enc(id) + "/hash")


func verify(id: String) -> EngineResult:
	return await _request(HTTPClient.METHOD_POST, "/v1/sessions/" + _enc(id) + "/verify", {})
```

- [ ] **Step 5: `client/engine/session_store.gd`** — create exactly (**no class_name** — becomes the `SessionStore` autoload in Task 6):

```gdscript
extends Node
## Autoload: SessionStore — the in-memory SessionRef (spec §4). Holds zero
## game truth: the current SessionEnvelope (§A3) and nothing else. Any
## reconnect re-fetches GET /v1/sessions/{id} via EngineClient.

signal session_changed(session: Dictionary)

var current: Dictionary = {}


func has_session() -> bool:
	return not current.is_empty()


func set_current(session: Dictionary) -> void:
	current = session
	session_changed.emit(current)


func clear() -> void:
	current = {}
	session_changed.emit(current)


func session_id() -> String:
	return str(current.get("id", ""))
```

- [ ] **Step 6: run tests, verify pass**

Run: `tools/run_client_tests.sh`
Expected: PASS (suite now ~17 tests; one sidecar boot for this file).

- [ ] **Step 7: lint, format, commit**

Run: `uv run gdformat client/engine client/tests && tools/run_client_lint.sh && tools/run_client_tests.sh`

```bash
git add client/engine client/tests/engine
git commit -m "feat(client): M2.4 EngineClient — typed v1 surface, envelope parsing, SessionStore"
```

---

## Task 5 (M2.5): StreamPump — NDJSON narration stream

**Files:**
- Create: `client/engine/stream_pump.gd`
- Test: `client/tests/engine/test_stream_pump.gd` (integration — real `world_intro` beat, template mode)

**Interfaces:**
- Consumes: Task 3 `SidecarProcess`, Task 4 `EngineClient`; §A4 block protocol.
- Produces: `StreamPump` (Node): `start(base_url: String, session_id: String, beat := "scene", steering := "")`, `stop()`; signals `block_received(block_type: String, content: String)`, `stream_finished()`, `stream_failed(message: String)`; `const BLOCK_TYPES := ["narration", "change", "badge", "done"]`.

**Why HTTPClient, not HTTPRequest:** `HTTPRequest` buffers the whole body — it cannot stream chunked NDJSON. `HTTPClient` exposes `read_response_body_chunk()`. Polling happens in `_process` (no threads).

**Byte-level framing (pin):** the buffer is a `PackedByteArray`, split on byte `10` (`\n`). Never decode chunks to String before splitting — a chunk boundary can fall inside a UTF-8 multibyte character (prose carries em-dashes and non-ASCII glyphs), and `get_string_from_utf8` on a partial sequence corrupts it. `\n` never appears inside a UTF-8 multibyte sequence, so byte-splitting is safe.

- [ ] **Step 1: failing integration test** — create `client/tests/engine/test_stream_pump.gd` exactly:

```gdscript
extends GdUnitTestSuite
## StreamPump integration: a real world_intro beat over NDJSON (§A4).
## The server runs unconfigured → template narration — same block types.

var _sidecar: SidecarProcess
var _client: EngineClient


func before_all() -> void:
	_sidecar = SidecarProcess.new()
	add_child(_sidecar)
	var outcome := {"ok": false}
	_sidecar.booted.connect(func(_url: String, _p: int) -> void: outcome["ok"] = true)
	_sidecar.spawn()
	var waited := 0.0
	while not outcome["ok"] and waited < 20.0:
		await get_tree().create_timer(0.1).timeout
		waited += 0.1
	if not outcome["ok"]:
		push_error("sidecar failed to boot")
	_client = EngineClient.new()
	add_child(_client)
	_client.setup(_sidecar.base_url)


func after_all() -> void:
	_sidecar.kill()


func _new_session() -> Dictionary:
	var name := "m2-pump-%d" % int(Time.get_unix_time_from_system() * 1000.0)
	var created: EngineResult = await _client.create_session(
		{"kind": "chargen", "name": name, "seed": 99, "pack_id": "scifi"}
	)
	return created.data["session"]


func _cleanup(session_id: String, save_name: String) -> void:
	await _client.delete_session(session_id)
	await _client.delete_save(save_name)


func test_world_intro_streams_the_block_sequence() -> void:
	var session := await _new_session()
	var pump: StreamPump = auto_free(StreamPump.new())
	add_child(pump)
	var blocks: Array = []
	var state := {"finished": false, "failed": ""}
	pump.block_received.connect(func(t: String, c: String) -> void: blocks.append([t, c]))
	pump.stream_finished.connect(func() -> void: state["finished"] = true)
	pump.stream_failed.connect(func(msg: String) -> void: state["failed"] = msg)
	pump.start(_sidecar.base_url, session["id"], "world_intro")
	var waited := 0.0
	while not state["finished"] and state["failed"] == "" and waited < 30.0:
		await get_tree().create_timer(0.1).timeout
		waited += 0.1
	assert_str(state["failed"]).is_empty()
	assert_bool(state["finished"]).is_true()
	# §A4: ≥1 narration, types only from BLOCK_TYPES, exactly one done, last.
	assert_bool(blocks.size() >= 2).is_true()
	var types := blocks.map(func(b: Array) -> String: return b[0])
	for t: String in types:
		assert_bool(t in StreamPump.BLOCK_TYPES).is_true()
	assert_str(types[0]).is_equal("narration")
	assert_str(types[-1]).is_equal("done")
	assert_that(types.count("done")).is_equal(1)
	for b: Array in blocks:
		if b[0] == "narration":
			assert_str(b[1]).is_not_empty()
		if b[0] == "badge":
			assert_bool(
				b[1] in ["narration unavailable — showing mechanical outcomes", "connection lost — template narration"]
			).is_true()
	await _cleanup(session["id"], session["name"])


func test_stop_midstream_is_silent() -> void:
	var session := await _new_session()
	var pump: StreamPump = auto_free(StreamPump.new())
	add_child(pump)
	var blocks: Array = []
	var finished := {"called": false}
	pump.block_received.connect(func(t: String, _c: String) -> void: blocks.append(t))
	pump.stream_finished.connect(func() -> void: finished["called"] = true)
	pump.start(_sidecar.base_url, session["id"], "world_intro")
	var waited := 0.0
	while blocks.is_empty() and waited < 30.0:
		await get_tree().create_timer(0.1).timeout
		waited += 0.1
	assert_bool(not blocks.is_empty()).is_true()
	pump.stop()
	var count_at_stop := blocks.size()
	await get_tree().create_timer(0.5).timeout
	assert_that(blocks.size()).is_equal(count_at_stop)
	assert_bool(finished["called"]).is_false()
	await _cleanup(session["id"], session["name"])


func test_unknown_session_fails_with_engine_message() -> void:
	var pump: StreamPump = auto_free(StreamPump.new())
	add_child(pump)
	var state := {"failed": ""}
	pump.stream_failed.connect(func(msg: String) -> void: state["failed"] = msg)
	pump.start(_sidecar.base_url, "no-such-session", "world_intro")
	var waited := 0.0
	while state["failed"] == "" and waited < 15.0:
		await get_tree().create_timer(0.1).timeout
		waited += 0.1
	assert_str(state["failed"]).is_not_empty()
```

- [ ] **Step 2: run tests, verify failure**

Run: `tools/run_client_tests.sh`
Expected: FAIL — `StreamPump` unknown.

- [ ] **Step 3: `client/engine/stream_pump.gd`** — create exactly:

```gdscript
class_name StreamPump
extends Node
## NDJSON narration stream reader (§A4) on the low-level HTTPClient —
## HTTPRequest buffers whole bodies and cannot stream. Polls in _process;
## no threads.
##
## Wire format: one JSON object per line, {"type": ..., "content": ...};
## block types are exactly narration | change | badge | done; `done` is
## always last; the server closes the body after it (routes_sessions.py:387-394).
## Pre-stream errors (e.g. 404 session_not_found) arrive as the HTTP error
## envelope (§A1) — surfaced via stream_failed with the engine's message
## verbatim.

signal block_received(block_type: String, content: String)
signal stream_finished
signal stream_failed(message: String)

const BLOCK_TYPES := ["narration", "change", "badge", "done"]
const _TRANSPORT_MESSAGE := "could not reach the referee — is the sidecar running?"

enum State { IDLE, CONNECTING, REQUESTING, READING_BODY }

var _http := HTTPClient.new()
var _state: int = State.IDLE
var _buffer := PackedByteArray()
var _resp_code := 0
var _path := ""
var _body := ""


func start(base_url: String, session_id: String, beat := "scene", steering := "") -> void:
	stop()
	var rest := base_url.trim_prefix("http://").trim_prefix("https://")
	var host := rest
	var p := 80
	if rest.contains(":"):
		host = rest.get_slice(":", 0)
		p = int(rest.get_slice(":", 1))
	var err := _http.connect_to_host(host, p)
	if err != OK:
		stream_failed.emit(_TRANSPORT_MESSAGE)
		return
	_path = "/v1/sessions/%s/narrate" % session_id.uri_encode()
	_body = JSON.stringify({"beat": beat, "steering": steering})
	_resp_code = 0
	_state = State.CONNECTING


## Close-on-skip: closes the connection without emitting stream_finished.
func stop() -> void:
	if _state != State.IDLE:
		_http.close()
	_state = State.IDLE
	_buffer = PackedByteArray()


func _exit_tree() -> void:
	stop()


func _process(_delta: float) -> void:
	if _state == State.IDLE:
		return
	_http.poll()
	match _state:
		State.CONNECTING:
			match _http.get_status():
				HTTPClient.STATUS_CONNECTED:
					_send_request()
				HTTPClient.STATUS_CANT_CONNECT, HTTPClient.STATUS_CONNECTION_ERROR:
					_fail_transport()
		State.REQUESTING:
			match _http.get_status():
				HTTPClient.STATUS_BODY:
					_resp_code = _http.get_response_code()
					_state = State.READING_BODY
					_read_chunks()
				HTTPClient.STATUS_CONNECTION_ERROR, HTTPClient.STATUS_CANT_CONNECT:
					_fail_transport()
		State.READING_BODY:
			_read_chunks()


func _send_request() -> void:
	var headers := PackedStringArray(["Content-Type: application/json"])
	var err := _http.request(HTTPClient.METHOD_POST, _path, headers, _body)
	if err != OK:
		_fail_transport()
		return
	_state = State.REQUESTING


func _read_chunks() -> void:
	while _http.get_status() == HTTPClient.STATUS_BODY:
		var chunk := _http.read_response_body_chunk()
		if chunk.size() == 0:
			break
		_buffer.append_array(chunk)
		_drain_lines()
	match _http.get_status():
		HTTPClient.STATUS_DISCONNECTED:
			# Body closed by the server — the stream is over.
			if _resp_code == 200:
				_drain_lines(true)
				_state = State.IDLE
				stream_finished.emit()
			else:
				_fail_with_envelope()
		HTTPClient.STATUS_CONNECTION_ERROR:
			_fail_transport()


func _drain_lines(flush_partial := false) -> void:
	while true:
		var idx := -1
		for i: int in _buffer.size():
			if _buffer[i] == 10:  # '\n'
				idx = i
				break
		if idx == -1:
			break
		var line := _buffer.slice(0, idx).get_string_from_utf8()
		_buffer = _buffer.slice(idx + 1)
		_emit_line(line)
	if flush_partial and not _buffer.is_empty():
		_emit_line(_buffer.get_string_from_utf8())
		_buffer = PackedByteArray()


func _emit_line(line: String) -> void:
	var stripped := line.strip_edges()
	if stripped == "":
		return
	var parsed: Variant = JSON.parse_string(stripped)
	if not (parsed is Dictionary):
		return  # malformed line — skip; the stream continues
	var block_type := str(parsed.get("type", ""))
	var content := str(parsed.get("content", ""))
	if block_type in BLOCK_TYPES:
		block_received.emit(block_type, content)


func _fail_transport() -> void:
	_http.close()
	_state = State.IDLE
	stream_failed.emit(_TRANSPORT_MESSAGE)


## Non-200 before/at the stream: the body is the §A1 error envelope.
func _fail_with_envelope() -> void:
	var text := _buffer.get_string_from_utf8()
	_buffer = PackedByteArray()
	_state = State.IDLE
	var message := "the referee answered with something unreadable"
	var parsed: Variant = JSON.parse_string(text)
	if parsed is Dictionary and parsed.has("error"):
		message = str(parsed["error"].get("message", message))
	stream_failed.emit(message)
```

- [ ] **Step 4: run tests, verify pass**

Run: `tools/run_client_tests.sh`
Expected: PASS (suite now ~20 tests).

- [ ] **Step 5: lint, format, commit**

Run: `uv run gdformat client/engine client/tests && tools/run_client_lint.sh && tools/run_client_tests.sh`

```bash
git add client/engine/stream_pump.gd client/tests/engine/test_stream_pump.gd
git commit -m "feat(client): M2.5 StreamPump — NDJSON narration stream over HTTPClient"
```

---

## Task 6 (M2.6): App shell — autoloads, ScreenStack, overlay, strip, kit, boot

**Files:**
- Create: `client/app/services.gd`, `client/app/client_settings.gd`, `client/app/base_screen.gd`, `client/app/screen_stack.gd`, `client/app/overlay_layer.gd`, `client/components/toast.gd`, `client/app/status_strip.gd`, `client/components/kit.gd`
- Modify: `client/app/main.gd` (replace placeholder), `client/app/main.tscn` (unchanged — already points at main.gd), `client/project.godot` (append `[autoload]`)
- Create: `client/tests/engine/fake_engine_client.gd`
- Test: `client/tests/app/test_screen_stack.gd`, `client/tests/app/test_client_settings.gd`

**Interfaces:**
- Consumes: Tasks 2–5 (`PackTheme`, `Fonts`, `SteppedFrame`, `Dither`, `SidecarProcess`, `EngineClient`, `EngineResult`).
- Produces:
  - Autoloads: `PackThemes` (Task 2 script), `ClientSettings`, `SessionStore` (Task 4 script), `Services`.
  - `Services.sidecar: SidecarProcess`, `Services.client: EngineClient`; `Services.shutdown()`.
  - `ClientSettings.get_value(key: String) -> Variant`, `set_value(key: String, value: Variant)`; `signal changed(key, value)`; keys: `reading/text_speed` (`slow|medium|fast|instant`, default `medium`), `reading/ambient_life` (true), `reading/reduced_motion` (false), `audio/master` (0.7), `audio/music` (0.55), `audio/effects` (0.8), `ui/last_played_pack` ("").
  - `BaseScreen` (Control): `screen_enter(params: Dictionary)`, `screen_exit()`, `esc_target() -> String`.
  - `ScreenStack` (Control): `register(name: String, screen: Control)`, `replace(name, params := {})`, `push(name, params := {})`, `pop(params := {})`, `current_name() -> String`, `current() -> Control`; `signal screen_changed(name)`.
  - `OverlayLayer` (CanvasLayer): `toast(message: String, kind := "ok")` (`kind ∈ ok|warn|bad`), `toast_error(result: EngineResult)`, `confirm(title: String, body: String, ok_label := "CONFIRM", cancel_label := "CANCEL") -> bool` (await it).
  - `StatusStrip` (Control): `refresh(status: Dictionary)` (the §A2 `/v1/llm/status` payload); `const CLIENT_VERSION := "0.1.0"`.
  - `Kit` (statics): `btn(text, t)`, `ghost_btn(text, t)`, `microlink(text, t, bad := false)`, `card(t)`, `data_field(text, t)`, `menu_item(num, title, note, t, dim := false)`, `px_frame(t, ring := "accent", fill := "panel")`, `toggle(on, t)`, `slider(value, t)`, `segmented(options: PackedStringArray, selected: int, t)` — inner classes `Kit.Toggle`, `Kit.SegmentedControl`, `Kit.MenuDocket`.
  - `FakeEngineClient` (Node): `responses: Dictionary` (method → `EngineResult` or FIFO `Array`), `calls: Array`; statics `ok(data: Dictionary)`, `err(status, code, msg)`; `contract_matches(...) -> true`. **Its methods are plain (non-coroutine) functions returning EngineResult — `await` on a plain value returns it immediately, so screens' `await` callsites work unchanged.**

**Navigation rule (pin):** M2 screens navigate exclusively with `replace` — the stack stays one deep, so ESC = `replace(esc_target())` never pollutes. `push`/`pop` exist for M3+ (advisor panels, overlays) and are not used in M2.

**Shell layout rule (pin):** `main.tscn` mounts `ScreenStack` + `OverlayLayer` only. There is **no** global SceneBackdrop in M2 — mocks 02/03/05 are flat `var(--bg)` screens; only Title owns a backdrop (its right-hand viewport pane, Task 7). This refines spec §6's layout line to what the mocks actually show.

- [ ] **Step 1: failing tests** — create `client/tests/app/test_screen_stack.gd` exactly:

```gdscript
extends GdUnitTestSuite
## ScreenStack navigation (spec §6): replace/enter/exit/ESC.

class ProbeScreen:
	extends BaseScreen
	var entered_with: Array = []
	var exits := 0

	func screen_enter(params: Dictionary) -> void:
		entered_with.append(params)

	func screen_exit() -> void:
		exits += 1


class EscScreen:
	extends ProbeScreen

	func esc_target() -> String:
		return "home"


func _stack_with_two() -> Array:
	var stack := ScreenStack.new()
	add_child(auto_free(stack))
	var a := ProbeScreen.new()
	var b := EscScreen.new()
	stack.register("home", a)
	stack.register("away", b)
	return [stack, a, b]


func test_replace_enters_and_exits() -> void:
	var ctx := await _stack_with_two()
	var stack: ScreenStack = ctx[0]
	var a: ProbeScreen = ctx[1]
	var b: ProbeScreen = ctx[2]
	stack.replace("home", {"from": "test"})
	assert_str(stack.current_name()).is_equal("home")
	assert_that(a.entered_with.size()).is_equal(1)
	assert_that(a.entered_with[0]).is_equal({"from": "test"})
	assert_bool(a.visible).is_true()
	assert_bool(b.visible).is_false()

	stack.replace("away")
	assert_str(stack.current_name()).is_equal("away")
	assert_that(a.exits).is_equal(1)
	assert_bool(a.visible).is_false()
	assert_bool(b.visible).is_true()


func test_esc_routes_to_esc_target() -> void:
	var ctx := await _stack_with_two()
	var stack: ScreenStack = ctx[0]
	stack.replace("away")
	var key := InputEventKey.new()
	key.pressed = true
	key.keycode = KEY_ESCAPE
	stack._unhandled_input(key)
	assert_str(stack.current_name()).is_equal("home")


func test_esc_does_nothing_without_target() -> void:
	var ctx := await _stack_with_two()
	var stack: ScreenStack = ctx[0]
	stack.replace("home")
	var key := InputEventKey.new()
	key.pressed = true
	key.keycode = KEY_ESCAPE
	stack._unhandled_input(key)
	assert_str(stack.current_name()).is_equal("home")
```

Create `client/tests/app/test_client_settings.gd` exactly:

```gdscript
extends GdUnitTestSuite
## ClientSettings: defaults, roundtrip, persistence across instances.

const ClientSettingsImpl := preload("res://app/client_settings.gd")


func test_defaults_match_the_mock_positions() -> void:
	var s: Node = auto_free(ClientSettingsImpl.new())
	add_child(s)
	assert_str(str(s.get_value("reading/text_speed"))).is_equal("medium")
	assert_bool(bool(s.get_value("reading/ambient_life"))).is_true()
	assert_bool(bool(s.get_value("reading/reduced_motion"))).is_false()
	assert_that(float(s.get_value("audio/master"))).is_equal(0.7)
	assert_that(float(s.get_value("audio/music"))).is_equal(0.55)
	assert_that(float(s.get_value("audio/effects"))).is_equal(0.8)
	assert_str(str(s.get_value("ui/last_played_pack"))).is_equal("")


func test_set_persists_across_instances_and_emits() -> void:
	var s: Node = auto_free(ClientSettingsImpl.new())
	add_child(s)
	var seen: Array = []
	s.changed.connect(func(key: String, value: Variant) -> void: seen.append([key, value]))
	s.set_value("reading/text_speed", "fast")
	assert_that(seen.size()).is_equal(1)
	var fresh: Node = auto_free(ClientSettingsImpl.new())
	add_child(fresh)
	assert_str(str(fresh.get_value("reading/text_speed"))).is_equal("fast")
	# restore the default so other tests/runs are unaffected
	s.set_value("reading/text_speed", "medium")
```

- [ ] **Step 2: run tests, verify failure**

Run: `tools/run_client_tests.sh`
Expected: FAIL — `BaseScreen`/`ScreenStack` unknown.

- [ ] **Step 3: autoload scripts** — create `client/app/services.gd` exactly:

```gdscript
extends Node
## Autoload: Services — the boot-time singletons (spec §6): SidecarProcess +
## EngineClient, set up by main.gd. Screens read Services.client.

var sidecar: SidecarProcess
var client: EngineClient


func shutdown() -> void:
	if sidecar != null:
		sidecar.kill()
```

Create `client/app/client_settings.gd` exactly (**no class_name** — autoload):

```gdscript
extends Node
## Autoload: ClientSettings — client-local prefs in user://settings.cfg
## (spec §6). Client-owned only: never game truth, never server-owned values.

signal changed(key: String, value: Variant)

const PATH := "user://settings.cfg"

const DEFAULTS := {
	"reading/text_speed": "medium",  # slow | medium | fast | instant
	"reading/ambient_life": true,
	"reading/reduced_motion": false,
	"audio/master": 0.7,
	"audio/music": 0.55,
	"audio/effects": 0.8,
	"ui/last_played_pack": "",
}

var _cfg := ConfigFile.new()


func _ready() -> void:
	_cfg.load(PATH)  # missing file is fine — defaults apply


func get_value(key: String) -> Variant:
	var parts := key.split("/")
	return _cfg.get_value(parts[0], parts[1], DEFAULTS.get(key))


func set_value(key: String, value: Variant) -> void:
	var parts := key.split("/")
	_cfg.set_value(parts[0], parts[1], value)
	_cfg.save(PATH)
	changed.emit(key, value)
```

- [ ] **Step 4: `client/app/base_screen.gd` + `client/app/screen_stack.gd`** — create exactly:

```gdscript
class_name BaseScreen
extends Control
## Screen contract for the ScreenStack (spec §6).


## Called by the stack when the screen becomes visible. Params come from the
## navigating caller ("" keys documented per screen).
func screen_enter(_params: Dictionary) -> void:
	pass


## Called when the screen is navigated away from.
func screen_exit() -> void:
	pass


## Where ESC goes; "" = ESC does nothing.
func esc_target() -> String:
	return ""
```

```gdscript
class_name ScreenStack
extends Control
## Push/replace/pop navigation (spec §6). Instant swaps in M2 — transitions
## are M5 polish. M2 screens navigate with `replace` only (the stack stays
## one deep); push/pop exist for M3+ overlays.

signal screen_changed(screen_name: String)

var _screens := {}
var _stack: Array = []


func register(screen_name: String, screen: Control) -> void:
	_screens[screen_name] = screen
	screen.visible = false
	add_child(screen)
	screen.set_anchors_preset(Control.PRESET_FULL_RECT)


func current_name() -> String:
	return str(_stack[-1]) if not _stack.is_empty() else ""


func current() -> Control:
	return _screens.get(current_name())


func replace(screen_name: String, params := {}) -> void:
	_hide_top()
	if _stack.is_empty():
		_stack.append(screen_name)
	else:
		_stack[-1] = screen_name
	_show_top(params)


func push(screen_name: String, params := {}) -> void:
	_hide_top()
	_stack.append(screen_name)
	_show_top(params)


func pop(params := {}) -> void:
	if _stack.size() <= 1:
		return
	_hide_top()
	_stack.pop_back()
	_show_top(params)


func _hide_top() -> void:
	if _stack.is_empty():
		return
	var old: Control = _screens[_stack[-1]]
	if old is BaseScreen:
		old.screen_exit()
	old.visible = false


func _show_top(params: Dictionary) -> void:
	var top: Control = _screens[_stack[-1]]
	top.visible = true
	if top is BaseScreen:
		top.screen_enter(params)
	screen_changed.emit(_stack[-1])


func _unhandled_input(event: InputEvent) -> void:
	if (
		event is InputEventKey
		and event.pressed
		and not event.echo
		and event.keycode == KEY_ESCAPE
	):
		var top := current()
		if top is BaseScreen and top.esc_target() != "":
			replace(top.esc_target())
			get_viewport().set_input_as_handled()
```

- [ ] **Step 5: run tests, verify pass**

Run: `tools/run_client_tests.sh`
Expected: PASS (the two new suites).

- [ ] **Step 6: `client/components/toast.gd`** — create exactly (tokens.css `.toast`: panel bg, 2px line border, 3px left bar by kind; kinds `ok`/`warn`/`bad` → ok/accent/danger):

```gdscript
class_name Toast
extends Control
## tokens.css .toast — engine strings verbatim (spec §6.6). Self-dismisses
## after 6s. Kind ∈ ok | warn | bad (left bar: ok / accent / danger).

var _message := ""
var _kind := "ok"
var _theme: PackTheme


func setup(message: String, kind: String, theme: PackTheme) -> void:
	_message = message
	_kind = kind
	_theme = theme
	custom_minimum_size = Vector2(320, 34)
	var label := Fonts.label(message, Fonts.data(), 11, theme.ink)
	label.position = Vector2(12, 9)
	label.size = Vector2(300, 16)
	label.clip_text = true
	add_child(label)
	var timer := Timer.new()
	timer.wait_time = 6.0
	timer.one_shot = true
	timer.timeout.connect(queue_free)
	add_child(timer)
	timer.start()


func _draw() -> void:
	if _theme == null:
		return
	var r := Rect2(Vector2.ZERO, size)
	# hard 3px offset shadow
	draw_rect(Rect2(Vector2(3, 3), size), Color(0, 0, 0, 0.45))
	draw_rect(r, _theme.panel)
	draw_rect(r, _theme.line, false, 2.0)
	var bar := _theme.ok
	match _kind:
		"warn":
			bar = _theme.accent
		"bad":
			bar = _theme.danger
	draw_rect(Rect2(Vector2.ZERO, Vector2(3, size.y)), bar)
```

- [ ] **Step 7: `client/app/overlay_layer.gd`** — create exactly:

```gdscript
class_name OverlayLayer
extends CanvasLayer
## Toasts (bottom-right stack, max 4) + modal confirms (spec §6).
## Engine messages arrive verbatim (§A1) via toast_error.

var _toast_box: VBoxContainer


func _ready() -> void:
	layer = 10
	_toast_box = VBoxContainer.new()
	_toast_box.set_anchors_preset(Control.PRESET_BOTTOM_RIGHT)
	_toast_box.grow_horizontal = Control.GROW_DIRECTION_BEGIN
	_toast_box.grow_vertical = Control.GROW_DIRECTION_BEGIN
	_toast_box.position -= Vector2(16, 16)
	_toast_box.add_theme_constant_override("separation", 8)
	add_child(_toast_box)


func toast(message: String, kind := "ok") -> void:
	var t := Toast.new()
	_toast_box.add_child(t)
	t.setup(message, kind, PackThemes.current)
	while _toast_box.get_child_count() > 4:
		_toast_box.get_child(0).queue_free()


func toast_error(result: EngineResult) -> void:
	toast(result.error_message, "bad")


## Modal confirm; await it. True = confirmed.
func confirm(title: String, body: String, ok_label := "CONFIRM", cancel_label := "CANCEL") -> bool:
	var modal := _ConfirmModal.new()
	add_child(modal)
	modal.setup(title, body, ok_label, cancel_label, PackThemes.current)
	var answer: bool = await modal.chosen
	modal.queue_free()
	return answer


class _ConfirmModal:
	extends Control

	signal chosen(answer: bool)

	var _answer := false

	func setup(title: String, body: String, ok_label: String, cancel_label: String, theme: PackTheme) -> void:
		set_anchors_preset(Control.PRESET_FULL_RECT)
		var dim := ColorRect.new()
		dim.color = Color(0, 0, 0, 0.6)
		dim.set_anchors_preset(Control.PRESET_FULL_RECT)
		add_child(dim)
		var center := CenterContainer.new()
		center.set_anchors_preset(Control.PRESET_FULL_RECT)
		add_child(center)
		var frame := SteppedFrame.new()
		frame.custom_minimum_size = Vector2(420, 0)
		frame.apply_theme(theme)
		center.add_child(frame)
		var box := VBoxContainer.new()
		box.add_theme_constant_override("separation", 10)
		frame.add_content(box)
		frame.set_content_margins(16, 14, 16, 14)
		box.add_child(Fonts.label(title, Fonts.inter(), 14, theme.ink))
		var body_label := Fonts.label(body, Fonts.prose(), 12, theme.muted)
		body_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		body_label.custom_minimum_size = Vector2(388, 0)
		box.add_child(body_label)
		var row := HBoxContainer.new()
		row.add_theme_constant_override("separation", 12)
		box.add_child(row)
		var ok_btn := Kit.btn(ok_label, theme)
		ok_btn.pressed.connect(_answer.bind(true))
		row.add_child(ok_btn)
		var cancel_btn := Kit.ghost_btn(cancel_label, theme)
		cancel_btn.pressed.connect(_answer.bind(false))
		row.add_child(cancel_btn)

	func _answer(value: bool) -> void:
		_answer = value
		chosen.emit(value)
```

- [ ] **Step 8: `client/app/status_strip.gd`** — create exactly (mock strip: `IBM Plex Mono 500 10px`, letterspaced, `rgba(8,10,16,.9)` bg, 2px top border):

```gdscript
class_name StatusStrip
extends Control
## The cockpit strip (spec §6): left "ENGINE SYNC ✓ · v0.1.0"; right
## "NARRATOR: <MODEL> ●" when configured, "NARRATOR: TEMPLATES ○" when not.
## Dot only (parent §6.6) — operator detail lives in Settings.

const CLIENT_VERSION := "0.1.0"

var theme: PackTheme:
	set(v):
		theme = v
		queue_redraw()

var _left_sync: Label
var _left_tick: Label
var _left_version: Label
var _right_text: Label
var _right_dot: Label


func _ready() -> void:
	custom_minimum_size = Vector2(0, 27)
	var row := HBoxContainer.new()
	row.set_anchors_preset(Control.PRESET_FULL_RECT)
	row.add_theme_constant_override("separation", 0)
	add_child(row)
	var left := HBoxContainer.new()
	left.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	left.add_theme_constant_override("separation", 0)
	row.add_child(left)
	_left_sync = Label.new()
	left.add_child(_left_sync)
	_left_tick = Label.new()
	left.add_child(_left_tick)
	_left_version = Label.new()
	left.add_child(_left_version)
	var right := HBoxContainer.new()
	right.alignment = BoxContainer.ALIGNMENT_END
	row.add_child(right)
	_right_text = Label.new()
	right.add_child(_right_text)
	_right_dot = Label.new()
	right.add_child(_right_dot)
	restyle()
	refresh({})


func restyle() -> void:
	if theme == null:
		return
	for label: Label in [_left_sync, _left_version, _right_text]:
		label.add_theme_font_override("font", Fonts.data())
		label.add_theme_font_size_override("font_size", 10)
		label.add_theme_color_override("font_color", theme.muted)
	for label: Label in [_left_tick, _right_dot]:
		label.add_theme_font_override("font", Fonts.data())
		label.add_theme_font_size_override("font_size", 10)
	_left_tick.add_theme_color_override("font_color", theme.ok)


## status = the /v1/llm/status payload (§A2); {} renders the unconfigured state.
func refresh(status: Dictionary) -> void:
	var configured := bool(status.get("configured", false))
	_left_sync.text = "ENGINE SYNC "
	_left_tick.text = "✓"
	_left_version.text = " · v" + CLIENT_VERSION
	if configured:
		_right_text.text = "NARRATOR: %s " % str(status.get("model", "")).to_upper()
		_right_dot.text = "●"
		if theme != null:
			_right_dot.add_theme_color_override("font_color", theme.ok)
	else:
		_right_text.text = "NARRATOR: TEMPLATES "
		_right_dot.text = "○"
		if theme != null:
			_right_dot.add_theme_color_override("font_color", theme.muted)


func _draw() -> void:
	if theme == null:
		return
	# rgba(8,10,16,.9) panel + 2px top border (tokens.css .strip).
	draw_rect(Rect2(Vector2.ZERO, size), Color(8.0 / 255, 10.0 / 255, 16.0 / 255, 0.9))
	draw_rect(Rect2(Vector2.ZERO, Vector2(size.x, 2)), theme.line)

- [ ] **Step 9: `client/components/kit.gd`** — create exactly. Every factory takes its `PackTheme` explicitly (per-widget tinting, mock 02). Hard offset shadows = StyleBoxFlat `shadow_size 0`, `shadow_offset (3,3)`, `shadow_color (0,0,0,0.45)`.

```gdscript
class_name Kit
extends RefCounted
## The Hi-bit Console component kit (tokens.css; spec §6). Statics only.


static func _shadow_box(bg: Color, border: Color, border_width := 0) -> StyleBoxFlat:
	var sb := StyleBoxFlat.new()
	sb.bg_color = bg
	sb.shadow_color = Color(0, 0, 0, 0.45)
	sb.shadow_size = 0
	sb.shadow_offset = Vector2(3, 3)
	if border_width > 0:
		sb.set_border_width_all(border_width)
		sb.border_color = border
	return sb


## .btn — accent fill, bg-colored Chakra Petch 600 text.
static func btn(text: String, t: PackTheme) -> Button:
	var b := Button.new()
	b.text = text
	b.add_theme_stylebox_override("normal", _shadow_box(t.accent, t.accent))
	b.add_theme_stylebox_override("hover", _shadow_box(t.accent.lightened(0.12), t.accent))
	b.add_theme_stylebox_override("pressed", _shadow_box(t.accent.darkened(0.12), t.accent))
	b.add_theme_stylebox_override("focus", StyleBoxEmpty.new())
	b.add_theme_font_override("font", Fonts.inter())
	b.add_theme_font_size_override("font_size", 13)
	b.add_theme_color_override("font_color", t.bg)
	b.add_theme_color_override("font_hover_color", t.bg)
	b.add_theme_color_override("font_pressed_color", t.bg)
	b.custom_minimum_size = Vector2(0, 34)
	return b


## .ghostbtn — panel fill, ink text, 2px line border.
static func ghost_btn(text: String, t: PackTheme) -> Button:
	var b := Button.new()
	b.text = text
	b.add_theme_stylebox_override("normal", _shadow_box(t.panel, t.line, 2))
	b.add_theme_stylebox_override("hover", _shadow_box(t.panel, t.accent, 2))
	b.add_theme_stylebox_override("pressed", _shadow_box(t.bg, t.line, 2))
	b.add_theme_stylebox_override("focus", StyleBoxEmpty.new())
	b.add_theme_font_override("font", Fonts.inter())
	b.add_theme_font_size_override("font_size", 12)
	b.add_theme_color_override("font_color", t.ink)
	b.add_theme_color_override("font_hover_color", t.ink)
	b.add_theme_color_override("font_pressed_color", t.ink)
	b.custom_minimum_size = Vector2(0, 30)
	return b


## .microlink — VT323 underlined; bad = danger color. (Godot's Button has
## no underline property — the underline is a 1px ColorRect at the bottom.)
static func microlink(text: String, t: PackTheme, bad := false) -> Button:
	var b := Button.new()
	b.text = text
	b.flat = true
	b.add_theme_stylebox_override("focus", StyleBoxEmpty.new())
	b.add_theme_font_override("font", Fonts.micro())
	b.add_theme_font_size_override("font_size", 13)
	var color := t.danger if bad else t.muted
	b.add_theme_color_override("font_color", color)
	b.add_theme_color_override("font_hover_color", color.lightened(0.25))
	b.add_theme_color_override("font_pressed_color", color)
	var rule := ColorRect.new()
	rule.color = color
	rule.custom_minimum_size = Vector2(0, 1)
	rule.set_anchors_preset(Control.PRESET_BOTTOM_WIDE)
	rule.offset_bottom = -2
	rule.mouse_filter = Control.MOUSE_FILTER_IGNORE
	b.add_child(rule)
	return b
```

```gdscript
## .card0 — panel bg, 2px line border, hard shadow. Content goes in the
## returned container.
static func card(t: PackTheme) -> PanelContainer:
	var p := PanelContainer.new()
	p.add_theme_stylebox_override("panel", _shadow_box(t.panel, t.line, 2))
	return p


## Settings boxed field (mock 05): bg fill, 2px line border, data font.
static func data_field(text: String, t: PackTheme) -> PanelContainer:
	var p := PanelContainer.new()
	var sb := StyleBoxFlat.new()
	sb.bg_color = t.bg
	sb.set_border_width_all(2)
	sb.border_color = t.line
	sb.content_margin_left = 10
	sb.content_margin_top = 7
	sb.content_margin_right = 10
	sb.content_margin_bottom = 7
	p.add_theme_stylebox_override("panel", sb)
	var label := Fonts.label(text, Fonts.data(), 11, t.muted)
	p.add_child(label)
	p.set_meta("label", label)  # screens update text via get_meta("label")
	return p


## .px stepped frame pre-themed (accent ring / panel fill by default).
static func px_frame(t: PackTheme, ring := "accent", fill := "panel") -> SteppedFrame:
	var f := SteppedFrame.new()
	f.apply_theme(t, ring, fill)
	return f


## .mi — numbered menu docket (mock 01). note may be "".
static func menu_item(num: String, item_title: String, note: String, t: PackTheme, dim := false) -> MenuDocket:
	var d := MenuDocket.new()
	d.setup(num, item_title, note, t, dim)
	return d


## Toggle (mock 05): 44×22 box, sliding knob. Emits BaseButton.toggled.
static func toggle(on: bool, t: PackTheme) -> Toggle:
	var sw := Toggle.new()
	sw.setup(on, t)
	return sw


## Slider (mock 05): 6px track, 10×14 ink handle.
static func slider(value: float, t: PackTheme) -> HSlider:
	var s := HSlider.new()
	s.min_value = 0.0
	s.max_value = 1.0
	s.step = 0.05
	s.value = value
	s.custom_minimum_size = Vector2(0, 22)
	var track := StyleBoxFlat.new()
	track.bg_color = t.bg
	track.set_border_width_all(1)
	track.border_color = t.line
	track.content_margin_top = 8
	track.content_margin_bottom = 8
	s.add_theme_stylebox_override("slider", track)
	var fill := StyleBoxFlat.new()
	fill.bg_color = t.accent
	fill.content_margin_top = 8
	fill.content_margin_bottom = 8
	s.add_theme_stylebox_override("grabber_area", fill)
	var handle := StyleBoxFlat.new()
	handle.bg_color = t.ink
	s.add_theme_stylebox_override("grabber", handle)
	s.add_theme_stylebox_override("grabber_highlight", handle)
	s.add_theme_stylebox_override("grabber_pressed", handle)
	s.add_theme_icon_override("grabber", _blank_icon())
	s.add_theme_icon_override("grabber_highlight", _blank_icon())
	s.add_theme_icon_override("grabber_pressed", _blank_icon())
	return s


static var _icon: ImageTexture


static func _blank_icon() -> ImageTexture:
	if _icon == null:
		var img := Image.create(10, 14, false, Image.FORMAT_RGBA8)
		img.fill(Color.WHITE)
		_icon = ImageTexture.create_from_image(img)
	return _icon


## Segmented control (mock 05 text speed): row of equal cells, selected =
## accent fill + bg text. `option_chosen(index)` signal.
static func segmented(options: PackedStringArray, selected: int, t: PackTheme) -> SegmentedControl:
	var sc := SegmentedControl.new()
	sc.setup(options, selected, t)
	return sc


class Toggle:
	extends BaseButton
	## Mock 05 toggle: 44×22, 2px line border, 16×14 knob (ok when on, muted
	## when off). toggle_mode is on; read `button_pressed`.

	var _theme: PackTheme

	func setup(on: bool, t: PackTheme) -> void:
		_theme = t
		toggle_mode = true
		button_pressed = on
		custom_minimum_size = Vector2(44, 22)
		toggled.connect(func(_on: bool) -> void: queue_redraw())

	func _draw() -> void:
		if _theme == null:
			return
		var r := Rect2(Vector2.ZERO, size)
		draw_rect(r, _theme.bg)
		draw_rect(r, _theme.line, false, 2.0)
		var knob := Rect2(Vector2(3, 3), Vector2(16, 14))
		if button_pressed:
			knob.position.x = size.x - 19
		draw_rect(knob, _theme.ok if button_pressed else _theme.muted)


class SegmentedControl:
	extends HBoxContainer

	signal option_chosen(index: int)

	var _options := PackedStringArray()
	var _selected := 0
	var _theme: PackTheme
	var _buttons: Array = []

	func setup(options: PackedStringArray, selected: int, t: PackTheme) -> void:
		_options = options
		_selected = selected
		_theme = t
		add_theme_constant_override("separation", 0)
		for i: int in _options.size():
			var b := Button.new()
			b.text = _options[i]
			b.toggle_mode = true
			b.size_flags_horizontal = Control.SIZE_EXPAND_FILL
			b.add_theme_font_override("font", Fonts.inter())
			b.add_theme_font_size_override("font_size", 11)
			b.add_theme_stylebox_override("focus", StyleBoxEmpty.new())
			b.pressed.connect(_choose.bind(i))
			add_child(b)
			_buttons.append(b)
		_restyle()

	func selected() -> int:
		return _selected

	func _choose(index: int) -> void:
		_selected = index
		_restyle()
		option_chosen.emit(index)

	func _restyle() -> void:
		for i: int in _buttons.size():
			var b: Button = _buttons[i]
			b.button_pressed = i == _selected
			var on := i == _selected
			var sb := StyleBoxFlat.new()
			sb.bg_color = _theme.accent if on else _theme.bg
			sb.set_border_width_all(2)
			sb.border_color = _theme.line
			b.add_theme_stylebox_override("normal", sb)
			b.add_theme_stylebox_override("hover", sb)
			b.add_theme_stylebox_override("pressed", sb)
			b.add_theme_color_override("font_color", _theme.bg if on else _theme.muted)
			b.add_theme_color_override("font_hover_color", _theme.bg if on else _theme.ink)
			b.add_theme_color_override("font_pressed_color", _theme.bg if on else _theme.ink)


class MenuDocket:
	extends Button
	## Mock 01 `.mi`: [num (data, accent)] [title (inter, ink)] [note (micro, muted, right)].
	## dim = .mi.dim (55% opacity, non-interactive).

	signal docket_pressed

	var _theme: PackTheme

	func setup(num: String, item_title: String, note: String, t: PackTheme, dim := false) -> void:
		_theme = t
		var sb := StyleBoxFlat.new()
		sb.bg_color = t.panel
		sb.set_border_width_all(2)
		sb.border_color = t.line
		sb.shadow_color = Color(0, 0, 0, 0.45)
		sb.shadow_size = 0
		sb.shadow_offset = Vector2(3, 3)
		sb.content_margin_left = 14
		sb.content_margin_top = 10
		sb.content_margin_right = 14
		sb.content_margin_bottom = 10
		for state: String in ["normal", "hover", "pressed"]:
			add_theme_stylebox_override(state, sb)
		add_theme_stylebox_override("focus", StyleBoxEmpty.new())
		var row := HBoxContainer.new()
		row.add_theme_constant_override("separation", 10)
		row.mouse_filter = Control.MOUSE_FILTER_IGNORE
		row.set_anchors_preset(Control.PRESET_FULL_RECT)
		add_child(row)
		row.add_child(Fonts.label(num, Fonts.data(), 10, t.accent))
		var title_label := Fonts.label(item_title, Fonts.inter(), 15, t.ink)
		title_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		row.add_child(title_label)
		if note != "":
			row.add_child(Fonts.label(note, Fonts.micro_tracked(), 12, t.muted))
		if dim:
			modulate.a = 0.55
			disabled = true
		else:
			pressed.connect(func() -> void: docket_pressed.emit())
```

- [ ] **Step 10: `client/tests/engine/fake_engine_client.gd`** — create exactly:

```gdscript
class_name FakeEngineClient
extends Node
## Test double for EngineClient (spec §8): same method surface, canned
## responses, scriptable errors, call log. Methods are plain (non-coroutine)
## — `await` on a plain value returns it immediately, so screens' await
## callsites work unchanged.

var responses := {}
var calls: Array = []
var contract_chargen := 1
var contract_adventure := 1


static func ok(data: Dictionary) -> EngineResult:
	return EngineResult.ok_result(200, data)


static func err(status: int, code: String, msg: String) -> EngineResult:
	return EngineResult.err_result(status, code, msg)


func contract_matches(_session: Dictionary) -> bool:
	return true


func _record(method: String, args: Array) -> EngineResult:
	calls.append([method] + args)
	var canned: Variant = responses.get(method)
	if canned is Array:
		if canned.is_empty():
			return EngineResult.err_result(500, "test", "no canned responses left for " + method)
		return canned.pop_front()
	if canned is EngineResult:
		return canned
	return EngineResult.err_result(500, "test", "no canned response for " + method)


func health() -> EngineResult:
	return _record("health", [])


func llm_status() -> EngineResult:
	return _record("llm_status", [])


func list_packs() -> EngineResult:
	return _record("list_packs", [])


func list_rulesets() -> EngineResult:
	return _record("list_rulesets", [])


func list_providers() -> EngineResult:
	return _record("list_providers", [])


func get_settings() -> EngineResult:
	return _record("get_settings", [])


func put_settings(payload: Dictionary) -> EngineResult:
	return _record("put_settings", [payload])


func test_settings() -> EngineResult:
	return _record("test_settings", [])


func list_saves() -> EngineResult:
	return _record("list_saves", [])


func delete_save(save_name: String) -> EngineResult:
	return _record("delete_save", [save_name])


func duplicate_save(save_name: String, new_name: String) -> EngineResult:
	return _record("duplicate_save", [save_name, new_name])


func export_save(save_name: String) -> EngineResult:
	return _record("export_save", [save_name])


func import_save(save_name: String, document: Dictionary) -> EngineResult:
	return _record("import_save", [save_name, document])


func create_session(payload: Dictionary) -> EngineResult:
	return _record("create_session", [payload])


func resume_session(from_save: String) -> EngineResult:
	return _record("resume_session", [from_save])


func list_sessions() -> EngineResult:
	return _record("list_sessions", [])


func get_session(id: String) -> EngineResult:
	return _record("get_session", [id])


func delete_session(id: String) -> EngineResult:
	return _record("delete_session", [id])


func choose(id: String, option_id: String, origin := "player") -> EngineResult:
	return _record("choose", [id, option_id, origin])


func freetext(id: String, text: String) -> EngineResult:
	return _record("freetext", [id, text])


func suggest(id: String) -> EngineResult:
	return _record("suggest", [id])


func set_name(id: String, char_name: String) -> EngineResult:
	return _record("set_name", [id, char_name])


func promote(id: String) -> EngineResult:
	return _record("promote", [id])


func save_session(id: String, save_name: String) -> EngineResult:
	return _record("save_session", [id, save_name])


func recap(id: String) -> EngineResult:
	return _record("recap", [id])
```

- [ ] **Step 11: `client/app/main.gd`** — replace the Task 1 placeholder with exactly:

```gdscript
extends Control
## Boot root (spec §6): spawn sidecar → LISTENING → health → Title.
## Mounts ScreenStack + OverlayLayer only — no global backdrop in M2
## (mocks 02/03/05 are flat-bg screens; Title owns its viewport pane).

var _stack: ScreenStack
var _overlay: OverlayLayer
var _boot_lines: Array = []
var _boot_error: Control


func _ready() -> void:
	_overlay = OverlayLayer.new()
	add_child(_overlay)
	_stack = ScreenStack.new()
	_stack.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(_stack)
	_stack.move_to_front()  # screens under the overlay (CanvasLayer sits above anyway)
	_boot()


func _notification(what: int) -> void:
	if what == NOTIFICATION_WM_CLOSE_REQUEST:
		Services.shutdown()
		get_tree().quit()


func _boot() -> void:
	if Services.sidecar == null:
		Services.sidecar = SidecarProcess.new()
		add_child(Services.sidecar)
	if Services.client == null:
		Services.client = EngineClient.new()
		add_child(Services.client)
	_boot_lines = ["REFEREE: WAKING…"]
	Services.sidecar.boot_failed.connect(_on_boot_failed)
	Services.sidecar.booted.connect(_on_booted)
	Services.sidecar.spawn()


func _on_booted(base_url: String, port: int) -> void:
	Services.client.setup(base_url)
	await Services.client.refresh_contracts()
	_boot_lines.append("REFEREE: LISTENING · 127.0.0.1:%d" % port)
	_boot_lines.append("SAVES: OK · DICE STREAMS: PRIMED")
	_register_screens()
	_stack.replace("title", {"boot_lines": _boot_lines})


func _on_boot_failed(reason: String) -> void:
	var t := PackThemes.current
	_boot_error = CenterContainer.new()
	_boot_error.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(_boot_error)
	var frame := Kit.px_frame(t, "danger", "panel")
	frame.custom_minimum_size = Vector2(520, 0)
	_boot_error.add_child(frame)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 12)
	frame.add_content(box)
	frame.set_content_margins(18, 16, 18, 16)
	box.add_child(Fonts.label("REFEREE NOT ANSWERING", Fonts.inter(), 15, t.danger))
	var msg := Fonts.label(reason, Fonts.data(), 11, t.muted)
	msg.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	msg.custom_minimum_size = Vector2(480, 0)
	box.add_child(msg)
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 12)
	box.add_child(row)
	var retry := Kit.btn("RETRY", t)
	retry.pressed.connect(_on_retry)
	row.add_child(retry)
	var quit := Kit.ghost_btn("QUIT", t)
	quit.pressed.connect(
		func() -> void:
			Services.shutdown()
			get_tree().quit()
	)
	row.add_child(quit)


func _on_retry() -> void:
	if _boot_error != null:
		_boot_error.queue_free()
		_boot_error = null
	_boot()


## Task 7 replaces this with the real set. Until then the shell boots to a
## placeholder so the wiring is inspectable.
func _register_screens() -> void:
	_stack.register("title", _placeholder("TITLE arrives in Task 7"))
	_stack.register("settings", _placeholder("SETTINGS arrives in Task 8"))
	_stack.register("chronicles", _placeholder("CHRONICLES arrives in Task 9"))
	_stack.register("new_journey", _placeholder("NEW JOURNEY arrives in Task 10"))
	_stack.register("stub", _placeholder("SHELL STUB arrives in Task 10"))


func _placeholder(text: String) -> Control:
	var c := CenterContainer.new()
	var t := PackThemes.current
	var bg := ColorRect.new()
	bg.color = t.bg
	bg.set_anchors_preset(Control.PRESET_FULL_RECT)
	c.add_child(bg)
	c.add_child(Fonts.label(text, Fonts.micro_tracked(), 13, t.muted))
	return c
```

- [ ] **Step 12: register the autoloads** — append to `client/project.godot` exactly:

```
[autoload]

PackThemes="*res://theme/pack_themes.gd"
ClientSettings="*res://app/client_settings.gd"
SessionStore="*res://engine/session_store.gd"
Services="*res://app/services.gd"
```

- [ ] **Step 13: full gate + manual boot smoke**

Run: `tools/run_client_lint.sh && tools/run_client_tests.sh` — all pass.
Then (needs a display — WSLg or `xvfb-run`): `tools/godot/Godot_v4.7.1-stable_linux.x86_64 --path client` and confirm: the sidecar boots, the placeholder Title appears, and quitting the window kills the server (`pgrep -f "src.server"` shows nothing after quit). If no display is available, note it and rely on the integration tests.

- [ ] **Step 14: Commit**

```bash
git add client/app client/components client/tests client/project.godot
git commit -m "feat(client): M2.6 app shell — autoloads, ScreenStack, OverlayLayer, StatusStrip, Kit, boot flow"
```

---

## Task 7 (M2.7): Title screen

**Files:**
- Create: `client/screens/title_screen.gd`
- Modify: `client/app/base_screen.gd` (add `navigate` signal), `client/app/screen_stack.gd` (connect it in `register`), `client/app/services.gd` (add `overlay`), `client/app/main.gd` (assign `Services.overlay`; register the real TitleScreen), `client/components/kit.gd` (add `relative_mtime`; MenuDocket `dim` becomes style-only)
- Test: `client/tests/screens/test_title_screen.gd`

**Interfaces:**
- Consumes: everything from Tasks 2–6.
- Produces: `TitleScreen` (BaseScreen); the **navigate pattern** all later screens use: `BaseScreen.signal navigate(target: String, params: Dictionary)`, auto-connected by `ScreenStack.register`; the **pack-change restyle pattern**: screens keep every theme-colored node reachable from `_build()`, and on `PackThemes.pack_changed` they rebuild (`_rebuild()` frees children, re-runs `_build()`, re-applies cached data); `Kit.relative_mtime(mtime: float) -> String`; `Services.overlay: OverlayLayer` for toasts.
- Screen params: `{"boot_lines": Array[String]}` (from main's boot flow).

**Navigation wiring edits (exact):**

1. `client/app/base_screen.gd` — insert directly under `extends Control`:

```gdscript
## Emitted to navigate; ScreenStack.register auto-connects it to replace().
signal navigate(target: String, params: Dictionary)
```

2. `client/app/screen_stack.gd` — in `register`, after `add_child(screen)` insert:

```gdscript
	if screen is BaseScreen:
		screen.navigate.connect(_on_screen_navigate)
```

and add this method after `register`:

```gdscript
func _on_screen_navigate(target: String, params: Dictionary) -> void:
	replace(target, params)
```

3. `client/app/services.gd` — add under the `client` var:

```gdscript
var overlay: OverlayLayer
```

4. `client/app/main.gd` — in `_ready()`, after `add_child(_overlay)` insert:

```gdscript
	Services.overlay = _overlay
```

In `_register_screens()`, replace the title placeholder line with:

```gdscript
	_stack.register("title", TitleScreen.new())
```

5. `client/components/kit.gd` — in `MenuDocket.setup`, delete the line `disabled = true` (dim is style-only; interactivity is decided by whether the screen connects `docket_pressed` — mock 01's Quit is dimmed but functional). Append to the end of `kit.gd` (outside any class):

```gdscript
## "2H AGO"-style relative time for save mtimes (mocks 01/02).
static func relative_mtime(mtime: float) -> String:
	var delta := int(Time.get_unix_time_from_system() - mtime)
	if delta < 3600:
		return "%dM AGO" % maxi(delta / 60, 1)
	if delta < 172800:
		return "%dH AGO" % (delta / 3600)
	return "%dD AGO" % (delta / 86400)


## Distinct-chronicle count from a /v1/saves payload (autosaves share a
## base_name with their manual save).
static func chronicle_count(saves: Array) -> int:
	var names := {}
	for entry: Dictionary in saves:
		names[str(entry.get("base_name", ""))] = true
	return names.size()
```

**Autoload note for screen tests (pin):** because Task 6 registered the autoloads in `project.godot`, gdUnit4 runs have the real `PackThemes`/`ClientSettings`/`SessionStore`/`Services` live at `/root/`. Screen tests never preload autoload scripts; they inject the HTTP layer via the screen's `client_override` and let screens read the real autoloads. `Services.overlay` stays null in tests, so canned responses must keep screens off toast paths unless the test is specifically exercising one (then assign a real `OverlayLayer` to `Services.overlay` first).

- [ ] **Step 1: failing test** — create `client/tests/screens/test_title_screen.gd` exactly:

```gdscript
extends GdUnitTestSuite
## Title screen against FakeEngineClient (mock 01: menu notes, boot readout).
## Autoloads are live in the test run; only the HTTP layer is faked.

var _fake: FakeEngineClient
var _screen: TitleScreen


func before_test() -> void:
	_fake = auto_free(FakeEngineClient.new())
	add_child(_fake)
	_screen = auto_free(TitleScreen.new())
	_screen.client_override = _fake
	add_child(_screen)


func _saves_payload() -> Dictionary:
	return {
		"saves": [
			{
				"name": "mara",
				"base_name": "mara",
				"autosave": false,
				"theme_pack": "scifi",
				"character_name": "Mara Voss",
				"terms": 4,
				"career": "Scout",
				"alive": true,
				"mtime": Time.get_unix_time_from_system() - 7200.0,
			},
			{
				"name": "branwen",
				"base_name": "branwen",
				"autosave": false,
				"theme_pack": "fantasy",
				"character_name": "Branwen",
				"terms": 2,
				"career": "Bard",
				"alive": true,
				"mtime": Time.get_unix_time_from_system() - 259200.0,
			},
		]
	}


func test_menu_notes_and_strip_with_saves() -> void:
	_fake.responses["list_saves"] = FakeEngineClient.ok(_saves_payload())
	_fake.responses["llm_status"] = FakeEngineClient.ok(
		{"configured": true, "model": "claude-sonnet-5", "key_backend": "keyring", "degraded_line": null}
	)
	await _screen.screen_enter({"boot_lines": ["REFEREE: LISTENING · 127.0.0.1:63216", "SAVES: OK"]})
	assert_str(_screen.menu_note("continue")).is_equal("MARA VOSS · 2H AGO")
	assert_str(_screen.menu_note("chronicles")).is_equal("2 SAVES")
	assert_bool(_screen.menu_enabled("continue")).is_true()
	assert_str(_screen.boot_text()).is_equal("REFEREE: LISTENING · 127.0.0.1:63216\nSAVES: OK")
	assert_str(_screen._strip._right_text.text).is_equal("NARRATOR: CLAUDE-SONNET-5 ")


func test_no_saves_dims_continue_and_zeroes_chronicles() -> void:
	_fake.responses["list_saves"] = FakeEngineClient.ok({"saves": []})
	_fake.responses["llm_status"] = FakeEngineClient.ok(
		{"configured": false, "model": null, "key_backend": "", "degraded_line": "narration unavailable — showing mechanical outcomes"}
	)
	await _screen.screen_enter({"boot_lines": []})
	assert_bool(_screen.menu_enabled("continue")).is_false()
	assert_str(_screen.menu_note("chronicles")).is_equal("0 SAVES")
	assert_str(_screen._strip._right_text.text).is_equal("NARRATOR: TEMPLATES ")


func test_menu_navigation_signals() -> void:
	_fake.responses["list_saves"] = FakeEngineClient.ok(_saves_payload())
	_fake.responses["llm_status"] = FakeEngineClient.ok({"configured": false, "model": null, "key_backend": "", "degraded_line": ""})
	await _screen.screen_enter({"boot_lines": []})
	var nav: Array = []
	_screen.navigate.connect(func(target: String, _params: Dictionary) -> void: nav.append(target))
	_screen.press_menu("new_journey")
	_screen.press_menu("chronicles")
	_screen.press_menu("settings")
	assert_that(nav).is_equal(["new_journey", "chronicles", "settings"])


func test_continue_resumes_latest_and_navigates_to_stub() -> void:
	_fake.responses["list_saves"] = FakeEngineClient.ok(_saves_payload())
	_fake.responses["llm_status"] = FakeEngineClient.ok({"configured": false, "model": null, "key_backend": "", "degraded_line": ""})
	_fake.responses["resume_session"] = FakeEngineClient.ok(
		{"session": {"id": "s1", "name": "mara", "kind": "chargen", "phase": "homeworld", "view": {}, "contract_version": 1}}
	)
	await _screen.screen_enter({"boot_lines": []})
	var nav: Array = []
	_screen.navigate.connect(func(target: String, params: Dictionary) -> void: nav.append([target, params]))
	_screen.press_menu("continue")
	await get_tree().process_frame  # let the async resume finish
	await get_tree().process_frame
	assert_that(_fake.calls.filter(func(c: Array) -> bool: return c[0] == "resume_session").size()).is_equal(1)
	var resume_call: Array = _fake.calls.filter(func(c: Array) -> bool: return c[0] == "resume_session")[0]
	assert_str(str(resume_call[1])).is_equal("mara")
	assert_that(nav.size()).is_equal(1)
	assert_str(str(nav[0][0])).is_equal("stub")
	assert_str(str(nav[0][1]["session"]["id"])).is_equal("s1")
```

- [ ] **Step 2: run tests, verify failure**

Run: `tools/run_client_tests.sh`
Expected: FAIL — `TitleScreen` unknown.

- [ ] **Step 3: `client/screens/title_screen.gd`** — create exactly (every layout number from mock 01):

```gdscript
class_name TitleScreen
extends BaseScreen
## 01-title.html: console boot. Pack-neutral graphite at first boot; tints to
## ClientSettings ui/last_played_pack on return. Left rail 380px: wordmark,
## kicker, accent rule + motif, numbered menu dockets, boot readout. Right:
## SceneBackdrop viewport (sc-night). Bottom: StatusStrip.

## Test hook: when set, used instead of Services.client.
var client_override: Node

var _theme: PackTheme
var _boot_lines: Array = []
var _saves: Array = []
var _status: Dictionary = {}
var _menu := {}  # action -> {docket, note, enabled}
var _boot_label: Label
var _strip: StatusStrip
var _backdrop: SceneBackdrop

const _MENU := [
	["continue", "01", "Continue"],
	["new_journey", "02", "New Journey"],
	["chronicles", "03", "Chronicles"],
	["settings", "04", "Settings"],
	["quit", "05", "Quit"],
]


func _ready() -> void:
	_theme = PackThemes.current
	PackThemes.pack_changed.connect(_on_pack_changed)
	_rebuild()


func esc_target() -> String:
	return ""  # nowhere to go back to


func screen_enter(params: Dictionary) -> void:
	_boot_lines = params.get("boot_lines", [])
	# Return-visit tint (mock 01): apply the last-played pack.
	var last := str(ClientSettings.get_value("ui/last_played_pack"))
	if last != "" and PackThemes.current.id != last:
		PackThemes.apply(last)
	else:
		_rebuild()
	await _load_data()


func _client() -> Node:
	return client_override if client_override != null else Services.client


func _on_pack_changed(t: PackTheme) -> void:
	_theme = t
	if is_inside_tree():
		_rebuild()


func _load_data() -> void:
	var saves_res: EngineResult = await _client().list_saves()
	if saves_res.ok:
		_saves = saves_res.data.get("saves", [])
	else:
		_saves = []
		Services.overlay.toast_error(saves_res)
	var status_res: EngineResult = await _client().llm_status()
	if status_res.ok:
		_status = status_res.data
	_apply_data()


# --- view -------------------------------------------------------------------


func _rebuild() -> void:
	for child: Node in get_children():
		child.queue_free()
	_menu = {}
	_build()
	_apply_data()


func _build() -> void:
	var t := _theme
	var bg := ColorRect.new()
	bg.color = t.bg
	bg.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(bg)

	var root := VBoxContainer.new()
	root.set_anchors_preset(Control.PRESET_FULL_RECT)
	root.add_theme_constant_override("separation", 0)
	add_child(root)

	var body := HBoxContainer.new()
	body.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body.add_theme_constant_override("separation", 0)
	root.add_child(body)

	_build_rail(body, t)

	_backdrop = SceneBackdrop.new()
	_backdrop.theme = t
	_backdrop.scene_id = "night"
	_backdrop.kicker_text = "◤ VIEWPORT · DEEP FIELD"
	_backdrop.footer_text = "RUUTH PRIME ORBIT · LOCAL DRIFT"
	_backdrop.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	body.add_child(_backdrop)

	_strip = StatusStrip.new()
	_strip.theme = t
	root.add_child(_strip)


func _build_rail(body: HBoxContainer, t: PackTheme) -> void:
	var rail := PanelContainer.new()
	rail.custom_minimum_size = Vector2(380, 0)
	var rail_sb := StyleBoxFlat.new()
	rail_sb.bg_color = t.bg
	rail_sb.border_width_right = 2
	rail_sb.border_color = t.line
	rail.add_theme_stylebox_override("panel", rail_sb)
	body.add_child(rail)

	var margin := MarginContainer.new()
	margin.add_theme_constant_override("margin_left", 28)
	margin.add_theme_constant_override("margin_top", 38)
	margin.add_theme_constant_override("margin_right", 28)
	margin.add_theme_constant_override("margin_bottom", 16)
	rail.add_child(margin)

	var col := VBoxContainer.new()
	col.add_theme_constant_override("separation", 8)
	margin.add_child(col)

	var wordmark_font := FontVariation.new()
	wordmark_font.base_font = Fonts.title()
	wordmark_font.spacing_glyph = 6  # .16em at 40px
	col.add_child(Fonts.label("ANDROMEDA", wordmark_font, 40, t.ink))
	col.add_child(Fonts.label("WRITTEN IN THE STARS", Fonts.micro_tracked(), 12, t.accent))

	var rule := _AccentRule.new()
	rule.theme = t
	col.add_child(rule)

	var spacer_top := Control.new()
	spacer_top.custom_minimum_size = Vector2(0, 12)
	col.add_child(spacer_top)

	for entry: Array in _MENU:
		var action: String = entry[0]
		var docket := Kit.menu_item(entry[1], entry[2], "", t)
		docket.docket_pressed.connect(_on_menu_pressed.bind(action))
		col.add_child(docket)
		_menu[action] = {"docket": docket, "note": ""}

	var spacer := Control.new()
	spacer.size_flags_vertical = Control.SIZE_EXPAND_FILL
	col.add_child(spacer)

	_boot_label = Fonts.label("", Fonts.micro_tracked(), 12, t.muted)
	col.add_child(_boot_label)


class _AccentRule:
	extends Control
	## Mock 01: 190×2 accent rule with the pack motif at its right end.

	var theme: PackTheme

	func _init() -> void:
		custom_minimum_size = Vector2(190, 10)

	func _draw() -> void:
		if theme == null:
			return
		draw_rect(Rect2(Vector2(0, 4), Vector2(190, 2)), theme.accent)
		draw_string(Fonts.micro(), Vector2(196, 12), theme.motif, HORIZONTAL_ALIGNMENT_LEFT, -1, 12, theme.accent)


# --- data -------------------------------------------------------------------


func _apply_data() -> void:
	if _boot_label == null:
		return
	_boot_label.text = "\n".join(PackedStringArray(_boot_lines))
	# Continue: most recently modified entry (spec §7.1).
	var latest := {}
	for entry: Dictionary in _saves:
		if latest.is_empty() or float(entry["mtime"]) > float(latest["mtime"]):
			latest = entry
	var continue_note := ""
	if not latest.is_empty():
		var who := str(latest.get("character_name", ""))
		if who == "":
			who = str(latest.get("base_name", ""))
		continue_note = "%s · %s" % [who.to_upper(), Kit.relative_mtime(float(latest["mtime"]))]
	_set_menu_note("continue", continue_note, not latest.is_empty())
	_set_menu_note("chronicles", "%d SAVES" % Kit.chronicle_count(_saves), true)
	_set_menu_note("new_journey", "", true)
	_set_menu_note("settings", "", true)
	_set_menu_note("quit", "", true)
	(_menu["quit"]["docket"] as Control).modulate.a = 0.55  # dim styling per mock
	_strip.theme = _theme
	_strip.restyle()
	_strip.refresh(_status)


func _set_menu_note(action: String, note: String, enabled: bool) -> void:
	var entry: Dictionary = _menu[action]
	entry["note"] = note
	entry["enabled"] = enabled
	var docket: Kit.MenuDocket = entry["docket"]
	docket.set_note(note)
	docket.disabled = not enabled


# --- accessors used by tests ------------------------------------------------


func menu_note(action: String) -> String:
	return str(_menu.get(action, {}).get("note", ""))


func menu_enabled(action: String) -> bool:
	return bool(_menu.get(action, {}).get("enabled", false))


func boot_text() -> String:
	return _boot_label.text


## Programmatic menu press (tests + keyboard later).
func press_menu(action: String) -> void:
	if menu_enabled(action):
		_on_menu_pressed(action)


func _on_menu_pressed(action: String) -> void:
	match action:
		"new_journey", "chronicles", "settings":
			navigate.emit(action, {})
		"quit":
			Services.shutdown()
			get_tree().quit()
		"continue":
			_continue()


func _continue() -> void:
	var latest := {}
	for entry: Dictionary in _saves:
		if latest.is_empty() or float(entry["mtime"]) > float(latest["mtime"]):
			latest = entry
	if latest.is_empty():
		return
	var res: EngineResult = await _client().resume_session(str(latest["base_name"]))
	if not res.ok:
		Services.overlay.toast_error(res)
		return
	var session: Dictionary = res.data["session"]
	if not _client().contract_matches(session):
		Services.overlay.toast(
			"contract drift: chronicle v%d, engine v%d — update the client"
			% [int(session.get("contract_version", -1)), _client().contract_chargen],
			"bad"
		)
		return
	SessionStore.set_current(session)
	ClientSettings.set_value("ui/last_played_pack", str(latest.get("theme_pack", "")))
	PackThemes.apply(str(latest.get("theme_pack", "neutral")))
	navigate.emit("stub", {"session": session})
```

- [ ] **Step 4: add `set_note` to MenuDocket** — in `client/components/kit.gd`, inside `class MenuDocket`, after `setup`, insert exactly (screens update the note after data loads):

```gdscript
	func set_note(note: String) -> void:
		if get_child_count() < 1:
			return
		var row := get_child(0)
		# note label is the last child when present
		if note == "":
			if row.get_child_count() > 2:
				row.get_child(row.get_child_count() - 1).queue_free()
			return
		if row.get_child_count() > 2:
			(row.get_child(row.get_child_count() - 1) as Label).text = note
		else:
			row.add_child(Fonts.label(note, Fonts.micro_tracked(), 12, _theme.muted))
```

Also in `MenuDocket.setup`, remove the early `if note != "":` guard's coupling to later updates — keep setup as written; `set_note` handles both directions.

- [ ] **Step 5: run tests, verify pass**

Run: `tools/run_client_tests.sh`
Expected: PASS (4 new tests). If `menu_note("continue")` fails on timing, check `Kit.relative_mtime` math — the fixture is exactly 7200s old → `2H AGO`.

- [ ] **Step 6: lint, format, full gate, commit**

Run: `uv run gdformat client/... (the six touched paths) && tools/run_client_lint.sh && tools/run_client_tests.sh` plus `uv run ruff check . && uv run pytest tests/ -q`.

```bash
git add client/screens/title_screen.gd client/app client/components/kit.gd client/tests/screens
git commit -m "feat(client): M2.7 Title screen — console boot, menu dockets, continue/resume wiring"
```

---

## Task 8 (M2.8): Settings screen

**Files:**
- Create: `client/screens/settings_screen.gd`
- Modify: `client/app/status_strip.gd` (add narrator-left + plain-right modes), `client/components/kit.gd` (add `screen_header` + `option`), `client/tests/engine/fake_engine_client.gd` (add `last_rtt_ms`), `client/app/main.gd` (register the real SettingsScreen)
- Test: `client/tests/screens/test_settings_screen.gd`

**Interfaces:**
- Consumes: Tasks 2–7.
- Produces: `SettingsScreen` (BaseScreen); `Kit.screen_header(title_text, t, right_hint := "ESC — BACK") -> PanelContainer`; `Kit.option(items: PackedStringArray, t: PackTheme) -> OptionButton`; `StatusStrip.show_narrator_left(status: Dictionary)`, `StatusStrip.set_right_plain(text: String)`. Screen params: none.
- Test hooks: members `_provider_option`, `_model_option`, `_key_status`, `_conn_status`, `_provider_warning`, `_retries_edit`, `_base_url_edit`, `_data_line`; methods `press_save()`, `press_test()`, `select_provider_index(i: int)`.

**Supporting edits (exact):**

1. `client/app/status_strip.gd` — append:

```gdscript
## Mock 05 strip: narrator on the left, plain status text on the right.
func show_narrator_left(status: Dictionary) -> void:
	var configured := bool(status.get("configured", false))
	if configured:
		_left_sync.text = "NARRATOR: %s " % str(status.get("model", "")).to_upper()
	else:
		_left_sync.text = "NARRATOR: TEMPLATES "
	_left_tick.text = "●" if configured else "○"
	_left_version.text = ""
	if theme != null:
		_left_tick.add_theme_color_override("font_color", theme.ok if configured else theme.muted)


func set_right_plain(text: String) -> void:
	_right_text.text = text
	_right_dot.text = ""
```

2. `client/components/kit.gd` — append (outside any class):

```gdscript
## Screen header (mocks 02/03/05): motif+title left, hint micro right, 2px bottom rule.
static func screen_header(title_text: String, t: PackTheme, right_hint := "ESC — BACK") -> PanelContainer:
	var p := PanelContainer.new()
	var sb := StyleBoxFlat.new()
	sb.bg_color = t.bg
	sb.border_width_bottom = 2
	sb.border_color = t.line
	sb.content_margin_left = 18
	sb.content_margin_top = 12
	sb.content_margin_right = 18
	sb.content_margin_bottom = 10
	p.add_theme_stylebox_override("panel", sb)
	var row := HBoxContainer.new()
	p.add_child(row)
	var title := Fonts.label("%s %s" % [t.motif, title_text], Fonts.title(), 20, t.ink)
	title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(title)
	row.add_child(Fonts.label(right_hint, Fonts.micro_tracked(), 12, t.muted))
	return p


## Styled dropdown (mock 05 provider/model fields).
static func option(items: PackedStringArray, t: PackTheme) -> OptionButton:
	var o := OptionButton.new()
	for item: String in items:
		o.add_item(item)
	o.add_theme_font_override("font", Fonts.data())
	o.add_theme_font_size_override("font_size", 11)
	o.add_theme_color_override("font_color", t.ink)
	var sb := StyleBoxFlat.new()
	sb.bg_color = t.bg
	sb.set_border_width_all(2)
	sb.border_color = t.line
	sb.content_margin_left = 10
	sb.content_margin_top = 6
	sb.content_margin_bottom = 6
	for state: String in ["normal", "hover", "pressed"]:
		o.add_theme_stylebox_override(state, sb)
	var popup := o.get_popup()
	popup.add_theme_font_override("font", Fonts.data())
	popup.add_theme_font_size_override("font_size", 11)
	return o
```

3. `client/tests/engine/fake_engine_client.gd` — add with the other vars:

```gdscript
var last_rtt_ms := 12  # deterministic latency for the settings status line
```

4. `client/app/main.gd` — in `_register_screens()`, replace the settings placeholder line with:

```gdscript
	_stack.register("settings", SettingsScreen.new())
```

- [ ] **Step 1: failing test** — create `client/tests/screens/test_settings_screen.gd` exactly:

```gdscript
extends GdUnitTestSuite
## Settings screen against FakeEngineClient (mock 05).

var _fake: FakeEngineClient
var _screen: SettingsScreen


func before_test() -> void:
	_fake = auto_free(FakeEngineClient.new())
	add_child(_fake)
	_fake.responses["get_settings"] = FakeEngineClient.ok(
		{
			"provider": "anthropic",
			"model": "claude-sonnet-5",
			"base_url": "",
			"max_retries": 3,
			"is_configured": true,
			"key_backend": "keyring",
			"key_tail": "wxyz",
		}
	)
	_fake.responses["list_providers"] = FakeEngineClient.ok(
		{
			"providers": [
				{
					"id": "anthropic",
					"label": "Anthropic",
					"presets": ["claude-sonnet-5", "claude-opus-5", "claude-haiku-4-5-20251001"],
					"default_base_url": "https://api.anthropic.com",
					"needs_base_url": false,
				},
				{
					"id": "openrouter",
					"label": "OpenRouter",
					"presets": ["anthropic/claude-sonnet-5"],
					"default_base_url": "https://openrouter.ai/api",
					"needs_base_url": false,
				},
			]
		}
	)
	_fake.responses["llm_status"] = FakeEngineClient.ok(
		{"configured": true, "model": "claude-sonnet-5", "key_backend": "keyring", "degraded_line": null}
	)
	_fake.responses["list_saves"] = FakeEngineClient.ok({"saves": []})
	_fake.responses["put_settings"] = FakeEngineClient.ok(
		{
			"provider": "anthropic",
			"model": "claude-sonnet-5",
			"base_url": "",
			"max_retries": 3,
			"is_configured": true,
			"key_backend": "keyring",
			"key_tail": "wxyz",
		}
	)
	_screen = auto_free(SettingsScreen.new())
	_screen.client_override = _fake
	add_child(_screen)
	await _screen.screen_enter({})


func test_fields_populate_from_server() -> void:
	assert_str(_screen._provider_option.get_item_text(_screen._provider_option.selected)).is_equal("Anthropic")
	assert_str(_screen._model_option.get_item_text(_screen._model_option.selected)).is_equal("claude-sonnet-5")
	assert_str(_screen._retries_edit.text).is_equal("3")
	assert_str(_screen._key_status.text).is_equal("sk-…wxyz · OS KEYRING")
	assert_str(_screen._data_line.text).is_equal("saves/ · 0 chronicles · autosaves on")
	assert_bool(_screen._provider_warning.visible).is_false()


func test_provider_switch_shows_the_key_warning() -> void:
	var idx := -1
	for i: int in _screen._provider_option.item_count:
		if _screen._provider_option.get_item_text(i) == "OpenRouter":
			idx = i
	_screen.select_provider_index(idx)
	assert_bool(_screen._provider_warning.visible).is_true()
	assert_str(_screen._provider_warning.text).is_equal(
		"Switching provider clears the stored key — re-enter it for the new provider."
	)


func test_test_connection_ok_line() -> void:
	_fake.responses["test_settings"] = FakeEngineClient.ok({"ok": true, "models": ["claude-sonnet-5"]})
	_screen.press_test()
	await get_tree().process_frame
	await get_tree().process_frame
	assert_str(_screen._conn_status.text).is_equal("✓ CONNECTION OK · claude-sonnet-5 · 12ms")


func test_test_connection_failure_line_is_verbatim() -> void:
	_fake.responses["test_settings"] = FakeEngineClient.ok({"ok": false, "error": "No API key stored"})
	_screen.press_test()
	await get_tree().process_frame
	await get_tree().process_frame
	assert_str(_screen._conn_status.text).is_equal("✗ No API key stored")


func test_save_sends_null_api_key_and_confirms() -> void:
	_screen.press_save()
	await get_tree().process_frame
	await get_tree().process_frame
	var puts := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "put_settings")
	assert_that(puts.size()).is_equal(1)
	var payload: Dictionary = puts[0][1]
	assert_str(str(payload["provider"])).is_equal("anthropic")
	assert_str(str(payload["model"])).is_equal("claude-sonnet-5")
	assert_bool(payload.has("api_key")).is_true()
	assert_that(payload["api_key"]).is_equal(null)
	assert_str(_screen._strip._right_text.text).is_equal("SETTINGS SAVED")
```

- [ ] **Step 2: run tests, verify failure**

Run: `tools/run_client_tests.sh`
Expected: FAIL — `SettingsScreen` unknown.

- [ ] **Step 3: `client/screens/settings_screen.gd`** — create exactly. Layout per mock 05: header, two-column grid (left SERVER · THE NARRATOR card; right column CLIENT · READING + CLIENT · AUDIO + SERVER · DATA), strip with narrator-left / saved-right. Copy strings are verbatim from the mock. Key semantics per §A7: SAVE sends `api_key: null` unless REPLACE mode is active; in REPLACE mode an empty field asks for confirmation (via `Services.overlay.confirm`) before sending `""` (delete). The REMOVE-KEY confirm path is not unit-tested (modal awaits input); it is on Task 11's manual checklist.

```gdscript
class_name SettingsScreen
extends BaseScreen
## 05-settings.html: server-owned narrator card (keyring-backed key, live
## test), client-owned reading/audio cards (user://settings.cfg), server data
## card. Server cards persist via PUT /v1/settings/llm; client cards write
## ClientSettings immediately.

## Test hook: when set, used instead of Services.client.
var client_override: Node

var _theme: PackTheme
var _settings: Dictionary = {}
var _providers: Array = []
var _status: Dictionary = {}
var _replace_key_mode := false

var _provider_option: OptionButton
var _model_option: OptionButton
var _key_status: Label
var _key_edit: LineEdit
var _base_url_edit: LineEdit
var _retries_edit: LineEdit
var _conn_status: Label
var _storage_status: Label
var _provider_warning: Label
var _data_line: Label
var _strip: StatusStrip
var _text_speed: Kit.SegmentedControl
var _ambient_toggle: Kit.Toggle
var _motion_toggle: Kit.Toggle
var _master_slider: HSlider
var _music_slider: HSlider
var _effects_slider: HSlider


func _ready() -> void:
	_theme = PackThemes.current
	PackThemes.pack_changed.connect(_on_pack_changed)
	_rebuild()


func esc_target() -> String:
	return "title"


func screen_enter(_params: Dictionary) -> void:
	await _load_data()


func _client() -> Node:
	return client_override if client_override != null else Services.client


func _on_pack_changed(t: PackTheme) -> void:
	_theme = t
	if is_inside_tree():
		_rebuild()


func _load_data() -> void:
	var settings_res: EngineResult = await _client().get_settings()
	if settings_res.ok:
		_settings = settings_res.data
	else:
		Services.overlay.toast_error(settings_res)
	var providers_res: EngineResult = await _client().list_providers()
	if providers_res.ok:
		_providers = providers_res.data.get("providers", [])
	var status_res: EngineResult = await _client().llm_status()
	if status_res.ok:
		_status = status_res.data
	var saves_res: EngineResult = await _client().list_saves()
	var saves: Array = saves_res.data.get("saves", []) if saves_res.ok else []
	_rebuild()
	_populate(saves)


# --- view -------------------------------------------------------------------


func _rebuild() -> void:
	for child: Node in get_children():
		child.queue_free()
	_build()


func _build() -> void:
	var t := _theme
	var bg := ColorRect.new()
	bg.color = t.bg
	bg.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(bg)

	var root := VBoxContainer.new()
	root.set_anchors_preset(Control.PRESET_FULL_RECT)
	root.add_theme_constant_override("separation", 0)
	add_child(root)
	root.add_child(Kit.screen_header("SETTINGS", t))

	var pad := MarginContainer.new()
	pad.size_flags_vertical = Control.SIZE_EXPAND_FILL
	pad.add_theme_constant_override("margin_left", 18)
	pad.add_theme_constant_override("margin_top", 16)
	pad.add_theme_constant_override("margin_right", 18)
	pad.add_theme_constant_override("margin_bottom", 18)
	root.add_child(pad)

	var scroll := ScrollContainer.new()
	scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	pad.add_child(scroll)

	var grid := HBoxContainer.new()
	grid.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	grid.add_theme_constant_override("separation", 16)
	scroll.add_child(grid)

	grid.add_child(_narrator_card(t))
	var right := VBoxContainer.new()
	right.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	right.add_theme_constant_override("separation", 16)
	grid.add_child(right)
	right.add_child(_reading_card(t))
	right.add_child(_audio_card(t))
	right.add_child(_data_card(t))

	_strip = StatusStrip.new()
	_strip.theme = t
	root.add_child(_strip)


func _card_title(text: String, t: PackTheme) -> Label:
	return Fonts.label(text, Fonts.data(), 10, t.muted)


func _row(label_text: String, field: Control, t: PackTheme) -> HBoxContainer:
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 10)
	var label := Fonts.label(label_text, Fonts.inter(), 11, t.ink)
	label.custom_minimum_size = Vector2(118, 0)
	row.add_child(label)
	field.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(field)
	return row


func _narrator_card(t: PackTheme) -> Control:
	var card := Kit.card(t)
	card.custom_minimum_size = Vector2(520, 0)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 9)
	card.add_child(box)
	box.add_child(_card_title("SERVER · THE NARRATOR", t))

	_provider_option = Kit.option(PackedStringArray(), t)
	_provider_option.item_selected.connect(_on_provider_selected)
	box.add_child(_row("Provider", _provider_option, t))

	_model_option = Kit.option(PackedStringArray(), t)
	box.add_child(_row("Model", _model_option, t))

	_key_status = Fonts.label("", Fonts.data(), 11, t.muted)
	var key_field := Kit.data_field("", t)
	(key_field.get_meta("label") as Label).queue_free()
	key_field.add_child(_key_status)
	box.add_child(_row("API key", key_field, t))

	_key_edit = LineEdit.new()
	_key_edit.secret = true
	_key_edit.visible = false
	_key_edit.add_theme_font_override("font", Fonts.data())
	box.add_child(_key_edit)

	_base_url_edit = LineEdit.new()
	_base_url_edit.placeholder_text = "provider default"
	box.add_child(_row("Base URL", _base_url_edit, t))

	_retries_edit = LineEdit.new()
	_retries_edit.text = "3"
	box.add_child(_row("Max retries", _retries_edit, t))

	_provider_warning = Fonts.label(
		"Switching provider clears the stored key — re-enter it for the new provider.",
		Fonts.prose(),
		11,
		t.danger
	)
	_provider_warning.visible = false
	_provider_warning.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	box.add_child(_provider_warning)

	var button_row := HBoxContainer.new()
	button_row.add_theme_constant_override("separation", 10)
	box.add_child(button_row)
	var test_btn := Kit.btn("TEST CONNECTION", t)
	test_btn.pressed.connect(press_test)
	button_row.add_child(test_btn)
	var save_btn := Kit.ghost_btn("SAVE", t)
	save_btn.pressed.connect(press_save)
	button_row.add_child(save_btn)
	var replace := Kit.microlink("REPLACE KEY", t)
	replace.pressed.connect(_on_replace_key)
	button_row.add_child(replace)

	_conn_status = Fonts.label("", Fonts.data(), 10, t.ok)
	box.add_child(_conn_status)
	_storage_status = Fonts.label("", Fonts.data(), 10, t.ok)
	box.add_child(_storage_status)
	var fallback := Fonts.label(
		"No OS keyring → owner-only file fallback, said so here. Narration falls back to templates — the game never breaks.",
		Fonts.data(),
		10,
		t.muted
	)
	fallback.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	box.add_child(fallback)
	return card


func _reading_card(t: PackTheme) -> Control:
	var card := Kit.card(t)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 10)
	card.add_child(box)
	box.add_child(_card_title("CLIENT · READING", t))
	_text_speed = Kit.segmented(PackedStringArray(["SLOW", "MEDIUM", "FAST", "INSTANT"]), 1, t)
	_text_speed.option_chosen.connect(_on_text_speed)
	box.add_child(_row("Text speed", _text_speed, t))
	_ambient_toggle = Kit.toggle(bool(ClientSettings.get_value("reading/ambient_life")), t)
	_ambient_toggle.toggled.connect(
		func(on: bool) -> void: ClientSettings.set_value("reading/ambient_life", on)
	)
	var ambient_row := _row("Ambient life", _ambient_toggle, t)
	ambient_row.add_child(Fonts.label("meteors, birds, fireflies", Fonts.prose(), 11, t.muted))
	box.add_child(ambient_row)
	_motion_toggle = Kit.toggle(bool(ClientSettings.get_value("reading/reduced_motion")), t)
	_motion_toggle.toggled.connect(
		func(on: bool) -> void: ClientSettings.set_value("reading/reduced_motion", on)
	)
	var motion_row := _row("Reduced motion", _motion_toggle, t)
	motion_row.add_child(Fonts.label("stills all animation", Fonts.prose(), 11, t.muted))
	box.add_child(motion_row)
	return card


func _audio_card(t: PackTheme) -> Control:
	var card := Kit.card(t)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 10)
	card.add_child(box)
	box.add_child(_card_title("CLIENT · AUDIO", t))
	_master_slider = _wired_slider("audio/master", t)
	box.add_child(_row("Master", _master_slider, t))
	_music_slider = _wired_slider("audio/music", t)
	box.add_child(_row("Music", _music_slider, t))
	_effects_slider = _wired_slider("audio/effects", t)
	box.add_child(_row("Effects", _effects_slider, t))
	return card


func _wired_slider(key: String, t: PackTheme) -> HSlider:
	var s := Kit.slider(float(ClientSettings.get_value(key)), t)
	s.value_changed.connect(func(v: float) -> void: ClientSettings.set_value(key, v))
	return s


func _data_card(t: PackTheme) -> Control:
	var card := Kit.card(t)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 10)
	card.add_child(box)
	box.add_child(_card_title("SERVER · DATA", t))
	_data_line = Fonts.label("", Fonts.data(), 11, t.muted)
	var field := Kit.data_field("", t)
	(field.get_meta("label") as Label).queue_free()
	field.add_child(_data_line)
	box.add_child(_row("Saves", field, t))
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 10)
	box.add_child(row)
	var open := Kit.ghost_btn("OPEN CHRONICLES ▸", t)
	open.pressed.connect(func() -> void: navigate.emit("chronicles", {}))
	row.add_child(open)
	var export := Kit.ghost_btn("EXPORT ALL", t)
	export.pressed.connect(_on_export_all)
	row.add_child(export)
	return card


# --- data -------------------------------------------------------------------


func _populate(saves: Array) -> void:
	_provider_option.clear()
	for p: Dictionary in _providers:
		_provider_option.add_item(str(p["label"]))
		_provider_option.set_item_metadata(_provider_option.item_count - 1, str(p["id"]))
	var current_provider := str(_settings.get("provider", "anthropic"))
	for i: int in _provider_option.item_count:
		if str(_provider_option.get_item_metadata(i)) == current_provider:
			_provider_option.select(i)
	_populate_models(current_provider)
	_base_url_edit.text = str(_settings.get("base_url", ""))
	_retries_edit.text = str(int(_settings.get("max_retries", 3)))
	_update_key_status()
	_storage_status.text = _storage_line()
	_data_line.text = "saves/ · %d chronicles · autosaves on" % Kit.chronicle_count(saves)
	_strip.show_narrator_left(_status)
	_strip.set_right_plain("")


func _populate_models(provider_id: String) -> void:
	_model_option.clear()
	for p: Dictionary in _providers:
		if str(p["id"]) == provider_id:
			for preset: String in p.get("presets", []):
				_model_option.add_item(preset)
	var current_model := str(_settings.get("model", ""))
	for i: int in _model_option.item_count:
		if _model_option.get_item_text(i) == current_model:
			_model_option.select(i)


func _update_key_status() -> void:
	var tail := str(_settings.get("key_tail", ""))
	if tail == "":
		_key_status.text = "not stored — REPLACE to add"
	else:
		_key_status.text = "sk-…%s · %s" % [tail, _backend_label()]


func _backend_label() -> String:
	match str(_settings.get("key_backend", "")):
		"keyring":
			return "OS KEYRING"
		"file":
			return "OWNER-ONLY FILE"
	return "NOT STORED"


func _storage_line() -> String:
	match str(_settings.get("key_backend", "")):
		"keyring":
			return "✓ KEY STORAGE: OS KEYRING"
		"file":
			return "✓ KEY STORAGE: OWNER-ONLY FILE (no OS keyring available)"
	return "KEY STORAGE: NOT STORED"


func _selected_provider_id() -> String:
	if _provider_option.selected < 0:
		return str(_settings.get("provider", "anthropic"))
	return str(_provider_option.get_item_metadata(_provider_option.selected))


func _on_provider_selected(index: int) -> void:
	var provider_id := str(_provider_option.get_item_metadata(index))
	_provider_warning.visible = provider_id != str(_settings.get("provider", ""))
	_populate_models(provider_id)


func select_provider_index(i: int) -> void:
	_provider_option.select(i)
	_on_provider_selected(i)


func _on_replace_key() -> void:
	_replace_key_mode = true
	_key_edit.visible = true
	_key_edit.placeholder_text = "new key — empty on SAVE removes the stored key"
	_key_edit.grab_focus()


func _on_text_speed(index: int) -> void:
	var values := ["slow", "medium", "fast", "instant"]
	ClientSettings.set_value("reading/text_speed", values[index])


# --- actions ----------------------------------------------------------------


func press_test() -> void:
	_conn_status.text = "TESTING…"
	var res: EngineResult = await _client().test_settings()
	if res.ok and bool(res.data.get("ok", false)):
		_conn_status.text = "✓ CONNECTION OK · %s · %dms" % [
			str(_settings.get("model", "")), int(_client().last_rtt_ms)
		]
		_conn_status.add_theme_color_override("font_color", _theme.ok)
	else:
		var message := (
			str(res.data.get("error", "")) if res.ok else res.error_message
		)
		_conn_status.text = "✗ " + message
		_conn_status.add_theme_color_override("font_color", _theme.danger)


func press_save() -> void:
	var retries_text := _retries_edit.text.strip_edges()
	if not retries_text.is_valid_int() or int(retries_text) < 0 or int(retries_text) > 10:
		Services.overlay.toast("MAX RETRIES: whole number 0–10", "bad")
		return
	var payload := {
		"provider": _selected_provider_id(),
		"model": _model_option.get_item_text(maxi(_model_option.selected, 0)),
		"base_url": _base_url_edit.text.strip_edges(),
		"max_retries": int(retries_text),
		"api_key": null,
	}
	if _replace_key_mode:
		var entered := _key_edit.text.strip_edges()
		if entered == "":
			var remove: bool = await Services.overlay.confirm(
				"REMOVE THE STORED KEY?",
				"The narrator will fall back to templates until a new key is saved.",
				"REMOVE",
				"KEEP"
			)
			if not remove:
				return
			payload["api_key"] = ""
		else:
			payload["api_key"] = entered
	var res: EngineResult = await _client().put_settings(payload)
	if not res.ok:
		Services.overlay.toast_error(res)
		return
	_settings = res.data
	_replace_key_mode = false
	_key_edit.visible = false
	_key_edit.text = ""
	_update_key_status()
	_storage_status.text = _storage_line()
	_provider_warning.visible = false
	_strip.set_right_plain("SETTINGS SAVED")


func _on_export_all() -> void:
	DisplayServer.file_dialog_show(
		"EXPORT ALL CHRONICLES — choose a folder",
		"",
		PackedStringArray(),
		DisplayServer.FILE_DIALOG_MODE_OPEN_DIR,
		Callable(self, "_on_export_dir")
	)


func _on_export_dir(status: bool, paths: PackedStringArray, _selected_filter: int) -> void:
	if not status or paths.is_empty():
		return
	var dir: String = paths[0]
	var saves_res: EngineResult = await _client().list_saves()
	if not saves_res.ok:
		Services.overlay.toast_error(saves_res)
		return
	var names := {}
	for entry: Dictionary in saves_res.data.get("saves", []):
		names[str(entry["base_name"])] = true
	var exported := 0
	for save_name: String in names.keys():
		var res: EngineResult = await _client().export_save(save_name)
		if not res.ok:
			Services.overlay.toast_error(res)
			return
		var f := FileAccess.open(dir.path_join(save_name + ".json"), FileAccess.WRITE)
		if f == null:
			Services.overlay.toast("could not write into " + dir, "bad")
			return
		f.store_string(JSON.stringify(res.data))
		f.close()
		exported += 1
	Services.overlay.toast("EXPORTED %d CHRONICLES → %s" % [exported, dir], "ok")
```

**Pin — two mock deviations, deliberate:**
1. Mock 05's storage line says `WINDOWS CREDENTIAL MANAGER (OS KEYRING)` — the server reports only the backend class (`keyring`/`file`/`""`, §A7), never the OS product name, so the client renders `OS KEYRING` / `OWNER-ONLY FILE` / `NOT STORED` (spec §7.2 generalized this).
2. The settings strip per mock has the narrator on the *left* and the save notice on the *right* — hence `show_narrator_left`/`set_right_plain` instead of `refresh()`.

- [ ] **Step 4: run tests, verify pass**

Run: `tools/run_client_tests.sh`
Expected: PASS (5 new tests). Note `12ms` in the test comes from the fake's `last_rtt_ms := 12`.

- [ ] **Step 5: lint, format, full gate, commit**

Run: `uv run gdformat client/screens client/components client/app client/tests && tools/run_client_lint.sh && tools/run_client_tests.sh` plus ruff + pytest.

```bash
git add client/screens/settings_screen.gd client/app client/components/kit.gd client/tests
git commit -m "feat(client): M2.8 Settings screen — narrator card, reading/audio, data card"
```

---

## Task 9 (M2.9): Chronicles screen

**Files:**
- Create: `client/screens/chronicles_screen.gd`
- Modify: `client/app/overlay_layer.gd` (add `prompt`), `client/app/main.gd` (register the real ChroniclesScreen)
- Test: `client/tests/screens/test_chronicles_screen.gd`

**Interfaces:**
- Consumes: Tasks 2–8.
- Produces: `ChroniclesScreen` (BaseScreen); `OverlayLayer.prompt(title: String, placeholder := "") -> String` (await it; `""` = cancelled). Screen params: none.
- Test hooks: `_list_box`, `_preview_name`, `_preview_prose`, `_preview_strip`, `_spines: Array`; methods `docket_count()`, `select_docket(i: int)`, `press_action(what: String)` (`"resume"|"duplicate"|"export"|"delete"`), `press_import()`.

**Supporting edits (exact):**

1. `client/app/overlay_layer.gd` — append to `OverlayLayer` (before the `_ConfirmModal` class):

```gdscript
## Modal text prompt; await it. Returns "" when cancelled.
func prompt(title: String, placeholder := "") -> String:
	var modal := _PromptModal.new()
	add_child(modal)
	modal.setup(title, placeholder, PackThemes.current)
	var answer: String = await modal.chosen
	modal.queue_free()
	return answer
```

and append this class at the end of the file:

```gdscript
class _PromptModal:
	extends Control

	signal chosen(text: String)

	func setup(title: String, placeholder: String, theme: PackTheme) -> void:
		set_anchors_preset(Control.PRESET_FULL_RECT)
		var dim := ColorRect.new()
		dim.color = Color(0, 0, 0, 0.6)
		dim.set_anchors_preset(Control.PRESET_FULL_RECT)
		add_child(dim)
		var center := CenterContainer.new()
		center.set_anchors_preset(Control.PRESET_FULL_RECT)
		add_child(center)
		var frame := SteppedFrame.new()
		frame.custom_minimum_size = Vector2(420, 0)
		frame.apply_theme(theme)
		center.add_child(frame)
		var box := VBoxContainer.new()
		box.add_theme_constant_override("separation", 10)
		frame.add_content(box)
		frame.set_content_margins(16, 14, 16, 14)
		box.add_child(Fonts.label(title, Fonts.inter(), 14, theme.ink))
		var edit := LineEdit.new()
		edit.placeholder_text = placeholder
		edit.add_theme_font_override("font", Fonts.data())
		edit.text_submitted.connect(
			func(text: String) -> void:
				if text.strip_edges() != "":
					chosen.emit(text.strip_edges())
		)
		box.add_child(edit)
		edit.grab_focus()
		var row := HBoxContainer.new()
		row.add_theme_constant_override("separation", 12)
		box.add_child(row)
		var ok_btn := Kit.btn("OK", theme)
		ok_btn.pressed.connect(
			func() -> void:
				if edit.text.strip_edges() != "":
					chosen.emit(edit.text.strip_edges())
		)
		row.add_child(ok_btn)
		var cancel_btn := Kit.ghost_btn("CANCEL", theme)
		cancel_btn.pressed.connect(func() -> void: chosen.emit(""))
		row.add_child(cancel_btn)
```

2. `client/app/main.gd` — in `_register_screens()`, replace the chronicles placeholder line with:

```gdscript
	_stack.register("chronicles", ChroniclesScreen.new())
```

**Pinned mock deviations (server payload limits — spec §13 two-sources rule):** `SaveEntry` (§A5) carries `career`, `terms`, `character_name`, `theme_pack`, `alive`, `mtime` — not rank, credits, mission, or scene. Therefore: docket line 1 is `{CAREER} · TERM {terms}` (career empty → `IN CHARGEN`); line 2 is `AUTO · {rel}` / `MANUAL · {rel}`; dead saves append ` · MEMORIALIZED` to line 1. The preview data strip is `{CAREER} · {terms} TERMS · {THEME_PACK} PACK` (all caps). Enriching these is server work, out of M2 scope.

**Vertical spine (pin):** mock 02's spine uses CSS `writing-mode: vertical-rl` (top-to-bottom). In Godot, `_Spine._draw` does `draw_set_transform(Vector2(size.x / 2 - 6, 8), PI / 2)` then `draw_string(...)` so the text reads top-to-bottom; the dashed left border is 2px-on/2px-off segments. Spine text: autosave → `AUTO·{rel}` (no "AGO", per mock); manual → `MANUAL`; dead → `✝ R.I.P.` in danger.

**Preview-session lifecycle (spec §7.3, pin):** selecting a docket awaits `_cleanup_preview()` (deletes the previous preview session), then `resume_session(base_name)` → `_preview_id`, then `recap(id)`. RESUME promotes: `SessionStore.set_current(preview)`, `_preview_id = ""`, apply pack + `last_played_pack`, navigate `stub`. `screen_exit` calls `_cleanup_preview()` without awaiting (fire-and-forget; the request completes in the background — the node stays in the tree while invisible).

- [ ] **Step 1: failing test** — create `client/tests/screens/test_chronicles_screen.gd` exactly:

```gdscript
extends GdUnitTestSuite
## Chronicles against FakeEngineClient (mock 02): dockets, preview, lifecycle.

var _fake: FakeEngineClient
var _screen: ChroniclesScreen


func _now() -> float:
	return Time.get_unix_time_from_system()


func _saves_payload() -> Dictionary:
	return {
		"saves": [
			{
				"name": "mara.autosave", "base_name": "mara", "autosave": true,
				"theme_pack": "scifi", "character_name": "Mara Voss", "terms": 4,
				"career": "Scout", "alive": true, "mtime": _now() - 7200.0,
			},
			{
				"name": "branwen", "base_name": "branwen", "autosave": false,
				"theme_pack": "fantasy", "character_name": "Branwen", "terms": 2,
				"career": "Bard", "alive": true, "mtime": _now() - 259200.0,
			},
			{
				"name": "rook", "base_name": "rook", "autosave": false,
				"theme_pack": "scifi", "character_name": "Rook (DEX-7)", "terms": 6,
				"career": "Marine", "alive": false, "mtime": _now() - 604800.0,
			},
		]
	}


func _envelope(save_name: String) -> Dictionary:
	return {
		"session": {
			"id": "sess-" + save_name, "name": save_name, "kind": "adventure",
			"phase": "scene", "view": {"phase": "scene", "game_over": false},
			"contract_version": 1,
		}
	}


func before_test() -> void:
	_fake = auto_free(FakeEngineClient.new())
	add_child(_fake)
	_fake.responses["list_saves"] = FakeEngineClient.ok(_saves_payload())
	_fake.responses["resume_session"] = [
		FakeEngineClient.ok(_envelope("mara")),
		FakeEngineClient.ok(_envelope("branwen")),
		FakeEngineClient.ok(_envelope("mara")),
	]
	_fake.responses["recap"] = FakeEngineClient.ok(
		{"lines": ["The crew took on a job.", "Unresolved: the beacon's debt"], "source": "template"}
	)
	_fake.responses["delete_session"] = FakeEngineClient.ok({})
	_fake.responses["delete_save"] = FakeEngineClient.ok({"deleted": ["mara.json"]})
	_fake.responses["duplicate_save"] = FakeEngineClient.ok({"created": ["mara-2.json"]})
	Services.overlay = auto_free(OverlayLayer.new())
	add_child(Services.overlay)
	_screen = auto_free(ChroniclesScreen.new())
	_screen.client_override = _fake
	add_child(_screen)
	await _screen.screen_enter({})
	# let the auto-selection of the first docket finish
	await get_tree().process_frame
	await get_tree().process_frame


func after_test() -> void:
	Services.overlay = null


func test_dockets_render_sorted_with_import_slot() -> void:
	# 3 saves + the import slot; autosave (newest mtime) first.
	assert_that(_screen.docket_count()).is_equal(4)
	assert_str(_screen._spines[0].text_content).is_equal("AUTO·2H")
	assert_str(_screen._spines[1].text_content).is_equal("MANUAL")
	assert_str(_screen._spines[2].text_content).is_equal("✝ R.I.P.")


func test_first_docket_auto_selected_with_recap() -> void:
	var resumes := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "resume_session")
	assert_that(resumes.size()).is_equal(1)
	assert_str(str(resumes[0][1])).is_equal("mara")
	assert_str(_screen._preview_name.text).is_equal("Mara Voss")
	assert_that(_screen._preview_prose.get_child_count()).is_equal(2)


func test_selection_change_deletes_previous_preview() -> void:
	await _screen.select_docket(1)
	await get_tree().process_frame
	await get_tree().process_frame
	var deletes := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "delete_session")
	assert_that(deletes.size()).is_equal(1)
	assert_str(str(deletes[0][1])).is_equal("sess-mara")
	var resumes := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "resume_session")
	assert_str(str(resumes[1][1])).is_equal("branwen")


func test_resume_promotes_preview_and_navigates() -> void:
	var nav: Array = []
	_screen.navigate.connect(func(target: String, params: Dictionary) -> void: nav.append([target, params]))
	_screen.press_action("resume")
	await get_tree().process_frame
	await get_tree().process_frame
	assert_str(str(nav[0][0])).is_equal("stub")
	assert_str(str(nav[0][1]["session"]["id"])).is_equal("sess-mara")
	assert_str(SessionStore.session_id()).is_equal("sess-mara")
	# promoted — exit must NOT delete it
	_screen.screen_exit()
	await get_tree().process_frame
	var deletes := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "delete_session")
	assert_that(deletes.size()).is_equal(0)
	SessionStore.clear()


func test_exit_deletes_unpromoted_preview() -> void:
	_screen.screen_exit()
	await get_tree().process_frame
	await get_tree().process_frame
	var deletes := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "delete_session")
	assert_that(deletes.size()).is_equal(1)
	assert_str(str(deletes[0][1])).is_equal("sess-mara")


func test_delete_flow_confirms_then_deletes() -> void:
	_screen.press_action("delete")
	await get_tree().process_frame
	# answer the confirm modal
	var modal: Node = Services.overlay.get_child(Services.overlay.get_child_count() - 1)
	modal._answer(true)
	await get_tree().process_frame
	await get_tree().process_frame
	var deletes := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "delete_save")
	assert_that(deletes.size()).is_equal(1)
	assert_str(str(deletes[0][1])).is_equal("mara")
```

- [ ] **Step 2: run tests, verify failure**

Run: `tools/run_client_tests.sh`
Expected: FAIL — `ChroniclesScreen` unknown.

- [ ] **Step 3: `client/screens/chronicles_screen.gd`** — create exactly. Layout per mock 02: header (`ESC — BACK TO TITLE`), 400px docket column, preview pane. Each docket is a `SteppedFrame` tinted to its save's pack with a 4px-margin wrapper that draws the accent selection outline; dead saves use the `dead` set.

```gdscript
class_name ChroniclesScreen
extends BaseScreen
## 02-chronicles.html: save dockets (per-pack tint, autosave spine) + recap
## preview + duplicate/export/delete/import. Selecting a docket resumes a
## preview session and fetches the recap (spec §7.3 lifecycle).

## Test hook: when set, used instead of Services.client.
var client_override: Node

var _theme: PackTheme
var _saves: Array = []
var _selected := -1
var _preview_id := ""
var _preview_session: Dictionary = {}

var _list_box: VBoxContainer
var _spines: Array = []
var _preview_name: Label
var _preview_strip: Label
var _preview_prose: VBoxContainer
var _preview_frame: SteppedFrame
var _strip: StatusStrip


func _ready() -> void:
	_theme = PackThemes.current
	PackThemes.pack_changed.connect(_on_pack_changed)
	_rebuild()


func esc_target() -> String:
	return "title"


func screen_enter(_params: Dictionary) -> void:
	await _load_data()


func screen_exit() -> void:
	if _preview_id != "":
		_cleanup_preview()  # fire-and-forget (spec §7.3)


func _client() -> Node:
	return client_override if client_override != null else Services.client


func _on_pack_changed(t: PackTheme) -> void:
	_theme = t
	if is_inside_tree():
		_rebuild()
		_render_list()
		_render_preview()


func _load_data() -> void:
	var res: EngineResult = await _client().list_saves()
	if res.ok:
		_saves = res.data.get("saves", [])
		_saves.sort_custom(func(a: Dictionary, b: Dictionary) -> bool: return float(a["mtime"]) > float(b["mtime"]))
	else:
		_saves = []
		Services.overlay.toast_error(res)
	_render_list()
	if not _saves.is_empty():
		await select_docket(0)
	else:
		_render_preview()


# --- view -------------------------------------------------------------------


func _rebuild() -> void:
	for child: Node in get_children():
		child.queue_free()
	_spines = []
	_build()


func _build() -> void:
	var t := _theme
	var bg := ColorRect.new()
	bg.color = t.bg
	bg.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(bg)

	var root := VBoxContainer.new()
	root.set_anchors_preset(Control.PRESET_FULL_RECT)
	root.add_theme_constant_override("separation", 0)
	add_child(root)
	root.add_child(Kit.screen_header("CHRONICLES", t, "ESC — BACK TO TITLE"))

	var pad := MarginContainer.new()
	pad.size_flags_vertical = Control.SIZE_EXPAND_FILL
	pad.add_theme_constant_override("margin_left", 18)
	pad.add_theme_constant_override("margin_top", 4)
	pad.add_theme_constant_override("margin_right", 18)
	pad.add_theme_constant_override("margin_bottom", 18)
	root.add_child(pad)

	var grid := HBoxContainer.new()
	grid.add_theme_constant_override("separation", 16)
	pad.add_child(grid)

	var scroll := ScrollContainer.new()
	scroll.custom_minimum_size = Vector2(400, 0)
	grid.add_child(scroll)
	_list_box = VBoxContainer.new()
	_list_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_list_box.add_theme_constant_override("separation", 10)
	scroll.add_child(_list_box)

	_preview_frame = Kit.px_frame(t)
	_preview_frame.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	grid.add_child(_preview_frame)

	_strip = StatusStrip.new()
	_strip.theme = t
	root.add_child(_strip)


func _render_list() -> void:
	for child: Node in _list_box.get_children():
		child.queue_free()
	_spines = []
	for i: int in _saves.size():
		_list_box.add_child(_build_docket(i))
	_list_box.add_child(_build_import_slot())
	_render_preview()


func _pack_of(entry: Dictionary) -> PackTheme:
	if not bool(entry.get("alive", true)):
		return PackThemes.get_theme("dead")
	return PackThemes.get_theme(str(entry.get("theme_pack", "neutral")))


func _build_docket(index: int) -> Control:
	var entry: Dictionary = _saves[index]
	var t := _pack_of(entry)
	var wrap := MarginContainer.new()  # 4px room for the selection outline
	wrap.add_theme_constant_override("margin_left", 4)
	wrap.add_theme_constant_override("margin_top", 4)
	wrap.add_theme_constant_override("margin_right", 4)
	wrap.add_theme_constant_override("margin_bottom", 4)
	wrap.set_meta("index", index)
	var outline := _SelectionOutline.new()
	wrap.add_child(outline)
	outline.set_anchors_preset(Control.PRESET_FULL_RECT)

	var frame := Kit.px_frame(t)
	frame.set_content_margins(10, 10, 12, 10)
	wrap.add_child(frame)

	var row := HBoxContainer.new()
	frame.add_content(row)
	var text_box := VBoxContainer.new()
	text_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(text_box)

	var display_name := str(entry.get("character_name", ""))
	if display_name == "":
		display_name = str(entry.get("base_name", ""))
	text_box.add_child(Fonts.label(display_name, Fonts.inter(), 15, t.ink))

	var career := str(entry.get("career", ""))
	var line1 := "%s · TERM %d" % [career.to_upper() if career != "" else "IN CHARGEN", int(entry.get("terms", 0))]
	if not bool(entry.get("alive", true)):
		line1 += " · MEMORIALIZED"
	var autosave := bool(entry.get("autosave", false))
	var line2 := "%s · %s" % ["AUTO" if autosave else "MANUAL", Kit.relative_mtime(float(entry.get("mtime", 0.0)))]
	text_box.add_child(Fonts.label(line1 + "\n" + line2, Fonts.data(), 10, t.muted))

	var spine := _Spine.new()
	if not bool(entry.get("alive", true)):
		spine.text_content = "✝ R.I.P."
		spine.text_color = t.danger
	elif autosave:
		spine.text_content = "AUTO·" + Kit.relative_mtime(float(entry.get("mtime", 0.0))).trim_suffix(" AGO")
		spine.text_color = t.accent
	else:
		spine.text_content = "MANUAL"
		spine.text_color = t.accent
	spine.line_color = t.line
	spine.custom_minimum_size = Vector2(24, 0)
	row.add_child(spine)
	_spines.append(spine)

	var click := Button.new()  # invisible full-rect click layer
	click.flat = true
	click.set_anchors_preset(Control.PRESET_FULL_RECT)
	click.add_theme_stylebox_override("focus", StyleBoxEmpty.new())
	click.pressed.connect(_on_docket_pressed.bind(index))
	wrap.add_child(click)
	return wrap


func _build_import_slot() -> Control:
	var t := _theme
	var wrap := MarginContainer.new()
	wrap.add_theme_constant_override("margin_left", 4)
	wrap.add_theme_constant_override("margin_top", 4)
	wrap.add_theme_constant_override("margin_right", 4)
	wrap.add_theme_constant_override("margin_bottom", 4)
	wrap.modulate.a = 0.55
	var frame := Kit.px_frame(t, "line", "panel")
	frame.set_content_margins(10, 10, 12, 10)
	wrap.add_child(frame)
	var box := VBoxContainer.new()
	frame.add_content(box)
	box.add_child(Fonts.label("— empty slot —", Fonts.inter(), 15, t.muted))
	box.add_child(Fonts.label("IMPORT A SAVE FILE…", Fonts.data(), 10, t.muted))
	var click := Button.new()
	click.flat = true
	click.set_anchors_preset(Control.PRESET_FULL_RECT)
	click.add_theme_stylebox_override("focus", StyleBoxEmpty.new())
	click.pressed.connect(press_import)
	wrap.add_child(click)
	return wrap


func _render_preview() -> void:
	for child: Node in _preview_frame.get_children():
		child.queue_free()
	var t := _theme
	if _selected >= 0 and _selected < _saves.size():
		t = _pack_of(_saves[_selected])
	_preview_frame.apply_theme(t)
	_preview_frame.set_content_margins(18, 16, 18, 16)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 10)
	_preview_frame.add_content(box)
	_preview_name = Fonts.label("", Fonts.title(), 22, t.ink)
	box.add_child(_preview_name)
	_preview_strip = Fonts.label("", Fonts.data(), 10, t.muted)
	box.add_child(_preview_strip)
	box.add_child(Fonts.label("THE STORY SO FAR", Fonts.data(), 10, t.accent))
	_preview_prose = VBoxContainer.new()
	_preview_prose.add_theme_constant_override("separation", 8)
	box.add_child(_preview_prose)
	var actions := HBoxContainer.new()
	actions.add_theme_constant_override("separation", 14)
	box.add_child(actions)
	var resume := Kit.btn("RESUME ▸", t)
	resume.pressed.connect(func() -> void: press_action("resume"))
	actions.add_child(resume)
	var dup := Kit.microlink("DUPLICATE", t)
	dup.pressed.connect(func() -> void: press_action("duplicate"))
	actions.add_child(dup)
	var exp := Kit.microlink("EXPORT", t)
	exp.pressed.connect(func() -> void: press_action("export"))
	actions.add_child(exp)
	var del := Kit.microlink("DELETE", t, true)
	del.pressed.connect(func() -> void: press_action("delete"))
	actions.add_child(del)
	if _selected >= 0 and _selected < _saves.size():
		_fill_preview_text(t)


func _fill_preview_text(t: PackTheme) -> void:
	var entry: Dictionary = _saves[_selected]
	var display_name := str(entry.get("character_name", ""))
	if display_name == "":
		display_name = str(entry.get("base_name", ""))
	_preview_name.text = display_name
	var career := str(entry.get("career", ""))
	_preview_strip.text = "%s · %d TERMS · %s PACK" % [
		career.to_upper() if career != "" else "IN CHARGEN",
		int(entry.get("terms", 0)),
		str(entry.get("theme_pack", "")).to_upper(),
	]


func _render_recap(lines: Array) -> void:
	for child: Node in _preview_prose.get_children():
		child.queue_free()
	var t := _pack_of(_saves[_selected]) if _selected >= 0 else _theme
	if lines.is_empty():
		_preview_prose.add_child(Fonts.label("No recap recorded yet.", Fonts.prose(), 13, t.muted))
		return
	for line: String in lines:
		var muted := line.to_lower().begins_with("unresolved")
		var label := Fonts.label(line, Fonts.prose(), 14, t.muted if muted else t.ink)
		label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		label.custom_minimum_size = Vector2(520, 0)
		_preview_prose.add_child(label)


# --- selection + preview session (spec §7.3) --------------------------------


func docket_count() -> int:
	return _list_box.get_child_count()


func _on_docket_pressed(index: int) -> void:
	await select_docket(index)


func select_docket(index: int) -> void:
	if index == _selected:
		return
	_selected = index
	_render_preview()
	if index < 0 or index >= _saves.size():
		return
	await _cleanup_preview()
	var base := str(_saves[index]["base_name"])
	var res: EngineResult = await _client().resume_session(base)
	if not res.ok:
		Services.overlay.toast_error(res)
		return
	_preview_session = res.data["session"]
	_preview_id = str(_preview_session.get("id", ""))
	var recap_res: EngineResult = await _client().recap(_preview_id)
	if recap_res.ok:
		_render_recap(recap_res.data.get("lines", []))
	else:
		Services.overlay.toast_error(recap_res)


func _cleanup_preview() -> void:
	if _preview_id == "":
		return
	var id := _preview_id
	_preview_id = ""
	_preview_session = {}
	await _client().delete_session(id)


# --- actions ----------------------------------------------------------------


func press_action(what: String) -> void:
	if _selected < 0 or _selected >= _saves.size():
		return
	var entry: Dictionary = _saves[_selected]
	match what:
		"resume":
			if _preview_session.is_empty():
				return
			SessionStore.set_current(_preview_session)
			_preview_id = ""  # promoted — screen_exit must not delete it
			var pack_id := str(entry.get("theme_pack", "neutral"))
			ClientSettings.set_value("ui/last_played_pack", pack_id)
			PackThemes.apply(pack_id)
			navigate.emit("stub", {"session": _preview_session})
		"duplicate":
			var entered: String = await Services.overlay.prompt("DUPLICATE AS…", "new chronicle name")
			if entered == "":
				return
			var res: EngineResult = await _client().duplicate_save(str(entry["base_name"]), entered)
			if not res.ok:
				Services.overlay.toast_error(res)
				return
			await _load_data()
		"export":
			DisplayServer.file_dialog_show(
				"EXPORT CHRONICLE — choose a folder",
				"",
				PackedStringArray(),
				DisplayServer.FILE_DIALOG_MODE_OPEN_DIR,
				Callable(self, "_on_export_dir")
			)
		"delete":
			var confirmed: bool = await Services.overlay.confirm(
				"DELETE %s?" % str(entry.get("character_name", entry["base_name"])).to_upper(),
				"The chronicle and its autosave are removed from disk. This is not recoverable.",
				"DELETE",
				"KEEP"
			)
			if not confirmed:
				return
			var res: EngineResult = await _client().delete_save(str(entry["base_name"]))
			if not res.ok:
				Services.overlay.toast_error(res)
				return
			Services.overlay.toast("%d FILES REMOVED" % Array(res.data.get("deleted", [])).size(), "ok")
			await _cleanup_preview()
			_selected = -1
			await _load_data()


func _on_export_dir(status: bool, paths: PackedStringArray, _selected_filter: int) -> void:
	if not status or paths.is_empty() or _selected < 0:
		return
	var entry: Dictionary = _saves[_selected]
	var res: EngineResult = await _client().export_save(str(entry["base_name"]))
	if not res.ok:
		Services.overlay.toast_error(res)
		return
	var path: String = paths[0].path_join(str(entry["base_name"]) + ".json")
	var f := FileAccess.open(path, FileAccess.WRITE)
	if f == null:
		Services.overlay.toast("could not write " + path, "bad")
		return
	f.store_string(JSON.stringify(res.data))
	f.close()
	Services.overlay.toast("EXPORTED → " + path, "ok")


func press_import() -> void:
	DisplayServer.file_dialog_show(
		"IMPORT A SAVE FILE",
		"",
		PackedStringArray(["*.json ; Andromeda save"]),
		DisplayServer.FILE_DIALOG_MODE_OPEN_FILE,
		Callable(self, "_on_import_file")
	)


func _on_import_file(status: bool, paths: PackedStringArray, _selected_filter: int) -> void:
	if not status or paths.is_empty():
		return
	var path: String = paths[0]
	var text := FileAccess.get_file_as_string(path)
	var parsed: Variant = JSON.parse_string(text)
	if not (parsed is Dictionary):
		Services.overlay.toast("that file isn't a chronicle", "bad")
		return
	var stem := path.get_file().get_basename()
	var entered: String = await Services.overlay.prompt("IMPORT AS…", stem)
	if entered == "":
		return
	var res: EngineResult = await _client().import_save(entered, parsed)
	if not res.ok:
		Services.overlay.toast_error(res)
		return
	Services.overlay.toast("IMPORTED AS " + entered.to_upper(), "ok")
	await _load_data()


# --- inner components ---------------------------------------------------------


class _SelectionOutline:
	extends Control
	## 2px accent outline drawn when the docket is selected (mock 02).

	var on := false
	var color := Color.WHITE

	func _ready() -> void:
		mouse_filter = Control.MOUSE_FILTER_IGNORE

	func _draw() -> void:
		if on:
			draw_rect(Rect2(Vector2.ZERO, size), color, false, 2.0)


class _Spine:
	extends Control
	## Vertical spine text (mock 02 writing-mode: vertical-rl) + dashed rule.

	var text_content := ""
	var text_color := Color.WHITE
	var line_color := Color.WHITE

	func _ready() -> void:
		mouse_filter = Control.MOUSE_FILTER_IGNORE

	func _draw() -> void:
		# dashed 2px rule on the left edge (2px on / 2px off)
		var y := 0.0
		while y < size.y:
			draw_rect(Rect2(Vector2(0, y), Vector2(2, minf(2.0, size.y - y))), line_color)
			y += 4.0
		# vertical text, top-to-bottom
		draw_set_transform(Vector2(size.x / 2 + 5, 6), PI / 2)
		draw_string(Fonts.micro(), Vector2.ZERO, text_content, HORIZONTAL_ALIGNMENT_LEFT, -1, 12, text_color)
		draw_set_transform(Vector2.ZERO, 0.0)
```

**Selection outline wiring (pin):** `select_docket` sets `_SelectionOutline.on`/`color` for the newly selected docket and clears the previous one. The outline node is the first child of each docket's wrapper; its `color` is the docket pack's accent. Add to `select_docket`, directly after `_selected = index`:

```gdscript
	for i: int in _list_box.get_child_count() - 1:  # last child is the import slot
		var outline := _list_box.get_child(i).get_child(0) as _SelectionOutline
		outline.on = i == index
		if i == index:
			outline.color = _pack_of(_saves[i]).accent
		outline.queue_redraw()
```

- [ ] **Step 4: run tests, verify pass**

Run: `tools/run_client_tests.sh`
Expected: PASS (6 new tests).

- [ ] **Step 5: lint, format, full gate, commit**

Run: `uv run gdformat client/screens client/app client/tests && tools/run_client_lint.sh && tools/run_client_tests.sh` plus ruff + pytest.

```bash
git add client/screens/chronicles_screen.gd client/app client/tests
git commit -m "feat(client): M2.9 Chronicles — dockets, recap preview, save actions, import"
```

---

## Task 10 (M2.10): New Journey screen + boundary stubs

**Files:**
- Create: `client/screens/new_journey_screen.gd`, `client/screens/stub_screen.gd`
- Modify: `client/app/main.gd` (register the real NewJourneyScreen + StubScreen)
- Test: `client/tests/screens/test_new_journey_screen.gd`, `client/tests/screens/test_stub_screen.gd`

**Interfaces:**
- Consumes: Tasks 2–9.
- Produces: `NewJourneyScreen` (BaseScreen; params none); `StubScreen` (BaseScreen; params `{"session": SessionEnvelope}` — §A3).
- Test hooks (NewJourney): `_name_edit`, `_seed_label`, `_pack_cards: Dictionary`, `_profile_cards: Dictionary`, `_death_cards: Dictionary`, `_narrator_line`, `_cap_line`; methods `press_begin()`, `press_reroll()`, `select_card(kind: String, id: String)` (`kind ∈ "pack"|"profile"|"death"`).
- Test hooks (Stub): `title_text() -> String`.

**Supporting edit:** `client/app/main.gd` — in `_register_screens()`, replace the two remaining placeholder lines with:

```gdscript
	_stack.register("new_journey", NewJourneyScreen.new())
	_stack.register("stub", StubScreen.new())
```

**Pinned copy (verbatim from mock 03):**

- Profile cards: `narrative` — desc `"Three tiers: strong hit / weak hit with complication / miss with consequence. Story-forward; the oracle tables talk back. Lifepath always uses classic CE mechanics either way."`, stats `"10+ STRONG · 7–9 WEAK · ≤6 MISS"`. `classic` — desc `"Binary 2D6+DM vs 8 with Effect margins. SRD-faithful, clean, unforgiving in the way dice are."`, stats `"2D6+DM ≥ 8"`. (Mock italics on "with complication"/"with consequence" are M5 polish — M2 renders plain text.)
- Death cards: `ironman` — `"Death is permanent — even in chargen. A life, told once."` / `"PERMADEATH · MEMORIAL"`. `checkpoint` — `"Death rewinds to the start of the scene. The abandoned branch stays in the audit log."` / `"SCENE REWIND"`. `narrative` — `"Defeat leaves lasting scars — injuries, debt, capture — and play continues."` / `"SCARS, NOT ENDINGS"`.
- Immutability notice (verbatim): `"Permanent once launched: pack, profile, and death mode are baked into the save so replays stay honest. Name and seed are just the chronicle's label and starting dice."` — render with `RichTextLabel` (BBCode `[b]` on the lead sentence, `normal_font`/`bold_font` overrides from `Fonts.prose()/prose_bold()`).
- Selected cards show the mock's `▸ LOCKED IN` micro stamp top-right.

**Pinned derivations & deviations:**
- Seed is client-generated (spec §7.4): `randi_range(100000, 999999)`; REROLL re-rolls. `CreateSessionRequest.seed` is `int | None` (models.py:17) — the client always sends the int.
- The mock's `SPEND CAP: 10 CALLS PER BEAT` has no server source (no calls-per-beat concept exists). The honest derivation: a beat costs at most `1 + max_retries` LLM calls (one attempt plus retries, §A7 settings). The line renders `SPEND CAP: %d CALLS PER BEAT` with that number (4 with the default 3). **This is a deliberate mock deviation — document it in the commit message.**
- Narrator line: configured → `NARRATOR: {MODEL} ● · TEMPLATES IF IT EVER FAILS`; unconfigured → `NARRATOR: UNCONFIGURED — TEMPLATES ACTIVE`.
- Card sets are gated by the server: profile cards render only for ids in `rulesets[0].resolution_profiles`, death cards only for ids in `death_modes` (§A6); pack cards render per `/v1/config/packs` entry. Unknown ids render no card.
- BEGIN validation: non-empty name; no case-insensitive collision with any `base_name` in `/v1/saves` (violation → bad toast `A CHRONICLE NAMED %s EXISTS — pick another name`). Server errors flow to `toast_error`.

- [ ] **Step 1: failing tests** — create `client/tests/screens/test_new_journey_screen.gd` exactly:

```gdscript
extends GdUnitTestSuite
## New Journey against FakeEngineClient (mock 03: the launch manifest).

var _fake: FakeEngineClient
var _screen: NewJourneyScreen


func before_test() -> void:
	_fake = auto_free(FakeEngineClient.new())
	add_child(_fake)
	_fake.responses["list_packs"] = FakeEngineClient.ok(
		{
			"packs": [
				{
					"id": "scifi", "name": "Frontier Sci-Fi",
					"description": "The Cepheus frontier.", "career_count": 25,
					"skill_count": 57, "has_cascades": true, "has_draft": false,
					"theme": {"motif": "✦", "accent": "amber", "ambience": ["meteors", "birds"]},
					"has_intro": true,
				},
				{
					"id": "fantasy", "name": "Sword & Sorcery",
					"description": "An original fantasy pack.", "career_count": 10,
					"skill_count": 40, "has_cascades": false, "has_draft": false,
					"theme": {"motif": "❧", "accent": "gold", "ambience": ["fireflies", "leaves"]},
					"has_intro": true,
				},
			]
		}
	)
	_fake.responses["list_rulesets"] = FakeEngineClient.ok(
		{
			"rulesets": [
				{
					"id": "cepheus", "name": "Cepheus Engine",
					"characteristics": [], "difficulty_ladder": {}, "resolution_target": 8,
					"resolution_profiles": ["classic", "narrative"],
					"death_modes": ["checkpoint", "ironman", "narrative"],
				}
			]
		}
	)
	_fake.responses["llm_status"] = FakeEngineClient.ok(
		{"configured": true, "model": "claude-sonnet-5", "key_backend": "keyring", "degraded_line": null}
	)
	_fake.responses["get_settings"] = FakeEngineClient.ok(
		{"provider": "anthropic", "model": "claude-sonnet-5", "base_url": "", "max_retries": 3, "is_configured": true, "key_backend": "keyring", "key_tail": "wxyz"}
	)
	_fake.responses["list_saves"] = FakeEngineClient.ok({"saves": []})
	Services.overlay = auto_free(OverlayLayer.new())
	add_child(Services.overlay)
	_screen = auto_free(NewJourneyScreen.new())
	_screen.client_override = _fake
	add_child(_screen)
	await _screen.screen_enter({})


func after_test() -> void:
	Services.overlay = null


func test_manifest_sections_render_with_defaults() -> void:
	assert_that(_screen._pack_cards.size()).is_equal(2)
	assert_that(_screen._profile_cards.size()).is_equal(2)
	assert_that(_screen._death_cards.size()).is_equal(3)
	assert_str(_screen.selected_pack).is_equal("scifi")
	assert_str(_screen.selected_profile).is_equal("narrative")
	assert_str(_screen.selected_death).is_equal("narrative")
	assert_str(_screen._narrator_line.text).is_equal(
		"NARRATOR: CLAUDE-SONNET-5 ● · TEMPLATES IF IT EVER FAILS"
	)
	assert_str(_screen._cap_line.text).is_equal("SPEND CAP: 4 CALLS PER BEAT")


func test_seed_is_six_digits_and_rerollable() -> void:
	var first := _screen._seed_label.text
	assert_bool(first.is_valid_int()).is_true()
	assert_bool(int(first) >= 100000 and int(first) <= 999999).is_true()
	var seen := {first: true}
	for i: int in 3:
		_screen.press_reroll()
		seen[_screen._seed_label.text] = true
	assert_bool(seen.size() > 1).is_true()


func test_begin_requires_a_name() -> void:
	_screen._name_edit.text = ""
	_screen.press_begin()
	await get_tree().process_frame
	assert_bool(_fake.calls.filter(func(c: Array) -> bool: return c[0] == "create_session").is_empty()).is_true()


func test_begin_rejects_name_collision() -> void:
	_fake.responses["list_saves"] = FakeEngineClient.ok(
		{"saves": [{"name": "mara", "base_name": "mara", "autosave": false, "theme_pack": "scifi", "character_name": "Mara", "terms": 1, "career": "Scout", "alive": true, "mtime": 1.0}]}
	)
	_screen._name_edit.text = "MARA"
	_screen.press_begin()
	await get_tree().process_frame
	await get_tree().process_frame
	assert_bool(_fake.calls.filter(func(c: Array) -> bool: return c[0] == "create_session").is_empty()).is_true()


func test_begin_creates_session_and_navigates() -> void:
	_fake.responses["create_session"] = FakeEngineClient.ok(
		{"session": {"id": "new1", "name": "The Ruuth Run", "kind": "chargen", "phase": "homeworld", "view": {}, "contract_version": 1}}
	)
	_screen._name_edit.text = "The Ruuth Run"
	var nav: Array = []
	_screen.navigate.connect(func(target: String, params: Dictionary) -> void: nav.append([target, params]))
	_screen.press_begin()
	await get_tree().process_frame
	await get_tree().process_frame
	var creates := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "create_session")
	assert_that(creates.size()).is_equal(1)
	var payload: Dictionary = creates[0][1]
	assert_str(str(payload["kind"])).is_equal("chargen")
	assert_str(str(payload["name"])).is_equal("The Ruuth Run")
	assert_str(str(payload["pack_id"])).is_equal("scifi")
	assert_str(str(payload["profile"])).is_equal("narrative")
	assert_str(str(payload["death_mode"])).is_equal("narrative")
	assert_bool(payload["seed"] is int).is_true()
	assert_str(str(nav[0][0])).is_equal("stub")
	SessionStore.clear()
```

Create `client/tests/screens/test_stub_screen.gd` exactly:

```gdscript
extends GdUnitTestSuite
## Boundary stubs (spec M2-D8): honest gates for M3/M4 screens.

func test_chargen_session_gets_the_ceremony_stub() -> void:
	var stub: StubScreen = auto_free(StubScreen.new())
	add_child(stub)
	stub.screen_enter(
		{"session": {"id": "s1", "name": "x", "kind": "chargen", "phase": "homeworld", "view": {"prompt": "Where?"}, "contract_version": 1}}
	)
	assert_str(stub.title_text()).is_equal("THE CEREMONY arrives in M3")
	assert_str(stub.esc_target()).is_equal("title")


func test_adventure_session_gets_the_shell_stub() -> void:
	var stub: StubScreen = auto_free(StubScreen.new())
	add_child(stub)
	stub.screen_enter(
		{"session": {"id": "s2", "name": "x", "kind": "adventure", "phase": "scene", "view": {"phase": "scene", "game_over": false}, "contract_version": 1}}
	)
	assert_str(stub.title_text()).is_equal("THE ADVENTURE SHELL arrives in M4")


func test_game_over_view_gets_the_memorial_stub() -> void:
	var stub: StubScreen = auto_free(StubScreen.new())
	add_child(stub)
	stub.screen_enter(
		{"session": {"id": "s3", "name": "x", "kind": "adventure", "phase": "game_over", "view": {"phase": "game_over", "game_over": true}, "contract_version": 1}}
	)
	assert_str(stub.title_text()).is_equal("THE MEMORIAL arrives in M4")
```

- [ ] **Step 2: run tests, verify failure**

Run: `tools/run_client_tests.sh`
Expected: FAIL — `NewJourneyScreen`/`StubScreen` unknown.

- [ ] **Step 3: `client/screens/stub_screen.gd`** — create exactly:

```gdscript
class_name StubScreen
extends BaseScreen
## The honest boundary gate (spec M2-D8): session created/resumed, the real
## screen arrives in a later milestone. Renders the session's current view as
## cockpit data — real wiring, inspectable, replaced wholesale by M3/M4.

var _session: Dictionary = {}
var _title := ""
var _title_label: Label
var _view_dump: Label


func esc_target() -> String:
	return "title"


func screen_enter(params: Dictionary) -> void:
	_session = params.get("session", {})
	var kind := str(_session.get("kind", ""))
	var view: Dictionary = _session.get("view", {})
	if kind == "chargen":
		_title = "THE CEREMONY arrives in M3"
	elif bool(view.get("game_over", false)):
		_title = "THE MEMORIAL arrives in M4"
	else:
		_title = "THE ADVENTURE SHELL arrives in M4"
	_rebuild()


func title_text() -> String:
	return _title


func _rebuild() -> void:
	for child: Node in get_children():
		child.queue_free()
	var t := PackThemes.current
	var bg := ColorRect.new()
	bg.color = t.bg
	bg.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(bg)
	var center := CenterContainer.new()
	center.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(center)
	var frame := Kit.px_frame(t)
	frame.custom_minimum_size = Vector2(640, 0)
	center.add_child(frame)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 10)
	frame.add_content(box)
	frame.set_content_margins(18, 16, 18, 16)
	_title_label = Fonts.label(_title, Fonts.inter(), 16, t.accent)
	box.add_child(_title_label)
	box.add_child(
		Fonts.label(
			(
				"SESSION %s · %s · phase %s · contract v%d"
				% [
					str(_session.get("id", "")),
					str(_session.get("kind", "")).to_upper(),
					str(_session.get("phase", "")),
					int(_session.get("contract_version", -1)),
				]
			),
			Fonts.data(),
			10,
			t.muted
		)
	)
	var prompt := str(_session.get("view", {}).get("prompt", ""))
	if prompt != "":
		box.add_child(Fonts.label(prompt, Fonts.prose(), 13, t.ink))
	var scroll := ScrollContainer.new()
	scroll.custom_minimum_size = Vector2(600, 260)
	box.add_child(scroll)
	_view_dump = Label.new()
	_view_dump.text = JSON.stringify(_session.get("view", {}), "  ")
	_view_dump.add_theme_font_override("font", Fonts.data())
	_view_dump.add_theme_font_size_override("font_size", 10)
	_view_dump.add_theme_color_override("font_color", t.muted)
	scroll.add_child(_view_dump)
	box.add_child(Fonts.label("ESC — BACK TO TITLE", Fonts.micro_tracked(), 12, t.muted))
```

- [ ] **Step 4: `client/screens/new_journey_screen.gd`** — create exactly. Layout per mock 03: header, four numbered sections, immutability notice, BEGIN row, strip (`refresh` + right `MANIFEST 04/04`).

```gdscript
class_name NewJourneyScreen
extends BaseScreen
## 03-new-journey.html: the launch manifest. Pack/profile/death-mode cards
## (selected = accent border + ▸ LOCKED IN), rerollable seed, immutability
## notice, narrator status. BEGIN → POST /v1/sessions {kind:"chargen"} → the
## Ceremony stub (M3).

## Test hook: when set, used instead of Services.client.
var client_override: Node

var selected_pack := "scifi"
var selected_profile := "narrative"
var selected_death := "narrative"

var _theme: PackTheme
var _packs: Array = []
var _ruleset: Dictionary = {}
var _status: Dictionary = {}
var _max_retries := 3
var _name_text := ""
var _seed_value := 0

var _name_edit: LineEdit
var _seed_label: Label
var _cards_box: VBoxContainer
var _pack_cards := {}
var _profile_cards := {}
var _death_cards := {}
var _narrator_line: Label
var _cap_line: Label
var _strip: StatusStrip

const _PROFILE_COPY := {
	"narrative": [
		"Three tiers: strong hit / weak hit with complication / miss with consequence. Story-forward; the oracle tables talk back. Lifepath always uses classic CE mechanics either way.",
		"10+ STRONG · 7–9 WEAK · ≤6 MISS",
	],
	"classic": [
		"Binary 2D6+DM vs 8 with Effect margins. SRD-faithful, clean, unforgiving in the way dice are.",
		"2D6+DM ≥ 8",
	],
}
const _DEATH_COPY := {
	"ironman": [
		"Death is permanent — even in chargen. A life, told once.",
		"PERMADEATH · MEMORIAL",
	],
	"checkpoint": [
		"Death rewinds to the start of the scene. The abandoned branch stays in the audit log.",
		"SCENE REWIND",
	],
	"narrative": [
		"Defeat leaves lasting scars — injuries, debt, capture — and play continues.",
		"SCARS, NOT ENDINGS",
	],
}
const _PROFILE_TITLES := {"narrative": "Narrative", "classic": "Classic"}
const _DEATH_TITLES := {"ironman": "Ironman", "checkpoint": "Checkpoint", "narrative": "Narrative"}


func _ready() -> void:
	_theme = PackThemes.current
	PackThemes.pack_changed.connect(_on_pack_changed)
	_rebuild()


func esc_target() -> String:
	return "title"


func screen_enter(_params: Dictionary) -> void:
	await _load_data()


func _client() -> Node:
	return client_override if client_override != null else Services.client


func _on_pack_changed(t: PackTheme) -> void:
	_theme = t
	if is_inside_tree():
		_rebuild()
		_render_cards()


func _load_data() -> void:
	var packs_res: EngineResult = await _client().list_packs()
	if packs_res.ok:
		_packs = packs_res.data.get("packs", [])
	else:
		Services.overlay.toast_error(packs_res)
	var rules_res: EngineResult = await _client().list_rulesets()
	if rules_res.ok and not Array(rules_res.data.get("rulesets", [])).is_empty():
		_ruleset = rules_res.data["rulesets"][0]
	var status_res: EngineResult = await _client().llm_status()
	if status_res.ok:
		_status = status_res.data
	var settings_res: EngineResult = await _client().get_settings()
	if settings_res.ok:
		_max_retries = int(settings_res.data.get("max_retries", 3))
	_render_cards()


# --- view -------------------------------------------------------------------


func _rebuild() -> void:
	for child: Node in get_children():
		child.queue_free()
	_build()


func _build() -> void:
	var t := _theme
	var bg := ColorRect.new()
	bg.color = t.bg
	bg.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(bg)

	var root := VBoxContainer.new()
	root.set_anchors_preset(Control.PRESET_FULL_RECT)
	root.add_theme_constant_override("separation", 0)
	add_child(root)
	root.add_child(Kit.screen_header("NEW JOURNEY — LAUNCH MANIFEST", t, "ESC — BACK"))

	var pad := MarginContainer.new()
	pad.size_flags_vertical = Control.SIZE_EXPAND_FILL
	pad.add_theme_constant_override("margin_left", 18)
	pad.add_theme_constant_override("margin_top", 16)
	pad.add_theme_constant_override("margin_right", 18)
	pad.add_theme_constant_override("margin_bottom", 18)
	root.add_child(pad)
	var scroll := ScrollContainer.new()
	pad.add_child(scroll)
	_cards_box = VBoxContainer.new()
	_cards_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_cards_box.add_theme_constant_override("separation", 16)
	scroll.add_child(_cards_box)

	_strip = StatusStrip.new()
	_strip.theme = t
	root.add_child(_strip)


func _section_label(text: String) -> Label:
	return Fonts.label("%s %s" % [_theme.motif, text], Fonts.data(), 10, _theme.muted)


func _render_cards() -> void:
	for child: Node in _cards_box.get_children():
		child.queue_free()
	_pack_cards = {}
	_profile_cards = {}
	_death_cards = {}
	var t := _theme

	# 01 · CHRONICLE
	_cards_box.add_child(_section_label("01 · CHRONICLE"))
	var id_row := HBoxContainer.new()
	id_row.add_theme_constant_override("separation", 12)
	_cards_box.add_child(id_row)
	var name_card := Kit.card(t)
	name_card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	id_row.add_child(name_card)
	var name_box := VBoxContainer.new()
	name_card.add_child(name_box)
	name_box.add_child(Fonts.label("SAVE NAME", Fonts.micro_tracked(), 11, t.muted))
	_name_edit = LineEdit.new()
	_name_edit.placeholder_text = "name the chronicle"
	_name_edit.text = _name_text
	_name_edit.text_changed.connect(func(new_text: String) -> void: _name_text = new_text)
	_name_edit.add_theme_font_override("font", Fonts.inter())
	_name_edit.add_theme_font_size_override("font_size", 17)
	_name_edit.add_theme_color_override("font_color", t.ink)
	_name_edit.add_theme_color_override("caret_color", t.accent)
	_name_edit.add_theme_stylebox_override("normal", StyleBoxEmpty.new())
	_name_edit.add_theme_stylebox_override("focus", StyleBoxEmpty.new())
	_name_edit.flat = true
	name_box.add_child(_name_edit)
	var seed_card := Kit.card(t)
	seed_card.custom_minimum_size = Vector2(250, 0)
	id_row.add_child(seed_card)
	var seed_row := HBoxContainer.new()
	seed_card.add_child(seed_row)
	var seed_box := VBoxContainer.new()
	seed_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	seed_row.add_child(seed_box)
	seed_box.add_child(Fonts.label("SEED", Fonts.micro_tracked(), 11, t.muted))
	if _seed_value == 0:
		_seed_value = randi_range(100000, 999999)
	_seed_label = Fonts.label(str(_seed_value), Fonts.data(), 15, t.ink)
	seed_box.add_child(_seed_label)
	var reroll := Kit.btn("⟳ REROLL", t)
	reroll.pressed.connect(press_reroll)
	seed_row.add_child(reroll)

	# 02 · THEME PACK
	_cards_box.add_child(_section_label("02 · THEME PACK — THE WORLD"))
	var pack_grid := HBoxContainer.new()
	pack_grid.add_theme_constant_override("separation", 12)
	_cards_box.add_child(pack_grid)
	for pack: Dictionary in _packs:
		var card := _choice_card(
			str(pack["id"]),
			"%s %s" % [str(pack.get("theme", {}).get("motif", "◆")), str(pack["name"])],
			str(pack.get("description", "")),
			_stats_line(pack),
			PackThemes.get_theme(str(pack["id"])),
			selected_pack == str(pack["id"])
		)
		card.get_meta("button").pressed.connect(select_card.bind("pack", str(pack["id"])))
		_pack_cards[str(pack["id"])] = card
		pack_grid.add_child(card)

	# 03 · RESOLUTION PROFILE
	_cards_box.add_child(_section_label("03 · RESOLUTION PROFILE — HOW CHECKS READ"))
	var profile_grid := HBoxContainer.new()
	profile_grid.add_theme_constant_override("separation", 12)
	_cards_box.add_child(profile_grid)
	for id: String in ["narrative", "classic"]:
		if not Array(_ruleset.get("resolution_profiles", [])).has(id):
			continue
		var card := _choice_card(
			id,
			"%s %s" % [t.motif, _PROFILE_TITLES[id]],
			_PROFILE_COPY[id][0],
			_PROFILE_COPY[id][1],
			t,
			selected_profile == id
		)
		card.get_meta("button").pressed.connect(select_card.bind("profile", id))
		_profile_cards[id] = card
		profile_grid.add_child(card)

	# 04 · DEATH MODE
	_cards_box.add_child(_section_label("04 · DEATH MODE — WHAT DEFEAT MEANS"))
	var death_grid := HBoxContainer.new()
	death_grid.add_theme_constant_override("separation", 12)
	_cards_box.add_child(death_grid)
	for id: String in ["ironman", "checkpoint", "narrative"]:
		if not Array(_ruleset.get("death_modes", [])).has(id):
			continue
		var card := _choice_card(
			id,
			"%s %s" % [t.motif, _DEATH_TITLES[id]],
			_DEATH_COPY[id][0],
			_DEATH_COPY[id][1],
			t,
			selected_death == id
		)
		card.get_meta("button").pressed.connect(select_card.bind("death", id))
		_death_cards[id] = card
		death_grid.add_child(card)

	# Immutability notice (verbatim mock copy)
	var notice_wrap := PanelContainer.new()
	var notice_sb := StyleBoxFlat.new()
	notice_sb.bg_color = Color(0, 0, 0, 0)
	notice_sb.border_width_left = 3
	notice_sb.border_color = t.accent
	notice_sb.content_margin_left = 12
	notice_sb.content_margin_top = 6
	notice_sb.content_margin_bottom = 6
	notice_wrap.add_theme_stylebox_override("panel", notice_sb)
	_cards_box.add_child(notice_wrap)
	var notice := RichTextLabel.new()
	notice.bbcode_enabled = true
	notice.fit_content = true
	notice.scroll_active = false
	notice.add_theme_font_override("normal_font", Fonts.prose())
	notice.add_theme_font_override("bold_font", Fonts.prose_bold())
	notice.add_theme_font_size_override("normal_font_size", 12)
	notice.add_theme_font_size_override("bold_font_size", 12)
	notice.add_theme_color_override("default_color", t.muted)
	notice.text = "[b]Permanent once launched:[/b] pack, profile, and death mode are baked into the save so replays stay honest. Name and seed are just the chronicle's label and starting dice."
	notice_wrap.add_child(notice)

	# BEGIN row
	var begin_row := HBoxContainer.new()
	begin_row.add_theme_constant_override("separation", 16)
	_cards_box.add_child(begin_row)
	var begin := Kit.btn("BEGIN — ROLL CHARACTERISTICS ▸", t)
	begin.add_theme_font_size_override("font_size", 14)
	begin.custom_minimum_size = Vector2(0, 42)
	begin.pressed.connect(press_begin)
	begin_row.add_child(begin)
	var narrator_box := VBoxContainer.new()
	begin_row.add_child(narrator_box)
	_narrator_line = Fonts.label("", Fonts.data(), 10, t.muted)
	narrator_box.add_child(_narrator_line)
	_cap_line = Fonts.label("", Fonts.data(), 10, t.muted)
	narrator_box.add_child(_cap_line)
	_update_narrator_lines()

	_strip.refresh(_status)
	_strip.set_right_plain("MANIFEST 04/04")


func _stats_line(pack: Dictionary) -> String:
	var line := "%d CAREERS · %d SKILLS" % [int(pack.get("career_count", 0)), int(pack.get("skill_count", 0))]
	if bool(pack.get("has_cascades", false)):
		line += " · CASCADES ✓"
	return line


## A manifest card (mock 03): title, prose desc, stats line; selected shows
## the accent border + ▸ LOCKED IN stamp. The clickable overlay is in
## meta "button".
func _choice_card(id: String, title_text: String, desc: String, stats: String, t: PackTheme, selected: bool) -> PanelContainer:
	var card := Kit.card(t)
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	card.set_meta("card_id", id)
	if selected:
		var sb: StyleBoxFlat = card.get_theme_stylebox("panel")
		var selected_sb := sb.duplicate()
		selected_sb.border_color = t.accent
		card.add_theme_stylebox_override("panel", selected_sb)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 5)
	card.add_child(box)
	var title_row := HBoxContainer.new()
	box.add_child(title_row)
	var title := Fonts.label(title_text, Fonts.inter(), 15, t.ink)
	title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	title_row.add_child(title)
	var stamp := Fonts.label("▸ LOCKED IN" if selected else "", Fonts.micro_tracked(), 10, t.accent)
	title_row.add_child(stamp)
	var body := Fonts.label(desc, Fonts.prose(), 12, t.muted)
	body.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	box.add_child(body)
	box.add_child(Fonts.label(stats, Fonts.data(), 9, t.muted))
	var click := Button.new()
	click.flat = true
	click.set_anchors_preset(Control.PRESET_FULL_RECT)
	click.add_theme_stylebox_override("focus", StyleBoxEmpty.new())
	card.add_child(click)
	card.set_meta("button", click)
	return card


func _update_narrator_lines() -> void:
	if bool(_status.get("configured", false)):
		_narrator_line.text = "NARRATOR: %s ● · TEMPLATES IF IT EVER FAILS" % str(_status.get("model", "")).to_upper()
	else:
		_narrator_line.text = "NARRATOR: UNCONFIGURED — TEMPLATES ACTIVE"
	_cap_line.text = "SPEND CAP: %d CALLS PER BEAT" % (1 + _max_retries)


func press_reroll() -> void:
	_seed_value = randi_range(100000, 999999)
	_seed_label.text = str(_seed_value)


func select_card(kind: String, id: String) -> void:
	match kind:
		"pack":
			selected_pack = id
		"profile":
			selected_profile = id
		"death":
			selected_death = id
	_render_cards()


func press_begin() -> void:
	var save_name := _name_edit.text.strip_edges()
	if save_name == "":
		Services.overlay.toast("NAME THE CHRONICLE FIRST", "bad")
		return
	var saves_res: EngineResult = await _client().list_saves()
	if saves_res.ok:
		for entry: Dictionary in saves_res.data.get("saves", []):
			if str(entry.get("base_name", "")).to_lower() == save_name.to_lower():
				Services.overlay.toast(
					"A CHRONICLE NAMED %s EXISTS — pick another name" % save_name.to_upper(), "bad"
				)
				return
	var res: EngineResult = await _client().create_session(
		{
			"kind": "chargen",
			"name": save_name,
			"seed": int(_seed_label.text),
			"pack_id": selected_pack,
			"profile": selected_profile,
			"death_mode": selected_death,
		}
	)
	if not res.ok:
		Services.overlay.toast_error(res)
		return
	var session: Dictionary = res.data["session"]
	if not _client().contract_matches(session):
		Services.overlay.toast(
			"contract drift: chronicle v%d, engine v%d — update the client"
			% [int(session.get("contract_version", -1)), _client().contract_chargen],
			"bad"
		)
		return
	SessionStore.set_current(session)
	ClientSettings.set_value("ui/last_played_pack", selected_pack)
	PackThemes.apply(selected_pack)
	navigate.emit("stub", {"session": session})
```

- [ ] **Step 5: run tests, verify pass**

Run: `tools/run_client_tests.sh`
Expected: PASS (8 new tests).

- [ ] **Step 6: lint, format, full gate, commit**

Run: `uv run gdformat client/screens client/app client/tests && tools/run_client_lint.sh && tools/run_client_tests.sh` plus ruff + pytest.

```bash
git add client/screens client/app/main.gd client/tests
git commit -m "feat(client): M2.10 New Journey manifest + M3/M4 boundary stubs

Spend-cap line derives 1 + max_retries (mock's illustrative \"10\" has no
server source) — deliberate deviation, see plan Task 10."
```

---

## Task 11 (M2.11): Golden-layout harness + M2 closeout

**Files:**
- Create: `client/tests/golden/golden_assert.gd`, `client/tests/golden/test_golden_screens.gd`
- Modify: `tools/run_client_tests.sh` (display mode), `.github/workflows/ci.yml` (golden runs under xvfb with a real renderer), `CLAUDE.md` (client commands section)
- Create (generated): `client/tests/golden/{title,settings,chronicles,new_journey}.png` — committed baselines

**Interfaces:**
- Consumes: Tasks 6–10 screens.
- Produces: `GoldenAssert` (statics): `supported() -> bool`, `update_mode() -> bool`, `capture(screen: Control, baseline_name: String) -> Dictionary` (`{"match": bool, "stats": String}`); constants `SIZE := Vector2i(1280, 720)`, `MAX_CHANNEL_DELTA := 16`, `MAX_BAD_PIXEL_RATIO := 0.005`, `MEAN_ABS_LIMIT := 1.0`.

**Display pinning (read carefully — the trap):** `tools/run_client_tests.sh` runs `--headless`, which uses the dummy renderer and cannot capture viewports; golden tests detect this (`DisplayServer.get_name() == "headless"`) and self-skip. To run them you need a real display AND the script must not pass `--headless`. Task 11 adds the `ANDROMEDA_DISPLAY=1` switch for that. Pre-push stays headless (goldens skipped); CI runs the display variant under `xvfb-run` (spec §9); locally, WSLg provides a display (`ANDROMEDA_DISPLAY=1 tools/run_client_tests.sh`).

**Determinism pinning:** goldens must be byte-stable across runs, so fixtures avoid every nondeterministic element:
- Title + Chronicles goldens use **empty save lists** — relative-time docket notes ("2H AGO") drift daily and would rot the baseline.
- New Journey's seed is random at render — the golden test sets `_screen._seed_value = 482991` and re-renders before capturing.
- Settings golden uses the canned fixture (no live TEST press — latency text would drift).

- [ ] **Step 1: `tools/run_client_tests.sh` display switch** — replace the run block:

```bash
set +e
"$GODOT_BIN" --headless --path client \
  -s res://addons/gdUnit4/bin/GdUnitCmdTool.gd \
  -a res://tests -c -rd /tmp/gdunit-reports
code=$?
set -e
```

with exactly:

```bash
HEADLESS_FLAG="--headless"
if [ "${ANDROMEDA_DISPLAY:-0}" = "1" ]; then
  HEADLESS_FLAG=""  # real renderer (xvfb-run or WSLg) — enables golden capture
fi

set +e
"$GODOT_BIN" $HEADLESS_FLAG --path client \
  -s res://addons/gdUnit4/bin/GdUnitCmdTool.gd \
  -a res://tests -c -rd /tmp/gdunit-reports
code=$?
set -e
```

- [ ] **Step 2: `.github/workflows/ci.yml`** — in the `client` job, replace:

```yaml
      - name: Client tests
        run: xvfb-run -a tools/run_client_tests.sh
```

with:

```yaml
      - name: Client tests (incl. golden screenshots)
        run: ANDROMEDA_DISPLAY=1 xvfb-run -a tools/run_client_tests.sh
```

- [ ] **Step 3: `client/tests/golden/golden_assert.gd`** — create exactly:

```gdscript
class_name GoldenAssert
extends RefCounted
## Golden-layout screenshots (spec M2-D9): capture a full-rect screen at the
## pinned 1280×720 and compare against the committed baseline. Baselines
## guard regression; the HTML mocks guard intent — no HTML↔Godot pixel
## matching (different text rasterizers).

const BASELINE_DIR := "res://tests/golden"
const SIZE := Vector2i(1280, 720)
const MAX_CHANNEL_DELTA := 16  # per-pixel channel tolerance
const MAX_BAD_PIXEL_RATIO := 0.005  # ≤0.5% of pixels may exceed the delta
const MEAN_ABS_LIMIT := 1.0  # mean absolute per-channel delta


static func supported() -> bool:
	return DisplayServer.get_name() != "headless"


static func update_mode() -> bool:
	return OS.get_environment("GOLDEN_UPDATE") == "1"


## The caller must: add the screen to the tree at full rect, let it finish
## its data load, and await two process frames before calling. In update
## mode the baseline is (re)written and the result is always a match.
static func capture(screen: Control, baseline_name: String) -> Dictionary:
	screen.set_anchors_preset(Control.PRESET_FULL_RECT)
	screen.size = Vector2(SIZE)
	var img := screen.get_viewport().get_texture().get_image()
	var res_path := BASELINE_DIR.path_join(baseline_name + ".png")
	if update_mode():
		var abs_path := ProjectSettings.globalize_path(res_path)
		var err := img.save_png(abs_path)
		return {"match": err == OK, "stats": "baseline written to " + abs_path}
	var baseline_tex: Texture2D = ResourceLoader.load(res_path)
	if baseline_tex == null:
		return {"match": false, "stats": "no baseline at " + res_path + " — run with GOLDEN_UPDATE=1"}
	return compare(img, baseline_tex.get_image())


static func compare(actual: Image, baseline: Image) -> Dictionary:
	if actual.get_size() != baseline.get_size():
		return {
			"match": false,
			"stats": "size mismatch: %s vs %s" % [actual.get_size(), baseline.get_size()],
		}
	var w := actual.get_width()
	var h := actual.get_height()
	var bad := 0
	var total := 0.0
	for y: int in h:
		for x: int in w:
			var a := actual.get_pixel(x, y)
			var b := baseline.get_pixel(x, y)
			var d := maxi(
				maxi(absi(int(a.r8) - int(b.r8)), absi(int(a.g8) - int(b.g8))),
				absi(int(a.b8) - int(b.b8))
			)
			total += d
			if d > MAX_CHANNEL_DELTA:
				bad += 1
	var ratio := float(bad) / float(w * h)
	var mean := total / float(w * h)
	return {
		"match": ratio <= MAX_BAD_PIXEL_RATIO and mean <= MEAN_ABS_LIMIT,
		"stats": "bad=%.4f%% mean=%.3f" % [ratio * 100.0, mean],
	}
```

- [ ] **Step 4: `client/tests/golden/test_golden_screens.gd`** — create exactly:

```gdscript
extends GdUnitTestSuite
## Golden layouts for the four M2 screens (spec M2-D9). Self-skips under the
## headless dummy renderer; runs under xvfb-run/CI and WSLg. Regenerate
## baselines deliberately: GOLDEN_UPDATE=1 ANDROMEDA_DISPLAY=1 xvfb-run -a tools/run_client_tests.sh

var _fake: FakeEngineClient


func before_test() -> void:
	if not GoldenAssert.supported():
		return
	_fake = auto_free(FakeEngineClient.new())
	add_child(_fake)
	_fake.responses["llm_status"] = FakeEngineClient.ok(
		{"configured": true, "model": "claude-sonnet-5", "key_backend": "keyring", "degraded_line": null}
	)
	_fake.responses["list_saves"] = FakeEngineClient.ok({"saves": []})  # determinism: no relative times
	_fake.responses["get_settings"] = FakeEngineClient.ok(
		{"provider": "anthropic", "model": "claude-sonnet-5", "base_url": "", "max_retries": 3, "is_configured": true, "key_backend": "keyring", "key_tail": "wxyz"}
	)
	_fake.responses["list_providers"] = FakeEngineClient.ok(
		{"providers": [{"id": "anthropic", "label": "Anthropic", "presets": ["claude-sonnet-5"], "default_base_url": "https://api.anthropic.com", "needs_base_url": false}]}
	)
	_fake.responses["list_packs"] = FakeEngineClient.ok(
		{"packs": [{"id": "scifi", "name": "Frontier Sci-Fi", "description": "The Cepheus frontier.", "career_count": 25, "skill_count": 57, "has_cascades": true, "has_draft": false, "theme": {"motif": "✦", "accent": "amber", "ambience": ["meteors", "birds"]}, "has_intro": true}]}
	)
	_fake.responses["list_rulesets"] = FakeEngineClient.ok(
		{"rulesets": [{"id": "cepheus", "name": "Cepheus Engine", "characteristics": [], "difficulty_ladder": {}, "resolution_target": 8, "resolution_profiles": ["classic", "narrative"], "death_modes": ["checkpoint", "ironman", "narrative"]}]}
	)


func _shoot(screen: BaseScreen, baseline_name: String, params: Dictionary) -> void:
	add_child(auto_free(screen))
	await screen.screen_enter(params)
	await get_tree().process_frame
	await get_tree().process_frame
	var result := GoldenAssert.capture(screen, baseline_name)
	assert_bool(result["match"]).is_true()  # on failure, read result["stats"] in the report


func test_title_golden() -> void:
	if not GoldenAssert.supported():
		return
	var screen := TitleScreen.new()
	screen.client_override = _fake
	await _shoot(screen, "title", {"boot_lines": ["REFEREE: LISTENING · 127.0.0.1:63216", "SAVES: OK · DICE STREAMS: PRIMED"]})


func test_settings_golden() -> void:
	if not GoldenAssert.supported():
		return
	var screen := SettingsScreen.new()
	screen.client_override = _fake
	await _shoot(screen, "settings", {})


func test_chronicles_golden() -> void:
	if not GoldenAssert.supported():
		return
	var screen := ChroniclesScreen.new()
	screen.client_override = _fake
	await _shoot(screen, "chronicles", {})


func test_new_journey_golden() -> void:
	if not GoldenAssert.supported():
		return
	var screen := NewJourneyScreen.new()
	screen.client_override = _fake
	add_child(auto_free(screen))
	await screen.screen_enter({})
	screen._seed_value = 482991  # determinism pin (see task header)
	screen._render_cards()
	await get_tree().process_frame
	await get_tree().process_frame
	var result := GoldenAssert.capture(screen, "new_journey")
	assert_bool(result["match"]).is_true()
```

- [ ] **Step 5: generate the baselines** (needs a display — WSLg, or `xvfb-run` if installed: `sudo apt-get install -y xvfb`)

Run: `GOLDEN_UPDATE=1 ANDROMEDA_DISPLAY=1 xvfb-run -a tools/run_client_tests.sh` (WSLg: drop the `xvfb-run -a`)
Expected: all tests pass; `ls client/tests/golden/*.png` shows 4 baselines. Then run once more WITHOUT `GOLDEN_UPDATE` to prove the baselines compare clean against themselves.

- [ ] **Step 6: CLAUDE.md client section** — append to `CLAUDE.md` under the `## Commands` section (after the quality-gate block):

````markdown
### Client (Godot)

```bash
tools/get_godot.sh               # one-time: pinned Godot 4.7.1 into tools/godot/
tools/run_client_lint.sh         # gdlint + gdformat over first-party GDScript
tools/run_client_tests.sh        # gdUnit4 headless (golden suites self-skip)
ANDROMEDA_DISPLAY=1 tools/run_client_tests.sh            # with a display: incl. golden
GOLDEN_UPDATE=1 ANDROMEDA_DISPLAY=1 tools/run_client_tests.sh  # regen golden baselines
```

The Godot project lives in `client/` (UI built in GDScript code; the only
scene is `client/app/main.tscn`). GDScript changes are gated by gdlint +
gdformat + gdUnit4 in the pre-push hook and CI; golden baselines compare
only under a real renderer (CI's xvfb job).
````

- [ ] **Step 7: manual verification checklist** (a human does these once, on a machine with a display; they cover the paths unit tests can't — native dialogs and the key-removal modal):
  - [ ] Boot the client (`tools/godot/Godot_v4.7.1-stable_linux.x86_64 --path client`): sidecar boots, Title appears with the real port in the boot readout; quit the window; `pgrep -f "src.server"` shows nothing.
  - [ ] Settings → REPLACE KEY, SAVE with the field empty → the confirm modal appears; KEEP cancels, REMOVE sends the deletion (key line flips to `not stored`).
  - [ ] Settings → EXPORT ALL → native folder picker → files land as `<base_name>.json`; toast reports the count.
  - [ ] Chronicles → IMPORT via the empty slot → native file picker → imported docket appears (use a file produced by EXPORT ALL).
  - [ ] Chronicles → DELETE → confirm modal → docket disappears.
  - [ ] New Journey → BEGIN with a name → lands on the Ceremony stub showing the session id; ESC returns to Title, now tinted to the chosen pack (last-played tint).
  - [ ] Kill the sidecar mid-session (`pkill -f src.server`) then press Continue → the transport-error toast reads "could not reach the referee — is the sidecar running?"

- [ ] **Step 8: full quality gate** — every line of the Global Constraints gate block, plus one display run:
  `tools/run_client_tests.sh` (headless) and `ANDROMEDA_DISPLAY=1 xvfb-run -a tools/run_client_tests.sh` (golden).
Expected: everything green.

- [ ] **Step 9: Commit**

```bash
git add client/tests/golden tools/run_client_tests.sh .github/workflows/ci.yml CLAUDE.md
git commit -m "test(client): M2.11 golden-layout harness + closeout"
```

---

## Traceability (spec → tasks)

| Spec section | Tasks |
|---|---|
| §3 repo layout & toolchain | 1 |
| §4 engine access layer | 3, 4, 5 (SessionStore in 4) |
| §5 theme system | 2 |
| §6 app shell | 6 |
| §7.1 Title | 7 |
| §7.2 Settings | 8 |
| §7.3 Chronicles | 9 |
| §7.4 New Journey | 10 |
| §7.5 boundary stubs (M2-D8) | 10 |
| §8 testing strategy | 3–5 (integration), 7–10 (fake), 11 (golden) |
| §9 quality gate | 1, 11 |
| §10 task map M2.1–M2.11 | 1–11 |
| §11 acceptance criteria | 1–11 (each criterion maps to its task's "Lands when") |

**Deferred enumerations, resolved (spec §12):** NDJSON block set = `narration | change | badge | done` (§A4, routes_sessions.py:387-394 — no `receipt`/`error` on the wire); `CreateSessionRequest.seed` = any JSON int, client sends `randi_range(100000, 999999)` (§A3, models.py:17); spend-cap line = `1 + max_retries` calls per beat (Task 10, deliberate deviation from the mock's illustrative "10").

**Documented mock deviations (all deliberate):** spend-cap derivation (Task 10); key-storage line shows the backend class not the OS product name (Task 8); docket/preview data lines use only the fields `SaveEntry` carries (Task 9); profile-card italics are M5 (Task 10); Title/Chronicles goldens use empty save lists for determinism (Task 11).

**Known limits (not bugs):** golden baselines are machine-sensitive to font rasterization — the tolerance constants in `GoldenAssert` absorb AA-level differences; if CI proves flakier than that, raise `MAX_BAD_PIXEL_RATIO` in one edit and note it in the commit. The `promote` wrapper and inspect endpoints ship without integration tests until M3/M4 (spec §4 note).
