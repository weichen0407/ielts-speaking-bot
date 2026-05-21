# IELTS Speaking Bot - Architecture

## 1. 全链路流程总览

```
User Message
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  Session-Level Processing (turn_count based)                     │
│                                                                  │
│  session/metadata["_counter_turn_count"]++                     │
│       │                                                         │
│       ├───── turn_count % 2 == 0 ─── vocab_subagent          │
│       │                                    └──► notes/vocab.md │
│       │                                                         │
│       ├───── turn_count % 3 == 0 ─── polisher_subagent        │
│       │                                    └──► notes/polisher.md
│       │                                                         │
│       └───── turn_count % 10 == 0 ── memory_subagent (已禁用)  │
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  user_responses.jsonl                                          │
│  (每条用户消息追加一行)                                         │
│  {"session_uuid","round","topic","content","timestamp"}         │
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  progress_tracker (file_line_count ≥ 2)                         │
│  gpt-4o-mini, silent                                          │
│  输入: contents[] (content字段，仅文本)                         │
│  输出: save_progress_entries(contents, entries)                  │
│  cursor: .cursor_progress_tracker.json (offset)                 │
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  progress_bank.jsonl                                            │
│  (每条highlight一行)                                           │
│  {"category","intent","expression","content","meta"}            │
└─────────────────────────────────────────────────────────────────┘
       │
       ├──────────────────┐
       │                  │
       ▼                  ▼ (cron: midnight daily)
┌──────────────┐  ┌─────────────────────────┐
│ progress_    │  │  CronJobs (jobs.json)    │
│ organizer    │  │                         │
│ (disabled)   │  │  ┌─ memory_cron ────────┼──► MEMORY.md
│              │  │  │  (midnight)           │     (facts & preferences)
│              │  │  │                      │
│              │  │  └─ daily_              │     daily/
└──────────────┘  │     consolidator          └──► daily_YYYY-MM-DD.md
       │         │     (every 8h)              (vocab + polish聚合)
       │         │
       │         └─ progress_organizer ─────┐
       │              (midnight)            │  (已禁用，依赖depends_on)
       │                                   ▼
       │                           ┌──────────────┐
       │                           │ progress.json │
       │                           │ (merged)      │
       │                           └──────────────┘
       │
       └───────────────────────────────────────────► daily/
                                                    (vocab + polish聚合)
```

---

## 2. Session-Level Subagents (turn_count based)

```
User Message (每条消息)
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  CounterEngine.check_triggers() — session.metadata               │
│  (turn_count: 每N条消息触发一次)                               │
└─────────────────────────────────────────────────────────────────┘
       │
       ├───── turn_count % 2 == 0 ───┬─── vocab_subagent ──► session/notes/vocab.md
       │                               │
       ├───── turn_count % 3 == 0 ───┼─── polisher_subagent ──► session/notes/polisher.md
       │                               │
       └───── turn_count % 10 == 0 ──┴─── memory_subagent (已禁用)

每个 Session 独立计数
```

**触发条件**：
- `vocab_analysis`: `kind: turn_count, count: 2`
- `polish_feedback`: `kind: turn_count, count: 3`
- `memory_update`: `kind: turn_count, count: 10` (已禁用，改用 memory_cron)

---

## 3. user_responses + progress_tracker (file_line_count)

```
User Response
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  session/notes/user_responses.jsonl                            │
│  (每条用户消息追加一行)                                         │
│  {"session_uuid":"...","round":1,"topic":"...","content":"...",│
│   "timestamp":"..."}                                          │
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  CounterEngine — file_line_count                               │
│  condition: kind=file_line_count, path=user_responses.jsonl    │
│  count=2 (当文件≥2行时触发)                                    │
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  progress_tracker_subagent (gpt-4o-mini)                        │
│  输入: contents[] (content字段，仅文本)                         │
│  输出: save_progress_entries(contents, entries)                 │
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  progress_bank.jsonl                                            │
│  {"category","intent","expression","content","meta"}            │
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  .cursor_progress_tracker.json  (offset cursor)                 │
│  {"offset": 150}                                               │
└─────────────────────────────────────────────────────────────────┘
```

**progress_bank.jsonl 条目格式**：
```json
{
  "category": "emotion",
  "intent": "preference",
  "expression": "be fond of",
  "content": "I'm really fond of collecting vintage sneakers",
  "meta": {
    "session_uuid": "...",
    "round": 4,
    "topic": "hobbies",
    "timestamp": "2026-05-21T..."
  }
}
```

---

