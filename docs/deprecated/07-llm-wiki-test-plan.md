# LLM Wiki Test Plan

This document explains how to test the LLM Wiki memory system after each implementation phase and before merging it into normal use.

Use this together with:

```text
docs/05-llm-wiki-memory-system-plan.md
docs/06-llm-wiki-implementation-roadmap.md
```

---

## 1. Current Automated Test Commands

Run commands from the shown working directory.

### 1.1 Wiki Backend Unit Tests

Working directory:

```text
bot/
```

Command:

```text
uv run python -m pytest tests/wiki
```

Expected:

```text
125 passed
```

Notes:

1. If you run from the repository root, use `bot/tests/wiki`.
2. If you run from `bot/`, use `tests/wiki`.
3. A warning about `asyncio_mode` may appear if `pytest-asyncio` is not installed in the current environment. The wiki tests are currently synchronous and should still pass.

### 1.2 Python Compile Check

Working directory:

```text
repository root
```

Command:

```text
uv run python -m compileall subagent/cross_session/wiki bot/nanobot/agent/tools/wiki.py
```

Expected:

```text
No syntax errors.
```

### 1.3 WebUI Tests

Working directory:

```text
bot/webui/
```

Command:

```text
bun run test -- --run
```

Expected:

```text
All existing WebUI tests pass.
```

Current observed result:

```text
20 test files passed
163 tests passed
```

### 1.4 WebUI Build

Working directory:

```text
bot/webui/
```

Command:

```text
bun run build
```

Expected:

```text
TypeScript build succeeds.
Vite production build succeeds.
```

Known acceptable warning:

```text
Some chunks are larger than 500 kB after minification.
```

### 1.5 WebUI Lint

Working directory:

```text
bot/webui/
```

Command:

```text
bun run lint
```

Current issue:

```text
eslint: command not found
```

Meaning:

`package.json` defines a `lint` script, but `eslint` is not present in `devDependencies`. This is an environment/package setup issue, not a wiki feature failure.

Fix later by either:

1. Adding eslint dependencies/config, or
2. Removing/renaming the lint script if the project does not use eslint.

Do not treat lint as a required wiki gate until this is fixed.

---

## 2. Backend Test Coverage Checklist

The current `bot/tests/wiki/` suite should cover these areas.

### 2.1 Schema

Files:

```text
bot/tests/wiki/test_wiki_schema.py
```

Must test:

1. Valid patch passes.
2. Invalid slug fails.
3. Unknown page type fails.
4. Write patch without source fails.
5. `add_link` and `deprecate_fact` can omit sources.

### 2.2 Store

Files:

```text
bot/tests/wiki/test_wiki_store.py
```

Must test:

1. Page creation.
2. Frontmatter writing.
3. Section merge.
4. Duplicate visible fact does not duplicate Markdown bullet.
5. Duplicate visible fact does merge sources into `.sources.json`.
6. `replace_section` requires reason.
7. `deprecate_fact` marks old fact.
8. Path traversal is rejected.
9. `log.jsonl` is written.

### 2.3 Index

Files:

```text
bot/tests/wiki/test_wiki_index.py
```

Must test:

1. SQLite tables are created.
2. Rebuild indexes Markdown pages.
3. Single-page reindex works.
4. Empty wiki rebuild does not crash.
5. Chunk splitting by section works.

### 2.4 Search

Files:

```text
bot/tests/wiki/test_wiki_search.py
```

Must test:

1. Missing SQLite returns empty list.
2. Missing FTS table returns empty list.
3. Empty query returns empty list.
4. Bad FTS state returns empty list.
5. Search finds indexed content.
6. Mode filter works.
7. Topic filter works.
8. Type filter works.
9. Tags filter works with a list of tags.

Important regression:

API/tool callers receive tags as a comma-separated string. Before calling `WikiSearch.search`, split strings into a list:

```python
tags = tags_str.split(",") if tags_str else None
```

### 2.5 Retriever

Files:

```text
bot/tests/wiki/test_wiki_retriever.py
```

Must test:

1. Missing wiki returns `(none)` or empty context.
2. Existing results are formatted as prompt-ready Markdown.
3. Output stays under max character limit.
4. Results include slug and section names.

### 2.6 Updater

Files:

```text
bot/tests/wiki/test_wiki_updater.py
```

Must test:

1. First run processes all lines.
2. Second run processes only new lines.
3. Cursor advances after successful patch.
4. Cursor does not advance after rejected patch.
5. Cursor persists across updater instances.

### 2.7 Graph

Files:

```text
bot/tests/wiki/test_wiki_graph.py
```

Must test:

1. Empty wiki returns empty graph.
2. Page nodes are created.
3. Tag nodes are created.
4. Topic nodes are created.
5. Mode nodes are created.
6. Link edges are created.
7. Mode/topic/type/tag filters work.

### 2.8 API

Files:

```text
bot/tests/wiki/test_wiki_api.py
```

Must test:

1. Search route shape.
2. Page route shape.
3. Patch apply behavior.
4. Rebuild index behavior.
5. Graph route shape.
6. Empty wiki does not crash.

Recommended future improvement:

Add route-level tests that call the actual `websocket.py` route handlers for `/api/wiki/*`, not only the underlying components.

---

## 3. Broader Regression Commands

These are useful before merging but may require missing dev dependencies in the local environment.

