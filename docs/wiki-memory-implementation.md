# Wiki Memory 功能实现文档

本文档详细说明项目中的 **Wiki Memory**（LLM Wiki 记忆系统）功能的完整实现，包括数据存储、索引搜索、知识图谱、补丁处理、API 接口以及前端交互。

---

## 1. 功能概述

Wiki Memory 是一个面向 LLM 的持久化知识库系统，用于：
- **结构化存储**：以 Markdown + YAML Frontmatter 格式保存知识页面
- **全文检索**：基于 SQLite FTS5 实现全文搜索
- **知识图谱**：可视化页面之间的链接、标签、主题关系
- **增量更新**：通过 WikiPatch 机制从 LLM 输出增量写入知识
- **来源追踪**：每条知识附带来源（会话 ID、消息 ID 等），支持可信度管理

---

## 2. 架构总览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              前端 (React / WebUI)                            │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │ WikiMemoryPanel │  │ WikiGraphView   │  │ Sidebar Button  │             │
│  │  - 搜索/查看/补丁 │  │  - 2D 力导向图谱 │  │  - 打开面板      │             │
│  └────────┬────────┘  └────────┬────────┘  └─────────────────┘             │
└───────────┼────────────────────┼───────────────────────────────────────────┘
            │ HTTP (Bearer Token)│
            ▼                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         后端 WebSocket Channel                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  bot/nanobot/channels/websocket.py                                   │   │
│  │  - _handle_wiki_search()      GET /api/wiki/search                 │   │
│  │  - _handle_wiki_page()        GET /api/wiki/page                   │   │
│  │  - _handle_wiki_graph()       GET /api/wiki/graph                  │   │
│  │  - _handle_wiki_patch()       GET /api/wiki/patch                  │   │
│  │  - _handle_wiki_rebuild_index GET /api/wiki/rebuild-index          │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │
            ┌───────────────────┼───────────────────┐
            ▼                   ▼                   ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│   WikiTool       │  │  subagent wiki   │  │ WikiRetriever    │
│  (Agent Tool)    │  │  processors      │  │ (Context Prompt) │
│  - search/read   │  │  - store/index   │  │ - read_wiki_     │
│  - apply_patch   │  │  - search/graph  │  │   context()      │
└──────────────────┘  └──────────────────┘  └──────────────────┘
```

---

## 3. 核心模块（subagent/cross_session/wiki/processor/）

### 3.1 schema.py — 数据模型与校验

定义整个 Wiki 系统的 Pydantic 模型：

| 模型 | 说明 |
|------|------|
| `WikiSource` | 单条来源引用（kind, session_id, message_id, file, timestamp） |
| `WikiSourcesEntry` | 事实条目（text, section, sources[], confirmations, first_seen, last_seen） |
| `WikiSourcesData` | 侧边栏 `sources.json` 文件格式 |
| `WikiPatch` | 补丁操作对象（operation, slug, title, type, mode, section, content, tags, topics, links, sources, confidence, reason） |
| `WikiPageMeta` | 页面 Frontmatter 元数据 |
| `WikiSearchResult` | 搜索结果（slug, title, type, mode, section, snippet, score, tags, topics） |

**支持的页面类型**：`user_profile`, `user_preference`, `user_goal`, `communication_style`, `ielts_topic`, `ielts_question_bank`, `ielts_speaking_example`, `language_weakness`, `expression_bank`, `freechat_project`, `freechat_interest`, `benative_article_learning`, `benative_answer_pattern`, `timeline_month`

**支持的模式**：`global`, `ielts`, `freechat`, `benative`, `language`

**支持的补丁操作**：`create_page`, `merge_section`, `append_section`, `replace_section`, `add_link`, `deprecate_fact`, `update_summary`

---

### 3.2 wiki_store.py — Markdown 持久化存储

`WikiStore` 是核心的文件系统存储层，负责读写 Markdown 页面。

**目录结构**：
```
persona/wiki/
├── pages/
│   ├── {slug}.md              # 页面正文 + YAML Frontmatter
│   ├── {slug}.sources.json    # 来源追踪侧边文件
│   └── sub/
│       └── {slug}.md          # 支持子目录
├── index/
│   └── wiki.sqlite            # SQLite FTS 索引
└── log.jsonl                  # 所有补丁操作日志
```

**核心方法**：
- `read_page(slug)` → 读取页面，返回 `(WikiPageMeta, body)`
- `write_page(meta, body)` → 原子写入（先写 `.tmp` 再 `rename`）
- `apply_patch(patch)` → 应用 WikiPatch，支持 7 种操作
- `list_pages()` → 列出所有页面

**补丁操作详解**：

| 操作 | 行为 |
|------|------|
| `create_page` | 新建页面；若已存在则降级为 `merge_section` |
| `merge_section` | 向指定 section 添加内容，自动去重（基于 bullet 归一化），更新 sources |
| `append_section` | 追加内容（不去重），用于时间线类页面 |
| `replace_section` | 整段替换，需填写 `reason` |
| `add_link` | 向 Frontmatter 的 `links` 列表添加链接 |
| `deprecate_fact` | 标记事实过期：sources 中 key 加 `__deprecated_` 前缀，正文 bullet 加 `[DEPRECATED]` |
| `update_summary` | 替换 `## Summary` section |

