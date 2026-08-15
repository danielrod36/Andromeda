# Andromeda M2 — Client Skeleton — Design Spec

> **Date:** 2026-08-13 · **Status:** approved design, pre-plan
> **Parent spec:** [`2026-08-13-game-client-design.md`](2026-08-13-game-client-design.md) (settled product design; this document is the M2 slice of its §11 milestone map)
> **Screen references:** `design/mockups/final/01-title.html` · `02-chronicles.html` · `03-new-journey.html` · `05-settings.html` · `12-components.html` · `tokens.css` — the mocks are the per-screen spec; this document never re-decides what they settle.
> **Scope rule:** M2 only. M3 (chargen vertical), M4 (adventure vertical), M5 (polish) each get their own spec/plan after the preceding milestone lands.

---

## 1. Goal

Deliver the Godot client skeleton end-to-end against the real sidecar: sidecar lifecycle, EngineClient + StreamPump, ScreenStack, theme from tokens — with **Title, Chronicles, New Journey, and Settings** fully wired per the mocks. Everything M3+ needs (streaming, theme, navigation, settings, session open/create) exists and is tested; nothing M3 owns (Ceremony, chargen beats) is faked.

Server reality this builds on (all shipped in Step 0, green on `main`): `src/server/` FastAPI app with the full v1 surface; `src/server/__main__.py` prints `LISTENING <port>` for the spawning client; 5-minute no-request self-exit watchdog; keyring-backed LLM settings; autosave after every beat.

## 2. Locked decisions

| # | Decision | Notes |
|---|----------|-------|
| M2-D1 | **Walking-skeleton build order** (Option A) | Scaffold+gate → engine layer → theme → shell → one screen at a time, each wired + golden-tested before the next. Rejected: UI-horizontal-first (fake shapes drift from the settled API; rework) and infrastructure-big-bang (no visible progress for half the milestone; StreamPump tested only synthetically). |
| M2-D2 | **Monorepo: `client/` Godot project** | Sibling to `src/`; sidecar spawns with repo root as cwd. One `Paths` helper resolves the repo root from the project dir. |
| M2-D3 | **Godot 4.7.1** (latest stable, 2026-07-14) | Satisfies parent D1 (Godot 4.7). `tools/get_godot.sh` downloads the Linux x86_64 build into `tools/godot/` (gitignored); CI downloads the same pinned build from GitHub releases. Subagents run `godot --headless`. |
| M2-D4 | **gdUnit4** for Godot-side tests | Committed under `client/addons/gdUnit4` (hermetic — no install step for CI or subagents). Rejected: GUT (dated API, weaker scene/screenshot tooling) and a custom harness (reinvents parameterized tests/reporting). |
| M2-D5 | **gdtoolkit (gdlint + gdformat) via uv** | Dev dependency in `pyproject.toml`; joins ruff/pytest in the quality gate. |
| M2-D6 | **Mocks are the screen spec** | Layout, copy, component choice, and wiring notes come from `design/mockups/final/*`. Discrepancies resolve toward the mock; genuine gaps get flagged, not improvised. |
| M2-D7 | **Static backdrop in M2; ambient motion in M5** | `SceneBackdrop` ships gradients/stars/planet/horizon/veil/kicker fully static. Twinkle, drift, beacon, meteor, birds (parent §6.5) are M5; reduced-motion then collapses what's already optional. |
| M2-D8 | **Honest boundary stubs for M3+ screens** | Session create/resume lands on a placeholder gate ("THE CEREMONY arrives in M3" etc.) rendering the session's current view as cockpit data. No fake UI pretending to be an unbuilt screen. |
| M2-D9 | **Golden screenshots guard regression, mocks guard intent** | No pixel-matching of Godot output against HTML mocks (different text rasterizers). Baselines stored per screen; comparison with tolerance; `GOLDEN_UPDATE=1` regenerates. Golden tests run under `xvfb-run` — `--headless` uses the dummy renderer and cannot capture viewports. |
| M2-D10 | **Five OFL font families committed** | Space Grotesk, Chakra Petch, Atkinson Hyperlegible, IBM Plex Mono, VT323 under `client/assets/fonts/` with OFL licenses; download script included; no runtime network dependency. |

## 3. Repo layout & toolchain