## 4. progress_organizer (cron-based, disabled)

```
progress_bank.jsonl
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  CronService — jobs.json                                       │
│  schedule: "0 0 * * *" (midnight daily)                        │
│  job.id: "progress_organizer"                                  │
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  on_cron_job (commands.py)                                      │
│  → finds trigger in counter_engine                             │
│  → spawns subagent                                            │
│  → waits for completion                                        │
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  progress_organizer_subagent (gpt-4o-mini)                      │
│  输入: contents[] (expression字段)                               │
│  输出: save_progress_organizer_entries(contents, entries)        │
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  progress.json                                                  │
│  (categories结构: emotion→preference→[{expression,content,meta}]) │
└─────────────────────────────────────────────────────────────────┘
```

**当前状态**：已禁用，通过 `depends_on` 触发改为 cron 独立调度

---

## 5. memory_cron (cron-based)

```
sessions/{uuid}/
  └── thread.jsonl (conversation)
          │  (mtime = 最后修改时间)
          ▼
┌─────────────────────────────────────────────────────────────────┐
│  CronService — jobs.json                                       │
│  schedule: "0 0 * * *" (midnight daily)                        │
│  job.id: "memory_cron"                                         │
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  cron_utils.py — find_modified_sessions()                       │
│  读取 .cursor_memory_cron.json                                  │
│  比较 session/thread.jsonl 的 mtime vs cursor timestamp         │
│  返回: [{path, uuid, topic, updated_at}, ...]                  │
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  .cursor_memory_cron.json                                       │
│  {"last_processed_timestamp": "2026-05-21T00:00:00Z"}          │
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  memory_cron_subagent (gpt-4o-mini)                            │
│  读取 modified sessions 的 thread.jsonl                          │
│  提取 NEW facts/preferences                                     │
│  写入: memory/MEMORY.md                                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 6. daily_consolidator (cron-based)

```
sessions/{uuid}/notes/
  ├── vocab.md
  └── polisher.md
          │  (各自的 mtime)
          ▼
┌─────────────────────────────────────────────────────────────────┐
│  CronService — jobs.json                                       │
│  schedule: "0 */8 * * *" (每8小时)                             │
│  job.id: "daily_consolidator"                                  │
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  cron_utils.py — find_sessions_with_modified_notes()            │
│  读取 .cursor_daily_consolidator.json                          │
│  比较 vocab.md/polisher.md 的 mtime vs cursor                  │
│  返回: [{path, uuid, vocab_path, polisher_path}, ...]          │
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  .cursor_daily_consolidator.json                                │
│  {"last_processed_timestamp": "2026-05-21T00:00:00Z"}          │
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  daily_consolidator_subagent (gpt-4o-mini)                     │
│  读取 modified sessions 的 vocab.md + polisher.md                │
│  聚合写入: daily/daily_2026-05-21.md                            │
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  persona/daily/                                               │
│  ├── daily_2026-05-21.md                                     │
│  ├── daily_2026-05-20.md                                     │
│  └── daily.md (latest)                                         │
└─────────────────────────────────────────────────────────────────┘
```

**daily.md 格式**：
```json
{
  "date": "2026-05-21",
  "generated_at": "2026-05-21T23:59:59Z",
  "vocabulary": {
    "new_words": [...],
    "topic_distribution": {"Family": 5}
  },
  "grammar_patterns": {
    "issues_observed": [...]
  },
  "polish_suggestions": [...],
  "stats": {
    "total_sessions": 3,
    "new_vocabulary_items": 12
  }
}
```

---

## 7. Mode 架构

### 文件组织总览

```
ielts-speaking-bot/
│
├── global/                          # 全局共享（不受 mode 影响，始终运行）
│   ├── trigger/
│   │   ├── count/count.yaml         # 全局 triggers 注册
│   │   └── cron/cron.yaml           # 全局 cron jobs
│   └── (其他全局资源)                # 仅注册，不存放 subagents
│
├── mode/                            # Mode 配置目录
│   ├── freechat/                    # Freechat mode
│   │   ├── context/                 # Bootstrap 文件
│   │   │   ├── AGENTS.md          # Agent 指令
│   │   │   ├── SOUL.md            # 性格定义
│   │   │   ├── USER.md            # 用户模板
│   │   │   ├── HEARTBEAT.md       # 定期任务
│   │   │   ├── TOOLS.md           # 工具说明
│   │   │   └── topic_bank.md      # 话题库
│   │   └── trigger/
│   │       └── count/count.yaml   # Mode-specific triggers
│   │
│   └── ielts/                      # IELTS mode
│       ├── context/                 # Bootstrap 文件
│       │   ├── AGENTS.md          # IELTS 指令
│       │   ├── SOUL.md            # IELTS examiner personality
│       │   ├── USER.md
│       │   └── HEARTBEAT.md
│       └── trigger/
│           └── count/count.yaml     # Mode-specific triggers
│
│   └── benative/                   # Be Native mode
│       ├── context/                 # Bootstrap 文件
│       │   ├── AGENTS.md          # Benative 指令
│       │   ├── SOUL.md            # Native speaker coach
│       │   ├── USER.md
│       │   ├── HEARTBEAT.md
│       │   └── TOOLS.md
│       └── trigger/
│           └── count/count.yaml     # Mode-specific triggers (benative_review)
│
├── subagents/                      # 所有 subagent prompts（集中管理）
│   ├── session/
│   │   ├── vocab_subagent.md
│   │   ├── polisher_subagent.md
│   │   ├── ielts_feedback_subagent.md
│   │   └── benative_review_subagent.md
│   └── cross_session/
│       ├── memory_cron_subagent.md
│       ├── daily_consolidator_subagent.md
│       ├── progress_tracker_subagent.md
│       ├── benative_article_fetcher_subagent.md
│       └── benative_translator_subagent.md
│
└── shared/                        # 共享数据
    ├── memory/MEMORY.md
    ├── daily/daily_*.md
    ├── progress.json
    ├── progress_bank.jsonl
    ├── user_responses.jsonl
    ├── benative/                   # Benative 模式数据
    │   ├── articles/               # 原始文章
    │   ├── pairs/                  # 翻译对 (英文+中文)
    │   └── sessions/{uuid}/         # 用户回答
    │       └── responses.jsonl
    ├── freechat/                   # Freechat 模式数据
    │   └── sessions/{uuid}/        # 用户回答
    │       └── responses.jsonl
    └── .cursor_*.json