**去重机制**：
- `merge_section` 使用 `_normalize_bullet()`（小写 + 去除首尾标点 + 去除 bullet 标记）比较重复性
- sources.json 使用 `normalized_fact_key()` 做 key，相同 key 只增加 `confirmations` 计数

---

### 3.3 wiki_index.py — SQLite FTS5 索引

`WikiIndex` 负责构建和维护全文搜索索引。

**数据库结构**：
```sql
-- pages 表：页面元数据
CREATE TABLE pages (slug PRIMARY KEY, title, type, mode, tags, topics, updated_at);

-- chunks 表：文本分块
CREATE TABLE chunks (id PRIMARY KEY AUTOINCREMENT, slug, section, content, chunk_index);

-- chunks_fts：FTS5 虚拟表（基于 chunks.content）
CREATE VIRTUAL TABLE chunks_fts USING fts5(content, content='chunks', content_rowid='id');
```

**分块策略**：
1. 按 `##` heading 分 section
2. 超过 2000 字符的 section 再按空行（段落）细分

**核心方法**：
- `init()` → 建表
- `rebuild()` → 从所有 Markdown 页面重建完整索引
- `index_page(slug)` → 增量索引/重新索引单个页面
- `delete_page(slug)` → 从索引中移除

---

### 3.4 wiki_search.py — FTS 全文搜索

`WikiSearch` 基于 `WikiIndex` 的 SQLite 数据库执行搜索。

**查询能力**：
- `query`：FTS5 `MATCH` 查询，BM25 排序
- `mode` / `topic` / `page_type` / `tags`：SQL 层面过滤
- `limit`：结果上限

**返回结果**：按 `bm25(chunks_fts)` 排序（分数越低越相关），同一页面只返回最佳匹配 chunk。

**Snippet 高亮**：使用 `snippet(chunks_fts, 0, '==', '==', '...', 32)` 在匹配词前后加 `==` 标记。

---

### 3.5 wiki_graph.py — 知识图谱构建

`build_wiki_graph()` 从页面元数据构建图数据，供前端 `react-force-graph-2d` 渲染。

**节点类型**（`kind`）：
- `page`：页面节点（slug → title）
- `tag`：标签节点（`tag:{name}`）
- `topic`：主题节点（`topic:{name}`）
- `mode`：模式节点（`mode:{name}`）

**边类型**（`kind`）：
- `link`：页面 → 页面（Frontmatter `links` 字段）
- `has_tag`：页面 → 标签
- `has_topic`：页面 → 主题
- `has_mode`：页面 → 模式

支持按 `mode` / `topic` / `page_type` / `tags` 过滤图谱。

---

### 3.6 wiki_retriever.py — LLM 上下文检索

`read_wiki_context(query, ...)` 用于在 LLM prompt 中注入相关知识。

- 先执行 FTS 搜索
- 拼接匹配 chunk 为 Markdown 格式
- 限制总长度（默认 4000 字符）
- 超出时降级为只输出标题列表
- 无结果返回 `"(none)"`

---

### 3.7 wiki_processor.py — JSONL 补丁批处理

`WikiProcessor` 解析 LLM 输出的 JSONL 并批量应用补丁。

**处理流程**：
1. 逐行解析 JSONL
2. 跳过 `"(none)"` 空行
3. 无效 JSON 行记录 warning，跳过
4. 有效行构建 `WikiPatch`
5. 调用 `WikiStore.apply_patch()`
6. 成功后调用 `WikiIndex.index_page(slug)` 更新索引

