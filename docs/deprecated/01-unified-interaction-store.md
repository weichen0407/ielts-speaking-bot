# Phase 1: Unified Interaction Store (Activity Log)

## 实施顺序

本模块是 **Phase 1**，是所有后续功能的基础。

| Phase | 模块 | 依赖 |
|-------|------|------|
| 1 | Unified Interaction Store | 无 |
| 2 | Data Processor Framework | Phase 1 |
| 3a | Knowledge Graph (NetworkX) | Phase 1 |
| 3b | Review Mode (Spaced Repetition) | Phase 2 |

## Context

### 现状问题

目前的数据流是：
- 每个 session 有独立的 `thread.jsonl`
- Vocab Subagent 从 session 的 thread 读取内容
- Polisher Subagent 从 session 的 thread 读取内容
- Quiz Generator 从 daily summary 读取内容
- Notes AI Assistant 单独处理 notes

问题：
1. **数据分散**：不同来源（freechat, benative, quiz, notes）的数据格式不统一
2. **难以跨会话查询**：想找「用户所有关于 food 的交互」需要遍历所有 session
3. **Subagent 耦合**：每个 subagent 直接读取 thread.jsonl，格式变化时都要改

### 设计目标

建立一个**统一的交互日志**，所有用户和 AI 的对话内容都记录其中，不同的 subagent 从中按需提取数据，生成各自的输出。

遵循 nanobot 的核心原则：**所有用户和 LLM 的交互都要记录到 JSONL**

---

## Session 的划分

### 什么是 Session？

一个 **Session** 是用户与 AI 之间一次完整的对话交互过程。当用户主动发起一次对话（切换话题、切换模式、结束当前对话），就形成一个新的 Session。

### Session 类型

| 类型 | 触发方式 | 示例 | 是否计入 |
|------|----------|------|----------|
| **IELTS 练习** | 用户开始一次 IELTS 话题练习 | 练习 "Favorite Sport" | ✅ |
| **Freechat** | 用户发起 /freechat | 自由聊天 | ✅ |
| **Benative** | 用户发起 /benative | 中英翻译练习 | ✅ |
| **Review 复习** | 用户进入复习模式 | 回答 quiz 题目 | ✅ |
| **Notes 笔记** | 用户添加笔记 | 在笔记功能中留言 | ❌ (附属) |

### Session 边界定义

```
用户 ──► Freechat Session ──► 结束 ──► Benative Session ──► 结束
              │                              │
              └── session_uuid: xxx          └── session_uuid: yyy

用户 ──► IELTS Session (Topic: Food) ──► 结束 ──► IELTS Session (Topic: Hobbies)
                                     │                              │
                                     └── session_uuid: zzz         └── session_uuid: www
```

### Notes 的特殊性

Notes（笔记）是**附属**在会话内部的功能：
- Notes 的内容来自用户在一个 Session 中的留言
- Notes 的 AI 回复也属于该 Session
- Notes 不单独计算为 Session

```
Session (freechat)
    │
    ├── 用户消息 1
    ├── AI 回复 1
    │
    ├── 用户添加 Note (附属，不产生新 Session)
    │   └── 记录到 session/notes/
    │
    └── 用户消息 2
```

### Event Sourcing / Activity Log

```
┌─────────────────────────────────────────────────────────────┐
│                    User ──── AI                             │
│                    User ──── AI                             │
│                    User ──── AI                             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              Unified Interaction Store                       │
│                 (shared/)                                   │
│                   thread.jsonl                              │
│              (append-only, 按时间顺序)                       │
└─────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
    ┌──────────┐       ┌──────────┐       ┌──────────┐
    │  Vocab   │       │ Polisher │       │   Quiz   │
    │ Processor│       │ Processor│       │Generator │
    └────┬─────┘       └────┬─────┘       └────┬─────┘
         │                  │                  │
         ▼                  ▼                  ▼
    vocab.jsonl       polisher.jsonl     knowledge_pool.jsonl

    ┌──────────┐       ┌──────────┐       ┌──────────┐
    │  Notes   │       │ Memory   │       │ Progress │
    │ Processor│       │   Cron   │       │ Tracker │
    └──────────┘       └──────────┘       └──────────┘
```

### 与 Message Bus 的区别

| | Message Bus | Unified Interaction Store |
|--|-------------|---------------------------|
| **目的** | 通信（异步传递） | 数据持久化（日志） |
| **生命周期** | 消息消费即消失 | Append-only，永久保留 |
| **消费模式** | 实时消费 | 可重复消费（subagent 按需读取） |
| **典型用途** | 事件通知、解耦 | 数据分析、重放、审计 |

---

## 数据结构

### Interaction Log (`shared/interactions/thread.jsonl`)

每行一条交互记录（JSON）：

```json
{
  "id": "interaction_uuid",
  "timestamp": "2026-05-21T14:30:00Z",
  "source": {
    "type": "session | note | quiz",
    "mode": "ielts | freechat | benative | review",
    "session_uuid": "session_uuid_or_null",
    "message_index": 0
  },
  "role": "user | assistant",
  "content": {
    "type": "text | audio",
    "text": "用户说的话或AI的回复",
    "audio_url": "optional_audio_url"
  },
  "metadata": {
    "topic": "food",
    "intent": "preference",
    "channel": "telegram",
    "languages": ["en", "zh"]
  }
}
```

