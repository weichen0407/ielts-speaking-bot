# 实施计划总结

## 四个设计文档

| Phase | 文档 | 核心内容 |
|-------|------|----------|
| 1 | `01-unified-interaction-store.md` | Session 划分，统一日志 `thread.jsonl` |
| 2 | `02-data-processor-framework.md` | Data Processor 机制，每个功能定义自己的 Schema |
| 3a | `03-networkx-knowledge-graph-plan.md` | 知识图谱，语义实体提取 |
| 3b | `04-review-mode-plan.md` | 复习模式，Spaced Repetition |

---

## Session 的划分原则

| 类型 | 示例 | 是否计入 |
|------|------|----------|
| IELTS 练习 | 用户开始一次 IELTS 话题练习 | ✅ |
| Freechat | 用户发起 /freechat | ✅ |
| Benative | 用户发起 /benative | ✅ |
| Review 复习 | 用户进入复习模式答题 | ✅ |
| Notes 笔记 | 用户在笔记功能中留言 | ❌ (附属) |

---

## 实施顺序

```
Phase 1 ──► Phase 2 ──┬──► Phase 3a (Knowledge Graph)
                       │
                       └──► Phase 3b (Review Mode)
```

Phase 3a 和 3b 可以并行开发。

---

## Phase 1: 统一日志 (thread.jsonl)

**核心**：SessionManager.save() 同时写入 `shared/thread.jsonl`

**新增文件**：
- `shared/thread.jsonl`

---

## Phase 2: Data Processor Framework

**核心**：每个功能定义自己的 Processor + Schema

**机制**：
1. 创建新功能 → 在 `data_processor/` 下创建 Processor
2. 定义 `schema.py` → Pydantic 验证输入输出
3. 定义 `processor.py` → 继承 BaseDataProcessor
4. 配置 trigger → count/cron 触发执行

**新增文件**：
```
data_processor/
├── base.py
├── vocab/schema.py + processor.py
├── polisher/schema.py + processor.py
└── ...
```

---

## Phase 3a: Knowledge Graph (NetworkX)

**核心**：语义实体提取，个性化推荐

**输入**：`thread.jsonl`
**输出**：`shared/graph/knowledge_graph.pkl`

---

## Phase 3b: Review Mode

**核心**：Spaced Repetition 复习系统

**输入**：`data_processor` 输出
**输出**：`shared/knowledge_pool.jsonl`, `shared/quiz_history.jsonl`

---

## 完整数据流

```
用户会话 (Session)
    │
    ▼
SessionManager.save()
    │
    ├──► session/{uuid}/thread.jsonl
    │
    └──► shared/thread.jsonl

──────────────────────────────────────

trigger 触发 (count/cron)
    │
    ▼
data_processor/
    │
    ├── VocabProcessor → shared/vocab.jsonl
    ├── PolisherProcessor → shared/polisher.jsonl
    └── QuizProcessor → shared/knowledge_pool.jsonl

──────────────────────────────────────

Phase 3a: entity_extractor → shared/graph/

Phase 3b: quiz_runner → 用户回答 → 更新得分
```

---

## 关键文件路径

```
shared/
├── thread.jsonl              # Phase 1
├── vocab.jsonl              # Phase 2
├── polisher.jsonl           # Phase 2
├── knowledge_pool.jsonl      # Phase 3b
├── quiz_history.jsonl       # Phase 3b
└── graph/
    └── knowledge_graph.pkl  # Phase 3a

data_processor/              # Phase 2
├── base.py
├── vocab/
├── polisher/
├── quiz/
└── notes/

knowledge_pool/              # Phase 3b
├── pool_manager.py
├── quiz_selector.py
└── question_generator.py

knowledge_graph/             # Phase 3a
├── node_types.py
├── edge_types.py
├── graph_store.py
├── entity_extractor.py
└── graph_query.py
```
