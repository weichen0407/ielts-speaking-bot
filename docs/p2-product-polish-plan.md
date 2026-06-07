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

- [ ] 1. Improve WebUI graph and learning artifact navigation.
- [ ] 2. Formalize the tool layer for agentic subagents.
- [ ] 3. Add cost, token, and model governance.
- [ ] 4. Add data lifecycle controls for test data, user data, and exports.
- [ ] 5. Add browser-level smoke tests for core user journeys.
- [ ] 6. Prepare channel expansion surfaces.

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

## Verification Commands

- `bun run check`
- `uv run pytest bot/tests/config bot/tests/wiki bot/tests/subagent bot/tests/counter -q`
- Browser smoke test command once added.
- `git diff --check`
