# LLM Game-Master Architectures — State of the Art (July 2026)

Scope: LLM-powered CYOA sci-fi RPG, deterministic rules engine underneath, LLM narrates only. Solo dev, Python-leaning.

## 1. Academic research on LLM game masters

**arXiv:2502.19519 verified** — "Static Vs. Agentic Game Master AI for Facilitating Solo Role-Playing Experiences" (Jorgensen et al., Aalborg Univ., Feb 2025, v2 Mar 2025; CUI 2025). Real paper. System: **ChatRPG**.
- V1 (static): GPT-4 via stateless API, all state as one long string, three prompt types (Do/Say/Attack), JSON responses, full history appended every call.
- V2 (agentic): multi-agent ReAct on LangChain — **Narrator** (player-facing, tools: WoundCharacter, HealCharacter, Battle) + **Archivist** (background "memory core", tools: UpdateCharacter/UpdateEnvironment persisting world state to a DB).
- Findings: v2 maintains play while significantly improving modularity and player experience (immersion, curiosity on PXI). Splitting narration from state-tracking also fixed a latency problem. Few-shot examples in prompts *and tool descriptions* mattered more than ReAct structure itself; prompts are extremely sensitive to example wording.
- https://arxiv.org/abs/2502.19519 · code: https://github.com/KarmaKamikaze/ChatRPG

**Other key papers (2023-2026):**
- arXiv:2409.06949 "…Enhancing AI Game Masters with Function Calling" — validates tool calls as the mechanism for LLM GMs to read/write game state.
- arXiv:2504.07304 PAYADOR — grounding LLMs on structured world data for interactive storytelling/RPGs (minimalist structured-state approach).
- MDPI Systems 14(2):175 (2026) — schema-governed LLM pipeline: LLM emits JSON-only output → deterministic normalization/validation → engine executes. Quest state machines enforced in code. https://www.mdpi.com/2079-8954/14/2/175
- CALYPSO (arXiv:2308.07540, AIIDE) — LLMs as DM *assistants* for human GMs, not autonomous GMs.
- "Guiding, Not Railroading" (IUI 2026, ACM 10.1145/3742413.3789218) — multi-agent narrative redirection; agentic steering without breaking agency.
- arXiv:2606.21666 (2026) — hallucination as context drift: naive full-broadcast state sharing between agents *increases* hallucination 34%; use curated/synced views, not firehose sharing.
- GTBench — LLMs systematically fail at strict rule execution → lock mechanics in deterministic code.

**Consensus architecture:** hybrid — "LLM handles semantic judgment, deterministic code handles mechanical judgment." Multi-agent (narrator/rules-oracle split) improves modularity and immersion, but a single narrator + engine tools is the validated minimal form.

## 2. Context management for long campaigns

Five strategies and tradeoffs (machinelearningmastery.com/context-window-management-for-long-running-agents-strategies-and-tradeoffs/):
- Sliding window: cheap, causes "digital amnesia" + repeated loops.
- Recursive summarization: preserves arc, loses detail ("blurry JPEG").
- Structured state scratchpad (JSON goals/facts): token-efficient; anything outside schema is invisible.
- RAG over logs: scales, but misses cross-connections between events.
- Dynamic model routing: cheap model routine / big model on escalation; routing logic is brittle.

**What works in practice (convergent evidence):** layered stack — (a) engine-held structured state as canonical spine, injected fresh each turn (curated view, not full history — ChatRPG v1's append-everything failed; 2606.21666 says over-sharing hurts); (b) rolling chapter summaries for narrative continuity (AI Dungeon's auto-summarization + Memory Bank; F&F snapshots memory every 5 turns and searches it into working context — still suffers drift); (c) RAG for lore/codex lookup only. Practitioner rule (Xebia Claude-DM blog): "memory lives on disk, not in the model; don't let the model be the source of truth."

## 3. Preventing LLM cheating / drift

