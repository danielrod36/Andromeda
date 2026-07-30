---
title: "Fix Foundational Resolution Math - Plan"
type: fix
date: 2026-07-29
topic: resolution-math
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-brainstorm
execution: code
---

# Fix Foundational Resolution Math - Plan

## Goal Capsule

**Objective:** Correct the difficulty ladder and characteristic DM ladder in `cepheus.py` to match the CE SRD, so every qualification, survival, advancement, and aging check resolves with the right modifiers.

**Product authority:** This plan owns the two lookup tables and their tests. The remaining chargen gaps (skill table die sizes, career data, aging mechanic, injury table, background skills, benefits persistence) are separately planned work — see the ideation artifact at `docs/ideation/2026-07-29-ce-srd-comprehensive-chargen-ideation.html` for the full gap map.

**Open blockers:** None. The SRD defines authoritative correct values.

## Product Contract

*Product Contract unchanged — enriched from requirements-only to implementation-ready.*

### Summary

Fix two foundational resolution constants in `cepheus.py` — the difficulty ladder and the characteristic DM ladder — so they match the CE SRD. Update the docstring and all affected tests.

### Problem Frame

Two lookup tables in `src/rulesets/cepheus.py` have wrong values, and together they corrupt every die roll in the game. Lifepath checks (qualification, survival, advancement, aging) route through `characteristic_dm`; scene checks additionally route through `difficulty_modifier`. Correcting both lookup tables fixes scene resolution and lifepath DMs simultaneously. The difficulty ladder sets Easy to +1 (SRD: +4), Difficult to −1 (SRD: −2), and Very Difficult to −2 (SRD: −4). The characteristic DM ladder returns −3 at score 0 (SRD: −2, matching the 0–2 band) and caps at +3 for all scores 15+ (SRD: +3 at 15–17, scaling to +4 at 18–20, up to +6 at 24–26). The docstring at `cepheus.py:128-129` enshrines these wrong values as correct, creating a self-reinforcing cycle. Every qualification, survival, advancement, and aging check routes through these two functions. Low-stat characters are penalized more harshly than intended; high-stat characters lose their reward; Easy tasks are 3 DM points harder than the SRD specifies.

### Requirements

**Difficulty Ladder**

R1. The difficulty ladder must return SRD-correct DM values: Easy +4, Routine +2, Average 0, Difficult −2, Very Difficult −4, Formidable −6.

R2. The class docstring must document the corrected ladder so future developers see the right values as authoritative.

**Characteristic DM Ladder**

R3. The `characteristic_dm` method must return −2 for scores 0–2 (not −3 for score 0 specifically).

R4. The method must extend past +3: +4 for 18–20, +5 for 21–23, +6 for 24+, matching the full SRD table.

R5. The method docstring must document the corrected ladder including the extended high-end range.

**Test Alignment**

R6. All existing tests that assert old wrong difficulty-ladder or characteristic-DM values must be updated to assert the SRD-correct values.

### Key Decisions

**Extend the DM ladder to the full SRD range (0–26).** The engine currently caps characteristics at 15 (`state.py`), but aging reductions, characteristic-increasing skill results, and future psionics can push stats outside that range. Implementing the full SRD table now avoids a silent fallback when those paths produce values above 15.

**Narrative profile DM clamping is unaffected.** The `NarrativeProfile` in `src/rulesets/profiles.py` clamps the total DM to [−3, +3] for PbtA tier resolution. This clamping is a separate resolution mechanic applied after the difficulty modifier — correcting the difficulty ladder does not change clamping behavior.

### Acceptance Examples

AE1. **Covers R1.** A character making an Easy check receives +4 DM, not +1. An Easy qualification with raw roll 4 passes (4 + 4 = 8 ≥ 8) instead of failing (4 + 1 = 5 < 8).

