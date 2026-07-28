# Cepheus Engine Ecosystem — Verification Dossier (2026-07-28)

Purpose: verify claims for an LLM-GM CYOA project with a deterministic rules engine. Verdicts: CONFIRMED / NUANCED / REFUTED.

## Claim 1 — Identity & core mechanic: CONFIRMED
- Cepheus Engine (CE) by Jason "Flynn" Kemp, Samardan Press, released July 2016 as a free/PWYW 208-page SRD on DriveThruRPG.
- OGL 1.0a retro-clone built from the Mongoose Traveller 1e SRD (2008) plus T20/d20 Modern OGC; created in response to Mongoose's restrictive Traveller 2e licensing. Third Imperium setting stripped (Marc Miller/FFE IP).
- Core mechanic verbatim from SRD: roll 2D6 + skill levels + characteristic DM + difficulty DM; total >= 8 succeeds.
- Sources: stargazersworld.com/2016/11/15/a-look-at-the-cepheus-engine/ ; github.com/orffen/cepheus-srd ; cepheus-srd.opengamingnetwork.com ; rockymountainnavy.com/2016/10/15/travellerrpg-cepheusengine-system-reference-document/

## Claim 2 — Variants: mostly CONFIRMED, two nuances
- CE SRD/Core (Samardan, 208pp, free SRD online): CONFIRMED.
- Cepheus Light (Stellagama, simplified): CONFIRMED w/ page nuance — original 2018 book is ~218pp; "Cepheus Light Upgraded" (2021) is 118pp, matching "~110pp". PWYW on DriveThruRPG. drivethrurpg.com/en/product/257644
- Cepheus Deluxe (Stellagama, 2021): CONFIRMED. Replaces characteristic damage with Stamina (END + Athletics) / Lifeblood (2x Stamina) pools; adds Traits (Advantage), Hero Points, and player-directed/point-buy-style chargen (assign stats, choose careers/skills). Source: rockymountainnavy.com/2021/11/21/cepheus-deluxe-stellagama-publishing-2021-the-new-heroic-travellerrpg/
- Cepheus Universal (Zozer Games / Paul Elliott, 2024, 443pp): CONFIRMED. Sources: rockymountainnavy.com/2024/10/06/...cepheus-universal... ; gmshoe.wordpress.com/2025/05/10/qa-paul-elliott...
- Cepheus Quantum (Stellagama, ultra-lite, Stamina): CONFIRMED but page count REFUTED — it is 2 pages (one sheet, two sides), not ~30pp. Revised Edition (June 2019) free on DTRPG (product 280143); a PWYW "Quantum SRD" companion exists. Stamina = 12 + 2xPhysical. Difficulty: Easy 4+ / Average 6+ / Difficult 8+ / Formidable 10+.
- Hostile (Zozer, Alien/Outland/Blade Runner blue-collar horror on CE): CONFIRMED. Setting is commercial Product Identity.

## Claim 3 — Licensing: CONFIRMED with critical distinctions
- CE SRD: "All of the text in this document is designated as Open Gaming Content" except the trademarks "Cepheus Engine" and "Samardan Press" (Product Identity). Separate trademark license permits compatibility statements. Verified LIVE on all claimed mirrors:
  - orffenspace.com/cepheus-srd/ — full SRD, live (github.com/orffen/cepheus-srd)
  - evolvedexperiment.github.io/cepheus-srd/ — full SRD as mdBook (conv. Steve Simenic), live
  - cepheus-srd.opengamingnetwork.com — full SRD incl. Trade & Commerce, Worlds, Ship Design, live
- Stellagama (Light/Deluxe): commercial books (Light is PWYW; paid "editable versions" sold for publishers). No free full-text online SRD found; stellagama.com did not respond during research. Rules text derived from CE OGC remains OGC by OGL flow-down, but new text/presentation is closed — you cannot treat these books as open SRDs.
- Cepheus Quantum: CC BY-SA 4.0 (per frank-mitchell.com/rpg/cepheus-quantum/ hosting the full rules text) — the most permissive license in the family, and free.
- Zozer (Universal/Hostile): commercial books only. Zozer declares CE-derived mechanics OGC, names/setting/companies PI; some Hostile supplements declare zero OGC. No free CU/Hostile SRD. zozergames.com / paulelliottbooks.com.
- Key distinction (as requested): only CE SRD (OGL) and Cepheus Quantum (CC BY-SA) are usable as open text bases. Light/Deluxe/Universal/Hostile full texts are commercial-only.