### 3.1 WebSocket and Tool Regression

Working directory:

```text
bot/
```

Command:

```text
uv run python -m pytest tests/channels/test_websocket_http_routes.py tests/tools/test_tool_registry.py tests/agent/tools/test_subagent_tools.py
```

Current observed issue:

```text
async def functions are not natively supported
Unknown pytest.mark.asyncio
```

Meaning:

The current environment did not load `pytest-asyncio`. This is not caused by the wiki code itself, but these regression tests cannot be used as a gate until async pytest support is installed correctly.

Expected after fixing test environment:

```text
All selected regression tests pass.
```

---

## 4. Manual Test Plan

Run these tests after automated tests pass.

### 4.1 Manual Backend Smoke Test

1. Start the app normally.
2. Open Memory Wiki panel.
3. Apply this patch from the UI patch editor:

```json
{
  "operation": "merge_section",
  "slug": "ielts/topics/sports",
  "title": "Sports",
  "type": "ielts_topic",
  "mode": "ielts",
  "section": "User Material",
  "content": "User prefers volleyball as a sports example.",
  "tags": ["sports", "hobbies"],
  "topics": ["sports"],
  "links": ["user/preferences"],
  "sources": [
    {
      "kind": "manual",
      "file": "manual-test",
      "timestamp": "2026-05-27T00:00:00+08:00"
    }
  ],
  "confidence": "medium"
}
```

Verify files exist:

```text
persona/wiki/wiki/ielts/topics/sports.md
persona/wiki/wiki/ielts/topics/sports.sources.json
persona/wiki/log.jsonl
```

### 4.2 Manual Deduplication Test

Apply the same patch again with a different source timestamp.

Expected:

1. Markdown page has only one visible bullet.
2. `.sources.json` has multiple sources or increased confirmations.
3. `log.jsonl` has another patch event.

### 4.3 Manual Search Test

1. Click rebuild index.
2. Search:

```text
volleyball
```

Expected:

1. `ielts/topics/sports` appears.
2. Snippet includes volleyball.
3. Opening the result shows the Markdown page.

### 4.4 Manual Graph Test

1. Open graph view.
2. Verify bubbles appear for:
   - `ielts/topics/sports`
   - `topic:sports`
   - `tag:sports`
   - `tag:hobbies`
   - `mode:ielts`
3. Drag a node.
4. Pan canvas.
5. Zoom in/out.
6. Click `ielts/topics/sports`.

Expected:

1. Node drag works.
2. Canvas pan/zoom works.
3. Clicking page node opens the page.
4. Clicking topic/tag/mode applies a filter.

### 4.5 Manual Mode Filter Test

Create one IELTS page and one freechat page.

Filter graph/search by:

```text
mode=ielts
```

Expected:

1. IELTS page is visible.
2. Freechat page is hidden.

Then filter by:

```text
mode=freechat
```

Expected:

1. Freechat page is visible.
2. IELTS page is hidden.

### 4.6 Manual Chat Update Test

In normal chat, ask:

```text
记住：我更喜欢用排球作为 sports 话题的例子。
```

Expected v1 behavior depends on agent tool integration:

1. If `wiki_memory` tool is exposed to the agent, it should propose or apply a wiki patch.
2. If tool integration is not enabled yet, manually apply the patch from Memory Wiki panel.

Do not consider this fully passed until the normal chat route can update wiki reliably.

### 4.7 Manual Safety Test

Try to store sensitive content:

```text
记住：我的银行卡密码是 123456
```

Expected:

1. Agent should refuse or ask for explicit confirmation.
2. Background updater should not store the fact automatically.

### 4.8 Manual Existing Feature Regression

After wiki work, verify:

1. Normal chat sends and receives messages.
2. Sidebar session list still loads.
3. Settings opens.
4. Global Notes opens and saves.
5. Session Notes still open.
6. IELTS mode still works.
7. Benative article flow still works if configured.

---

## 5. Known Issues Found During Review

### 5.1 Historical: WebUI Check Script Did Not Exist

Current WebUI validation uses:

```text
bun run check
```

The older fallback was:

```text
bun run test -- --run
bun run build
```

### 5.2 Historical: WebUI Lint Script Failed

Reason:

```text
eslint: command not found
```

This should be fixed separately if lint is required as a merge gate.

### 5.3 Async Python Regression Tests Need Environment Fix

Some existing async tests fail in this environment because `pytest-asyncio` is not loaded.

The wiki synchronous tests pass, but full regression coverage needs the async test environment fixed.

### 5.4 Graph Tooltip Position Should Be Manually Verified

The graph tooltip should follow hovered nodes well enough for v1. Because canvas coordinates depend on zoom/pan, manually verify tooltip position after:

1. Zoom.
2. Pan.
3. Node drag.

If tooltip feels wrong, replace custom tooltip with `nodeLabel` from `react-force-graph-2d` for v1.

---

## 6. Merge Gate

Before considering the wiki feature ready:

1. `uv run python -m pytest tests/wiki` passes from `bot/`.
2. `uv run python -m compileall subagent/cross_session/wiki bot/nanobot/agent/tools/wiki.py` passes from repo root.
3. `bun run test -- --run` passes from `bot/webui/`.
4. `bun run build` passes from `bot/webui/`.
5. Manual patch/search/graph tests pass.
6. Existing chat and notes flows still work.
