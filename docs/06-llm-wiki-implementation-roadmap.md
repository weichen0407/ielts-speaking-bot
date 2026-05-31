# LLM Wiki Implementation Roadmap

This document is the coding roadmap for `docs/05-llm-wiki-memory-system-plan.md`.

Use this file when assigning implementation work to a less capable model. Each phase should be implemented separately. Do not ask the model to implement the whole system in one pass.

Core rule:

```text
Markdown pages are the source of truth.
SQLite is a derived search index.
Graph visualization is derived from wiki page metadata.
KG code stays untouched until the wiki system works.
```

---

## Phase 0: Preparation

Goal:

Understand existing patterns and create empty module structure.

Read first:

```text
subagent/_shared/base.py
subagent/cross_session/kg/processor/
bot/nanobot/channels/websocket.py
bot/webui/src/lib/api.ts
bot/webui/src/App.tsx
```

Create directories:

```text
subagent/cross_session/wiki/
subagent/cross_session/wiki/context/
subagent/cross_session/wiki/processor/
subagent/cross_session/wiki/data/
```

Create placeholder files:

```text
subagent/cross_session/wiki/__init__.py
subagent/cross_session/wiki/processor/__init__.py
subagent/cross_session/wiki/data/README.md
```

Do not:

1. Delete `subagent/cross_session/kg/`.
2. Modify WebUI.
3. Modify API routes.

Acceptance:

1. New wiki module exists.
2. Existing tests still pass.

---

## Phase 1: Schema and Store

Goal:

Implement the canonical Markdown wiki store and patch application.

Files to create:

```text
subagent/cross_session/wiki/processor/schema.py
subagent/cross_session/wiki/processor/wiki_store.py
```

Files to test:

```text
bot/tests/wiki/test_wiki_schema.py
bot/tests/wiki/test_wiki_store.py
```

Required behavior:

1. Validate `WikiPatch`, `WikiSource`, `WikiPageMeta`.
2. Reject bad slugs:
   - `../x`
   - `/x`
   - `x/../../y`
3. Reject unknown page types.
4. Reject write patches without sources.
5. Store pages under:

```text
persona/wiki/wiki/{slug}.md
```

6. Store source metadata under:

```text
persona/wiki/wiki/{slug}.sources.json
```

Important source rule:

Visible Markdown bullets should be deduplicated, but sources must not be lost.

When a duplicate fact appears:

```text
Do not add a duplicate bullet to Markdown.
Do merge the new source into {slug}.sources.json.
Do increment confirmations.
Do update last_seen.
Do append an event to log.jsonl.
```

Suggested sidecar format:

```json
{
  "facts": {
    "user likes playing basketball": {
      "text": "User likes playing basketball.",
      "section": "User Material",
      "sources": [
        {
          "kind": "session",
          "session_id": "abc",
          "message_id": "user:4",
          "timestamp": "2026-05-27T10:00:00+08:00"
        }
      ],
      "confirmations": 1,
      "first_seen": "2026-05-27T10:00:00+08:00",
      "last_seen": "2026-05-27T10:00:00+08:00"
    }
  }
}
```

Patch operations to support in Phase 1:

```text
create_page
merge_section
append_section
replace_section
add_link
update_summary
deprecate_fact
```

Implementation notes:

1. Use atomic writes.
2. Keep Markdown readable.
3. Use simple frontmatter parsing. If no YAML library is already available, implement a small parser for the `---` block.
4. Do not import `WikiIndex` or `WikiSearch` from `wiki_store.py`.

Acceptance:

1. Applying `merge_section` creates a page if missing.
2. Applying the same patch twice creates one visible bullet.
3. The duplicate patch adds another source in `.sources.json`.
4. Path traversal is rejected.
5. `persona/wiki/log.jsonl` records patch events.

Suggested command:

```text
uv run python -m pytest bot/tests/wiki/test_wiki_schema.py bot/tests/wiki/test_wiki_store.py
```

---

## Phase 2: Index and Search

Goal:

Build a SQLite FTS index and searchable retrieval.

Files to create:

