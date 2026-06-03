# Phase 3a Replacement: LLM Wiki Memory System

## 0. Goal

Replace the current KG module with a lightweight but powerful LLM wiki memory system.

The wiki is the canonical long-term memory store for the user. It must support:

1. Memory from all modes:
   - IELTS mode: topics, questions, examples, weaknesses, useful expressions.
   - Freechat mode: personal context, projects, interests, plans, preferences.
   - Benative mode: article learning, native expression bank, answer patterns, weaknesses.
   - Global notes: user-written notes and quoted conversation snippets.
   - Progress/review data: learning progress, review hooks, recurring issues.
2. Search:
   - Keyword search.
   - Filter by mode, topic, page type, tags.
   - Retrieve short snippets for prompt injection.
3. User-visible knowledge graph:
   - View all wiki memory as a graph.
   - Filter graph by IELTS topic.
   - Filter graph by function/category, such as user profile, IELTS topic, language weakness, expression bank, project, Benative learning.
4. Conversation-based wiki updates:
   - The existing chat UI should be able to update the wiki.
   - User can ask the bot to remember/update/correct/delete a memory.
   - User can inspect proposed wiki changes before applying them in the UI.
5. Keep the implementation lightweight:
   - Markdown files are the source of truth.
   - SQLite index is derived data and can be rebuilt.
   - No graph database in v1.
   - No vector database in v1.
   - Embeddings are optional v2.

This document is written as an implementation guide for a less capable model. Follow it in order. Do not jump ahead.

---

## 1. Current State

Current KG files:

```text
subagent/cross_session/kg/
  context/kg_subagent.md
  processor/
    cursor.py
    entity_store.py
    extractor.py
    kg_processor.py
    kg_updater.py
    schema.py
    topics.py
  data/
```

Important observations:

1. KG is currently not deeply integrated into the main chat loop.
2. `subagent/cross_session/kg/data/` is empty in the current workspace.
3. The current KG stores entities and relations in `entity_database.json`.
4. NetworkX is only used as an in-memory graph helper in `entity_store.py`.
5. The KG prompt and extractor disagree on output format:
   - `kg_subagent.md` asks for tab-separated lines.
   - `extractor.py` expects `ENTITY:` and `RELATION:` lines.

Because the KG is not yet deeply wired into the product, replacing it with wiki is low risk.

---

## 2. Final Directory Layout

Create a new wiki module. Do not delete KG at first.

```text
subagent/cross_session/wiki/
  __init__.py
  context/
    wiki_subagent.md
  processor/
    __init__.py
    schema.py
    wiki_store.py
    wiki_index.py
    wiki_search.py
    wiki_retriever.py
    wiki_updater.py
    wiki_processor.py
  data/
    README.md
```

Canonical wiki data lives under `persona/wiki/`:

```text
persona/wiki/
  purpose.md
  schema.md
  index.md
  log.jsonl
  wiki/
    user/
      profile.md
      profile.sources.json
      preferences.md
      preferences.sources.json
      communication-style.md
      communication-style.sources.json
      goals.md
      goals.sources.json
    ielts/
      topics/
        sports.md
        sports.sources.json
        work.md
        work.sources.json
        travel.md
        travel.sources.json
      question-bank.md
      question-bank.sources.json
      speaking-examples.md
      speaking-examples.sources.json
      weaknesses.md
      weaknesses.sources.json
    freechat/
      projects.md
      projects.sources.json
      interests.md
      interests.sources.json
      ideas.md
      ideas.sources.json
      life-context.md
      life-context.sources.json
    benative/
      article-learning.md
      article-learning.sources.json
      native-expression-bank.md
      native-expression-bank.sources.json
      answer-patterns.md
      answer-patterns.sources.json
      weaknesses.md
      weaknesses.sources.json
    language/
      vocabulary.md
      vocabulary.sources.json
      grammar-patterns.md
      grammar-patterns.sources.json
      collocations.md
      collocations.sources.json
      pronunciation.md
      pronunciation.sources.json
    timeline/
      2026-05.md
      2026-05.sources.json
  index/
    wiki.sqlite
```

Rules:

1. Markdown pages in `persona/wiki/wiki/` are the source of truth.
2. `persona/wiki/index/wiki.sqlite` is derived. It must be rebuildable from Markdown.
3. `persona/wiki/log.jsonl` records all applied patches.
4. `persona/memory/MEMORY.md` remains as a compact always-injected summary. It can later be generated from the wiki.
5. Each page has a companion `wiki/{slug}.sources.json` sidecar file that tracks fact sources. Markdown stays clean; sources are preserved for provenance and conflict detection.

---

## 3. Wiki Page Format

Every page must be Markdown with YAML frontmatter.

Example:

```md
---
slug: ielts/topics/sports
title: Sports
type: ielts_topic
mode: ielts
tags: [sports, hobbies, health]
topics: [sports]
links: [user/preferences, language/collocations]
updated_at: 2026-05-27T10:00:00+08:00
confidence: medium
---

# Sports

## Summary

The user can use basketball and volleyball as personal examples for IELTS sports, hobbies, health, teamwork, and childhood memory questions.

## User Material

- User enjoys basketball as a relaxing activity.
- User has discussed volleyball and team sports.

## Useful Expressions

- It helps me unwind after a long day.
- It builds a strong sense of teamwork.

## Weaknesses

- User may say "play basketball is good" instead of "playing basketball is good for...".

## Review Hooks

- Ask the user to describe a sport they enjoyed as a child.

## Sources

- `session:... message:... 2026-05-27`
```

Required frontmatter fields:

| Field | Required | Meaning |
|---|---:|---|
| `slug` | yes | Stable page id without `.md` |
| `title` | yes | Human-readable title |
| `type` | yes | Page type |
| `mode` | yes | `global`, `ielts`, `freechat`, `benative`, or `language` |
| `tags` | yes | Free-form tags |
| `topics` | no | IELTS or learning topics |
| `links` | yes | Other page slugs |
| `updated_at` | yes | ISO timestamp |
| `confidence` | no | `low`, `medium`, `high` |

Allowed page types in v1:

```text
user_profile
user_preference
user_goal
communication_style
ielts_topic
ielts_question_bank
ielts_speaking_example
language_weakness
expression_bank
freechat_project
freechat_interest
benative_article_learning
benative_answer_pattern
timeline_month
```

If a patch references an unknown type, reject it.

---

## 4. Wiki Patch Format

LLM updates must not overwrite a full page directly. They must produce patches.

Use JSONL. Each line is one patch.

```json
{
  "operation": "merge_section",
  "slug": "ielts/topics/sports",
  "title": "Sports",
  "type": "ielts_topic",
  "mode": "ielts",
  "section": "User Material",
  "content": "User often uses basketball as a personal example for hobbies and health topics.",
  "tags": ["sports", "hobbies", "health"],
  "topics": ["sports"],
  "links": ["user/preferences", "language/collocations"],
  "sources": [
    {
      "kind": "session",
      "session_id": "abc",
      "message_id": "user:12",
      "timestamp": "2026-05-27T10:00:00+08:00"
    }
  ],
  "confidence": "medium",
  "reason": "The user mentioned basketball while answering an IELTS hobbies question."
}
```

Supported operations:

| Operation | Meaning |
|---|---|
| `create_page` | Create a page if it does not exist |
| `merge_section` | Add new facts into a section, deduplicating similar bullets |
| `append_section` | Append content without deduplication; use only for timeline pages |
| `replace_section` | Replace a section; requires `reason` |
| `add_link` | Add links to frontmatter |
| `deprecate_fact` | Mark an old fact as no longer true |
| `update_summary` | Replace only the `## Summary` section |

Rules:

1. Prefer `merge_section`.
2. Use `append_section` only for chronological logs.
3. Use `replace_section` only when correcting stale or wrong memory.
4. Every patch must include at least one source.
5. Do not store secrets, passwords, API keys, private tokens, or medical/legal/financial sensitive details unless the user explicitly asks to remember them.
6. If a patch contains unsafe memory, reject it and log a rejected patch event.

---

## 5. Backend Implementation Tasks

### Task 5.1: Create `schema.py`

File:

```text
subagent/cross_session/wiki/processor/schema.py
```

Implement Pydantic models:

```python
class WikiSource(BaseModel):
    kind: str
    session_id: str | None = None
    message_id: str | None = None
    file: str | None = None
    timestamp: str | None = None

class WikiPatch(BaseModel):
    operation: Literal[
        "create_page",
        "merge_section",
        "append_section",
        "replace_section",
        "add_link",
        "deprecate_fact",
        "update_summary",
    ]
    slug: str
    title: str
    type: str
    mode: Literal["global", "ielts", "freechat", "benative", "language"]
    section: str | None = None
    content: str = ""
    tags: list[str] = []
    topics: list[str] = []
    links: list[str] = []
    sources: list[WikiSource] = []
    confidence: Literal["low", "medium", "high"] = "medium"
    reason: str | None = None

class WikiPageMeta(BaseModel):
    slug: str
    title: str
    type: str
    mode: str
    tags: list[str] = []
    topics: list[str] = []
    links: list[str] = []
    updated_at: str
    confidence: str = "medium"

class WikiSearchResult(BaseModel):
    slug: str
    title: str
    type: str
    mode: str
    section: str
    snippet: str
    score: float
    tags: list[str] = []
    topics: list[str] = []
```

Validation rules:

1. `slug` must match `^[a-z0-9][a-z0-9/_-]*$`.
2. `slug` must not contain `..`.
3. `slug` must not start with `/`.
4. `type` must be in the allowed type list.
5. `sources` must not be empty for write operations.

Acceptance:

1. Unit tests reject bad slugs.
2. Unit tests reject unknown page types.
3. Unit tests reject write patches without sources.

---

### Task 5.2: Create `wiki_store.py`

File:

```text
subagent/cross_session/wiki/processor/wiki_store.py
```

Responsibilities:

1. Resolve wiki root:
   - Default root: `{workspace}/persona/wiki`.
   - Allow explicit root for tests.
2. Read a page by slug.
3. Write a page by slug.
4. Parse frontmatter.
5. Render frontmatter.
6. Apply `WikiPatch`, including managing the sidecar `sources.json`.
7. Atomic writes.
8. Append applied/rejected patches to `log.jsonl`.

Required class:

```python
class WikiStore:
    def __init__(self, workspace: Path, wiki_root: Path | None = None): ...
    def page_path(self, slug: str) -> Path: ...
    def sources_path(self, slug: str) -> Path: ...
    def read_page(self, slug: str) -> tuple[WikiPageMeta, str] | None: ...
    def write_page(self, meta: WikiPageMeta, body: str) -> None: ...
    def read_sources(self, slug: str) -> dict | None: ...
    def write_sources(self, slug: str, sources: dict) -> None: ...
    def apply_patch(self, patch: WikiPatch) -> bool: ...
    def list_pages(self) -> list[WikiPageMeta]: ...
    def append_log(self, event: dict) -> None: ...
```

Implementation details:

1. Page path is `wiki_root / "wiki" / f"{slug}.md"`.
2. Do not allow page paths outside `wiki_root/wiki`.
3. Atomic write:
   - Write to `.tmp`.
   - Replace final file.
4. Section handling:
   - Sections are Markdown headings like `## Summary`.
   - `merge_section` should add bullet lines under the section.
   - If section does not exist, create it at the end.
5. Deduplication and sources:
   - Normalize bullet text by lowercasing and stripping punctuation.
   - If normalized content already exists in the section, do not add a duplicate bullet to Markdown.
   - Instead, merge the new sources into `wiki/{slug}.sources.json` under the matching fact key, increment `confirmations`, and update `last_seen`.
   - If the fact does not exist, add the bullet to Markdown and create a new entry in `sources.json`.
   - The `sources.json` file is never shown to users; it exists only for provenance and conflict detection.
6. Sources sidecar format:

```json
{
  "facts": {
    "user likes playing basketball": {
      "text": "User likes playing basketball.",
      "section": "User Material",
      "sources": [
        {"kind": "session", "session_id": "abc", "message_id": "user:12", "timestamp": "2026-05-27T10:00:00+08:00"}
      ],
      "confirmations": 1,
      "first_seen": "2026-05-27T10:00:00+08:00",
      "last_seen": "2026-05-27T10:00:00+08:00"
    }
  }
}
```
7. Links/tags/topics:
   - Merge unique values into frontmatter.
7. `updated_at`:
   - Set to current local timestamp on successful write.

Acceptance:

1. Applying `merge_section` to a missing page creates it.
2. Applying the same patch twice does not duplicate bullets.
3. Bad slugs cannot escape `persona/wiki/wiki`.
4. `log.jsonl` receives one event per patch.

---

### Task 5.3: Create `wiki_index.py`

File:

```text
subagent/cross_session/wiki/processor/wiki_index.py
```

Use SQLite FTS5.

Database:

```text
persona/wiki/index/wiki.sqlite
```

Tables:

```sql
CREATE TABLE IF NOT EXISTS pages (
  slug TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  type TEXT NOT NULL,
  mode TEXT NOT NULL,
  tags_json TEXT NOT NULL,
  topics_json TEXT NOT NULL,
  links_json TEXT NOT NULL,
  path TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS chunks (
  id TEXT PRIMARY KEY,
  slug TEXT NOT NULL,
  section TEXT NOT NULL,
  text TEXT NOT NULL,
  source_refs_json TEXT NOT NULL DEFAULT '[]',
  FOREIGN KEY(slug) REFERENCES pages(slug)
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  id UNINDEXED,
  slug UNINDEXED,
  section,
  text,
  content=''
);
```

Required class:

```python
class WikiIndex:
    def __init__(self, workspace: Path, wiki_root: Path | None = None): ...
    def rebuild(self) -> None: ...
    def index_page(self, slug: str) -> None: ...
    def remove_page(self, slug: str) -> None: ...
```

Chunking rules:

1. Split page body by `##` sections.
2. Each section is one chunk.
3. If a section is longer than 1200 characters, split by paragraphs.
4. Store `slug`, `section`, and chunk text.

