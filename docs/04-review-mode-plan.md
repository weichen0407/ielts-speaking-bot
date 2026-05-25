# Phase 3b: Review Mode (Spaced Repetition)

## 实施顺序

本模块是 **Phase 3b**，依赖于 Phase 2 的 Data Processor Framework。

| Phase | 模块 | 依赖 |
|-------|------|------|
| 1 | Unified Interaction Store (thread.jsonl) | 无 |
| 2 | Data Processor Framework | Phase 1 |
| 3a | Knowledge Graph (NetworkX) | Phase 1 |
| 3b | Review Mode (Spaced Repetition) | Phase 2 |

## Context

用户需要一个「复习模式」，配合现有的 daily_consolidator，实现：
1. 记录用户一天内所有行为和反馈
2. AI 总结每日知识点（类似 daily_consolidator）
3. 将知识点转化为「考题」存入池子
4. 基于类似艾宾浩斯的间隔重复算法，每天抽取题目考察用户
5. 知识点有得分（答对+1，答错0），得分高到阈值后退休，从低分题目中补充

---

## 整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         每日会话 (vocab, polisher, notes)           │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Daily Consolidator (已有)                        │
│            聚合 vocab.md, polisher.md → daily_{date}.md            │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Review Quiz Subagent (新增)                      │
│         读取 daily_{date}.md → 生成 quiz questions → 存入池子      │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     Knowledge Pool (新增)                           │
│              knowledge_pool.jsonl (知识点 + 得分 + 历史)            │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Daily Quiz Trigger (新增)                        │
│         每天定时抽取 X 道题 → 生成 quiz → 用户作答 → 更新得分       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 数据结构

### 1. Knowledge Pool (`shared/knowledge_pool.jsonl`)

每行一个知识点（JSON）：

```json
{
  "id": "kp_uuid",
  "date_created": "2026-05-21",
  "source": "daily_consolidator",
  "source_file": "daily/daily_2026-05-21.md",
  "type": "vocab | grammar | polish",
  "question": "请用更自然的英语表达方式说 'I like hamburgers'",
  "answer": "I'm quite fond of hamburgers",
  "answer_keywords": ["quite fond", "partial to", "have a weakness for"],
  "evaluation_criteria": "是否使用了比 'like' 更自然的表达方式",
  "score": 0,
  "total_attempts": 0,
  "last_attempted": null,
  "status": "active | retired",
  "retired_at": null,
  "tags": ["food", "preference", "ielts"],
  "session_uuid": "original_session_uuid"
}
```

**字段说明**：
- `score`: 累计正确次数
- `total_attempts`: 总尝试次数
- `answer_keywords`: 期望答案中包含的关键词（用于 AI 评估）
- `evaluation_criteria`: 评估标准
- `status`: active（活跃）/ retired（退休）
- `retired_at`: 退休时间（当 score >= threshold 时）

### 2. Quiz History (`shared/quiz_history.jsonl`)

每次quiz的记录：

```json
{
  "quiz_id": "quiz_uuid",
  "date": "2026-05-21",
  "questions": ["kp_uuid1", "kp_uuid2", ...],
  "answers": [1, 0, 1, ...],
  "correct_count": 2,
  "total_count": 3,
  "timestamp": "2026-05-21T08:00:00Z"
}
```

### 3. Daily Summary (已有，扩展)

`daily/daily_{date}.md` 保持现有格式，但新增 `knowledge_points` 数组供 quiz subagent 使用：

```json
{
  "date": "2026-05-21",
  "knowledge_points": [
    {
      "type": "vocab",
      "original": "i like humburgers",
      "improved": "I'm quite fond of hamburgers",
      "focus": "preference expression",
      "topic": "food"
    }
  ]
}
```

---

## 复习模式入口

### 用户流程

```
用户主菜单
    │
    ├─► 雅思练习 (现有模式)
    ├─► 自由聊天 (现有 /freechat)
    └─► 复习模式 (新增)
              │
              ▼
         展示今日 Quiz
         (从 knowledge_pool 选取)
              │
              ▼
         用户语音/文字回答
              │
              ▼
         AI 评估答案
              │
              ▼
         更新知识点得分
         显示下一题或结束
```

**重要**：Quiz 题目在用户结束当天学习后，由 cron 在后台预生成。用户进入复习模式时，看到的是已经准备好的题目。

### 题型设计

