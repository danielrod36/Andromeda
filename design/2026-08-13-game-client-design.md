# Andromeda Game Client — Design Spec

> **Date:** 2026-08-13 · **Status:** approved design, pre-implementation
> **Artifacts:** `design/mockups/deck.html` (navigable final deck) · `design/mockups/final/` (12 canonical screens + `tokens.css`) · `design/mockups/*.html` (exploration history)
> **Origin:** engine completeness review 2026-08-13 → client-path brainstorm (this document is the settled output).

---

## 1. Goal

Build Andromeda's real game client: a **Godot 4.7 (GDScript) application** that *feels like a shipped game* — reading-first, hi-bit pixel-art presentation in the Sea of Stars "retro plus" idiom — over the unchanged Python engine, which runs as a **local FastAPI sidecar** speaking HTTP + NDJSON streaming. First-release distribution target: plays great on the developer's machine; packaging is deferred, not precluded.

Settled product inputs: shipped-game feel · my-machine distribution · sprite-based illustration set (Sea of Stars direction) · maximum API flexibility (expose-readily, consume-later) · autosave alongside manual saves · a narrative that builds around the rolls with a player-facing steering chat · rolls rendered graphically, never as text walls.

## 2. Locked decisions

| # | Decision | Notes |
|---|----------|-------|
| D1 | **Godot 4.7 + GDScript** client | Best-maintained open 2D engine (verified 2026-08); PointLight2D + normal-mapped sprites are purpose-built for the hi-bit look; GDScript ≈ Python-frictionless. |
| D2 | **FastAPI sidecar over 127.0.0.1**, NDJSON streaming | `execute_with_pipe` (the stdio alternative) is demonstrably unmaintained upstream (godot#102340, #97423, #111029). Session layer stays transport-agnostic; a stdio adapter remains a ~50-line future option. |
| D3 | **Hi-bit Console design language** | Pixel-stepped frames, dither, hard offset shadows; pack-token palettes; type system and rules in §6. |
| D4 | **Cinematic shell everywhere** | Scene backdrop + veil + kicker + prose persist through chargen and adventure; interactions stage onto the cinema. |
| D5 | **Roll readouts, not text walls** | Every roll renders as pips + named DM chips + total + tier meter (§6.4). Text dockets only for non-dice events. |
| D6 | **Narrative steering with funnel provenance** | Per-beat LLM narration + a steering chat; "the past is written, the present can be re-told, the future is steered"; story directions are canonical funnel events. |
| D7 | **Key storage in the OS keychain** | `keyring` package; owner-only-file fallback with visible status. The client never holds the key. |
| D8 | **No-tilt rule** | All elements level on the grid. |

## 3. Architecture

```
┌─ Godot 4.7 (GDScript) ───────────────┐      ┌─ Python sidecar ─────────────────┐
│ main.tscn: ScreenStack + OverlayLayer │      │ src/server/ — FastAPI app        │
│ engine/  EngineClient (HTTPRequest)   │ HTTP │  wraps ChargenSession +          │
│         StreamPump (HTTPClient, NDJSON)│◄────►│  AdventureSession (new)          │
│ director/ BeatDirector (beat pipeline)│ NDJSON│ src/engine + src/game (untouched)│
│ ui/ screens + components              │      │ src/llm (adapter, advisor, ...)  │
│ theme/ tokens → Theme resource        │      └──────────────────────────────────┘
└───────────────────────────────────────┘        spawned by Godot, killed on quit;
                                                  5-min no-request self-exit watchdog
```

**Sidecar lifecycle:** Godot spawns `uv run python -m src.server --port 0`; server prints `LISTENING <port>` on stdout (the only stdout line Godot reads); client health-checks, then plays. Quit → Godot kills the PID. Orphan guard → server self-exits after 5 min without requests.

**The BeatDirector** is the client's heart; every action everywhere runs one pipeline:
```
input → POST /choose (instant: mechanics resolve, receipts render)
      → POST /narrate → NDJSON block stream → prose types in
      → choices unlock
```
Skip = close stream, show full text, unlock. Template mode = same blocks, one batch. The engine's existing `NarrationBlock` types (`narration|receipt|change|badge|done|error`) are the wire protocol — degraded modes need no client branching.

**Hard rules:** the client holds zero game truth (every render from server view models; reconnect = `GET /v1/sessions/{id}`); no mechanics math in GDScript beyond presentation; client-local settings (audio, text speed, reduced motion, ambient toggle) in `user://settings.cfg`.

## 4. Step 0 — engine-side work (pre-client)

| # | Item | Nature |
|---|------|--------|
| M0.1 | **B4 fix**: `AdventureController._do_push_for_ending` gates `scenes_completed >= min_scenes` before any roll | engine fix |
| M0.2 | **G6**: ratification produces a real `NpcRecord` + disposition rolled on the pack's `npc_reaction` table | engine feature |
| M0.3 | **`AdventureSession`** versioned contract (mirrors `ChargenSession`): create/current_view/choose/submit_freetext/serialize/restore, `CONTRACT_VERSION = 1` | packaging |
| M0.4 | **Beat narration**: `build_beat_facts(events)` helper + initial/steered prompt builders + world-intro surface (`build_world_intro_prompt` + pack `intro:` fallback) | engine helper + LLM prompts |
| M0.5 | **`RecordStoryDirectionCommand`** + narrator memory (prior prose in prompt; shipped prose always funneled to the narrative log) | one command + prompts |
| M0.6 | **API surface** (§5) incl. narration beats with `steering` | server transport |
| M0.7 | **Keyring storage** for the LLM key (`settings.py` split; masked tail; backend reported) | server settings |

## 5. API surface (v1, all under `/v1`)

Sessions: `POST /sessions` · `GET /sessions/{id}` · `POST .../choose` · `POST .../freetext` · `POST .../suggest` · `POST .../narrate` (NDJSON; `{beat, steering?}`) · `DELETE /sessions/{id}` · `GET /sessions` · `GET .../sheet` · `GET .../recap` · `GET .../memorial`.
Saves: `GET /saves` (manual + autosave flagged) · `POST .../save` · `DELETE /saves/{name}` · `POST /saves/{name}/duplicate` · `GET /saves/{name}/export` · `POST /saves/import`.
Config: `GET /config/packs` (incl. `theme:` hints) · `GET /config/rulesets` · `GET /config/providers`.
Settings: `GET/PUT /settings/llm` (masked key) · `POST /settings/llm/test`.
Introspection: `GET .../audit?kind=&stream=&since=` · `GET .../llm-context` · `POST .../odds` · `GET .../hash` · `POST .../verify` (**deferred** — needs the engine replay walker).
Meta: `GET /health` · `GET /llm/status`.

Errors: `{"error":{"code","message"}}`, 4xx/422; client renders engine messages verbatim in toasts. Every view response carries `contract_version`. **Autosave:** server writes `{name}.autosave.json` after every beat (atomic temp+replace; checkpoint sidecar cadence preserved; stale-write detection intact).

## 6. Design language — Hi-bit Console

### 6.1 Type system
Space Grotesk 700 (screen titles, big numbers) · Chakra Petch 500/600 (interactive titles: menus, choices, buttons) · Atkinson Hyperlegible 400/700 (prose) · IBM Plex Mono 500/600 (data: receipts, odds, audit) · VT323 (micro-labels: kickers, pack tags, SEQ stamps — never main content).

### 6.2 Tokens
Per-pack custom-property sets: `bg · panel · line · ink · muted · accent · ok · danger` + motif glyph. scifi ✦ amber · fantasy ❧ gold · neutral ◆ graphite/steel · dead ✝ umber. Packs may ship a `theme:` block; loader defaults otherwise. Tokens also carry an `ambience` list (fantasy swaps meteors/birds for fireflies/leaves).

### 6.3 Frames & texture
2px stepped pixel corners (accent outer / panel inner) · 4px dither overlay ~3% · hard 3px offset shadows · glass panels over scenes · dashed hairlines for secondary separators · everything level (D8).

### 6.4 The roll readout (D5)
Full: pip dice + named signed DM chips (green/red) + big total + `vs target` + effect chip + **tier meter** (narrative: miss/weak/strong zones; classic: single cut at 8) with landing marker. Compact: 18px pips + signed chips, no meter. Table rolls (aging/benefits/costs): meterless dice+result form. Natural 2/12 get crit/fumble frames. Meter overflow clamps with a chip.

### 6.5 Motion & ambience
Typewriter prose (skippable) · stamp landings · staggered choice rise (40ms) · boot flicker. Ambient backdrop: twinkling stars, 140s far-star drift, breathing planet glow, blinking horizon beacon; rare events (meteor ~1/min, bird flock ~1/2min) on jittered timers. `prefers-reduced-motion` collapses everything. Godot mapping: GPUParticles2D (stars/meteor), AnimatedSprite2D (birds), Timer-driven PointLight2D (beacon).

## 7. Screen requirements (the deck, screen by screen)

Each entry: purpose · primary content · endpoints. All screens render pack tokens; all overlays are read-only views that launch funnel-safe actions.

1. **Title** — console-boot layout; menu dockets (Continue carries last autosave note); sidecar boot readout; ambient viewport. `GET /health`, `GET /llm/status`.
2. **Chronicles** — save dockets (autosave spine, ✝ memorialized saves resume into memorial) + recap preview + duplicate/export/delete/import. `GET /saves`, `GET .../recap`.
3. **New Journey** — the manifest: name, rerollable seed, pack cards (token-tinted, content stats), profile cards (tier math), death-mode cards (honest consequences), immutability notice, narrator status. `GET /config/*` → `POST /sessions`.
4. **Ceremony** — FATE SEEDED stamp → world-intro stream → name capture. `POST .../narrate {beat:"world_intro"}`, `SetCharacterNameCommand`.
5. **Settings** — server-owned narrator card (keyring-backed key, live test) + data card; client-owned reading/audio cards. `GET/PUT /settings/llm`, `POST .../test`.
6. **Chargen shell** — journey strip; pool-assign stage (drag or tap-tap); pinned sheet drawer; story rail; narrator chat; advisor dock button; per-phase backdrop dressing. `choose`, `suggest`, `narrate`.
7. **Chargen beats** — career deck (per-career sprite vistas + hero rail with big-number odds; stat filter chips; free-text), aging slot assignment with crisis warnings, crisis beat (rolled cost; pay/scar; death-mode aware), per-career muster allocation (pips, lifetime cash cap, claims ledger), career-change routing.
8. **Character reveal** — the chronicle page: sheet card, term ledger (record + rail truth), closing passage, audit-this-life. `GET /sheet`, `narrate {beat:"chargen_close"}`.
9. **Adventure shell** — mission header (clocks from `scenes_completed/min_scenes` + threads), NPC chips (dispositions from G6), spine (prose · choice · **readout** · outcome · change lines), odded choice cards, gated push-for-ending with requirement, free-text slot, advisor/narrator links, abandon. Dice ceremony (skippable, preference remembered).
10. **Hook / free-text** — patron card (objective/complication/reward; accept/refuse; pinned via `pending_hook`); interpretation card (your words → exact check, odds, lethality; proceed/rephrase/back; pinned via `pending_freetext`).
11. **Defeat & memorial** — checkpoint rewind divider (abandoned branch dimmed above it), narrative consequence card, ironman memorial (audit-derived obituary, notable rolls with pips, template-first epitaph). `GET /memorial`.
12. **Overlays** — sheet drawer · audit viewer (filters, rewind rows, export; verify-replay disabled until engine support) · LLM-context inspector (with never-includes strip) · advisor panel (mandatory provenance line) · pause menu · toasts (verbatim engine strings).

## 8. Art direction

Hi-bit sprite illustration set: per-career vistas (25 sci-fi + 10 fantasy; card strip + hero crop), scene backdrops (parallax layers), NPC/character portrait chips — all with normal maps so pack lighting (PointLight2D) plays across them. Production: bounded, one curated pass (AI-assisted generation + hand curation/touch-up is acceptable for this project), then frozen. Ambient per §6.5.

## 9. Error & degradation model

LLM unreachable/invalid → template narration, same block types, status strip says so (canonical strings only). Advisor absent → dock button dims with reason. Retry exhaustion → mechanical outcomes displayed; flag in audit. Save conflict → toast with reload/save-as-copy. Server down mid-session → reconnect card; session reconstructs from the autosave. Reduced motion → static everything.

## 10. Testing strategy

Server: contract tests per endpoint (request/response shapes), NDJSON stream tests with forced rollers, autosave cadence tests, keyring abstraction tests (fake backend). Client: Godot scene tests for the BeatDirector state machine (fake EngineClient), golden-layout scenes compared against `final/` mocks. Engine: Step-0 items land with their own tests (B4 gate, G6 producer, beat facts, story direction replay).

## 11. Milestones

- **M1 — Step 0 (engine + server contract):** M0.1–M0.7; API testable with curl; no Godot yet.
- **M2 — Client skeleton:** sidecar lifecycle, EngineClient + StreamPump, ScreenStack, theme from tokens; title + Chronicles + New Journey + Settings end-to-end.
- **M3 — Chargen vertical:** Ceremony → full chargen → reveal, with story rail, narrator chat, advisor, readouts.
- **M4 — Adventure vertical:** shell, hooks, free-text, defeat modes, memorial, overlays.
- **M5 — Polish pass:** ambient system, dice ceremony, art integration, audio, accessibility sweep.

## 12. Explicitly out of scope

Multiplayer · authored scenario modules · second ruleset (the scene-path hardcoding stays documented) · remote/server-hosted play · packaging/installers (deferred) · engine replay walker (the `/verify` endpoint ships disabled).