**字段说明**：
- `id`: 全局唯一 ID
- `timestamp`: 精确到秒的时间戳
- `source.type`:
  - `session`: 来自会话（freechat, benative, ielts 等）
  - `note`: 来自用户笔记
  - `quiz`: 来自 quiz 回答
- `source.mode`: 模式标识
- `role`: user（用户）或 assistant（AI）
- `content.type`: text（文本）或 audio（语音）
- `metadata`: 可扩展的元数据

### 元数据索引 (`shared/interactions/index.json`)

为了快速查询，建立索引文件：

```json
{
  "last_updated": "2026-05-21T23:59:00Z",
  "total_interactions": 1234,
  "by_mode": {
    "ielts": 500,
    "freechat": 200,
    "benative": 150,
    "review": 100
  },
  "by_topic": {
    "food": 45,
    "hobbies": 32,
    "education": 28
  },
  "by_session": {
    "session_uuid_1": 24,
    "session_uuid_2": 18
  }
}
```

索引在每次 append 后更新，或定期批量更新。

---

## 数据流

### 写入流程

```
用户消息 ──► AgentLoop ──► SessionManager.save()
                              │
                              ├──► sessions/{uuid}/thread.jsonl (已有)
                              │
                              └──► interactions/thread.jsonl (新增)
```

**实现要点**：
1. 在 `SessionManager.save()` 中同时写入两个文件
2. `thread.jsonl` 使用 append 模式，不做全文重写
3. 保证两个写入的原子性（或 eventual consistency）

### 读取流程

```
Subagent 触发
    │
    ▼
读取 thread.jsonl
    │
    ├──► 按 filter 过滤（mode, topic, date_range, session_uuid）
    │
    ▼
Subagent 特定的处理逻辑
    │
    ▼
生成 output (vocab.md, polisher.md, quiz_pool, etc.)
```

---

## 目录结构

```
ielts-speaking-bot/
├── shared/
│   └── thread.jsonl              # 统一的交互日志 (append-only)
└── ...
```

**注意**：`thread.jsonl` 是 append-only 的追加日志，不需要复杂的索引结构。索引可在读取时按需构建。

---

## Subagent 适配

### Vocab Subagent

**输入**： thread.jsonl 中该 session 的所有 user 消息
**输出**： vocab.md（不变）

**适配**：
```python
# 原来：从 session/thread.jsonl 读取
# 现在：从 thread.jsonl 读取，filter session_uuid
```

### Polisher Subagent

**输入**： thread.jsonl 中该 session 的所有消息（user + assistant）
**输出**： polisher.md（不变）

### Quiz Generator

**输入**： thread.jsonl 中某日的所有交互
**输出**： knowledge_pool.jsonl 中的新题目

### Daily Consolidator

**输入**： thread.jsonl 中某日的所有交互
**输出**： daily/daily_{date}.md（不变）

### Memory Cron

**输入**： thread.jsonl 中新增的交互
**输出**： MEMORY.md（不变）

---

## 扩展功能

### 1. 跨会话查询

```python
# 查找用户所有关于 food 的交互
query_interactions(
    topic="food",
    role="user",
    limit=100
)

# 查找用户在 freechat 模式下说了什么
query_interactions(
    mode="freechat",
    role="user",
    date_range=("2026-05-01", "2026-05-21")
)
```

### 2. 数据重放

```python
# 重放某天的所有交互
replay_interactions(date="2026-05-21")
```

### 3. 统计分析

```python
# 用户最常用的话题
get_topic_distribution(user_id="xxx")

# 用户的平均回答长度
get_avg_response_length(user_id="xxx")
```

---

## 与现有系统集成

### 兼容性

1. **thread.jsonl 保留**：现有 session 仍使用 thread.jsonl，不改变
2. **thread.jsonl 新增**：作为统一日志新增
3. **索引按需构建**：不需要实时更新，可以用 cron 定期批量更新索引

### 数据一致性

写入流程：
```
AgentLoop ──► SessionManager.save()
                    │
                    ├──► thread.jsonl (已有)
                    │
                    └──► thread.jsonl (append)
```

如果 thread.jsonl 写入失败，不影响 thread.jsonl（已有的原子性保持）。

可以设计「追账」机制：定期检查两个文件的差异，补全缺失的交互。

---

## 实现顺序

### Phase 1: 基础设施（本文档）

1. 创建 `shared/` 目录（如果不存在）
2. 修改 `SessionManager.save()` 同时写入 `shared/thread.jsonl`
3. 保留现有的 `sessions/{uuid}/thread.jsonl` 不变

**关键实现**：
- `SessionManager.save()` 在保存 session 的同时，append 到 `shared/thread.jsonl`
- 不改变现有的 session thread.jsonl 结构
- `shared/thread.jsonl` 是独立的追加日志

---

## 文件清单

### 新增文件

```
shared/
└── thread.jsonl                   # 统一交互日志 (gitignore)
```

### 修改文件

```
bot/nanobot/session/manager.py    # MODIFY: 同时写入 shared/thread.jsonl
```

---

## 命名确认

使用 `thread.jsonl` 而非 `interactions.jsonl`，与 nanobot 现有命名保持一致。