```

### 核心概念

| 概念 | 说明 |
|------|------|
| **global/** | 全局共享内容，始终运行。包含 global triggers、cron jobs，不存放 bootstrap |
| **mode/** | 各模式独有内容，只有该模式激活时才加载。包含 bootstrap files、mode-specific triggers |
| **context/** | Mode 内的 bootstrap 文件夹（mode/{mode}/context/），包含 AGENTS.md、SOUL.md 等 |
| **shared/** | 共享数据文件，所有 mode 共用（memory、daily、progress 等） |

---

### 完整工作流程

```
用户消息
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  AgentLoop._state_build()                                  │
│                                                             │
│  1. 获取 session.metadata["mode"]                          │
│     - 有 mode → 使用 mode/{mode}/                          │
│     - 无 mode → 使用 workspace 根目录                       │
│                                                             │
│  2. ContextBuilder.build_system_prompt()                    │
│     - Bootstrap: mode/{mode}/ (或 workspace 根目录)        │
│     - Memory: shared/memory/MEMORY.md                      │
│     - Skills: nanobot skills                               │
│                                                             │
│  3. CounterEngine.check_triggers()                         │
│     - 全局 triggers: global/trigger/count/count.yaml       │
│     - Mode triggers: mode/{mode}/trigger/count/count.yaml  │
└─────────────────────────────────────────────────────────────┘
    │
    ├─────────────────────┬─────────────────────┐
    ▼                     ▼                     ▼
┌─────────┐         ┌─────────┐         ┌─────────┐
│ Global  │         │  Mode   │         │  No    │
│ Triggers│         │ Triggers│         │  Mode  │
│ (always │         │ (only   │         │(normal │
│  run)   │         │  when   │         │  chat) │
│         │         │  active)│         │        │
└────┬────┘         └────┬────┘         └───┬────┘
     │                     │                    │
     ▼                     ▼                    ▼
┌─────────────────────────────────────────────────────────┐
│  SubagentManager.spawn()                                │
│                                                         │
│  Session-level: vocab_subagent, polisher_subagent      │
│    - 每个 session 独立运行                              │
│    - 触发条件: turn_count                              │
│                                                         │
│  Cross-session-level: memory_cron, daily_consolidator  │
│    - 全局运行，不受 mode 影响                           │
│    - 触发条件: cron 或 file_line_count                │
└─────────────────────────────────────────────────────────┘
```

---

### Mode 切换流程

```
用户输入 /freechat 或 /ielts
         │
         ▼