```
client/
  project.godot            # Godot 4.7.1 project
  addons/gdUnit4/          # committed test framework (M2-D4)
  assets/fonts/            # 5 OFL families + licenses (M2-D10)
  engine/                  # SidecarProcess, EngineClient, StreamPump, SessionStore
  theme/                   # PackTheme, Fonts, SteppedFrame, dither, SceneBackdrop
  app/                     # main.tscn, ScreenStack, OverlayLayer, StatusStrip, ClientSettings
  screens/                 # title, settings, chronicles, new_journey, stubs
  tests/                   # gdUnit4 suites; tests/golden/ baselines
tools/get_godot.sh         # pinned Godot download (gitignored output)
```

- `.gitignore` gains: `.godot/`, `tools/godot/`, golden-test temp output.
- `uv.lock` changes with the `gdtoolkit` dev dependency → re-run `uv lock` (a stale lockfile fails CI).
- Editor use is unrestricted (WSLg or Windows-side against the same files); the gate only requires the headless binary.

## 4. Engine access layer (`client/engine/`)

**`SidecarProcess`** — owns the Python sidecar lifecycle.
- Spawns `uv run python -m src.server --port 0` via `OS.create_process` with piped stdout, cwd = repo root.
- Reads stdout until the `LISTENING <port>` line (the only line it consumes), then health-checks `GET /health` before declaring ready.
- Kills the PID on quit (`NOTIFICATION_WM_CLOSE_REQUEST`). The server-side 5-minute idle watchdog (already shipped) backstops crashes — a dead client never leaves a permanent orphan.
- Boot timeout → honest error card with retry; never a hang.
- Dev override: `ANDROMEDA_SIDECAR_URL` attaches to an already-running server and skips spawning (screen iteration without respawn).

**`EngineClient`** — typed async wrappers (GDScript `await`) for every v1 route, grouped as the server groups them: sessions, saves, config, settings, inspect, meta.
- One-shot calls ride a small pool of `HTTPRequest` nodes (Godot's `HTTPRequest` is one-request-per-node).
- Every call returns a Result — `Ok(view_model)` or `Err(code, message, status)`; the `{"error":{"code","message"}}` envelope is parsed exactly once, here.
- Engine messages flow verbatim to toasts (parent §6.6 voice rule).
- Every view response carries `contract_version`; the client asserts the major version and shows a mismatch card rather than rendering garbage.

**`StreamPump`** — NDJSON reader on the low-level `HTTPClient` (chunked reads; `HTTPRequest` cannot stream).
- Polls in `_process` (no threads), emits `block_received(type, payload)` per line, supports close-on-skip.
- Block types are exactly what `src/server/routes_sessions.py` yields (`narration`, `change`, `badge`, `done`, `error`; the plan enumerates the exact set from the `_ndjson` call sites).
- No M2 screen streams; it is built and integration-tested now against a real `world_intro` beat in template mode so M3 starts with working plumbing.

**`SessionStore` autoload** — the in-memory `SessionRef` (id, kind, contract_version, last view model).
- Holds zero game truth (parent §3 hard rule): any reconnect re-fetches `GET /v1/sessions/{id}`.
- If the sidecar restarted and the id is gone, the reconnect card offers reconstruction from the autosave via `POST /v1/sessions {from_save}` (parent §9 degradation path; Chronicles needs this flow regardless).

## 5. Theme system (`client/theme/`)

`tokens.css` is the source of truth; translation is mechanical, never reinterpreted.

- **`PackTheme`** — Resource carrying the eight colors (`bg · panel · line · ink · muted · accent · ok · danger`) + motif glyph + ambience list. Four built-in sets (`scifi`, `fantasy`, `neutral`, `dead`) matching `tokens.css` exactly, constructed in code at boot by a `PackThemes` autoload (no `.tres` drift). **Color truth is the built-in set** (tokens.css hexes). The server's per-pack `theme` hints from `GET /v1/config/packs` are symbolic — motif glyph, named accent (e.g. `"amber"`), ambience list — and are applied over the built-in set (motif/ambience adopted; a named accent that doesn't match the built-in set is noted, not resolved to a guessed hex). Unknown pack → `neutral`. Applying a pack writes theme overrides on the root so every component repaints.
- **Type system** — the five families mapped to roles (`title`, `int`, `prose`, `data`, `micro`) as constants; one `Fonts.role(...)` helper so no screen ever names a font file.
- **`SteppedFrame`** — the CSS `clip-path` pixel-stepped corner has no stock StyleBox equivalent: a custom `Control` draws the stepped outer-accent polygon + inner panel in `_draw()`, with the exact 2px-step geometry from `tokens.css`, plus content margins. The 4px dither overlay is a Bayer-matrix `ImageTexture` generated in code at ~3% alpha, tiled — no asset file.
- **`SceneBackdrop`** — the `.sc-*` gradients (night/dawn/dusk/flare/gold/noon/port/dead) as `GradientTexture2D` with the exact stops from `tokens.css`; static star specks; the radial-gradient planet; the horizon silhouette converted point-for-point from the `clip-path` polygon to a `Polygon2D`; veil gradient; kicker label. Static in M2 (M2-D7).