---

### 3.8 wiki_updater.py — 游标式增量更新

`WikiUpdater` 持续扫描外部 JSONL 数据源（如 vocab、polisher、notes 等子代理的输出），增量应用到 Wiki。

**游标机制**：
- 每个源文件维护一个行号游标，记录在 `updater_cursors.json`
- 只处理游标之后的新行
- 成功应用后才推进游标
- 验证失败或补丁拒绝时停止处理（不推进游标）

**默认扫描源**：
```python
DEFAULT_SOURCES = [
    "subagent/single_session/vocab/data/vocab.jsonl",
    "subagent/single_session/polisher/data/polisher.jsonl",
    "subagent/single_session/notes/data/notes.jsonl",
    "subagent/cross_session/progress_tracker/data/progress_bank.jsonl",
]
```

---

## 4. 后端集成

### 4.1 WebSocket Channel API（bot/nanobot/channels/websocket.py）

在 `_dispatch_http()` 中注册了 5 个 Wiki HTTP 端点：

| 端点 | 方法 | 处理器 | 说明 |
|------|------|--------|------|
| `/api/wiki/search` | GET | `_handle_wiki_search` | 全文搜索 |
| `/api/wiki/page` | GET | `_handle_wiki_page` | 读取单个页面 |
| `/api/wiki/graph` | GET | `_handle_wiki_graph` | 获取图谱数据 |
| `/api/wiki/patch` | GET | `_handle_wiki_patch` | 应用补丁（URL-encoded JSON） |
| `/api/wiki/rebuild-index` | GET | `_handle_wiki_rebuild_index` | 重建 FTS 索引 |

**鉴权**：所有端点都通过 `_check_api_token(request)` 检查 Bearer Token。

**Wiki 根目录**：`{project_root}/persona/wiki`

---

### 4.2 Agent Tool（bot/nanobot/agent/tools/wiki.py）

`WikiTool` 注册为 agent 可调用的工具（`name="wiki_memory"`），支持 5 个 action：

| action | 说明 |
|--------|------|
| `search` | 全文搜索，返回结果列表 |
| `read` | 按 slug 读取页面内容和元数据 |
| `propose_patch` | 校验 patch 有效性，返回预览 |
| `apply_patch` | 应用 patch（需要 `RequestContext`，即需要用户确认） |
| `graph` | 获取知识图谱节点和边 |

---

## 5. 前端实现（bot/webui/src/）

### 5.1 组件结构

| 组件 | 文件 | 说明 |
|------|------|------|
| `WikiMemoryPanel` | `components/WikiMemoryPanel.tsx` | 主面板：搜索、页面查看、补丁编辑器 |
| `WikiMemoryFloatingButton` | `components/WikiMemoryPanel.tsx` | 右下角浮动按钮（打开/关闭面板） |
| `WikiGraphView` | `components/WikiGraphView.tsx` | 2D 力导向知识图谱（`react-force-graph-2d`） |

### 5.2 API 客户端（lib/api.ts）

```typescript
fetchWikiSearch(token, { q, mode, topic, type, tags, limit })
fetchWikiPage(token, slug)
fetchWikiGraph(token, { mode, topic, type, tags })
applyWikiPatch(token, patch)
rebuildWikiIndex(token)
```

### 5.3 UI 交互流程

1. 用户点击 Sidebar 的 "Wiki Memory" 或右下角浮动按钮
2. `WikiMemoryPanel` 打开，默认显示 **Search** tab
3. 输入关键词或筛选条件（mode/topic/type/tags），调用 `/api/wiki/search`
4. 点击搜索结果进入 **Page** tab，调用 `/api/wiki/page?slug=...`
5. 页面内容以 Markdown 原文展示，附带 meta 标签
6. **Patch** tab 允许手动粘贴 WikiPatch JSON 并应用
7. 面板顶部有 "Rebuild Index" 按钮，用于重建搜索索引

---

## 6. 数据流示例

### 6.1 LLM 写入知识（通过子代理输出）

