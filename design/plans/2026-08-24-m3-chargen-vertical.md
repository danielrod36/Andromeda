# M3 — Chargen vertical: Ceremony → full chargen → reveal

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the character-creation vertical end-to-end — the Ceremony (fate stamp → world intro → name), the full chargen shell rendering all 21 engine phases with story rail, narrator chat, advisor and roll readouts, and the Character Reveal that promotes into the adventure — per `design/2026-08-13-game-client-design.md` §7 screens 4/6/7/8 and the canonical mockups `design/mockups/final/04-ceremony.html`, `06-chargen-shell.html`, `07-chargen-beats.html`, `08-character-reveal.html`.

**Architecture:** Everything renders from existing server truth; **zero new mechanics**. The one server change (Task S1) is additive: expose the campaign seed in the SessionEnvelope. The client grows a `BeatDirector` (spec §3's one pipeline: choose → receipts → narrate → prose types → unlock), a `RollReadout` family (spec §6.4), and three screens (Ceremony, ChargenShell, Reveal) that replace the M2 `StubScreen` boundary. Overlays (sheet drawer, advisor panel) are the first real exercise of `ScreenStack.push/pop`. The engine/game/server layers otherwise ship as-is — M3 is a client milestone plus one envelope field and two deferred integration tests.

---

## Contracts (server truth M3 consumes — verified 2026-08-24)

### The SessionEnvelope (`routes_sessions._session_payload`)

```
{id, name, kind: "chargen"|"adventure", phase: str, view: ChoicePointView|AdventureView|null, contract_version: int}
```

When `phase == "complete"`, `view` is `null` (server sessions.py semantics). After S1 the envelope also carries `seed: int` (`GameState.seed`, state.py:167) and `death_mode: str` (`state.campaign.death_mode` — C7's crisis-card label source).

### ChoicePointView (`src/engine/lifepath_choices.py:37-46`)

```
{choice_id, phase, prompt, options: [ChoiceOptionView], allows_advisor: bool, allows_freetext: bool, freetext_hint: str}
ChoiceOptionView = {option_id, label, description, preview: [str], odds_line: str|null, dimmed: bool, requirement: str|null}
```

### The 21 phases (`_BUILDERS`, lifepath_choices.py:803-825) → journey strip mapping

| Journey segment (mockup 06) | Phases |
|---|---|
| POOL | `roll_characteristics` |
| ASSIGN | `assign_characteristics` |
| BACKGROUND | `choose_background_skills` |
| CAREER | `choose_career`, `choose_qualification_fallback`, `choose_career_change` |
| TERMS | `run_survival`, `choose_commission`, `choose_advancement`, `choose_skills`, `choose_specialization`, `choose_basic_training_skill`, `run_aging`, `choose_aging_reduction`, `mishap_roll`, `choose_injury_stat`, `choose_crisis_resolution`, `re_enlist` |
| MUSTER | `mustering_out`, `muster_out_allocate` |
| (reveal) | `complete` |

(ORIGIN on the strip = the Ceremony; it precedes the shell.)

### Mutations (routes_sessions.py)

- `POST /choose {option_id, origin="player"}` → `{session, result: StepResult, events: [Event]}`
  `StepResult = {view: ChoicePointView|null, receipts: [str], completed, contract_version}` (chargen/api.py:30-40)
- `POST /freetext {text}` (chargen) → `{session, record: TranslationRecord, events}` — **422 `translator_unavailable`** when no narrator model is configured
- `POST /suggest` → `{record: SuggestionRecord|null}` — **422 `advisor_unavailable`**; `SuggestionRecord = {choice_id, selected_option_id, rationale, alternatives: [{option_id, why_not}], context_hash, model_id, prompt_version}` (llm/advisor.py:44-60)
- `POST /name {name}` → `{session}` (SetCharacterNameCommand through the funnel)
- `POST /promote` → `{session}` (kind flips to `adventure`) — **422 `invalid_phase`** unless complete

### Events → readouts

`Event = {seq, kind, command_type, description, roll: RollResult|null, changes}`; `RollResult = {stream, ndice, sides, modifiers, rolls: [int], total}` (engine/audit.py, engine/dice.py). Readouts render from `Event.roll`; receipt lines from `StepResult.receipts`; change lines arrive as NDJSON `change` blocks.

### Narrate (routes_sessions.py:296-398)

`POST /narrate {beat, steering?}` → NDJSON lines `{"type": "narration"|"change"|"badge"|"done", "content"}` — the stream carries **no events array**. Beats: `world_intro` (replays its record unless steered), `chargen_beat` (per-phase facts), `chargen_close` (reveal's closing passage). Steering lands first via `RecordStoryDirectionCommand` — a steered direction becomes a SEQ-bearing `record_story_direction` event in the server log, but it has **no change-line formatter** (`_FORMATTERS`, src/game/change_lines.py:209-239) and never appears in the stream, so the client fetches it via `GET /audit?since={last_seq}` after the stream completes (C9 mechanism). Shipped prose is canonical (`RecordNarrationCommand`) before the client sees a word.

### Client seams (M2, all existing)

`EngineClient` already has typed `choose/freetext/suggest/set_character_name/promote/sheet/recap/audit` (engine_client.gd:209-266). `StreamPump` delivers NDJSON blocks via signals. `ScreenStack` has `replace/push/pop` + `esc_target()` (push/pop currently unused — M3 exercises them). `NewJourneyScreen` BEGIN currently navigates to `"stub"` — M3 retargets to `"ceremony"`. `StubScreen` remains for M4 (adventure views + memorial). Kit primitives: `btn/ghost_btn/microlink/card/data_field/px_frame/menu_item/toggle/slider/segmented`. `PackTheme` tokens: bg/panel/line/ink/muted/accent/ok/danger + motif + ambience. `OverlayLayer`: toast/toast_error/confirm/prompt. `StatusStrip`: refresh/show_narrator_left/set_right_plain. `SessionStore` holds the current envelope.

---

## Pinned rules (deviations & scope locks)

1. **Navigation (extends the M2 pin):** shell-internal overlays — sheet drawer, advisor panel — use `push`/`pop` (first use; they own ESC while open and pop on close). Screen-level transitions stay `replace`. ESC targets: Ceremony → `title` (confirm: abandon this fate), ChargenShell → `title` (confirm), Reveal → `title` (no confirm — the life is saved).
2. **Art placeholders:** per-career sprite vistas are the §8 art pass, M5. M3 career cards render a token-tinted procedural vista (PackTheme gradient + motif silhouette) exactly like mockup 07's CSS stand-ins. No `art/` assets in M3.
3. **No dice ceremony yet:** §6.5's animated dice ceremony is M5. M3 readouts land statically with the stamp-landing tween only (reduced-motion collapses to instant).
4. **Ambient:** M2's static scene dressing (SceneBackdrop) carries M3; the animated ambient system is M5.
5. **Copy rule §6.6:** player-facing copy never uses source vocabulary. Journey strip says CHAPTER/Term language, not phase keys; SEQ/autosave are allowed (taught in place). The FATE SEEDED stamp shows `seed` as a plain number (docket, level).
6. **Zero game truth:** every number on screen comes from `view`/`events`/`sheet`. The readout computes *presentation* only (pip layout from `rolls`, chip text from parsed receipts) — never odds or outcomes.
7. **`complete` renders Reveal, not the shell.** `view == null` at `phase == "complete"` is the Reveal trigger, exactly as the M2 StubScreen guarded.

---

## Tasks

### S1 — Expose `seed` + `death_mode` in the SessionEnvelope (+ the two M2-deferred integration tests)

- [ ] `src/server/routes_sessions.py` `_session_payload`: add `"seed": record.game.state.seed` and `"death_mode": record.game.state.campaign.death_mode` (additive; no contract bump — additive fields per M1 convention). Update the envelope contract test in `tests/server/test_sessions.py`.
- [ ] `tests/server/test_persistence_contract.py` (or `test_sessions.py`): the M2-deferred **promote integration test** — scripted chargen to `complete` via real `choose` calls (deterministic seed + fixed option sequence), then `POST /promote` → envelope `kind == "adventure"`, phase is the adventure's first view; promote before complete → 422 `invalid_phase`.
- [ ] Same file: **narrate replay test** — `world_intro` twice without steering returns identical prose (record replay, no second LLM call); with steering it re-tells (new record).
- **Commit:** `feat(server): seed in SessionEnvelope + promote/world-intro integration tests (M3-S1)`

### C1 — BeatDirector: the one pipeline

- [ ] New `client/engine/beat_director.gd` (Node). States: `IDLE → CHOOSING → RECEIPTS → NARRATING (stream) → DONE`. API:
  ```
  signal beat_finished(session: Dictionary)        # new envelope after narrate
  signal block_received(type: String, content: String)
  signal receipts_ready(events: Array)             # readouts render here
  signal beat_failed(code: String, message: String)
  func run(choose_args) -> void        # choose → receipts → narrate(chargen_beat) → unlock
  func skip() -> void                  # close stream, emit full-text block, unlock
  func narrate_only(beat: String, steering := "") -> void   # ceremony/reveal/steered re-tell
  ```
  Skips close the StreamPump and synthesize a `done`. Template mode needs no branching — blocks arrive the same (spec §3). Errors mid-pipeline surface via `beat_failed` and re-enable input; `ActionInFlightError` maps to **409** `action_in_flight` (src/server/errors.py:47-49 — not 422) and renders as a toast, returning the director to IDLE.
- [ ] `client/tests/engine/test_beat_director.gd` with `FakeEngineClient` + a fake pump: happy path, skip mid-stream, transport error after choose (envelope retained, choices unlock), 409 `action_in_flight` + 422 handling.
- **Commit:** `feat(client): BeatDirector choose→narrate pipeline (M3-C1)`

### C2 — Readout + shell primitives

- [ ] `client/components/roll_readout.gd`: full form (pip dice from `rolls[]`, signed DM chips from `modifiers` + receipt-parsed names, big total, `vs`/verdict from the receipt line), compact form (18px pips + chips), table-roll form (dice + `→ RESULT`, meterless — aging/muster). Parses `RollResult` dictionaries; crit/fumble (natural 2/12) get accent/danger frames. Static render + stamp-landing tween; no meter in M3 (tier meter lands with adventure odds UI in M4).
- [ ] `client/components/journey_strip.gd`: segments from the pinned phase table, `here` marker (`▸ SEGMENT`), `done` dimming; player-facing segment names only (pin 5).
- [ ] `client/components/typewriter_prose.gd`: RichTextLabel + caret `▌`, per-sentence feed from `narration` blocks (sentences pre-split server-side), SKIP microlink completes instantly (reduced-motion: instant).
- [ ] `client/components/story_rail.gd`: `THE STORY SO FAR` — beat entries `{stamp: "TERM 2 · SURVEY DUTY", prose, old: bool}`; stamps derived from phase + age in the session view (no invention); `RE-TOLD` suffix on steered beats.
- [ ] `client/components/stat_row.gd`: name / value / DM chip, `drop` highlight, `→ NEWVALUE` preview variant (aging/injury).
- [ ] Tests: `client/tests/components/` — readout forms from canned `RollResult`s (incl. natural 2/12), strip mapping for every phase, typewriter skip, rail stamps. No goldens here.
- **Commit:** `feat(client): readout, journey strip, typewriter, story rail, stat row (M3-C2)`

### C3 — Ceremony screen

- [ ] New `client/screens/ceremony_screen.gd` + registry in `main.gd`. Three beats on one scene (mockup 04):
  1. **FATE SEEDED** — docket `FATE SEEDED · {seed}` (envelope after S1), auto-advances (~1.2s) —
  2. **WORLD INTRO** — `beat_director.narrate_only("world_intro")`, typewriter over the scene, SKIP / CONTINUE once done —
  3. **THE NAME** — `OverlayLayer.prompt` or inline card; commits via `set_character_name` → then `replace("chargen")`. Empty name keeps START disabled; input capped at 80 chars (`SetCharacterNameCommand` rejects longer, src/engine/commands.py:294-295, surfacing as 422 `invalid_choice`). No uniqueness pre-check — character names carry no uniqueness constraint, and NewJourney's duplicate check is about *save* names at create time, which the ceremony never touches.
- [ ] Retarget `new_journey_screen.gd` BEGIN: `navigate` to `"ceremony"` (was `"stub"`); stub stays registered for M4.
- [ ] ESC → `title` with confirm (abandon). Session cleanup: deleting via `delete_session` on confirm-abandon.
- [ ] Tests: `client/tests/screens/test_ceremony_screen.gd` — beat sequencing with canned world_intro blocks, name commit calls `set_character_name` with the typed value, ESC confirm path, BEGIN lands on ceremony (update `test_new_journey_screen.gd`).
- **Commit:** `feat(client): Ceremony screen — fate stamp, world intro, the name (M3-C3)`

### C4 — Chargen shell frame

- [ ] New `client/screens/chargen_screen.gd` — the shell for every non-complete phase (mockups 06/07): scene + veil + kicker (chapter language), `JourneyStrip` top-center, layout regions `rail | stage | dock` (narrator chat slides in as the third column, mockup 06c), dockbar with `✦ ASK THE ADVISOR` / `✎ TALK TO THE NARRATOR` ghost buttons + contextual subnote.
- [ ] **Generic stage:** renders any `ChoicePointView` — prompt as prose lead, options as `Kit.card` choice cards (title=label, `odds_line` as the mono data line, `preview` bullets, dimmed cards at 45% with `requirement` note, staggered rise 40ms). This is the fallback renderer for phases without a bespoke one below; it must ship first so every phase is playable even before C5–C7 dress it.
- [ ] **Sheet drawer** (`push`): pinned right panel (mockup 06 left pane): name/age/term from envelope+sheet (`get sheet` on open), pool receipts. First `push/pop` consumer — `ScreenStack` gets its push/pop tests here (`client/tests/app/test_screen_stack.gd` extended: push owns ESC, pop restores).
- [ ] Reconnect: on `screen_enter`, `get_session(id)` refresh; mismatched contract → the M2 contract card.
- [ ] Tests: shell renders canned envelopes per journey segment; card dimming; sheet push/pop; ESC → title confirm.
- **Commit:** `feat(client): chargen shell — journey strip, generic stage, sheet drawer (M3-C4)`

### C5 — Bespoke stages I: pool, background, career deck

- [ ] `assign_characteristics`: pool chips (ghost = spent, flight = dragging) + 3×2 stat matrix; tap-tap assignment (tap chip, tap row; drag optional), reroll-once ghost button wired to the reroll option, CONTINUE gated until all six placed (mockup 06).
- [ ] `choose_background_skills`: multi-select cards until the count is met; CONTINUE commits the set.
- [ ] `choose_career` — the career deck (mockup 07a): filter chips (ALL / per-characteristic / OFFICER TRACK) client-side filter over `options`; cards with procedural vista (pin 2), `odds_line` percent + band + bar (ok/accent/danger by band); selected card opens the hero rail (big % + full preview bullets + ATTEMPT QUALIFICATION); free-text slot in the dockbar when `allows_freetext` (freetext → `record` TranslationRecord rendered as an interpretation card: your words → the career the translator picked; 422 `translator_unavailable` dims the slot with the reason).
- [ ] `choose_qualification_fallback` / `choose_career_change`: generic cards (already playable via C4) + copy pass only.
- [ ] Tests: assignment gating + reroll-once; filter behavior; hero rail from odds_line; freetext dim/422 path.
- **Commit:** `feat(client): pool assign, background, career deck stages (M3-C5)`

### C6 — Bespoke stages II: the term loop

- [ ] Term beats (`run_survival`, `choose_commission`, `choose_advancement`, `choose_skills`, `choose_specialization`, `choose_basic_training_skill`, `re_enlist`): stage = story rail (left, filling as terms resolve) + readout of the just-rolled event (center, from `events` — survival/commission/advancement rolls render full readouts) + choice cards (mockup 06b). Every choose routes through `BeatDirector.run` — receipts → `RollReadout`, prose → rail typewriter, then unlock.
- [ ] Kicker derives chapter language: `◤ TERM {n} — {duty} · AGE {age}` (age = 18 + 4×terms from the sheet/derivation in view — never client math beyond this display constant already in the mockups; if the view lacks age, derive from `preview`/receipts only. Pin: no invented numbers — if absent, omit the age).
- [ ] Tests: each phase renders via canned envelopes; a scripted two-term run against `FakeEngineClient` walks survival → skills → re-enlist with readouts and rail entries asserted.
- **Commit:** `feat(client): term-loop stages with readouts + rail (M3-C6)`

### C7 — Bespoke stages III: aging, crisis, mishap

- [ ] `run_aging`: table-roll readout (2D6 − terms → table result), then `choose_aging_reduction`: slot tokens (ASSIGNING dashed / PENDING solid), stat rows with `cur → new` previews, crisis-bound row bordered danger (mockup 07b).
- [ ] `choose_crisis_resolution`: cost readout (1D6 → CR{n}k), pay vs scar cards — pay dims with shortfall (`REQUIRES … YOU HAVE …`), scar card is death-mode aware: `narrative` → "Accept the scar"; `ironman` → "ACCEPT DEATH" and choosing it ends the life. The label reads `death_mode` **from the SessionEnvelope** (exposed in S1) — server data only, which also covers sessions resumed from saves that never passed through New Journey. No client-held fallback (pin 6).
- [ ] `mishap_roll` / `choose_injury_stat`: table-roll readout + stat pick with previews.
- [ ] Tests: slot flow, crisis card states per death mode, injury previews.
- **Commit:** `feat(client): aging, crisis, mishap stages (M3-C7)`

### C8 — Muster → Reveal

- [ ] `mustering_out`/`muster_out_allocate`: roll pips (done/filled vs remaining), cash vs material cards (cash dims at 3/3 lifetime with the ledger line), claims ledger dashed box, each claim renders inline as a table-roll readout; FINISH EARLY ghost button routes to `choose_career_change` or completion (mockup 07d).
- [ ] New `client/screens/reveal_screen.gd` (mockup 08): sheet card (`GET /sheet`: characteristics grid + DMs, skills, estate incl. scars), term ledger (rows: term span stamp, prose from the rail, outcome chip — merged from rail data + CareerTermRecord via the sheet/recap payloads), closing passage (`narrate_only("chargen_close")` typewriter), dockbar: OPEN THE RAIL (sheet drawer push), ⧉ AUDIT THIS LIFE (audit overlay — read-only event list, rewind rows dimmed-disabled like M2's inspect stub), `Saved · autosave written` subnote, **BEGIN THE ADVENTURE ▸** → `promote()` → success: `replace("stub")` (adventure stub, M4's seam; envelope kind flips to adventure) → failure 422 → toast.
- [ ] `phase == "complete"` routing: shell auto-`replace("reveal")`.
- [ ] Tests: muster caps/dimming, claim readouts, reveal renders canned sheet + rail, promote success/failure paths, complete-routing.
- **Commit:** `feat(client): muster + character reveal, promote wiring (M3-C8)`

### C9 — Narrator chat + advisor panel

- [ ] Narrator chat (mockup 06c): third-column panel — steering rules line printed (`THE PAST IS WRITTEN · THE PRESENT CAN BE RE-TOLD · THE FUTURE IS STEERED`), chat bubbles (YOU right / NARRATOR left), `⇒ DIRECTION RECORDED · "{text}" · SEQ {n}` dashed chip, input row with SEND. **Chip data source + cursor discipline:** the narrate stream carries no events and `record_story_direction` has no change-line, so after the stream completes the BeatDirector fetches `GET /v1/sessions/{id}/audit?since={last_seen_seq}` and renders chips from returned `record_story_direction` events (`changes.text` + `seq`). `last_seen_seq` advances to **max(seq) of every events source** — choose-response `events` *and* each audit response — so consecutive steers of the same beat (no intervening choose) never duplicate chips and the first fetch never over-sweeps the log. Sending = `narrate_only(current_beat, steering)`; stage shows the re-tell subnote while streaming; rail stamps the beat RE-TOLD.
- [ ] Advisor panel (`push`, mockup 12): `ASK THE ADVISOR` → `suggest()` → SuggestionRecord card: selected option highlighted, rationale prose, alternatives as `why_not` lines, **mandatory provenance line** (`model_id` or `HEURISTIC — OFFLINE` when model_id empty; context_hash tail). 422 `advisor_unavailable` → dock button dims with reason (spec §9). Apply = choose the selected option through the funnel (provenance already recorded server-side).
- [ ] Tests: chat send → steering in narrate args; direction chip rendered from the audit fetch (fake returns the `record_story_direction` event); advisor card fields; dim states on 422.
- **Commit:** `feat(client): narrator chat + advisor panel with provenance (M3-C9)`

### C10 — Goldens, integration smoke, gates

- [ ] Golden baselines: ceremony (fate+intro+name), shell/assign, career deck, crisis, muster, reveal — capture under `ANDROMEDA_DISPLAY=1 GOLDEN_UPDATE=1`, commit PNGs; suites self-skip headless (M2 pattern).
- [ ] Integration smoke (extends the M2 itest pattern): spawn the real sidecar headless; script a full deterministic chargen (fixed seed + option sequence) from create → ceremony name → every phase → complete → promote; assert the final envelope `kind == "adventure"` and the autosave exists. Lives in `client/tests/` guarded to run when the sidecar can spawn (as M2's sidecar tests do).
- [ ] Full gate: `uv run pytest`, `tools/run_client_lint.sh`, `tools/run_client_tests.sh`, goldens in CI's xvfb job; README/CLAUDE.md status lines → M3 shipped, M4 next.
- **Commit(s):** `test(client): M3 goldens + sidecar chargen smoke (M3-C10)` then `docs: M3 shipped, M4 next`

---

## Acceptance (milestone exit)

1. New Journey BEGIN → Ceremony → name → every chargen phase playable → Reveal → BEGIN THE ADVENTURE promotes — all against the **real sidecar**, zero game truth client-side.
2. Every roll renders as a readout (full/compact/table-roll), never a text wall; receipts land before prose; skip works everywhere.
3. Story rail fills with canonical prose; steered beats re-tell and stamp RE-TOLD; directions show as SEQ chips.
4. Advisor shows provenance; both 422 unavailable states dim their entry points with reasons.
5. Sheet drawer and advisor panel push/pop cleanly; ESC semantics hold per pin 1.
6. Gates green: pytest (incl. S1's promote/world-intro integration tests), ruff, gdlint/gdformat, gdUnit (new suites), goldens in CI.
7. `phase == complete` never renders the shell; promote flips the envelope to adventure and lands on the M4 stub.

## Known limits (not bugs)

- Career vistas are procedural placeholders until the M5 art pass (pin 2); the normal-mapped sprite pipeline is out of M3 scope.
- Tier meters on readouts ship with M4's odds surfaces; M3 readouts show dice/chips/total/verdict only.
- The adventure side of the promoted session is the M2 stub — M4 replaces it.
- Steered re-tells cost one narration round-trip each; spend-cap display stays as New Journey renders it.