```text
subagent/cross_session/wiki/processor/wiki_index.py
subagent/cross_session/wiki/processor/wiki_search.py
subagent/cross_session/wiki/processor/wiki_retriever.py
```

Files to test:

```text
bot/tests/wiki/test_wiki_index.py
bot/tests/wiki/test_wiki_search.py
bot/tests/wiki/test_wiki_retriever.py
```

Database path:

```text
persona/wiki/index/wiki.sqlite
```

Dependency direction:

```text
WikiIndex -> WikiStore
WikiSearch -> SQLite only
WikiRetriever -> WikiSearch
API layer -> WikiIndex + WikiSearch
```

Important rule:

`WikiSearch` must not rebuild the index in `__init__`.

Search behavior:

1. If SQLite file is missing, return empty results.
2. If FTS tables are missing, return empty results.
3. Do not raise for missing index.
4. Rebuild is explicit through:
   - `WikiIndex.rebuild()`
   - `/api/wiki/rebuild-index`
   - `WikiIndex.index_page(slug)` after patch apply

Index tables:

```text
pages
chunks
chunks_fts
```

Chunking:

1. Split page body by `##` sections.
2. One section is one chunk.
3. Split very long sections by paragraphs.

Search filters:

```text
query
mode
topic
page_type
tags
limit
```

Acceptance:

1. `WikiIndex.rebuild()` indexes existing Markdown pages.
2. `WikiSearch.search("basketball")` finds matching chunks.
3. Missing SQLite returns `[]`.
4. Missing FTS table returns `[]`.
5. `read_wiki_context()` returns prompt-ready Markdown under max character limit.

Suggested command:

```text
uv run python -m pytest bot/tests/wiki/test_wiki_index.py bot/tests/wiki/test_wiki_search.py bot/tests/wiki/test_wiki_retriever.py
```

Do not:

1. Modify WebUI.
2. Add API routes yet.
3. Add embeddings.

---

## Phase 3: Patch Processor and Updater

Goal:

Connect processor inputs to wiki patch generation and incremental updates.

Files to create:

```text
subagent/cross_session/wiki/context/wiki_subagent.md
subagent/cross_session/wiki/processor/wiki_processor.py
subagent/cross_session/wiki/processor/wiki_updater.py
```

Files to test:

```text
bot/tests/wiki/test_wiki_processor.py
bot/tests/wiki/test_wiki_updater.py
```

`wiki_subagent.md` requirements:

1. Output JSONL only.
2. Output `(none)` if no useful memory exists.
3. Include examples for IELTS, freechat, and Benative.
4. Include safety rules.
5. Include allowed page types and operations.

`wiki_processor.py` responsibilities:

1. Parse LLM JSONL patches.
2. Ignore `(none)`.
3. Reject invalid JSON lines.
4. Apply valid patches through `WikiStore`.
5. Call `WikiIndex.index_page(slug)` for changed pages.

`wiki_updater.py` responsibilities:

1. Track line cursors.
2. Read new rows from existing JSONL sources.
3. Update cursor only after successful patch application.

Initial sources from the old patch-JSONL plan, superseded by the current
`persona/events/thread.jsonl` ingest flow:

```text
subagent/single_session/vocab/data/vocab.jsonl
subagent/single_session/polisher/data/polisher.jsonl
subagent/single_session/notes/data/notes.jsonl
subagent/cross_session/progress_tracker/data/progress_bank.jsonl
```

Acceptance:

1. Valid JSONL patch creates/updates pages.
2. Invalid patch is logged and skipped.
3. First updater run processes all lines.
4. Second updater run processes only new lines.
5. Cursor is not advanced when patch application fails.

Suggested command:

```text
uv run python -m pytest bot/tests/wiki/test_wiki_processor.py bot/tests/wiki/test_wiki_updater.py
```

Do not:

1. Add automatic triggers until manual tests pass.
2. Delete KG.

---

## Phase 4: Backend API

Goal:

Expose wiki search, page reading, patching, index rebuild, and graph data to WebUI.

File to edit:

```text
bot/nanobot/channels/websocket.py
```

