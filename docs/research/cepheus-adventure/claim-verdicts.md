# Claim Verdicts — Cepheus Product Contract (verified independently, 2026-07-28)

Each claim verified against live/archived web sources, not the dossiers.

## 1. Cepheus Engine SRD — OGL, all text OGC, free online mirrors — CONFIRMED (one nuance)
- Both mirrors are live and host the full SRD:
  - https://evolvedexperiment.github.io/cepheus-srd/ (mdBook)
  - https://orffenspace.com/cepheus-srd/ (HTML)
- Both state verbatim: "All of the text in this document is designated as Open Gaming Content" under the Open Gaming License, "except for the titles of products published by Samardan Press, and the trademarks 'Cepheus Engine' and 'Samardan Press'". Copyright 2016 Samardan Press, Jason "Flynn" Kemp; built on the Traveller SRD OGC.
- Nuance: "all text is OGC" carries the standard Product Identity carve-out for the two trademarks — compatibility use requires Samardan's separate trademark license, not the OGL alone.

## 2. Cepheus Quantum — ~2-page micro-game, CC BY-SA 4.0, Stellagama — CONFIRMED (one nuance)
- DriveThruRPG product 280143 (Cepheus Quantum Revised Edition, Stellagama Publishing, free): "Re-released under the Creative Commons Attribution-ShareAlike 4.0 International License (CC BY-SA 4.0)". Single two-sided sheet (2 pages); 2d6 + skill vs 4+/6+/8+/10+.
- https://legacy.drivethrurpg.com/product/280143/Cepheus-Quantum-Revised-Edition
- Full text with CC BY-SA legal statement mirrored at https://frank-mitchell.com/rpg/cepheus-quantum/
- Nuance: the CC BY-SA 4.0 license applies to the Revised Edition (2019); the original 2018 edition was released under the OGL.

## 3. Cepheus Light / Deluxe / Universal / Hostile — commercial, no free/open SRD — CONFIRMED (two nuances)
- None of the four has a free, openly licensed full-text SRD online. All are commercial books (Stellagama for Light/Deluxe; Zozer Games for Universal/Hostile). The only free open text in the family remains the CE SRD itself (orffenspace/evolvedexperiment mirrors) and Quantum.
- Nuance A: Cepheus Light is Pay-What-You-Want, so the full text can be obtained at $0 — but it is not open-licensed (a paid "editable version" for publishers is sold separately, DTRPG product 260927).
- Nuance B: Cepheus Universal has an official stripped SRD, but it is a paid product (~$6.99, DTRPG product 496014) with a compatibility license — not free text.
- Hostile's setting is declared Product Identity by Zozer.
- Sources: https://www.zozergames.com/cepheus-universal.html , https://www.drivethrurpg.com/ko/product/496014/cepheus-universal-srd , https://www.drivethrurpg.com/en/product/260927/cepheus-light-editable-version

## 4. Starforged Reference Guide/SRD + dataforged JSON — CC BY 4.0, commercially reusable — CONFIRMED (one nuance)
- Shawn Tomkin's official post "Let's Talk About Ironsworn Licensing" (tomkinpress.com): the Ironsworn SRD and "the entirety of the text in the Starforged Reference Guide, which includes moves, rules summaries, and oracles" are CC BY 4.0 for commercial use; the full rulebook text is CC BY-NC-SA 4.0 (non-commercial). Corroborated by ironswornrpg.com/licensing pointers in iron-vault LICENSE.md and RoleForge's attributions page.
- https://tomkinpress.com/blogs/news/lets-talk-about-ironsworn-licensing
- rsek/dataforged LICENSE.md: Markdown/JSON/YAML data + SVG icons = CC BY 4.0 (text "originally from the Ironsworn: Starforged Reference Guide"); code = MIT.
- https://github.com/rsek/dataforged/blob/main/LICENSE.md
- Nuance: dataforged's legacy `ironsworn` subdirectory preview JSON and raster images are CC BY-NC 4.0 — harvest the Starforged data, not the legacy Ironsworn preview, for commercial use.

## 5. PbtA mechanics free (Bakers' policy, credit appreciated); AW text not open — CONFIRMED
- From the Bakers' own policy page (live site snapshot archived 2026-06-14; current apocalypse-world.com has a broken TLS cert but identical content):
  "If you've created a game inspired by Apocalypse World, and would like to publish it, please do. If you're using our words, you need our permission, per copyright law. If you aren't using our words, you don't need our permission... we consider it appropriate and sufficient for you to mention Apocalypse World in your thanks, notes, or credits section." PbtA logo by permission only.
- Source: https://web.archive.org/web/20260614061424/https://apocalypse-world.com/pbta/policy
- Matches claim: mechanics (not their words) freely usable; credit expected; the book text itself is not open-licensed.