Acceptance:

1. `rebuild()` creates the SQLite file from Markdown pages.
2. `index_page(slug)` updates only one page.
3. Search can find text from a Markdown section.

---

### Task 5.4: Create `wiki_search.py`

File:

```text
subagent/cross_session/wiki/processor/wiki_search.py
```

Required class:

```python
class WikiSearch:
    def __init__(self, workspace: Path, wiki_root: Path | None = None): ...
    def search(
        self,
        query: str,
        mode: str | None = None,
        topic: str | None = None,
        page_type: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
    ) -> list[WikiSearchResult]: ...
```

Ranking v1:

```text
final_score = bm25_score + metadata_boost
```

Boosts:

1. `+2.0` if exact topic match.
2. `+1.0` if mode match.
3. `+1.0` if requested tag is in page tags.
4. `+0.5` if query appears in page title.

Search behavior:

1. Use SQLite FTS5 over `chunks_fts`.
2. Apply metadata filters from `pages`.
3. Return snippets no longer than 500 characters.
4. If FTS returns nothing, fallback to simple title/tag/topic filtering.
5. If SQLite DB or FTS tables do not exist, return an empty list. Do not attempt to rebuild.

Acceptance:

1. Query `"basketball"` returns `ielts/topics/sports` if it contains basketball.
2. Filter `mode="ielts"` excludes `freechat` pages.
3. Filter `topic="sports"` boosts sports pages.
4. Search returns `[]` without raising if the index DB is missing.

---

### Task 5.5: Create `wiki_retriever.py`

File:

```text
subagent/cross_session/wiki/processor/wiki_retriever.py
```

Purpose:

Return prompt-ready wiki context for the main agent.

Required function:

```python
def read_wiki_context(
    workspace: Path,
    query: str,
    mode: str | None = None,
    topic: str | None = None,
    limit: int = 5,
    max_chars: int = 4000,
) -> str:
    ...
```

Output format:

```md
## Relevant Wiki Memory

### ielts/topics/sports — Sports
Section: User Material
User enjoys basketball...

### language/grammar-patterns — Grammar Patterns
Section: Weaknesses
User sometimes says...
```

Rules:

1. Keep output under `max_chars`.
2. Prefer diverse slugs; avoid returning 5 chunks from the same page unless there are no alternatives.
3. Include slug and section so the agent can cite/update the page.

Acceptance:

1. Returns empty string if no wiki exists.
2. Never raises if SQLite is missing; it should return empty results, not rebuild.
3. `WikiSearch.search()` must not call `WikiIndex.rebuild()` in `__init__` or `search()`.

---

### Task 5.6: Create `wiki_subagent.md`

File:

```text
subagent/cross_session/wiki/context/wiki_subagent.md
```

Content requirements:

1. Explain that the subagent converts conversation/processor data into wiki patches.
2. Require JSONL output only.
3. Include allowed operations.
4. Include allowed page types.
5. Include safety rules.
6. Include examples for IELTS, freechat, and Benative.

Example output:

```jsonl
{"operation":"merge_section","slug":"ielts/topics/sports","title":"Sports","type":"ielts_topic","mode":"ielts","section":"User Material","content":"User can use basketball as a personal example for IELTS hobbies and health questions.","tags":["sports","hobbies"],"topics":["sports"],"links":["language/collocations"],"sources":[{"kind":"session","session_id":"abc","message_id":"user:4","timestamp":"2026-05-27T10:00:00+08:00"}],"confidence":"medium","reason":"User used basketball in an IELTS answer."}
```

Acceptance:

1. The prompt tells the LLM not to write prose outside JSONL.
2. The prompt tells the LLM to output `(none)` if there is no useful memory.

---

### Task 5.7: Create `wiki_processor.py`

File:

```text
subagent/cross_session/wiki/processor/wiki_processor.py
```

Responsibilities:

1. Read input data from existing JSONL or Markdown sources.
2. Build prompt using `wiki_subagent.md`.
3. Parse JSONL patches.
4. Apply patches through `WikiStore`.
5. Reindex changed pages through `WikiIndex`.

Required class:

```python
class WikiProcessor(BaseDataProcessor[WikiInput, WikiPatch]):
    name = "wiki"
```

Input sources v1, superseded by the current `persona/events/thread.jsonl`
ingest path:

```text
subagent/single_session/vocab/data/vocab.jsonl
subagent/single_session/polisher/data/polisher.jsonl
subagent/single_session/notes/data/notes.jsonl
persona/processor/freechat/progress_tracker.jsonl
persona/memory/MEMORY.md
```

Important:

1. Do not implement LLM provider logic here if other processors do not.
2. Follow existing `BaseDataProcessor` pattern.
3. If `_call_llm` is not available in current framework, keep a clear TODO and implement parser/store/index first.