**主要题型：口语输出**
- 题目不提供选项，让用户自己组织语言回答
- AI 评估用户回答的正确性和自然度
- 可以复述原句、造句、情景对话等

**问题生成示例**：
```
知识点: "i like humburgers" → "I'm quite fond of hamburgers"

生成问题（口语输出型）:
"请用更自然的英语表达方式说 'I like hamburgers'。尝试使用你今天学到的表达。"

用户回答: "I'm quite fond of hamburgers"
AI 评估: 正确！使用了 "be quite fond of" 这个短语，比 "like" 更自然。
```

**其他可选题型**（扩展）：
- 改错题：给出一个有问题的句子，让用户改正
- 翻译题：给出一个中文句子，让用户翻译成英文
- 造句题：给出一个单词或短语，让用户造句

---

## 新增文件

### 核心模块

| 文件路径 | 用途 |
|---------|------|
| `shared/knowledge_pool.jsonl` | 知识点池 |
| `shared/quiz_history.jsonl` | 答题历史 |
| `knowledge_pool/` | 新增模块目录 |
| `knowledge_pool/__init__.py` | 公共 API |
| `knowledge_pool/pool_manager.py` | 知识点池管理（增删改查、得分更新） |
| `knowledge_pool/quiz_selector.py` | 题目选择算法 |
| `knowledge_pool/question_generator.py` | 从 daily summary 生成题目 |

### Subagent

| 文件路径 | 用途 |
|---------|------|
| `subagents/cross_session/quiz_generator_subagent.md` | 读取 daily summary，生成 quiz questions |
| `subagents/cross_session/quiz_runner_subagent.md` | 执行每日 quiz，向用户提问，收集答案 |
| `subagents/cross_session/quiz_scorer_subagent.md` | 评估用户答案，更新知识点得分 |

### Trigger 配置

| 文件路径 | 用途 |
|---------|------|
| `global/trigger/cron/quiz_cron.yaml` | 每日 quiz 触发时间 |

---

## 流程详解

### Phase 1: 每日知识点提取

**触发时机**：现有的 `daily_consolidator` 执行后（每 8 小时）

**流程**：
1. `daily_consolidator_subagent` 生成 `daily/daily_{date}.md`
2. 触发 `quiz_generator_subagent`

**quiz_generator_subagent**：
- 读取 `daily/daily_{date}.md`
- 读取该日所有的 `vocab.md`, `polisher.md`
- 为每个知识点生成：
  - 一个口语输出型问题
  - 期望的答案/答案要点
- 写入 `shared/knowledge_pool.jsonl`

**问题生成示例**：
```
原文: "i like humburgers"
改进: "I'm quite fond of hamburgers"

生成问题(口语输出型):
{
  "question": "请用更自然的英语表达方式说 'I like hamburgers'。尝试使用你今天学到的表达。",
  "answer": "I'm quite fond of hamburgers",
  "answer_keywords": ["quite fond", "partial to", "have a weakness for"],
  "evaluation_criteria": "是否使用了比 'like' 更自然的表达方式"
}
```

### Phase 2: 每日 Quiz（用户进入复习模式）

**触发时机**：用户从主菜单选择「复习模式」

**题目预生成**（cron，后台）：
- cron job 在每天固定时间（如 20:00，用户结束学习后）运行
- 调用 quiz_generator 生成当日新题目
- 如果当日已有新题目，跳过生成

**quiz_selector 算法**：
```python
def select_quiz_questions(pool, x=5, threshold=3):
    # 1. 过滤 status=active 的题目
    # 2. 按 score 升序排列（得分低的优先）
    # 3. 优先选择 x 道题
    # 4. 如果 active 题目不足 x，从 retired 中随机复活一些
    # 5. 返回选中的题目
```

**阈值退休机制**：
- 当 `score >= threshold`（如 3 次连续正确），标记为 `retired`
- 退休题目保留在池中，但不再自动选择

**Quiz 执行流程**：
1. 用户选择「复习模式」
2. 系统读取 `knowledge_pool.jsonl`，选择 x 道题
3. 依次展示问题给用户（口语回答）
4. 用户回复后，AI 评估答案
5. 调用 `quiz_scorer_subagent` 更新得分
6. 记录到 `quiz_history.jsonl`
7. 展示下一题或结束

### Phase 3: 得分更新

**评估规则**：
- 用户回复包含正确答案 → `score += 1`
- 用户回复错误 → `score = 0`（或 -1，具体待定）
- 更新 `last_attempted` 时间戳