## 6. Free League Year Zero Engine Free Tabletop License v1.1 excludes video games — CONFIRMED
- YZE FTL version 1.1 (dated March 31, 2026), Section 1: grants rights to distribute the YZE SRD "in printed form, as a PDF, or as a virtual tabletop module ('VTT')... VTTs do not include NFTs or video games, only virtual tabletop modules."
- Section 3 also adds a generative-AI disclosure requirement.
- Source (PDF read directly): https://freeleaguepublishing.com/wp-content/uploads/2026/03/Year-Zero-Engine-License-Agreement-version-1.1.pdf
- Listed at: https://freeleaguepublishing.com/community-content/free-tabletop-licenses/

## 7. twodsix FoundryVTT system is Apache-2.0; other open CE/Traveller chargens exist — CONFIRMED
- https://github.com/xdy/twodsix-foundryvtt — "Twodsix — Cepheus & Traveller (Unofficial)" FoundryVTT system, Apache License v2 (TypeScript; game content OGL-derived).
- Open-source chargen/generator projects confirmed on GitHub:
  - https://github.com/justinaquinoGITB/cechargen (Cepheus Engine lifepath chargen, JS)
  - https://github.com/pgorman/travellercharactergenerator (Classic Traveller, BSD-2-Clause)
  - https://github.com/kari/traveller-chargen (TypeScript, MPL-2.0)
  - https://github.com/Golan2072/CTMassChargen (Python), https://github.com/makhidkarun/worldgen (CE world gen)

## 8. ink (inkle) is MIT-licensed — CONFIRMED
- https://github.com/inkle/ink — "inkle's open source scripting language for writing interactive narrative", MIT license.

## 9. ChoiceScript license terms — CONFIRMED (source-available, NOT open source)
- Repo: https://github.com/dfabulich/choicescript under the "ChoiceScript License (CSL) v1.0".
- Terms: non-commercial usage and modification permitted (keep license text with the project); the interpreter may not be used "for any commercial purposes, including sales of complete applications, or to generate advertising revenue". Commercial use requires a separate commercial license from Choice of Games (support@choiceofgames.com).
- Practical answer: you can build and freely distribute non-commercial ChoiceScript games (self-hosting OK); commercial games must be licensed from/published through Choice of Games (incl. the Hosted Games label). It is not OSI open source.

## 10. arXiv 2502.19519 agentic vs static GM paper — CONFIRMED
- "Static Vs. Agentic Game Master AI for Facilitating Solo Role-Playing Experiences" — Jørgensen, Tharmabalan, Aslan, Hansen, Merritt (Aalborg University). System: ChatRPG. v1 static prompt engineering; v2 multi-agent ReAct (Narrator + Archivist with state-mutation tools).
- Finding as claimed: v2 "maintains play while significantly improving modularity and game experience, including immersion and curiosity" (PXI measures).
- https://arxiv.org/abs/2502.19519 (code: https://github.com/KarmaKamikaze/ChatRPG)

## 11. LiteLLM supply-chain compromise ~March 2026 — CONFIRMED
- On March 24, 2026, LiteLLM 1.82.7 and 1.82.8 were published to PyPI with credential-stealing malware (harvested LLM API keys, AWS/SSH/K8s creds; K8s lateral movement; persistent backdoor via systemd + `litellm_init.pth`). Root cause: TeamPCP compromised the Trivy GitHub Action in LiteLLM's CI/CD and stole PyPI publishing tokens. Cleaned up in v1.83.0. Directly justifies version pinning/auditing.
- Sources: https://www.halborn.com/blog/post/explained-the-litellm-hack-march-2026 , https://www.kunalganglani.com/blog/litellm-supply-chain-attack-pypi , https://labs.cloudsecurityalliance.org/research/csa-research-note-litellm-cve-2026-42271-ai-gateway-exploita/

## 12. Mid-2026 Python structured-output stack (Pydantic AI v2, Instructor, LangGraph) — CONFIRMED
- Pydantic AI: v1.0 Sept 2025; v2.0 released June 23, 2026 ("capabilities-first" harness redesign; v2.12.0 by mid-July 2026). https://pydantic.dev/docs/ai/project/version-policy/ , https://github.com/pydantic/pydantic-ai/releases
- Instructor: still an actively integrated standard for validated structured output across providers (JSON mode + tools mode). https://dev.writer.com/home/integrations/instructor
- LangGraph: recommended for checkpointed/cyclic/stateful multi-agent orchestration; overkill for a single-agent loop (framework comparisons and Pydantic's own multi-agent guidance agree). https://www.speakeasy.com/blog/ai-agent-framework-comparison/ , https://pydantic.dev/docs/ai/guides/multi-agent-applications/