Acceptance:

1. Parser accepts valid JSONL.
2. Parser ignores `(none)`.
3. Invalid JSON lines are rejected and logged.
4. Applying parsed patches creates Markdown pages.

---

### Task 5.8: Create `wiki_updater.py`

File:

```text
subagent/cross_session/wiki/processor/wiki_updater.py
```

Reuse cursor logic from KG, but point to wiki data.

Cursor file:

```text
persona/wiki/.cursor.json
```

Sources v1, superseded by the current event-stream ingest path:

```python
SOURCES = [
    "subagent/single_session/vocab/data/vocab.jsonl",
    "subagent/single_session/polisher/data/polisher.jsonl",
    "subagent/single_session/notes/data/notes.jsonl",
    "persona/processor/freechat/progress_tracker.jsonl",
]
```

Required class:

```python
class WikiUpdater:
    def __init__(self, workspace: Path): ...
    def get_pending_sources(self) -> list[str]: ...
    def read_new_lines(self, source: str) -> list[dict]: ...
    def update_source_cursor(self, source: str, processed_lines: int) -> None: ...
```

Acceptance:

1. First run processes all existing lines.
2. Second run processes only new lines.
3. Cursor is updated only after patches are applied successfully.

---

## 6. Knowledge Graph Visualization

The graph is derived from wiki data. Do not store a separate graph database.

The visual effect should be a draggable bubble graph:

1. Nodes appear as circular bubbles.
2. Users can drag individual nodes.
3. Users can drag the canvas.
4. Users can zoom with mouse wheel or trackpad.
5. The graph uses force-directed auto layout.
6. Clicking a page bubble opens the wiki page.
7. Clicking a topic/tag/mode bubble applies a filter.
8. Hovering a bubble shows title, type, tags, summary, and updated time.

Use a mature graph visualization library. Do not hand-roll force layout, zoom, hit detection, or drag behavior in v1.

Recommended v1 library:

```text
react-force-graph-2d
```

Why:

1. It provides bubble-style force graph layout.
2. It supports node drag, canvas pan, and zoom out of the box.
3. Canvas rendering performs well for the expected wiki size.
4. It is simple to connect to the backend graph JSON.

Alternative libraries:

| Library | Use when | Recommendation |
|---|---|---|
| `react-force-graph-2d` | Bubble graph, draggable nodes, zoom/pan, automatic layout | Use for v1 |
| `@xyflow/react` | Manual node layout, flow charts, editable workflows | Do not use for this wiki graph v1 |
| `sigma.js` + `graphology` | Very large or more advanced graph analysis | Consider for v2 |
| Custom SVG | Tiny demo only | Avoid for production v1 |

### 6.1 Graph Model

Nodes:

1. Page nodes:
   - id: page slug.
   - label: page title.
   - kind: `page`.
   - type: page type.
   - mode: page mode.
2. Tag nodes:
   - id: `tag:{tag}`.
   - label: tag.
   - kind: `tag`.
3. Topic nodes:
   - id: `topic:{topic}`.
   - label: topic.
   - kind: `topic`.
4. Mode nodes:
   - id: `mode:{mode}`.
   - label: mode.
   - kind: `mode`.

Edges:

1. Page-to-page links:
   - source: page slug.
   - target: linked page slug.
   - kind: `link`.
2. Page-to-tag:
   - source: page slug.
   - target: `tag:{tag}`.
   - kind: `tagged`.
3. Page-to-topic:
   - source: page slug.
   - target: `topic:{topic}`.
   - kind: `topic`.
4. Page-to-mode:
   - source: page slug.
   - target: `mode:{mode}`.
   - kind: `mode`.

Graph response shape:

```json
{
  "nodes": [
    {
      "id": "ielts/topics/sports",
      "label": "Sports",
      "kind": "page",
      "type": "ielts_topic",
      "mode": "ielts",
      "tags": ["sports"],
      "topics": ["sports"],
      "size": 8
    }
  ],
  "edges": [
    {
      "id": "ielts/topics/sports->topic:sports",
      "source": "ielts/topics/sports",
      "target": "topic:sports",
      "kind": "topic"
    }
  ]
}
```

Frontend data mapping:

`react-force-graph-2d` expects `links`, not `edges`. The WebUI should map backend edges into links:

```ts
const graphData = {
  nodes,
  links: edges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    kind: edge.kind,
  })),
};
```

Suggested visual rules:

1. Page nodes are medium bubbles.
2. Topic nodes are green bubbles.
3. Tag nodes are blue small bubbles.
4. Mode nodes are purple large anchor bubbles.
5. `language_weakness` pages use orange/red page bubbles.
6. `expression_bank` pages use amber page bubbles.
7. Recently updated pages get a highlighted ring.
8. Search matches get a stronger ring and higher opacity.
9. Non-matching nodes in a filtered view should be hidden, not merely faded, in v1.

