# P2 Product Polish And Scale Plan

Date: 2026-06-07

This document tracks the product and scale tier after P0 cleanup and P1 runtime hardening. P2 focuses on making the system feel coherent to use, cheaper to operate, and easier to extend.

## Goal

Turn the current research-grade agent system into a polished learning product:

```text
clear mode UX
-> stable background analysis
-> readable learning artifacts
-> inspectable memory graph
-> cost-aware agent execution
-> extensible tools and channels
```

## Checklist

- [x] 1. Improve WebUI graph and learning artifact navigation.
- [x] 2. Formalize the tool layer for agentic subagents.
- [x] 3. Add cost, token, and model governance.
- [x] 4. Add data lifecycle controls for test data, user data, and exports.
- [x] 5. Add browser-level smoke tests for core user journeys.
- [x] 6. Prepare channel expansion surfaces.

## Task 1: WebUI Graph And Artifact Navigation

Current state:

- Wiki graph has a hierarchy mode and a global overview mode.
- The graph is better than the original force-only view, but it still needs stronger navigation and learning-context affordances.

Work:

- Add graph entry modes:
  - all knowledge
  - topic
  - subtopic
  - entity
  - concept
  - session
- Add stable layout persistence:
  - Cache node positions by graph scope.
  - Avoid layout jumps when hovering or selecting.
- Add graph filtering:
  - Mode: `freechat`, `ielts`, `benative`
  - Memory status: `confirmed`, `uncertain`, `stale`
  - Type: entity, concept, source, synthesis, question, decision, gap
- Add artifact navigation:
  - One panel for `vocab`, `polisher`, `review`, `quiz`, and `notes`.
  - Mode-specific tabs:
    - Freechat: vocab, polisher
    - Be Native: review
    - IELTS: feedback, review, vocab, polisher
- Add empty states that explain the real cause:
  - no session
  - no new input
  - trigger disabled
  - processor failed
  - artifact not created yet

Done when:

- A user can answer "what did the system learn from this conversation?" without opening JSONL files.

Status:

- Done on 2026-06-07.
- Wiki graph nodes now carry `memory_status`, and `/api/wiki/graph` supports memory filters such as `confirmed`, `uncertain`, and `stale`.
- WebUI graph caches node positions by graph scope to reduce layout jumps when hovering, selecting, or changing focus.
- Wiki Memory panel exposes memory status filtering and page memory status badges.
- Session artifact empty states now explain likely causes: trigger disabled, no new input, processor failure, or artifact not created yet.
- Radix dialog/sheet accessibility warnings were cleaned up by using standard Title/Description components.

## Task 2: Agentic Tool Layer

Current state:

- `config/capabilities.yaml` defines tools such as `thread_query`, `artifact_read`, `user_profile`, and `wiki_query`.
- Agentic mode is registered, but tool execution should become a first-class layer.

Work:

- Define a tool interface:
  - name
  - description
  - input schema
  - output schema
  - permissions
  - timeout
  - audit log fields
- Add local tool implementations:
  - `thread_query`
  - `artifact_read`
  - `user_profile`
  - `wiki_query`
- Add test doubles:
  - Agentic subagent tests should not need real network or provider calls.
- Add future adapters:
  - MCP-style adapter
  - function-calling adapter
  - web search adapter

Done when:

- A subagent can switch between `api` and `agentic` execution modes from config, and the tool calls are visible in monitor logs.

Status:

- Done on 2026-06-07.
- Existing local subagent tools (`thread_query`, `artifact_read`, `user_profile`, `wiki_query`) remain loaded through `scope="subagent"` in `SubagentManager`.
- `config/capabilities.yaml` now formalizes each tool with description, input schema, output schema, permissions, timeout, and audit log fields.
- Validator now rejects incomplete tool contracts.
- Future adapter work remains a separate implementation track; the registry contract is now ready for MCP/function-calling/web-search adapters.

## Task 3: Cost, Token, And Model Governance

Current state:

- Most processor/subagent configs use `deepseek-v4-flash`.
- Monitor has some cost summary surfaces, but cost needs to become a first-class engineering control.

Work:

- Add model registry:
  - provider
  - model name
  - intended use
  - context window
  - input/output cost estimate
  - default max tokens
- Add per-run token accounting:
  - prompt tokens
  - completion tokens
  - cached tokens if available
  - estimated cost