Documented platform failures show the stakes: AI Realm applied a player's STR mod to enemy damage, got AC wrong, ignored nat-1 auto-fail; F&F had an NPC both dead and alive; AI Dungeon improvises rolls entirely. Patterns that work:
- **Engine-resolves-everything**: dice rolled in code, outcome injected as fact for the LLM to narrate. NarrativeEngine-P pre-rolls d20 pools ("Dice Fairness") so the GM can never fabricate results. RoleForge markets "a deterministic rules engine the AI cannot override."
- **Tool-call-only mutations**: LLM may only change state via validated function calls (ChatRPG v2 tools; MCP-based rpg-mcp-servers; MDPI schema pipeline rejects invalid output before engine execution).
- **Structured output validation**: JSON-schema/Pydantic contract per response; invalid → reject/regenerate.
- **Retire LLM judgment for mechanics**: DungeonGPT explicitly removed AI adjudication of milestones in favor of engine-refereed outcomes, AI narrates only.
- **Assume failure, build guardrails** (Xebia): reconciliation ledger (canon vs. table events), two-layer output (what GM *knows* vs. *says* — fixes secret-keeping), catch-list of corrections.
- Evidence base: GTBench (LLMs can't reliably execute rules); 2606.07937 (hallucination cascades in agent chains — keep chains shallow).

## 4. Commercial platforms (mid-2026)

"None have a real rules engine" is **no longer accurate** — but it's true of the biggest incumbents.
- **AI Dungeon (Latitude)**: pure LLM freestyle — "no character sheet, no enforced dice mechanics, no rules engine." Memory = trimming + Story Cards + Memory Bank; long-campaign drift is the top user complaint. Successor **Voyage** in expanded beta (Apr 2026). help.aidungeon.com, dungeonsdeep.ai/blog/ai-dungeon-review-2026
- **Friends & Fables (Franz)**: 5e-inspired; reports conflict — dungeonsdeep says rules run through the LLM (combat disabled during revamp), arcanumrpgs credits it with 5e tactical combat under the hood. Memory snapshot every 5 turns; documented drift bugs.
- **AI Realm**: chat-first, 5e SRD through the LLM, no engine; Player's Guide admits "if it's not in your Notes, the AI will eventually forget it."
- **RoleForge**: claims real dice + deterministic rules engine AI cannot override; young, small content library.
- **DungeonsDeep.ai**: "a rules engine running a game with an LLM narrating it," server-side dice, VTT + battle map; closed beta.
- **Craft RPGs**: "Roblox for AI RPGs" — build your own rules/files/sheets; Orbit AI worldbuilding assistant (craftrpgs.com, May 2026).
- **Hidden Door**: alive — launched 2025 (Variety), licensed fan-fiction worlds, blog active into 2026; narrative-first, no public evidence of a deterministic engine.
- Roundups: dungeonsdeep.ai/blog/the-best-ai-game-masters-compared-in-2026 · arcanumrpgs.com/blog/llm-rpg-games/

**Gap confirmed:** the market leaders are LLM-freestyle with bolted-on memory; engine-under-LLM is the differentiator only newer/small entrants pursue. Your architecture is the validated gap.

## 5. Open-source projects worth learning from

- **KarmaKamikaze/ChatRPG** (C#) — the academic reference impl; prompts + tool patterns in-repo.
- **Sagesheep/NarrativeEngine-P** — self-hosted DM: Divergence Register (fact sheet w/ knownBy scoping), pre-rolled dice pools, tool-call lore/state. Closest to your design.
- **EdwardAThomson/DungeonGPT + DungeonGPT-JS** — GPT-4o DM, save/load, RAG memory; lesson: retired AI judgment for engine-refereed outcomes.
- **JoeCotellese/rpggame** — Python terminal game: D&D 5E SRD engine + LLM narrative layer (direct stack match).
- **kdai11830/ll-dm** — SQL DB + function calling for indefinite long-term memory (MIDS capstone).
- **Mnehmos/rpg-mcp-servers**, **LoreKit**, **native-gaming-harness** — MCP/tool-use TTRPG engines; the latter's docs/references.md is a curated reading list.
- **Xebia blog** "Building a D&D DM Out of Claude" — best failure-mode writeup (world misreporting, secret leakage, character drift) with fixes.
- Common themes: externalize all state; JSON/tool-call I/O; separate narration from state mutation; assume the model fails and ledger everything.

## 6. Python LLM stack currency check (mid-2026)

- **Instructor**: still a valid, actively-referenced standard for structured output (15+ providers natively, 100+ via LiteLLM; validation + retries). Thin layer, no agent loop.
- **Pydantic AI**: hit v1.0 Sept 2025, **v2.0 June 2026** ("capabilities-first"); the current pick for typed single-agent loops + tools. (agenticwire.news, ianas.fr comparisons)
- **LangGraph**: still recommended for stateful/branching/checkpointed multi-agent workflows (1.2.x, active); overkill for a single-narrator loop.
- **LiteLLM**: still the most-used multi-provider gateway BUT **March 2026 supply-chain compromise** — PyPI 1.82.7/1.82.8 exfiltrated credentials (netspi.com writeup). Pin/audit versions, or use OpenRouter / Bifrost / Vercel AI Gateway instead.
- **Native structured outputs** (OpenAI json_schema response_format, Anthropic tool use) increasingly replace Instructor when single-provider.
- Alternatives: Outlines/XGrammar (constrained decoding, self-hosted), BAML (cross-lang schemas), DSPy.
- **TypeScript path is viable**: Vercel AI SDK v5 + AI Gateway (GA Aug 2025, zero markup, native streaming + Zod structured output) is the TS standard; strong fit if streaming UX is a priority.
- Avoid: AutoGen (maintenance mode since Q1 2026; community fork AG2), Helicone (maintenance mode).

## What this means for a solo-dev MVP

1. **Architecture**: single narrator agent + deterministic engine. Engine owns dice, state, calculations; LLM gets a curated state view + tool definitions, narrates outcomes only. This is the academically validated (2502.19519 v2 minus the second agent) and market-gap architecture. Add an Archivist-style background agent only if state-update latency shows up.
2. **Anti-drift**: all mutations via Pydantic-validated tool calls; dice pre-rolled by the engine and injected as facts; reject-and-retry on invalid structured output. Skip prompt-based honesty — it demonstrably fails (AI Realm, F&F).
3. **Memory**: canonical JSON state (engine) + rolling chapter summaries + RAG over lore/codex. Never append full history. This mirrors what the platforms converged on, minus their drift.
4. **Stack**: Python — Pydantic AI v2 (agent loop + tools + validation in one) or raw provider SDK + Instructor; provider-direct structured outputs; avoid LiteLLM or pin it hard. Add LangGraph only if you grow real multi-agent branching. TypeScript + Vercel AI SDK is a legitimate alternative if streaming-first web UX outweighs the Python ecosystem.
5. **Reference before building**: read ChatRPG's prompts/tool descriptions (github.com/KarmaKamikaze/ChatRPG) and NarrativeEngine-P's Divergence Register + dice-fairness pattern; both are directly liftable designs.