Suggested sizing:

```text
node_size = 4 + min(16, degree * 2) + recent_update_boost
```

Where:

1. `degree` is number of connected edges.
2. `recent_update_boost` is 4 if updated in the last 7 days, otherwise 0.

### 6.2 Backend Graph API

Add these handlers to `bot/nanobot/channels/websocket.py` next to existing `/api/notes` routes.

Routes:

```text
GET /api/wiki/search?q=...&mode=...&topic=...&type=...&tags=tag1,tag2&limit=10
GET /api/wiki/page?slug=ielts/topics/sports
GET /api/wiki/graph?mode=...&topic=...&type=...&tags=tag1,tag2
GET /api/wiki/patch?data=<urlencoded JSON>
GET /api/wiki/rebuild-index
```

Why GET:

The current WebUI API style in `websocket.py` already uses GET query params for notes because the WebSocket HTTP parser is limited. Follow the existing pattern in v1.

Route behavior:

1. `/api/wiki/search`
   - Calls `WikiSearch.search`.
   - Returns `{ "results": [...] }`.
2. `/api/wiki/page`
   - Calls `WikiStore.read_page`.
   - Returns `{ "meta": {...}, "content": "..." }`.
3. `/api/wiki/graph`
   - Reads all pages from `WikiStore`.
   - Builds graph nodes and edges.
   - Applies optional filters.
   - Returns `{ "nodes": [...], "edges": [...] }`.
4. `/api/wiki/patch`
   - Parses one `WikiPatch` or list of patches from `data`.
   - Applies patches.
   - Reindexes changed pages.
   - Returns `{ "applied": N, "rejected": M, "errors": [...] }`.
5. `/api/wiki/rebuild-index`
   - Calls `WikiIndex.rebuild`.
   - Returns `{ "rebuilt": true }`.

Filter rules for `/api/wiki/graph`:

1. `mode=ielts`: include pages where `mode == "ielts"` plus connected tag/topic/mode nodes.
2. `topic=sports`: include pages where frontmatter `topics` contains `sports` or `tags` contains `sports`.
3. `type=expression_bank`: include pages where `type == "expression_bank"`.
4. `tags=sports,hobbies`: include pages with any matching tag.
5. If no filter is provided, return all nodes but cap page nodes to 300 in v1.

Acceptance:

1. Graph API returns valid JSON when no wiki exists.
2. Graph API returns page, tag, topic, and mode nodes after pages are created.
3. Topic filter returns only matching page nodes and their immediate metadata nodes.
4. Each node includes enough metadata for hover UI:
   - `label`
   - `kind`
   - `type`
   - `mode`
   - `tags`
   - `topics`
   - `updated_at`
   - `summary`
5. Each page node includes a numeric `size`.

---

## 7. Conversation-Based Wiki Updates

There are two update paths.

### 7.1 Automatic Asynchronous Updates

Use `WikiUpdater` and `WikiProcessor`.

Flow:

```text
vocab/polisher/notes/progress data
  -> WikiUpdater finds new lines
  -> WikiProcessor asks LLM for patches
  -> WikiStore applies patches
  -> WikiIndex updates changed pages
```

This is for background memory consolidation.

### 7.2 User-Initiated Chat Updates

The user can update wiki from the existing chat box.

Examples:

```text
记住：我喜欢用排球作为 sports 话题例子
把我之前说喜欢篮球改成更准确：我更喜欢排球
忘掉我喜欢篮球这件事
搜索我的 sports 相关记忆
打开 ielts/topics/sports 这页
```

Implementation v1:

1. Add a small built-in command router before normal chat processing, or add an agent tool.
2. Prefer an agent tool if the existing tool system is easy to extend.
3. Minimum tool names:
   - `search_wiki`
   - `read_wiki_page`
   - `propose_wiki_patch`
   - `apply_wiki_patch`

Recommended first implementation:

1. Implement backend API first.
2. In WebUI, add a wiki panel with a search box and patch editor.
3. Let normal chat continue working.
4. Later expose wiki tools to the LLM.

User safety:

1. If the user explicitly says "remember", "update", or "forget", the change can be proposed immediately.
2. If the agent infers a memory update from casual conversation, it should go through background processor, not immediate overwrite.
3. Destructive operations like `deprecate_fact` should require either:
   - explicit user wording, or
   - UI confirmation.

---

## 8. WebUI Implementation Tasks

### Task 8.1: Add API client functions

File:

```text
bot/webui/src/lib/api.ts
```

Add types:

```ts
export interface WikiSearchResult {
  slug: string;
  title: string;
  type: string;
  mode: string;
  section: string;
  snippet: string;
  score: number;
  tags: string[];
  topics: string[];
}

export interface WikiGraphNode {
  id: string;
  label: string;
  kind: "page" | "tag" | "topic" | "mode";
  type?: string;
  mode?: string;
  tags?: string[];
  topics?: string[];
  size?: number;
}

export interface WikiGraphEdge {
  id: string;
  source: string;
  target: string;
  kind: "link" | "tagged" | "topic" | "mode";
}
```

Add functions:

```ts
fetchWikiSearch(token, params, base?)
fetchWikiPage(token, slug, base?)
fetchWikiGraph(token, params, base?)
applyWikiPatch(token, patchOrPatches, base?)
rebuildWikiIndex(token, base?)
```

Acceptance:

1. Functions follow existing `request<T>()` helper.
2. Query params are encoded with `URLSearchParams`.

---

### Task 8.2: Add `WikiMemoryPanel`

New file:

```text
bot/webui/src/components/WikiMemoryPanel.tsx
```

Panel features:

1. Search input.
2. Filters:
   - Mode: All / IELTS / Freechat / Benative / Language / Global.
   - Topic: text input or dropdown.
   - Type: dropdown.
3. Results list:
   - Show title, slug, type, mode, tags.
   - Show snippet.
   - Click result to open page.
4. Page viewer:
   - Show Markdown content.
   - Show frontmatter summary.
5. Patch editor:
   - Textarea for JSON patch.
   - Apply button.
   - Show applied/rejected result.

Use existing UI components:

```text
Button
Input
Textarea
Sheet
ScrollArea
```

Do not add nested cards. Keep layout simple.

Acceptance:

1. User can search wiki.
2. User can open a page.
3. User can apply a valid patch.
4. Invalid patch shows an error.

---

### Task 8.3: Add `WikiGraphView`

New file:

```text
bot/webui/src/components/WikiGraphView.tsx
```

Recommended dependency:

```text
react-force-graph-2d
```

If adding dependency is not desired, implement a simple SVG graph only for v1. The preferred path is `react-force-graph-2d` because it is faster to implement and gives zoom/pan/node drag.

Features:

1. Bubble graph canvas using `react-force-graph-2d`.
2. Filters:
   - All.
   - By mode.
   - By topic.
   - By page type.
   - By tags.
3. Node colors:
   - Page: neutral.
   - Tag: blue.
   - Topic: green.
   - Mode: purple.
4. Node click:
   - Opens page in `WikiMemoryPanel` if node kind is `page`.
   - Applies filter if node kind is `tag`, `topic`, or `mode`.
5. Drag/zoom/pan:
   - Users can drag nodes.
   - Users can drag the graph canvas.
   - Users can zoom in/out.
   - Users can double-click or use a reset button to fit graph to view.
6. Hover tooltip:
   - Show title, slug/id, type, mode, tags, topics, summary, and updated time.
7. Search highlight:
   - Search results should highlight matching page nodes.
   - Recently updated nodes should show a visible ring or stronger border.
8. Edge labels:
   - Do not render labels by default; show kind in hover tooltip if easy.

Implementation sketch:

```tsx
import ForceGraph2D from "react-force-graph-2d";

<ForceGraph2D
  graphData={{ nodes, links }}
  nodeLabel={(node) => node.summary || node.label}
  nodeVal={(node) => node.size ?? 4}
  nodeAutoColorBy="kind"
  onNodeClick={(node) => {
    if (node.kind === "page") openPage(node.id);
    if (node.kind === "topic") setTopic(node.label);
    if (node.kind === "tag") setTag(node.label);
    if (node.kind === "mode") setMode(node.label);
  }}
/>
```

Do not write a custom physics engine. If `react-force-graph-2d` cannot be installed, use a static SVG fallback for the first pass and leave a TODO to switch to the library.

Acceptance:

1. `/api/wiki/graph` data renders without crashing.
2. Empty graph shows an empty state.
3. Filtering by `topic=sports` updates the graph.
4. Clicking a page node opens the page content.
5. User can drag nodes.
6. User can pan and zoom the graph.
7. Hovering a node shows useful metadata.
8. Search results visually highlight matching nodes.

---

### Task 8.4: Add entry point to App

File:

```text
bot/webui/src/App.tsx
```

Add a floating wiki button similar to `GlobalNotesFloatingButton`, or add an item in the sidebar.

Suggested UI:

```text
Left sidebar:
  Chat sessions
  Settings
  Memory Wiki
```

If sidebar changes are too risky, add a floating button first.

Acceptance:

1. User can open Memory Wiki from the main UI.
2. Existing chat UI still works.
3. Existing GlobalNotes still works.

---

## 9. Agent Tool Integration

This is optional for v1. Do it after backend and UI work.

