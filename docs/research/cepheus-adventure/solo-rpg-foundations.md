# Solo RPG Foundations Dossier — LLM-GM CYOA Sci-Fi RPG (2026-07-28)

Scope: challenge/validate the "Cepheus 2D6 + PbtA hybrid" hypothesis for a deterministic engine + LLM narrator.

## Q1 — Solo RPG design patterns worth borrowing

**Ironsworn / Starforged (Shawn Tomkin).** Dual-licensed: full rulebook is CC BY-NC-SA 4.0 (non-commercial only),
but the **Starforged Reference Guide (all moves, rules summaries, oracles), the Ironsworn SRD, and the Dataforged
JSON dataset are CC-BY-4.0 — commercially reusable with attribution, irrevocable** (Tomkin's own statement).
Reusable mechanics: strong hit / weak hit / miss three-tier outcomes; momentum track (a spendable +2..+10 resource
that replaces your roll when it matches — a perfect deterministic "narrative currency"); progress tracks (10-box
clocks for vows/expeditions/combat); oracle tables (yes/no with "and/but" qualifiers, action+theme pairs).
Sources: tomkinpress.com/blogs/news/lets-talk-about-ironsworn-licensing ; github.com/rsek/dataforged (LICENSE.md).

**Mythic GM Emulator (Word Mill, commercial — concepts only).** Fate Chart: cross-reference natural-language odds
("Likely") against a **Chaos Factor (1–9)** that rises when scenes end out of control and falls when they end in
control; d100 roll-under, extreme bands = Exceptional Yes/No. Scene structure: declare expected scene, roll vs
Chaos → as-expected / altered / interrupt; doubles on Fate rolls trigger Random Events (focus + meaning tables);
Threads and Characters lists feed the randomness. The Chaos Factor is a superb "director dial" for an LLM GM.
Sources: wordmillgames.com/page/mythic-gme.html ; wispsoftime.com (Rolling Solo ch.6).

**Zozer SOLO 2nd ed. (2025, commercial $11.99 — concepts only).** Key steal: **"The Plan" — fortune-in-the-middle
scene resolution: player states plan + risk level, one 2D6 roll, then narrate the outcome**. Plus six campaign
frames (Travellers, Star Traders, Scouts, Navy, Mercenaries, Salvagers), whole-crew drama rules, ask-the-D6 oracle.
Proof that Cepheus works solo — but as a campaign-framework layer, not a resolution engine.
Sources: zozergames.com/solo-for-traveller.html ; alegisdownport.wordpress.com (2025-07 review).

**What makes no-human-GM solo work:** (1) an oracle that answers yes/no with a complication gradient, (2) explicit
scene-framing with twist injection, (3) a momentum/luck economy, (4) clocks for long-term goals, (5) lists
(threads/NPCs) giving randomness context. An LLM replaces exactly the interpretation step these tools punt to the
player — the core synergy of this project.

## Q2 — Powered by the Apocalypse: claims verified (with one correction)

Core claims **mostly confirmed**: 2d6+stat; 6- miss / 7-9 partial / 10+ full; stats typically -1..+3; moves =
triggered discrete rules ("when you X, roll+Y"). **Correction: partial success is ~33–44%, not ~58%.** Verified
table (2d6): at -1: 58% miss/33% partial/8% full; +0: 42/42/17; +1: 28/44/28; +2: 17/42/42; +3: 8/33/58 full.
The partial band is deliberately flat — stat growth shifts miss→full, partials stay the narrative engine.
Sources: gauntlet-archive.github.io (PbtA d10 thread) ; troypress.com/probabilities-of-2d6-compared-to-d6-dice-pools.

**License:** Bakers' policy (apocalypse-world.com/pbta/policy): mechanics are free (not copyrightable); verbatim
text needs permission; credit "appropriate and sufficient"; logo by permission. Mechanics reuse is legally safe.
**Open text options:** PbtA Commons (troypress.com/the-pbta-commons) catalogs CC releases — Dungeon World full
text is CC-BY-3.0 (fantasy). Sci-fi specifically: **Offworlders (Wolf & Gulin), a Traveller-flavored WoDu hack,
widely reported as CC-BY-4.0 — verify on itch.io before verbatim reuse**; Uncharted Worlds has an author-blessed
open/hack-friendly SRD but no formal CC grant (verify); The Sprawl is NOT open. Safe route: write your own move
text (moves are short and functional), borrow CC-BY text only where useful.

## Q3 — Alternative systems evaluated

**Cepheus Engine:** OGL (all SRD text is Open Game Content) + Compatibility-Statement License, perpetual &
irrevocable; modified standalones labeled "House Rules"; can't sell unchanged copies. Solid legal ground.
Mechanically binary pass/fail 2D6 (8+), so partial-success texture must be invented; heavy simulation subsystems
(career chargen, trade, world-gen) are high-code, low-narrative-yield under an LLM. Sources: orffenspace.com/cepheus-srd/legal.html.
**Stars Without Number:** free PDF edition; 2d6+skill+attr vs DC (binary); text NOT openly licensed (fan policy
covers free-edition fan works); mechanics reusable. Its superb GM tools (tags, generators) are worth mining as
LLM world-gen prompt structures. **Mothership:** d100 roll-under + stress/panic; 3rd-party license is
supplement-oriented; horror-specific; binary outcomes — poor narrative gradient, great engine simplicity.
**Year Zero Engine:** Free Tabletop License is royalty-free/irrevocable BUT v1.1 restricts formats to print/PDF/VTT
and **explicitly excludes video games** + adds a gen-AI disclosure clause — disqualified for this project.
**Forged in the Dark:** CC-BY-3.0, non-viral; d6-pool highest-die gives the same 1-3/4-5/6 three-tier contract;
**progress clocks are the cleanest deterministic state object to hand an LLM**; low solo fit as-written.
Sources: bladesinthedark.com/licensing ; freeleaguepublishing.com/community-content/free-tabletop-licenses.
**Mongoose Traveller:** 1e SRD (OGL) is what Cepheus derives from; 2e is closed; current "Traveller Compatible"
license is supplement-only. Do not build on Mongoose. **Classic Traveller:** NOT public domain (Internet Archive
uploads notwithstanding); FFE copyright, $35 CD-ROM, fan policy revocable on 90 days' notice — avoid as foundation.

## Q4 — Open-source foundations

- **xdy/twodsix-foundryvtt** — Cepheus-family 2D6 system in TypeScript; code Apache-2.0, content OGL. Best existing
  reference implementation of the Cepheus resolution/chargen logic. github.com/xdy/twodsix-foundryvtt
- **orffen/cepheus-srd** — CE SRD in HTML; code public domain (Unlicense).
- **rsek/dataforged + rsek/datasworn** — Starforged/Ironsworn moves, oracles, assets as typed JSON + TS API;
  content CC-BY-4.0. Directly harvestable oracle/move data — the single most valuable dataset for this project.
- Digital Ironsworn to study: ben/foundry-ironsworn, iron-vault-plugin/iron-vault (Obsidian), scottbenton
  Iron-Fellowship/Iron-Link (web app, solo-first UX).
- CYOA runtimes: **ink by Inkle — MIT**, embeddable, proven in commercial games (80 Days) — best fit; Twine GPLv3
  (copyleft caution; story output unaffected); ChoiceScript proprietary, non-commercial only — avoid.
- Dice/rules libs (TS): randsum.dev, greenimp rpg-dice-roller, risadams/dice-roller. Dice are trivial; the real
  asset to build is the move/oracle/clock state machine, which no library provides.

## Q5 — CYOA/IF design precedents: choice granularity

ChoiceScript community norm (choicescriptdev wiki): **2–4 options per choice node is the standard**; CoG's own
guidance: every option must change state, reveal information, express character, or create tension — else cut it;
nested option counts explode authoring complexity exponentially. AI Dungeon's lesson (2019–2021): pure free-text
input causes coherence drift and decision paralysis; players flounder without affordances. Synthesis for this
project: **present 2–4 LLM-generated structured options (each pre-mapped by the engine to a move + stat + risk),
plus one free-text "something else" slot the LLM classifies into an existing move** — engagement of structure with
an escape valve for agency.

## Comparison table — candidate base systems

| System | License (digital product OK?) | Code complexity | Narrative fit (partial-success → LLM) | Solo fit |
|---|---|---|---|---|
| Cepheus Engine (2D6) | OGL+CSL, irrevocable. Yes | Med-high (careers, trade, combat, world-gen) | Low — binary; tiers must be invented | Med — proven via SOLO (commercial concepts) |
| PbtA core (2D6+stat) | Mechanics free; write own text. Yes | Low (stats, moves, harm) | Excellent — 3-tier, 33-44% partial band | Med — needs oracle layer bolted on |
| Starforged/Ironsworn | CC-BY-4.0 (Ref Guide/SRD/Dataforged). Yes | Medium (moves, momentum, tracks, oracles) | Excellent — strong/weak/miss + clocks | Excellent — built for it |
| SWN (2D6) | Text closed; mechanics reusable. Caution | Med-high (full trad chassis) | Low — binary | Med — GM-tool goldmine |
| Mothership (d100) | 3P license, supplements-oriented. Verify | Low | Low — binary + panic | Med (horror only) |
| Year Zero Engine | FTL v1.1 **excludes video games**. No | Medium | Med (stunts, push) | Low-med |
| Forged in the Dark | CC-BY-3.0. Yes | Medium (pools, position/effect, clocks) | Excellent — 3-tier + clocks | Low (crew/GM-assumed) |
| Classic Traveller | FFE copyright, fan policy revocable. No | Low | Low | Historical only |

## Recommendation

**Reject "Cepheus as the resolution engine." Adopt a Starforged-style PbtA core (2d6+stat, strong/weak/miss) as
the player-facing contract, with FitD/Starforged progress clocks and a Mythic-style Chaos Factor as deterministic
state, and keep Cepheus only as optional simulation/setting texture (career-flavored chargen, world/trade tables
for the LLM to narrate over).** Rationale: the LLM's job is narrating graded outcomes; a three-tier roll is the
exact interface for that, and binary 2D6 8+ forces you to invent complication machinery anyway — so the "Cepheus
hybrid" converges to PbtA regardless. License-wise this stack is maximally safe: PbtA mechanics free, Starforged
CC-BY-4.0, FitD CC-BY-3.0, ink MIT. If Traveller flavor is load-bearing for the audience, layer Cepheus chargen
and skill names on top (OGL-safe) — flavor, not engine. Zozer SOLO's "Plan" (fortune-in-the-middle) is the right
scene-resolution pattern to copy conceptually for CYOA nodes: declare intent → engine rolls → LLM narrates.