**连续正确奖励**（可选）：
- 如果 `score` 达到 threshold（如 3），标记为 retired
- 可以设计「连续正确 N 次」奖励机制

---

## 复习模式入口

### 主菜单入口

在主菜单中添加「复习模式」选项，用户选择后进入复习流程。

```
mode/review/
├── config.yaml           # review mode 配置
└── trigger/
    └── count/
        └── count.yaml    # 触发条件
```

**config.yaml**：
```yaml
mode: review
quiz:
  questions_per_day: 5
  threshold: 3
  retired_cooldown_hours: 24
```

**复习流程**：
1. 用户从主菜单选择「复习模式」
2. 系统从 knowledge_pool 选择题目
3. 依次展示给用户
4. 用户语音/文字回答
5. AI 即时评估并更新得分
6. 完成后显示统计（正确率、剩余题目等）

---

## 与现有系统集成

### 复用现有组件

1. **data_processor (Phase 2)** - 为本模块提供结构化的 vocab/polisher 数据
2. **knowledge_pool.jsonl** - 存储 quiz 题目
3. **trigger 系统** - 复用现有 cron trigger 机制
4. **subagent spawning** - 复用现有 SubagentManager

### 数据流

```
用户会话 (白天)
    │
    ▼
thread.jsonl (统一日志)
    │
    ▼
data_processor (Phase 2)
    │
    ├─► VocabProcessor ──► shared/vocab.jsonl
    └─► PolisherProcessor ──► shared/polisher.jsonl
    │
    ▼
quiz_generator (cron 触发) ──► knowledge_pool.jsonl

──────────────────────────────────────────────

用户进入复习模式 (主菜单)
    │
    ▼
quiz_runner ──► 选择题目 ──► 展示给用户
    │
    ▼
用户语音/文字回答
    │
    ▼
quiz_scorer ──► 评估答案 ──► 更新得分 ──► knowledge_pool.jsonl
    │
    ▼
记录到 quiz_history.jsonl ──► 展示下一题或结束
```

---

## 验证方式

1. **单元测试**：
   - `pool_manager`: 测试增删改查、得分更新
   - `quiz_selector`: 测试选择算法

2. **集成测试**：
   - 运行一天会话后，检查 `knowledge_pool.jsonl` 有正确条目
   - 触发 quiz，确认题目被正确选择
   - 回答问题后，检查得分被正确更新

3. **手动验证**：
   ```bash
   # 查看知识点池
   cat shared/knowledge_pool.jsonl | jq '.'

   # 查看某个知识点的得分
   jq '.[] | select(.id == "kp_uuid")' shared/knowledge_pool.jsonl

   # 查看 quiz 历史
   cat shared/quiz_history.jsonl | jq '.'
   ```

---

## 文件清单

### 新增文件

```
ielts-speaking-bot/
├── knowledge_pool/                           [NEW]
│   ├── __init__.py
│   ├── pool_manager.py                       # 知识点池管理
│   ├── quiz_selector.py                      # 题目选择算法
│   └── question_generator.py                 # 题目生成
├── shared/
│   ├── knowledge_pool.jsonl                  [NEW] 知识点池
│   └── quiz_history.jsonl                    [NEW] 答题历史
├── mode/
│   └── review/                              [NEW]
│       ├── config.yaml
│       └── trigger/
│           └── count/
│               └── count.yaml
└── subagents/
    └── cross_session/
        ├── quiz_generator_subagent.md        [NEW]
        ├── quiz_runner_subagent.md           [NEW]
        └── quiz_scorer_subagent.md           [NEW]
```

### 修改文件

```
global/trigger/cron/cron.yaml                  [MODIFY] 添加 quiz_runner cron
data_processor/quiz/processor.py               [MODIFY] quiz_generator 实现
```

---

## 待确认

以下问题已在讨论中确认：

1. **每日 quiz 数量**：默认 5 道 ✅
2. **得分阈值**：连续正确 3 次退休 ✅
3. **退休题目的处理**：保留在池中，标记为 retired ✅
4. **quiz 触发时间**：
   - 题目由 cron 在后台预生成（在用户结束学习后）
   - 用户从主菜单进入「复习模式」查看和作答 ✅
5. **问题类型**：口语输出型为主（用户提供答案，AI 评估） ✅
6. **复习模式入口**：主菜单入口 ✅