Create a tool:

```text
bot/nanobot/agent/tools/wiki.py
```

Tool actions:

```text
search
read
propose_patch
apply_patch
graph
```

Tool examples:

```json
{"action":"search","query":"sports basketball","mode":"ielts","limit":5}
{"action":"read","slug":"ielts/topics/sports"}
{"action":"apply_patch","patch":{...}}
```

System prompt guidance:

1. Use wiki search when the user asks about remembered facts.
2. Use wiki search when starting an IELTS topic.
3. Propose a patch when the user says "remember", "update", or "forget".
4. Do not store sensitive information without explicit user request.

Acceptance:

1. The agent can answer "我之前 sports 话题有什么素材？" from wiki.
2. The agent can propose a patch after "记住：我喜欢排球".
3. The agent can read a page by slug.

---

## 10. Replacing KG

Do this only after wiki backend and UI are working.

Steps:

1. Keep `subagent/cross_session/kg/` in place.
2. Add `subagent/cross_session/wiki/`.
3. Add wiki tests.
4. Add wiki API routes.
5. Add WebUI wiki panel.
6. Add graph view.
7. Run tests.
8. Mark KG as deprecated in docs.
9. Remove KG triggers if any exist.
10. Later delete KG code in a separate cleanup PR.

Do not delete KG in the same change that introduces wiki.

---

## 11. Test Plan

### Backend unit tests

Add tests under:

```text
bot/tests/wiki/
```

Tests:

1. `test_wiki_schema.py`
   - Valid patch passes.
   - Bad slug fails.
   - Unknown type fails.
   - Missing source fails.
2. `test_wiki_store.py`
   - Create page.
   - Merge section.
   - Deduplicate bullet (same text does not duplicate Markdown bullet).
   - Merge sources (duplicate fact increments confirmations in sources.json, does not re-add bullet).
   - Add links/tags/topics.
   - Reject path traversal.
3. `test_wiki_index.py`
   - Rebuild index.
   - Index page.
   - Remove page.
4. `test_wiki_search.py`
   - Keyword search.
   - Mode filter.
   - Topic filter.
   - Type filter.
5. `test_wiki_graph_api.py`
   - Empty graph.
   - Graph with page/tag/topic/mode nodes.
   - Topic-filtered graph.

### WebUI tests

Add tests under:

```text
bot/webui/src/tests/
```

Tests:

1. `wiki-memory-panel.test.tsx`
   - Renders search UI.
   - Shows search results.
   - Opens page.
   - Shows patch error.
2. `wiki-graph-view.test.tsx`
   - Renders empty state.
   - Renders graph with nodes.
   - Calls page open handler on page node click.

### Manual test script

Create these files manually or through a test fixture:

```text
persona/wiki/wiki/ielts/topics/sports.md
persona/wiki/wiki/user/preferences.md
```

Run:

```text
rebuild wiki index
search basketball
open graph all
filter graph topic=sports
apply patch to sports page
search new patch content
```

Acceptance:

1. Search finds the new patch.
2. Graph shows the sports page connected to `topic:sports`.
3. UI can open the page.

---

## 12. Implementation Order

Follow this exact order:

1. Add `schema.py`.
2. Add `wiki_store.py`.
3. Add store/schema tests.
4. Add `wiki_index.py`.
5. Add `wiki_search.py`.
6. Add index/search tests.
7. Add `wiki_retriever.py`.
8. Add `wiki_subagent.md`.
9. Add `wiki_processor.py`.
10. Add `wiki_updater.py`.
11. Add backend API routes in `websocket.py`.
12. Add graph builder helper.
13. Add WebUI API client functions.
14. Add `WikiMemoryPanel`.
15. Add `WikiGraphView`.
16. Add App entry point.
17. Add optional agent tool.
18. Deprecate KG.

Important rule:

After each step, run the smallest relevant test before moving on.

---

## 13. Definition of Done

The feature is done when:

1. `persona/wiki/wiki/` contains readable Markdown memories.
2. `persona/wiki/index/wiki.sqlite` can be rebuilt.
3. User can search wiki from WebUI.
4. User can view a page from WebUI.
5. User can apply a wiki patch from WebUI.
6. User can see a graph of all wiki pages.
7. User can filter graph by mode/topic/type/tag.
8. Existing chat, notes, IELTS, and Benative flows still work.
9. Backend tests pass.
10. WebUI tests pass.

---

## 14. V2 Ideas

Do not implement these in v1:

1. Embedding search.
2. Visual graph clustering.
3. Obsidian-compatible backlink generation.
4. Auto-generated `persona/memory/MEMORY.md` from wiki.
5. Conflict review UI.
6. Full version history per page.
7. Multi-user wiki roots.

V1 should stay boring and reliable.