┌──────────────────────────────────────────────┐
│  cmd_freechat / cmd_ielts                    │
│                                              │
│  1. session.metadata["mode"] = "freechat"   │
│  2. counter_engine.set_mode("freechat")      │
│     → 加载 global/trigger/count.yaml        │
│     → 加载 mode/freechat/trigger/count.yaml │
│     → 合并 triggers                          │
│  3. ContextBuilder 使用 mode/freechat/context/
└──────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────┐
│  CounterEngine._triggers = [               │
│    global_triggers + mode_triggers          │
│  ]                                         │
│                                              │
│  Global (始终): memory_cron,               │
│              daily_consolidator,             │
│              progress_tracker                │
│                                              │
│  Mode (仅该 mode 激活时):                  │
│    freechat: vocab, polish                 │
│    ielts:    vocab, polish, ielts_feedback │
└──────────────────────────────────────────────┘
```

---

### Bootstrap 文件作用

每个 mode 的 `context/` 下的文件组成该 mode 的 system prompt：

| 文件 | 内容 | 用途 |
|------|------|------|
| **AGENTS.md** | agent 指令 | 告诉 agent 如何运作 |
| **SOUL.md** | 核心性格 | 定义语气、风格 |
| **USER.md** | 用户 profile | 个性化信息 |
| **HEARTBEAT.md** | 定期任务 | 定时检查的任务 |
| **TOOLS.md** | 工具说明 | 工具使用文档 |

**System prompt 结构**：
```
[Identity]

## AGENTS.md (from global/)
## SOUL.md (from global/)
[Mode AGENTS.md - mode/{mode}/context/]
[Mode SOUL.md - mode/{mode}/context/]
## USER.md
## HEARTBEAT.md
## TOOLS.md

---
[Memory: shared/memory/MEMORY.md]
[Skills: nanobot built-in skills]
```

---

### Subagent 类型

| 类型 | 作用域 | 示例 | 触发方式 |
|------|--------|------|----------|
| **cross_session** | 全局共享 | memory_cron, daily_consolidator | cron / file_line_count |
| **session** | mode-specific | vocab_subagent, polisher_subagent | turn_count |

**Subagent 目录搜索顺序**：
```
load_prompt(trigger):
    1. subagents/{prompt_file}        # 集中管理的 subagents
    2. mode/{mode}/{prompt_file}      # mode-specific
    3. workspace/{prompt_file}       # 回退到 workspace 根目录
```

---

### 不同 Mode 下的 Triggers

| Mode | 激活的 Triggers |
|------|-----------------|
| **无 mode** (默认) | global: memory_cron, daily_consolidator, progress_tracker |
| **freechat** | global + vocab, polish |
| **ielts** | global + vocab, polish, ielts_feedback |
| **benative** | global + benative_review |

**Global Triggers (所有 mode 都运行)**:
- `memory_cron`: cron (0 0 * * *) - 更新用户记忆
- `daily_consolidator`: cron (0 */8 * * *) - 聚合每日笔记
- `progress_tracker`: file_line_count (2) - 跟踪用户表达
- `benative_article_fetcher`: cron (0 12 * * *) - 爬取新闻文章
- `benative_translator`: cron (0 13 * * *) - 翻译文章为中文

**Mode-specific Triggers**:
- `vocab_analysis`: turn_count (2) - 词汇分析
- `polish_feedback`: turn_count (3) - 语法润色
- `ielts_feedback`: turn_count (5) - IELTS 反馈
- `benative_review`: turn_count (10) - Benative 回答评测

---

## 8. 触发条件类型

| 类型 | 条件 | 作用域 | 示例 |
|------|------|--------|------|
| turn_count | 每N条消息 | session (各session独立) | vocab (2), polish (3), ielts_feedback (5) |
| file_line_count | 文件≥N行 | global | progress_tracker (2行) |
| cron | cron表达式 | global (jobs.json调度) | memory_cron (0 0 * * *), daily (0 */8 * * *) |

---

## 9. Cursor 类型

| Cursor文件 | 类型 | 比较方式 |
|-----------|------|---------|
| .cursor_progress_tracker.json | offset | 行号 |
| .cursor_memory_cron.json | timestamp | 文件 mtime vs timestamp |
| .cursor_daily_consolidator.json | timestamp | 文件 mtime vs timestamp |

**Timestamp Cursor 原理**：
- 首次运行：cursor 不存在，处理所有 session
- 后续运行：读取 cursor timestamp，比较 session 文件的 mtime
- mtime > cursor timestamp → 该 session 有新内容，需处理
- 处理完成后：更新 cursor 为当前时间