## Claim 4 — Core mechanics: mostly CONFIRMED
- Characteristic DM table: CONFIRMED w/ nuance — standard table is 0:-3, 1-2:-2, 3-5:-1, 6-8:+0, 9-11:+1, 12-14:+2, 15-17:+3 (claim's "12+ -> +2" holds to 14; 15+ is +3).
- Difficulty ladder: NUANCED — CE SRD uses fixed target 8+ with difficulty DMs: Routine +2, Average +0, Difficult -2, Very Difficult -4, Formidable -6 (effective raw 6+ to 14+; no "Impossible 16+" tier in core SRD). The "Routine 6+ to Impossible 16+" framing is the Mongoose target-number style; mathematically equivalent.
- Lifepath: CONFIRMED — 24 careers, 4-year terms, per-career survival rolls, natural 2 always fails, death on failed survival (optional Survival Mishaps table keeps character alive).
- Combat: CONFIRMED, very lethal — first injury applied to END, then STR or DEX (player choice); armor absorbs; two characteristics at 0 = unconscious; all three at 0 = dead.
- Skills: CONFIRMED — ~60 skills (~68 list entries incl. cascades); "~50+" is conservative.
- Trade system: CONFIRMED (Trade and Commerce chapter). UWP world generation: CONFIRMED (Worlds chapter).

## Claim 5 — Digital implementations: CONFIRMED
- FoundryVTT "Twodsix - Cepheus & Traveller (Unofficial)": github.com/xdy/twodsix-foundryvtt — actively maintained, OGL-derived, implements CE Core + variant rulesets; listed on foundryvtt.com/packages/twodsix. Best reference implementation for a deterministic engine.
- Mongoose's own official system: github.com/Mongoose-Publishing/traveller-foundryvtt (separate, non-CE).
- SRD-as-code: github.com/orffen/cepheus-srd (HTML), evolvedexperiment mdBook; github.com/orffen/cepheus ("Cepheus Engine Toolbox", JS utilities).
- Chargens/generators: github.com/justinaquinoGITB/cechargen (CE lifepath), pgorman/travellercharactergenerator and kari/traveller-chargen (Classic Traveller), carloscasalar/traveller-npc-generator, makhidkarun/traveller_pyroute (trade routes), Golan2072/CTMassChargen; bluesunconsulting.com/traveller/cechargen.html (web CE chargen).

## License summary table
| Variant | Publisher | Year/Pages | License | Free text online? |
|---|---|---|---|---|
| CE SRD / Core | Samardan Press | 2016 / 208pp | OGL 1.0a; all text OGC except 2 trademarks | YES — 3 live mirrors + GitHub |
| Cepheus Quantum | Stellagama | 2019 / 2pp | CC BY-SA 4.0 | YES — DTRPG free + blog full text |
| Cepheus Light / Upgraded | Stellagama | 2018/2021 / 218pp/118pp | OGL-derived OGC inside; book commercial (PWYW) | NO full SRD |
| Cepheus Deluxe | Stellagama | 2021 | OGL-derived OGC inside; book commercial | NO full SRD |
| Cepheus Universal | Zozer Games | 2024 / 443pp | OGL-derived OGC inside; book commercial | NO full SRD |
| Hostile | Zozer Games | 2017+ | Setting = Product Identity, commercial | NO |

## Recommendation for the CYOA rule-set module
FIRST MODULE: Cepheus Engine SRD (Core). Rationale:
1. Licensing is the strongest in the family: entire text is OGC under the perpetual OGL 1.0a; only the "Cepheus Engine"/"Samardan Press" names are barred (use a compatibility statement per Samardan's trademark license; keep OGL Section 15 notices in-product).
2. Mechanics are single-resolution (2D6 + DM >= 8) and table-driven (lifepath, trade, UWP) — trivially deterministic and encodable; proven by the open-source twodsix Foundry system and CE chargens, which double as reference code.
3. Complete game (characters, combat, trade, worlds, starships) with real depth for an LLM GM to narrate; adopt Book 1 only for v1.
4. Zero acquisition cost; canonical text fetchable today from orffenspace / evolvedexperiment / opengamingnetwork mirrors.
OPTIONAL v0 PROTOTYPE: Cepheus Quantum (CC BY-SA 4.0, 2pp, 6 skills, target numbers 4+/6+/8+/10+, Stamina HP pool) if you want the absolute minimal engine to validate the LLM-GM loop; its HP-pool damage is also kinder to CYOA players than CE's lethal stat-depletion.
AVOID as text basis: Light/Deluxe/Universal/Hostile — commercial books without open SRD text (reimplement only inherited OGC mechanics if ever needed; Deluxe's Stamina/Lifeblood idea is worth borrowing as a house rule via its OGC derivation).
CAVEATS: OGL products must ship the OGL text + Section 15; never use Mongoose/FFE "Traveller" trademarks; get a legal pass before commercial release. Stellagama/zozergames.com pages partially unreachable during research — recheck before citing their terms.