```
subagent/single_session/notes/data/notes.jsonl
    │ 每行一个 WikiPatch JSON
    ▼
WikiUpdater.scan_source() ──游标──► WikiProcessor.process_jsonl()
                                       │
                                       ▼
                               WikiStore.apply_patch()
                                       │
                    ┌──────────────────┼──────────────────┐
                    ▼                  ▼                  ▼
            {slug}.md          {slug}.sources.json      log.jsonl
            (页面正文)            (来源追踪)              (操作日志)
                    │                  │
                    ▼                  ▼
              WikiIndex.index_page(slug)
                    │
                    ▼
            persona/wiki/index/wiki.sqlite
```

### 6.2 用户搜索知识

```
用户输入关键词 ──► WikiMemoryPanel.doSearch()
                      │
                      ▼
              fetchWikiSearch() → GET /api/wiki/search?q=...
                      │
                      ▼
              _handle_wiki_search()
                      │
                      ▼
              WikiSearch.search(query)
                      │
                      ▼
              SQLite FTS5 MATCH + BM25
                      │
                      ▼
              返回 WikiSearchResult[]
```

### 6.3 LLM 读取知识（作为上下文）

```
Agent Loop ──► WikiTool(action="search")
                  │
                  ▼
              read_wiki_context(query)
                  │
                  ▼
              WikiSearch.search(query)
                  │
                  ▼
              拼接为 Markdown context string
              注入 LLM prompt
```

---

## 7. 文件清单

### 核心处理器（subagent/cross_session/wiki/processor/）

| 文件 | 行数 | 核心职责 |
|------|------|----------|
| `schema.py` | 208 | Pydantic 模型、slug/类型校验 |
| `wiki_store.py` | 573 | Markdown 读写、补丁应用、来源追踪 |
| `wiki_index.py` | 283 | SQLite FTS5 索引管理 |
| `wiki_search.py` | 148 | FTS 搜索 + BM25 排序 |
| `wiki_graph.py` | 150 | 知识图谱数据构建 |
| `wiki_retriever.py` | 76 | LLM 上下文检索 |
| `wiki_processor.py` | 85 | JSONL 补丁批处理 |
| `wiki_updater.py` | 187 | 游标式增量更新 |

### 后端集成

| 文件 | 职责 |
|------|------|
| `bot/nanobot/channels/websocket.py` | 5 个 Wiki HTTP API 端点 |
| `bot/nanobot/agent/tools/wiki.py` | Agent 可调用的 WikiTool |
| `bot/nanobot/__init__.py` | 确保项目根目录在 `sys.path` 中（使 subagent 可导入） |

### 前端

| 文件 | 职责 |
|------|------|
| `bot/webui/src/components/WikiMemoryPanel.tsx` | 搜索/查看/补丁面板 |
| `bot/webui/src/components/WikiGraphView.tsx` | 2D 力导向图谱 |
| `bot/webui/src/lib/api.ts` | Wiki API 客户端函数 + TypeScript 类型 |
| `bot/webui/src/App.tsx` | 挂载 WikiMemoryPanel 和浮动按钮 |
| `bot/webui/src/components/Sidebar.tsx` | Sidebar "Wiki Memory" 入口 |

---

## 8. 配置与初始化

### 8.1 初始化空 Wiki

Wiki 是惰性创建的——第一次调用 `WikiStore` 或 `WikiIndex` 时会自动创建目录：
```
persona/wiki/pages/
persona/wiki/index/
persona/wiki/log.jsonl
```

### 8.2 重建索引

当 FTS 索引损坏或需要全量重建时：
- 前端点击面板顶部的 "Rebuild Index" 按钮
- 后端调用 `WikiIndex.rebuild()`
- 遍历所有 `pages/**/*.md`，重新分块并写入 `chunks_fts`

### 8.3 从外部源导入

运行 `WikiUpdater.scan_all()` 可一次性扫描所有默认 JSONL 源，将子代理输出同步到 Wiki。

---

## 9. 关键设计决策

1. **Markdown + YAML Frontmatter**：人类可读，便于手动编辑和版本控制
2. **sources.json 侧边文件**：将来源追踪与正文分离，保持 Markdown 纯净
3. **FTS5 + BM25**：轻量、无需外部依赖、支持 snippet 高亮
4. **WikiPatch 原子操作**：7 种精细操作覆盖增删改，支持去重和来源累积
5. **游标式增量更新**：保证子代理输出不会重复处理，失败时安全停止
6. **路径隔离**：所有 slug 经过 `_validate_slug()` 和路径遍历检查，防止 `../` 攻击