Possible helper file:

```text
subagent/cross_session/wiki/processor/wiki_graph.py
```

Routes to add:

```text
GET /api/wiki/search?q=...&mode=...&topic=...&type=...&tags=tag1,tag2&limit=10
GET /api/wiki/page?slug=ielts/topics/sports
GET /api/wiki/graph?mode=...&topic=...&type=...&tags=tag1,tag2
GET /api/wiki/patch?data=<urlencoded JSON>
GET /api/wiki/rebuild-index
```

Use GET query params because existing WebUI APIs in `websocket.py` already use this pattern.

Graph behavior:

1. Read wiki page metadata.
2. Build page nodes.
3. Build tag nodes.
4. Build topic nodes.
5. Build mode nodes.
6. Build edges:
   - page to page from `links`
   - page to tag from `tags`
   - page to topic from `topics`
   - page to mode from `mode`

Graph node metadata must include:

```text
id
label
kind
type
mode
tags
topics
updated_at
summary
size
```

Acceptance:

1. Search route returns `{ "results": [...] }`.
2. Page route returns `{ "meta": {...}, "content": "..." }`.
3. Patch route applies a valid patch and indexes changed pages.
4. Rebuild route rebuilds SQLite.
5. Graph route returns `{ "nodes": [...], "edges": [...] }`.
6. Empty wiki does not crash any route.

Tests:

```text
bot/tests/wiki/test_wiki_api.py
bot/tests/wiki/test_wiki_graph.py
```

Suggested command:

```text
uv run python -m pytest bot/tests/wiki/test_wiki_api.py bot/tests/wiki/test_wiki_graph.py
```

Do not:

1. Add frontend before these routes work.
2. Add agent tool yet.

---

## Phase 5: WebUI API Client

Goal:

Add typed frontend API helpers.

File to edit:

```text
bot/webui/src/lib/api.ts
```

Add types:

```text
WikiSearchResult
WikiGraphNode
WikiGraphEdge
WikiPageResponse
WikiPatchResponse
```

Add functions:

```text
fetchWikiSearch
fetchWikiPage
fetchWikiGraph
applyWikiPatch
rebuildWikiIndex
```

Acceptance:

1. Functions use existing `request<T>()`.
2. Query params use `URLSearchParams`.
3. No UI code yet.

Suggested command:

```text
pnpm run build
```

---

## Phase 6: WebUI Memory Panel

Goal:

Let the user search, inspect, and manually patch wiki memory.

File to create:

```text
bot/webui/src/components/WikiMemoryPanel.tsx
```

Features:

1. Search input.
2. Filters:
   - mode
   - topic
   - type
   - tags
3. Search results list.
4. Page viewer.
5. JSON patch editor.
6. Apply patch button.
7. Rebuild index button.

UX rules:

1. Keep it tool-like and dense.
2. Do not add nested cards.
3. Use existing UI components.
4. Show errors clearly.

Acceptance:

1. User can search.
2. User can open a page.
3. User can paste and apply a valid patch.
4. Invalid patch shows error.
5. Rebuild button works.

Tests:

```text
bot/webui/src/tests/wiki-memory-panel.test.tsx
```

Suggested command:

```text
pnpm test -- --run
pnpm run build
```

---

## Phase 7: WebUI Graph View

Goal:

Render draggable bubble knowledge graph.

File to create:

```text
bot/webui/src/components/WikiGraphView.tsx
```

Preferred dependency:

```text
react-force-graph-2d
```

If dependency installation is not available, create a static SVG fallback and leave a TODO.

Expected effects:

1. Circular bubble nodes.
2. Force-directed automatic layout.
3. Drag nodes.
4. Drag canvas.
5. Zoom in/out.
6. Click page node to open page.
7. Click topic/tag/mode node to filter.
8. Hover tooltip with metadata.
9. Search result highlights.
10. Recently updated nodes show a visible ring.

Frontend mapping:

```text
backend edges -> react-force-graph links
```

Acceptance:

1. Empty graph renders empty state.
2. Graph with sample nodes renders.
3. User can drag nodes.
4. User can zoom and pan.
5. Clicking page node opens page.
6. Filtering by topic updates graph.

