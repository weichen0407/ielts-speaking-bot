# Subagent 字段需求表

## Processor 分层

| 层级 | 说明 |
|------|------|
| Level 1 | thread.jsonl - 原始对话 |
| Level 2 | Vocab, Polisher, Notes - 单 session 处理 |
| Level 3 | KG Builder, Review Builder, Quiz - 跨 session 汇总 |

---

## Level 2 Processors

### Vocab Processor
| 阶段 | 字段 |
|------|------|
| 入参（第一工程层） | id, role=user, content.text, topic |
| LLM 输出 | original, improved, type, reason |
| 出参（第二工程层） | id, content, topic, improvements[{original, improved, type, reason}] |
| MD 格式 | 见下方 Vocab MD 模板 |

**Topic 来源：**
- freechat mode：LLM 生成 freechat 时确定 session 名称（topic），从固定话题分类中选择
- 分类体系：雅思话题 / 通用闲聊（如 Basketball, Food, Hobbies 等）

**Vocab MD 模板：**
```markdown
# Vocab

## 1
- **原文**: 3 points
- **提升**: three-point shot
- **类型**: expression
- **原句**: curry's 3 points is good
- **解释**: 在篮球语境中，"three-point shot" 是更专业的术语

## 2
- **原文**: is good
- **提升**: is on fire
- **类型**: collocation
- **原句**: curry's 3 points is good
- **解释**: "on fire" 是英语习语，表示状态火热
```

### Polisher Processor
| 阶段 | 字段 |
|------|------|
| 入参（第一工程层） | id, role=user, content.text, topic |
| LLM 输出 | original, improved, grammar_type, explanation |
| 出参（第二工程层） | id, content, topic, polishings[{original, improved, grammar_type, explanation}] |
| MD 格式 | 见下方 Polisher MD 模板 |

**Polisher MD 模板：**
```markdown
# Polisher

## 1
- **原文**: i like
- **提升**: I'm quite fond of
- **语法类型**: verb phrase
- **原句**: i like collecting sneakers
- **解释**: 使用 "quite fond of" 比 "like" 更正式，表达更细腻

## 2
- **原文**: very good
- **提升**: excellent
- **语法类型**: adjective
- **原句**: this is very good
- **解释**: "excellent" 比 "very good" 更简洁有力
```

### Notes Processor
| 阶段 | 字段 |
|------|------|
| 入参（第一工程层） | id, topic, reference（可选）, user_question |
| LLM 输出 | title, content, category |
| 出参（第二工程层） | id, topic, reference, notes[{title, content, category}] |
| MD 格式 | 见下方 Notes MD 模板 |

**Notes 说明：**
- 用户主动记录不会的表达
- reference：对话中相关的回复（可选），提供上下文
- user_question：用户自己写的提问

**Notes MD 模板：**
```markdown
# Notes

## Topic: Basketball

### 1. 三分球怎么说
- **分类**: vocabulary
- **内容**: 用户问三分球怎么说
- **参考**: "curry's 3 points is good"
- **上下文**: 用户想表达 Curry 三分球很准

### 2. 防守重要性
- **分类**: opinion
- **内容**: 用户想表达防守也很重要
- **参考**: "defense is also important"
- **上下文**: ...
```

---

## Level 3 Processors

### KG Builder
| 阶段 | 字段 |
|------|------|
| 入参（第一工程层） | 所有 L2 文件的增量（cursor） |
| LLM 输出 | entity, entity_type, relations, topics |
| 出参（第二工程层） | entities[], relations[] |
| MD 格式 | 不需要（KG 是结构化数据，用 NetworkX） |

### Review Builder（第一步：总结知识点）
| 阶段 | 字段 |
|------|------|
| 入参（第一工程层） | 所有 L2 文件的增量（cursor） |
| LLM 输出 | review_point, question_type, familiarity_hint |
| 出参（第二工程层） | review_points[], review_index{} |
| MD 格式 | 见下方 Review MD 模板 |

**Review Builder MD 模板：**
```markdown
# Review

## 1. three-point shot
- **复习点**: three-point shot
- **题目类型**: sentence_use
- **熟悉度提示**: 3/5
- **示例**: Curry is on fire from three-point range tonight.

## 2. be fond of
- **复习点**: be fond of
- **题目类型**: translation
- **熟悉度提示**: 2/5
- **示例**: I'm quite fond of collecting vintage sneakers.
```

### Quiz（第二步：生成问题和答案）
| 阶段 | 字段 |
|------|------|
| 入参 | Review Builder 输出的知识点 |
| LLM 输出 | question, answer, difficulty |
| 出参 | quiz_items[{question, answer, difficulty}] |
| MD 格式 | 见下方 Quiz MD 模板 |

**Quiz MD 模板：**
```markdown
# Quiz

## 1
- **题目**: How would you describe someone's basketball skills using a more natural expression?
- **答案**: He is on fire / He is excellent at shooting
- **难度**: intermediate

## 2
- **题目**: Translate: 我非常喜欢收集球鞋
- **答案**: I'm quite fond of collecting sneakers
- **难度**: intermediate
```

---

## Cross Session Subagents（非 Level）

### Memory Cron
| 阶段 | 字段 |
|------|------|
| 入参（第一工程层） | content.text, timestamp, session_uuid |
| LLM 输出 | fact_type, fact_content, topics |
| 出参（第二工程层） | 更新 MEMORY.md |
| MD 格式 | 不需要（直接更新 MEMORY.md） |

### Daily Consolidator
| 阶段 | 字段 |
|------|------|
| 入参（第一工程层） | improvements集合, topic分布 |
| LLM 输出 | summary, stats, highlights |
| 出参（第二工程层） | daily_{date}.md |
| MD 格式 | 见下方 Daily MD 模板 |

**Daily MD 模板：**
```markdown
# Daily Report - 2026-05-25

## 统计
- 总消息数: 45
- 用户消息: 30
- 新词汇: 12
- 新语法: 8

## 词汇亮点
- be fond of (代替 like)
- three-point shot (代替 3 points)
- be on fire (代替 is good)

## 语法亮点
- 使用 "quite fond of" 替代 "very like"
- 使用比较级和最高级

## 话题分布
- Basketball: 15
- Food: 10
- Hobbies: 8
```

---

## Thread.jsonl 字段

```json
{
  "id": "string",
  "timestamp": "ISO8601",
  "role": "user|assistant",
  "content": {
    "text": "string"
  },
  "source": {
    "mode": "freechat|ielts|benative",
    "session_uuid": "string"
  },
  "metadata": {
    "topic": "string|null",
    "message_index": "int"
  }
}
```

**说明：**
- content 只有 text 字段（ASR 后的文本）
- 统一格式，无需 type 字段

## 待讨论

1. Topic 分类体系：雅思话题 vs 通用闲聊，具体有哪些分类？
2. Notes 的 user_question 是用户自己输入，还是从对话中提取？
3. Quiz 的答案需要后续 AI 比对，是否需要存储多种参考答案？