AE2. **Covers R3.** A character with STR 0 receives DM −2 on a survival check, not −3. A raw roll of 10 with the old −3 DM yields 7 (fail vs 8); with the corrected −2 DM it yields 8 (pass).

AE3. **Covers R4.** A character with INT 18 receives DM +4, not +3. A raw roll of 4 on an Average qualification passes (4 + 4 = 8) instead of failing (4 + 3 = 7 < 8).

AE4. **Covers R1, R3, R6.** Existing tests asserting `characteristic_dm(0) == -3` or `difficulty_modifier("easy") == 1` fail after the fix and must be updated to the SRD-correct values.

### Scope Boundaries

- **Not in scope:** The aging mechanic (binary vs graduated table) — separately planned as ideation survivor #5.
- **Not in scope:** Skill table die sizes (2D6 vs 1D6) — separately planned as ideation survivor #2.
- **Not in scope:** Career data correction (wrong qualification/survival/advancement targets) — separately planned as ideation survivor #7.
- **Not in scope:** Changing the characteristic cap (max 15) — part of broader career lifecycle work.
- **Not in scope:** Save-file migration for characters generated with old values.

### Sources / Research

- CE SRD Character Creation: `https://cepheus-srd.opengamingnetwork.com/cepheus-engine-srd/cepheus-engine-character-creation/`
- SRD Rules Audit: `docs/research/cepheus-adventure/srd-rules-audit.md` (findings B1, B2)
- Ideation Artifact: `docs/ideation/2026-07-29-ce-srd-comprehensive-chargen-ideation.html` (survivor #1)

---

## Planning Contract

### Key Technical Decisions

**KTD1: Difficulty ladder correction is a dict-value swap.** The `_difficulty_ladder` class attribute at `cepheus.py:58-65` maps difficulty names to DM integers. Three values are wrong (Easy, Difficult, Very Difficult); three are correct (Routine, Average, Formidable). The fix is swapping the three wrong values. The `difficulty_modifier()` method and `resolve_check()` method need no changes — they look up the dict and pass through.

**KTD2: Characteristic DM extension adds three elif branches.** The `characteristic_dm()` method at `cepheus.py:125-144` uses an if-elif chain. Score 0 currently returns −3 (should be −2, matching the 0–2 band). The high end caps at `else: return 3` for all 15+, but the SRD extends to +6 at 24+. The fix: change the score-0 branch from `value <= 0: return -3` to `value <= 2: return -2`, and split the final `else` into four bands: 15–17 (+3), 18–20 (+4), 21–23 (+5), 24+ (+6).

**KTD3: Narrative profile clamping absorbs the Easy +4 change.** The `NarrativeProfile` clamps DM to [−3, +3] via `clamp_dm()` in `profiles.py:59-70` — an engine design decision, not an SRD rule. After fixing Easy to +4, the narrative profile clamps it to +3 (previously +1 passed through unclamped, a +2 effective swing). No change to `profiles.py` is needed. If +3-clamped Easy does not match the desired narrative-mode feel, that is a separate product decision outside this plan's scope.

**KTD4: Docstring updates prevent the self-reinforcing wrongness cycle.** Both the class-level docstring (`cepheus.py:29-51`) and the `characteristic_dm` method docstring (`cepheus.py:128-129`) currently state the wrong values as authoritative. A developer reading either would believe the code is correct. Updating both docstrings to match the SRD values is load-bearing — it prevents regression.

---

## Implementation Units

### U1. Fix difficulty ladder and characteristic DM values in cepheus.py

**Goal:** Correct the two lookup tables and their docstrings to match the CE SRD.

**Requirements:** R1, R2, R3, R4, R5

**Dependencies:** None

**Files:**
- `src/rulesets/cepheus.py` (modify)

**Approach:**

*Difficulty ladder (R1, R2):* In the `_difficulty_ladder` dict at line 58, change three values: `"easy": 1` → `"easy": 4`, `"difficult": -1` → `"difficult": -2`, `"very_difficult": -2` → `"very_difficult": -4`. Update the class docstring's difficulty ladder table (lines 29-38) to show the corrected values.

*Characteristic DM (R3, R4, R5):* In the `characteristic_dm` method at lines 125-144, change the score-0 branch from `if value <= 0: return -3` to fold score 0 into the existing `value <= 2` band (which already returns −2). Replace the final `else: return 3` with four bands: 15–17 (+3), 18–20 (+4), 21–23 (+5), 24+ (+6). Update the method docstring (lines 128-129) to show the full corrected ladder.

**Patterns to follow:** The existing if-elif chain structure in `characteristic_dm` is the right pattern — extend it with additional elif branches rather than restructuring.

**Test scenarios:** See U2.

**Verification:** `characteristic_dm(0)` returns −2. `characteristic_dm(18)` returns +4. `difficulty_modifier("easy")` returns +4. Full test suite passes after U2.

---

### U2. Update test assertions to match SRD-correct values

**Goal:** Fix all test assertions that enshrine wrong values and add coverage for the extended DM range.

**Requirements:** R6

**Dependencies:** U1

**Files:**
- `tests/rulesets/test_base.py` (modify)

**Approach:**

Three test functions in `test_base.py` directly assert wrong values:

1. `test_difficulty_ladder_modifiers_match_ce_srd` (lines 50-58): Asserts `easy == 1`, `difficult == -1`, `very_difficult == -2`. Update to `easy == 4`, `difficult == -2`, `very_difficult == -4`.

2. `test_difficulty_ladder_values` (lines 67-76): Asserts the full dict with wrong values. Update the three wrong entries.

3. `test_characteristic_dm_ladder` (lines 186-199): Asserts `characteristic_dm(0) == -3` and caps at `characteristic_dm(15) == 3`. Change the score-0 assertion to −2. Add assertions for the extended range: `characteristic_dm(18) == 4`, `characteristic_dm(20) == 4`, `characteristic_dm(21) == 5`, `characteristic_dm(24) == 6`, `characteristic_dm(26) == 6`.

After updating, run the full test suite to catch any dependent test failures in lifepath or scene tests that rely on the old values through seeded dice interactions.

**Test scenarios:**
- Covers AE1. `test_difficulty_ladder_modifiers_match_ce_srd` asserts `easy == 4`, validating the Easy +4 acceptance example.
- Covers AE4. `test_difficulty_ladder_modifiers_match_ce_srd` asserts the six SRD-correct difficulty values.
- Covers AE4. `test_difficulty_ladder_values` asserts the complete corrected dict.
- Covers AE2. `test_characteristic_dm_ladder` asserts `characteristic_dm(0) == -2` (not −3).
- Covers AE3. `test_characteristic_dm_ladder` asserts `characteristic_dm(18) == 4`, `characteristic_dm(21) == 5`, `characteristic_dm(24) == 6`.
- Boundary: `characteristic_dm(15) == 3`, `characteristic_dm(17) == 3` (still +3 at 15–17).
- Boundary: `characteristic_dm(2) == -2` (score 2 still −2, unchanged).
- Regression: full test suite passes — no lifepath or scene test breaks from the DM value changes.

**Verification:** `pytest tests/` exits 0. No test asserts a pre-fix value.

---

## Verification Contract

- `pytest tests/rulesets/test_base.py -v` — all difficulty ladder and characteristic DM tests pass with corrected values.
- `pytest tests/` — full suite passes; no regressions from DM value changes in lifepath, scene, or profile tests.

## Definition of Done

- Difficulty ladder returns SRD-correct values (Easy +4, Routine +2, Average 0, Difficult −2, Very Difficult −4, Formidable −6).
- Characteristic DM returns −2 for scores 0–2 and extends to +6 at 24+.
- Both docstrings reflect the corrected values.
- All tests pass with no assertion of a pre-fix value.