Tests:

```text
bot/webui/src/tests/wiki-graph-view.test.tsx
```

Suggested command:

```text
pnpm test -- --run
pnpm run build
```

---

## Phase 8: WebUI Entry Point

Goal:

Expose Memory Wiki in the app.

Files to edit:

```text
bot/webui/src/App.tsx
bot/webui/src/components/Sidebar.tsx
```

Simplest option:

Add a floating Memory Wiki button like Global Notes.

Better option:

Add Memory Wiki entry to the sidebar.

Acceptance:

1. User can open Memory Wiki from main UI.
2. Chat still works.
3. Global Notes still works.
4. Settings still works.

Suggested command:

```text
pnpm test -- --run
pnpm run build
```

---

## Phase 9: Optional Agent Tool

Goal:

Allow the main agent to search/read/propose/apply wiki changes.

File to create:

```text
bot/nanobot/agent/tools/wiki.py
```

Actions:

```text
search
read
propose_patch
apply_patch
graph
```

Use cases:

1. User asks: "我之前 sports 话题有什么素材？"
2. User says: "记住：我更喜欢排球。"
3. User says: "忘掉我喜欢篮球这件事。"

Safety:

1. `apply_patch` should require explicit user intent or UI confirmation.
2. Sensitive memories should be rejected unless explicitly requested.
3. The tool should return patch previews when unsure.

Acceptance:

1. Agent can search wiki.
2. Agent can read a page.
3. Agent can propose a patch.
4. Agent can apply a patch when explicitly requested.

---

## Phase 10: Deprecate KG

Goal:

Remove old KG only after wiki is working.

Steps:

1. Confirm wiki backend tests pass.
2. Confirm wiki WebUI tests pass.
3. Confirm manual wiki search works.
4. Confirm graph view works.
5. Confirm patch apply works.
6. Search for KG triggers.
7. Disable KG triggers if present.
8. Update docs to mark KG deprecated.
9. Delete KG code in a separate cleanup change.

Do not delete KG in the same PR/change as the initial wiki implementation.

---

## Recommended Assignment Prompts

Use prompts like these when asking another model to code.

### Prompt for Phase 1

```text
Implement only Phase 1 from docs/06-llm-wiki-implementation-roadmap.md.
Create schema.py and wiki_store.py.
Add tests for schema and store.
Do not implement search, index, API, WebUI, or agent tools.
Do not modify KG code.
Run the relevant tests and report results.
```

### Prompt for Phase 2

```text
Implement only Phase 2 from docs/06-llm-wiki-implementation-roadmap.md.
Create wiki_index.py, wiki_search.py, and wiki_retriever.py.
Important: WikiSearch must not rebuild indexes in __init__.
If SQLite or FTS is missing, search returns [].
Add tests and run them.
Do not modify WebUI or API routes.
```

### Prompt for Phase 4

```text
Implement only Phase 4 from docs/06-llm-wiki-implementation-roadmap.md.
Add backend wiki API routes in websocket.py and graph helper if needed.
Do not implement WebUI.
Add API/graph tests and run them.
```

### Prompt for Phases 6-7

```text
Implement only the WebUI wiki panel and graph view from docs/06-llm-wiki-implementation-roadmap.md.
Use existing UI components.
Use react-force-graph-2d for the bubble graph if dependency installation is available.
Do not modify backend behavior.
Run `pnpm test -- --run` and `pnpm run build`.
```

---

## Final Done Criteria

The whole implementation is done when:

1. Wiki Markdown pages can be created and updated.
2. Duplicate visible facts merge sources instead of losing evidence.
3. SQLite search index can be rebuilt.
4. Search returns relevant snippets.
5. Missing SQLite never crashes search.
6. Backend wiki routes work.
7. WebUI can search and open wiki pages.
8. WebUI can apply patch updates.
9. WebUI graph shows draggable bubble nodes.
10. Graph can filter by mode, topic, type, and tags.
11. Existing chat, notes, IELTS, and Benative flows still work.