- Add per-mode budget views:
  - Freechat daily cost
  - Be Native daily cost
  - Wiki sync daily cost
  - Cron/background cost
- Add safety limits:
  - max runs per session
  - max background cost per day
  - dry-run mode for processors
- Keep token-saving architecture visible:
  - Processor middleware extracts compact input.
  - LLM does not need to emit full user-facing JSON when deterministic post-processing can assemble final artifacts.

Done when:

- Monitor can answer "which model spent money, why, and which artifact did it produce?"

Status:

- Done on 2026-06-07.
- Model registry now includes provider, model name, intended use, context window, default max tokens, and input/cache/output cost estimates.
- Validator checks model governance fields.
- Admin monitor cost summary now includes per-mode aggregation with configured daily budget and usage percentage.
- `config/capabilities.yaml` defines daily and per-session budget controls plus processor dry-run env naming.

## Task 4: Data Lifecycle And Export

Current state:

- Runtime data lives mainly under `persona/`.
- Test data has been cleaned aggressively, but the project still needs explicit lifecycle controls.

Work:

- Add reset commands for development:
  - clear monitor logs
  - clear processor artifacts
  - clear wiki derived indexes
  - keep or clear user memory by explicit flag
- Add export commands:
  - export one session
  - export all learning artifacts for a mode
  - export wiki pages and sources
- Add privacy-oriented separation:
  - raw user events
  - derived learning artifacts
  - long-term memory
  - monitor observability logs
- Add backup / restore docs:
  - minimal user backup
  - full developer backup

Done when:

- The project can safely switch between demo/testing data and real user data.

Status:

- Done on 2026-06-07.
- Added `scripts/data_lifecycle.py` with conservative reset and export commands.
- Reset can clear monitor logs, processor artifacts, and wiki derived indexes while keeping user memory by default.
- `--clear-user-memory` is explicit for destructive user-memory cleanup.
- Added exports for one session, one mode's learning artifacts, and LLM Wiki pages/raw sources.
- Added `docs/data-lifecycle-and-export.md` with data classes, reset/export commands, and backup/restore boundaries.

## Task 5: Browser-Level Smoke Tests

Current state:

- Backend tests cover key processor and wiki behavior.
- WebUI still needs end-to-end smoke coverage.

Work:

- Add Playwright or browser smoke tests for:
  - WebUI bootstrap loads.
  - Freechat sends one user message and shows processor toast.
  - Be Native starts a fixed article and advances to the next sentence immediately.
  - Monitor shows processor/subagent run details.
  - Wiki graph endpoint returns nodes and links.
- Keep Bun as the WebUI package/runtime path.
- Add screenshots for graph and monitor regressions when possible.

Done when:

- A local smoke test catches broken bootstrap, missing JSON, or graph rendering regressions before manual testing.

Status:

- Done on 2026-06-07.
- Added `bot/webui/scripts/smoke-gateway.mjs` and `bun run smoke:gateway`.
- The smoke script checks bootstrap JSON, wiki graph nodes/edges shape, and admin monitor trigger arrays against a running gateway.
- Screenshot-level Playwright tests are still future polish; this smoke path catches the previous HTML-instead-of-JSON class of failure.

## Task 6: Channel Expansion Surfaces

Current state:

- WebUI is the main product surface.
- The architecture can later connect to WeChat, Feishu, Telegram, or other channels.

Work:

- Define channel-independent event shape:
  - user message
  - assistant message
  - tool/progress event
  - processor status
  - subagent status
- Keep `persona/events/thread.jsonl` channel-neutral.
- Add channel routing docs:
  - which UI events should be rendered
  - which background events should be silent
  - which artifacts should be sent back to the user

Done when:

- Adding a new channel does not require rewriting processor, wiki, or subagent logic.

Status:

- Done on 2026-06-07.
- Added `docs/channel-event-contract.md` with channel-neutral user/assistant/tool/processor/subagent event shapes.
- Documented rendering rules for chat messages, transient tool/progress events, artifacts, and wiki updates.
- Documented adapter boundary for future WeChat, Feishu, Telegram, or similar channels.

## Verification Commands

- `bun run check`
- `uv run pytest bot/tests/config bot/tests/wiki bot/tests/subagent bot/tests/counter -q`
- `bun run smoke:gateway` with `WEBUI_BASE` pointing at a running gateway/WebUI target.
- `git diff --check`