## 6. App shell (`client/app/` + `main.tscn`)

- **`main.tscn`:** root → `SceneBackdrop` (bottom) → `ScreenStack` → `OverlayLayer` (toasts, top).
- **`ScreenStack`** — push/replace/pop of packed Control scenes with `screen_enter(params)` / `screen_exit()`; instant swaps in M2 (transitions are M5); ESC routes per mock ("ESC — BACK TO TITLE" etc.).
- **`OverlayLayer`** — the toast stack (component per `12-components.html`): engine errors verbatim, degradation badges, save-conflict prompts; plus the modal root — in M2 scope because Chronicles DELETE confirms modally (§7.3); later overlays reuse it.
- **`StatusStrip`** — cockpit strip: `ENGINE SYNC ✓ · v0.1.0` left, `NARRATOR: <model> ●` right, fed by `/health` + `/v1/llm/status`. Dot only (parent §6.6); operator detail lives in Settings.
- **`ClientSettings` autoload** — `user://settings.cfg`: text speed, ambient life, reduced motion, audio levels (persisted now; busses wired in M5), `last_played_pack` (Title tints to it on return).
- **Boot flow** — spawn → `LISTENING` → health → Title, with real boot lines feeding the Title readout. Any failure → error card + retry.

## 7. Screens

All four render pack tokens, route ESC per mock, and show engine errors as verbatim toasts.

### 7.1 Title — `01-title.html`
Left rail: ANDROMEDA wordmark, "WRITTEN IN THE STARS" kicker, accent rule + motif glyph, numbered menu dockets: **Continue** (annotated `<name> · <ago>` from the most recently modified entry in `GET /v1/saves` — typically the autosave; dimmed when no saves), **New Journey**, **Chronicles** (annotated `N SAVES`), **Settings**, **Quit** (dimmed styling per mock, but functional: kills the sidecar and exits). Boot readout shows real `SidecarProcess` lines (`REFEREE: LISTENING · 127.0.0.1:<port>` / `SAVES: OK · DICE STREAMS: PRIMED`). Right: static `SceneBackdrop` (sc-night + planet + horizon + veil-cinema + `◤ VIEWPORT · DEEP FIELD` + location line). Pack-neutral graphite at first boot; tints to `last_played_pack` on return. Strip: `ENGINE SYNC ✓ · v0.1.0` | `NARRATOR: <model> ●`.

