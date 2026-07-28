# CE SRD Rules Audit — July 2026

**Sources:**
- [CE SRD Character Creation](https://cepheus-srd.opengamingnetwork.com/cepheus-engine-srd/cepheus-engine-character-creation/)
- [CE SRD Skills (task resolution)](https://cepheus-srd.opengamingnetwork.com/cepheus-engine-srd/cepheus-engine-skills/)
- [CE SRD full text (Scribd)](https://www.scribd.com/document/498436772/Cepheus-Engine-srd)

---

## Tier 1 — Critical Bugs (wrong mechanics, produces incorrect results)

### B1. Difficulty Ladder — Wrong values for 4 of 6 rungs
**SRD** (goes up by 2s):
| Difficulty | DM |
|---|---|
| Easy | **+4** |
| Routine | +2 |
| Average | 0 |
| Difficult | **−2** |
| Very Difficult | **−4** |
| Formidable | −6 |

**Our implementation** ([cepheus.py:58-65](src/rulesets/cepheus.py#L58-L65)):
```
routine: +2, easy: +1, average: 0, difficult: -1, very_difficult: -2, formidable: -6
```
Only Routine, Average, and Formidable match. Easy, Difficult, and Very Difficult are all wrong — they use ±1/±2 instead of ±4/±2/±4.

### B2. Characteristic DM Table — Wrong at score 0 and caps at +3
**SRD:**
| Score | DM |
|---|---|
| 0–2 | −2 |
| 3–5 | −1 |
| 6–8 | 0 |
| 9–11 | +1 |
| 12–14 | +2 |
| 15–17 | +3 |
| 18–20 | +4 |
| 21–23 | +5 |
| 24–26 | +6 |

**Our implementation** ([cepheus.py:131-144](src/rulesets/cepheus.py#L131-L144)):
- Score 0 → **−3** (WRONG: should be −2, same as 1–2)
- Score 15+ → **+3** (WRONG: caps too early; 18–20 should be +4, etc.)

### B3. Skill Table Die Size — Uses 2D6 instead of 1D6
**SRD:** "pick one of these tables and **roll 1D6** to see which skill you increase." All career skill tables have 6 entries numbered 1–6.

**Our implementation:** All career YAML data uses `num_dice: 2, die_size: 6` (range 2–12). The [TableRange model](src/rulesets/base.py#L66-L95) docstring hard-codes the assumption: "All die tables in Cepheus use 2D6 (range 2–12)." This affects **every skill table roll** in lifepath.

### B4. Aging Mechanic — Completely Wrong
**SRD:** Roll 2D6, apply total terms as a **negative DM**, compare to a graduated table:
| Result | Effect |
|---|---|
| ≤−6 | Reduce 3 physical by 2, reduce 1 mental by 1 |
| −5 | Reduce 3 physical by 2 |
| −4 | Reduce 2 physical by 2, reduce 1 physical by 1 |
| −3 | Reduce 1 physical by 2, reduce 2 physical by 1 |
| −2 | Reduce 3 physical by 1 |
| −1 | Reduce 2 physical by 1 |
| 0 | Reduce 1 physical by 1 |
| 1+ | No effect |

**Our implementation** ([lifepath.py:339-376](src/engine/lifepath.py#L339-L376)): Rolls 2D6 vs static target 8. On failure reduces STR/DEX/END by 1 each (or all six on natural 2). Neither the mechanic nor the table matches the SRD.

### B5. Scout and Drifter Have Advancement Defined — Should Have None
**SRD:** "Commissions and advancement are not available in the Athlete, Barbarian, Belter, Drifter, Entertainer, Hunter and Scout careers."

**Our data:**
- [careers.yaml Scout](src/themepacks/data/scifi/careers.yaml#L362-L364): has `advancement: {characteristic: INT, target: 7}` — WRONG, should have no advancement.
- [careers.yaml Drifter](src/themepacks/data/scifi/careers.yaml#L612-L614): has `advancement: {characteristic: END, target: 7}` — WRONG, should have no advancement.

Both should get **2 skill rolls per term** instead (see B8).

### B6. Career-Specific Data Errors (Agent example)
**SRD Agent:**
| Check | SRD | Our Data |
|---|---|---|
| Qualification | Soc 6+ | INT 5 (**WRONG**) |
| Survival | Int 6+ | INT 5 (**WRONG**) |
| Commission | Edu 7+ | (missing entirely) |
| Advancement | Edu 6+ | INT 7 (**WRONG**) |
| Re-enlistment | 6+ | (missing) |

Other careers likely have similar discrepancies — all 8 career definitions need systematic re-verification against the SRD career tables.

---

## Tier 2 — Missing Core Mechanics (present in SRD, absent in engine)

### B7. No Advanced Education Prerequisite
**SRD:** "You may only roll on the Advanced Education table if your character has Education 8+."
**Our code:** No check exists. Players can freely select Advanced Education.

### B8. No Separate Commission Step
**SRD:** Commission is a **separate optional roll** from advancement. A Rank 0 character may attempt commission; success → Rank 1 + extra skill roll. Draftees cannot attempt commission in first term. Commission and advancement can both be attempted in the same term.

**Our code:** Only `AdvancementCommand` exists. No commission phase, no commission `CheckRef` in `CareerData` model. The [CareerData](src/rulesets/base.py#L140-L157) model has qualification/survival/advancement but no commission field.

### B9. No 2-Roll Bonus for Non-Hierarchy Careers
**SRD:** Careers without commission/advancement (Athlete, Barbarian, Belter, Drifter, Entertainer, Hunter, Scout) get **2 skill rolls** per term instead of 1.

**Our code:** [compute_num_skill_rolls](src/engine/lifepath.py#L600-L610) gives 1 base + 1 if advancement success + 1 if rank 3+. Scout and Drifter would never get the 2-roll bonus they're entitled to (and wrongfully roll advancement instead).

### B10. No Background Skills
**SRD:** Before careers, gain skills = 3 + Education DM. First 2 from homeworld (trade codes), rest from education list.
**Our code:** Not implemented.

### B11. No Basic Training
**SRD:** First term in first career = ALL Service Skills at Level 0. First term in subsequent careers = pick ONE Service Skill at Level 0.
**Our code:** Not implemented.

### B12. No Re-enlistment Roll
**SRD:** At end of each term, roll 2D6 vs career re-enlistment number. Natural 12 = must continue. 7+ terms = must retire.
**Our code:** Player simply chooses to continue or leave. No re-enlistment `CheckRef` in `CareerData` model.

### B13. No Injury Table
**SRD:** Survival mishap results 1 and 6 require rolling on the Injury table (1D6 with specific characteristic reductions). Result 1 on injury table = nearly killed (reduce one physical by 1D6). If any characteristic hits 0 → injury crisis (pay Cr10K or die).
**Our code:** Mishaps just force career exit. No injury table, no injury crisis.

### B14. Missing Specialist Skills Table
**SRD:** Careers have **4 skill tables**: Personal Development, Service Skills, **Specialist Skills**, Advanced Education.
**Our code:** All careers have 3 tables (no Specialist Skills). The [SkillTable docstring](src/rulesets/base.py#L113-L117) says "three skill tables."

### B15. Mustering-Out Rank Bonuses Wrong
**SRD:** Extra benefit rolls: Rank O4 → +1, O5 → +2, O6 → +3. Cash rolls **capped at 3**; all others must be material. Benefit tables have 7 entries (7th reached via rank DM).
**Our code:** [muster_out](src/engine/lifepath.py#L716-L766) does `min(terms, 3)` cash rolls, `terms` material rolls. No rank-based extra benefit rolls. Benefit tables have 6 entries, not 7.

### B16. No Draft
**SRD:** On failed qualification, can submit to the draft (1D6 → military career) or take Drifter. Can only be drafted once.
**Our code:** Falls back to Drifter only.

### B17. No Career Change
**SRD:** After leaving a career (total terms < 7), can choose a new career. DM −2 to qualification per previous career. Cannot return to a career you've left (except Drifter).
**Our code:** No career change support.

---

## Tier 3 — Model/Data Structure Gaps

### B18. TableRange Forces 2D6 Assumption
The [TableRange](src/rulesets/base.py#L66-L95) model validates contiguity against `num_dice` (default 2) × `die_size` (default 6), so range 2–12. Skill tables need 1D6 (range 1–6). While the fields exist to override defaults, the validation and all YAML data use 2D6.

### B19. CareerData Missing Fields
The [CareerData](src/rulesets/base.py#L140-L157) model needs:
- `commission: CheckRef | None` — separate from advancement
- `re_enlistment: int` — target number for re-enlistment roll
- `has_hierarchy: bool` — whether commission/advancement exist (for 2-roll bonus logic)

### B20. Only 8 of 24 SRD Careers
The SRD defines 24 careers. We have 8 (Navy, Army, Marines, Merchant, Scout, Agent, Noble, Drifter). Missing 16: Aerospace System Defense, Athlete, Barbarian, Belter, Bureaucrat, Colonist, Diplomat, Entertainer, Hunter, Maritime System Defense, Mercenary, Physician, Pirate, Rogue, Scientist, Surface System Defense, Technician.

---

## What's Correct

These areas match the SRD:
- ✅ 2D6 characteristics in standard order (STR/DEX/END/INT/EDU/SOC)
- ✅ Core task resolution target: 2D6 + DM ≥ 8
- ✅ Classic resolution profile (binary pass/fail with Effect)
- ✅ Narrative profile design (PbtA 10+/7-9/≤6 with DM clamping) — original design, not SRD
- ✅ Survival roll structure (2D6 + characteristic DM vs career target)
- ✅ Death mode branching (Ironman death vs mishap)
- ✅ Natural 2 always fails survival
- ✅ Skill table roll → apply result mechanic (gain skill or +characteristic)
- ✅ Mustering out produces cash and material benefits (structure correct, amounts/bonuses wrong)
- ✅ Event log audit trail
- ✅ Save/resume with deterministic seeded RNG
- ✅ Characteristic score limits (max 15, min 1)
- ✅ Social Standing noble title table (implicit in Noble career ranks)

---

## Fix Priority

**Block all playtesting until fixed:**
1. **B3** — Skill table 1D6 not 2D6 (affects every roll)
2. **B4** — Aging table completely wrong
3. **B1** — Difficulty ladder wrong values
4. **B2** — Characteristic DM score 0 and high-end cap
5. **B5** — Scout/Drifter advancement removal
6. **B8** — Commission as separate optional step
7. **B9** — 2-roll bonus for non-hierarchy careers

**Fix before calling chargen "complete":**
8. **B6** — Systematic career data re-verification
9. **B7** — Advanced Education prerequisite
10. **B14** — Specialist Skills table (data + model)
11. **B10** — Background skills
12. **B11** — Basic training
13. **B12** — Re-enlistment roll
14. **B15** — Mustering-out rank bonuses + 7th table entry
15. **B19** — CareerData model fields (commission, re_enlistment)

**Nice to have:**
16. **B13** — Injury table
17. **B16** — The Draft
18. **B17** — Career change
19. **B18** — TableRange 1D6 support
20. **B20** — Remaining 16 careers