### 7.2 Settings — `05-settings.html`
- **SERVER · THE NARRATOR:** provider + model dropdowns (both populated from `/v1/config/providers` presets; no free-text model entry in M2 — the mock shows only the dropdown); API key field (masked tail + keychain backend + REPLACE; an absent key field on PUT keeps the stored key per the mock's wiring note); base URL; max retries. TEST CONNECTION → `POST /v1/settings/llm/test` with client-measured latency (`✓ CONNECTION OK · <model> · 640ms`). Key-storage backend stated visibly, including the owner-only-file fallback sentence. A provider switch clears the stored key (Step 0 server behavior); the UI says so at the moment of switch.
- **CLIENT · READING:** text-speed segmented control (SLOW/MEDIUM/FAST/INSTANT), ambient-life toggle, reduced-motion toggle → `settings.cfg`, effective immediately.
- **CLIENT · AUDIO:** Master/Music/Effects sliders → `settings.cfg`.
- **SERVER · DATA:** saves summary line, OPEN CHRONICLES ▸, EXPORT ALL (loops `GET /v1/saves/{name}/export` over every save, writing one `<save-name>.json` per export into a user-picked folder via native FileDialog).
- Strip: `NARRATOR: <model> ●` | `SETTINGS SAVED` (after a successful PUT).

### 7.3 Chronicles — `02-chronicles.html`
Docket list from `GET /v1/saves`: each docket px-framed and **tinted to its save's pack**; name + data lines (career rank · term · credits / mission · scene); vertical spine (`AUTO·2H` / `MANUAL` / `✝ R.I.P.` — dead saves tint `t-dead`). Selected docket gets the accent outline. Trailing "— empty slot — / IMPORT A SAVE FILE…" docket → native file pick → `POST /v1/saves/import` (409 → verbatim toast). Preview pane (tinted to selection): name, data strip, THE STORY SO FAR + Unresolved line — per the mock's wiring note, selecting a docket resumes the session (`POST /v1/sessions {from_save}`) and fetches `GET .../recap`. Resume takes the **base** save name (autosave-suffixed names are rejected with 422; the saves list flags autosaves, and the client strips to the base name). Every resume creates a fresh server-side session — `SessionRegistry._open` never dedups — so the client owns **preview-session hygiene**: selecting a docket resumes that save and DELETEs the previous preview session; leaving the screen DELETEs the active preview; RESUME instead promotes the preview to the live session handed to the boundary stub (no delete). Actions: RESUME ▸, DUPLICATE (name prompt → `POST .../duplicate`), EXPORT (folder pick → `GET .../export`), DELETE (confirm modal → `DELETE /v1/saves/{name}`). RESUME lands on the matching boundary stub (M2-D8).

### 7.4 New Journey — `03-new-journey.html`
The four-section manifest exactly as mocked: **01 CHRONICLE** (name field with accent caret; seed display + ⟳ REROLL — the seed is client-generated, determinism-as-feature; the mock shows six digits, and the plan pins the exact type/range from `CreateSessionRequest`); **02 THEME PACK** (per-pack tinted cards with motif, description, stats line from `/v1/config/packs`; selected = accent border + `▸ LOCKED IN`); **03 RESOLUTION PROFILE** (narrative/classic cards with tier-math lines); **04 DEATH MODE** (three cards, honest consequences) — profiles/death modes from `/v1/config/rulesets`. Immutability notice verbatim. Beside BEGIN, the narrator status line per mock: `NARRATOR: <model> ● · TEMPLATES IF IT EVER FAILS` / `SPEND CAP: <n> CALLS PER BEAT` (fed by `/v1/llm/status` + `/v1/settings/llm`; the plan pins where the cap number comes from). BEGIN validates (non-empty name; no save-name collision — checked client-side, server 409 → toast) → `POST /v1/sessions {kind:"chargen", name, seed, pack_id, profile, death_mode}` → the Ceremony boundary stub (M2-D8).

### 7.5 Boundary stubs (M2-D8)
Reached from New Journey BEGIN, Title Continue, and Chronicles RESUME. Each states what arrives in which milestone ("THE CEREMONY arrives in M3" / adventure shell in M4) and renders the session's current view as formatted cockpit data — real wiring, inspectable, replaced wholesale by M3/M4. Dead saves (mock 02: ✝ dockets) resume server-side into adventure sessions whose view is `game_over` (Step 0 `resume()` behavior); the client detects that view and lands on the memorial stub naming M4.

## 8. Testing strategy (gdUnit4)

- **Integration** (real sidecar spawned once per suite via `SidecarProcess`): every `EngineClient` route group; envelope parsing (e.g. 404 → `session_not_found`); `contract_version` presence; `StreamPump` driving a real `world_intro` in template mode (assert block sequence through `done`; close-on-skip).
- **Unit/fake** — `FakeEngineClient` script-double (same method surface, canned view models, scriptable errors): screen logic, validation, toast routing, ESC/stack navigation, `ScreenStack` push/replace/pop.
- **Golden layout** — one baseline screenshot per screen at a pinned 1280×720 window (the mocks' 1180px content column plus margins), stored in `client/tests/golden/`; tolerance comparison; `GOLDEN_UPDATE=1` regenerates (M2-D9).
- **Python side untouched:** ruff + the full pytest suite still gate every push.

## 9. Quality gate integration

Pre-push hook (`.githooks/pre-push`) and CI (`.github/workflows/ci.yml`) each gain:
1. `uv run gdlint client/` and `uv run gdformat --check client/` (M2-D5).
2. gdUnit4 headless run (unit + integration) via the pinned Godot binary.
3. Golden-layout job under `xvfb-run` (CI installs `xvfb`; WSLg covers local runs).

The 600s push-timeout rule of thumb stays (the gate now does strictly more work).

## 10. Task map

| # | Task | Lands when |
|---|------|-----------|
| M2.1 | Scaffold + toolchain: `client/` project, `get_godot.sh`, gdUnit4, gdtoolkit, `.gitignore`, gate wiring, fonts | `godot --headless` runs an empty suite in pre-push |
| M2.2 | Theme foundations: PackTheme ×4, Fonts, SteppedFrame, dither, static SceneBackdrop | token-conformance test asserts values match `tokens.css` |
| M2.3 | SidecarProcess + handshake + health + kill + dev-URL override | integration: boot → health ✓ |
| M2.4 | EngineClient: route groups, Result, envelope, contract check | integration per route group |
| M2.5 | StreamPump + block model | integration vs `world_intro` (template mode) |
| M2.6 | App shell: main.tscn, ScreenStack, OverlayLayer/toasts, StatusStrip, ClientSettings, boot flow + error card | boots to a stub screen |
| M2.7 | Title screen | end-to-end; golden baseline |
| M2.8 | Settings screen | end-to-end; golden baseline |
| M2.9 | Chronicles screen (dockets, resume+recap preview, actions, import) | end-to-end; golden baseline |
| M2.10 | New Journey + session create + boundary stubs | end-to-end; golden baseline |
| M2.11 | Golden harness formalization + M2 closeout (docs, gate, PR) | M2 acceptance met |

Sequencing note for the plan: theme (M2.2) precedes shell/screens (consumers); the engine layer (M2.3–M2.5) is independent of theme and can interleave; each task lands with the gate green.

## 11. Acceptance criteria (M2)

The parent spec's M2 line, made checkable:
1. Godot spawns the sidecar, parses `LISTENING`, health-checks, and kills it on quit; `ANDROMEDA_SIDECAR_URL` override works.
2. `EngineClient` covers the full v1 surface used by the four screens; `StreamPump` streams a real `world_intro` beat block-by-block in template mode.
3. `ScreenStack` navigates Title ↔ Settings ↔ Chronicles ↔ New Journey with ESC routing; toasts render engine errors verbatim.
4. Theme applies per-pack tokens from code-built `PackTheme`s; a conformance test pins them to `tokens.css`.
5. Title, Settings, Chronicles, New Journey work end-to-end against the real server, matching their mocks; each has a golden baseline.
6. Session create/resume lands on the honest boundary stubs.
7. Full quality gate green: ruff, gdformat/gdlint, pytest, gdUnit4 (headless + golden).

## 12. Execution model & plan detail standard

The implementation plan for this spec is executed by subagents on a cheaper model, so the plan — not the executor — carries the thinking. The standard (same as the Step 0 plan):

- **Two sources of truth only:** the mocks (`design/mockups/final/*`) and the server code (`src/server/`, `src/llm/`, `src/engine/`). Anything not in either is a gap the plan must close, not a freedom the executor may exercise.
- **No shape guessing:** every request/response body, error code, enum value, and NDJSON block type the client touches is inlined in the plan with a `file:line` citation to the server code that produces it.
- **No name guessing:** every GDScript class, autoload, signal, method signature, file path, and scene structure is specified in the plan. Inline code comments in the delivered GDScript explain intent as usual; the plan's detail is *in addition to* those, not a replacement.
- **Deferred enumerations land in the plan:** the exact NDJSON block-type set (`routes_sessions.py` `_ndjson` call sites), the `CreateSessionRequest` seed type/range (`src/server/models.py`), and the narrator spend-cap source are resolved with citations when the plan is written — not at execution time.
- **Verification is executable:** every task ends in a gate-runnable check (a gdUnit4 suite, a golden baseline, a `curl` against the real server) with the expected output stated in the plan.

## 13. Out of scope for M2

Ceremony, chargen beats, character reveal (M3) · adventure shell, hooks, defeat/memorial, overlays (M4) · ambient motion system, dice ceremony, sprite art, audio busses, transitions, accessibility sweep (M5) · everything in the parent spec's §12 · pixel-matching Godot output against the HTML mocks (M2-D9) · streaming consumers (StreamPump ships tested but unread until M3).
