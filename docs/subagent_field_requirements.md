# Subagent 字段需求表

## Single Session Subagents

### Vocab Processor
| 阶段 | 字段 |
|------|------|
| 入参（第一工程层） | role=user, content.text |
| LLM 输出 | original, improved, type, reason |
| 出参（第二工程层） | id, content, topic, improvements[{original, improved, type, reason}] |
| MD 格式 | 见下方 Vocab MD 模板 |

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
| 入参（第一工程层） | role=user, content.text |
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

### Quiz Processor
| 阶段 | 字段 |
|------|------|
| 入参（第一工程层） | role=assistant, content.text |
| LLM 输出 | question, answer, topic, difficulty |
| 出参（第二工程层） | id, content, topic, quiz_items[{question, answer, topic, difficulty}] |
| MD 格式 | 见下方 Quiz MD 模板 |

**Quiz MD 模板：**
```markdown
# Quiz

## 1
- **题目**: How would you describe someone's basketball skills using a more natural expression?
- **答案**: He is on fire / He is excellent at shooting
- **话题**: basketball
- **难度**: intermediate

## 2
- **题目**: ...
- **答案**: ...
- **话题**: ...
- **难度**: ...
```

### Notes Processor
| 阶段 | 字段 |
|------|------|
| 入参（第一工程层） | role=*, content.text |
| LLM 输出 | title, content, category |
| 出参（第二工程层） | id, content, topic, notes[{title, content, category}] |
| MD 格式 | 见下方 Notes MD 模板 |

**Notes MD 模板：**
```markdown
# Notes

## Topic: Basketball

### 1. Curry 的三分能力
- **分类**: expression
- **内容**: Curry 的三分球命中率很高，经常在关键时刻命中
- **原句**: curry's 3 points is good

### 2. 防守重要性
- **分类**: opinion
- **内容**: 防守在篮球比赛中同样重要
- **原句**: defense is also important
```

## Cross Session Subagents

### KG Builder
| 阶段 | 字段 |
|------|------|
| 入参（第一工程层） | content.text, topic, mode, session_uuid |
| LLM 输出 | entity, entity_type, relations, topics |
| 出参（第二工程层） | entities[], relations[] |
| MD 格式 | 不需要（KG 是结构化数据） |

### Review Builder
| 阶段 | 字段 |
|------|------|
| 入参（第一工程层） | improvements, topic, type |
| LLM 输出 | review_point, question_type, familiarity_hint |
| 出参（第二工程层） | review_points[], review_index{} |
| MD 格式 | 见下方 Review MD 模板 |

**Review MD 模板：**
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

## Thread.jsonl 必需字段（草案）

```json
{
  "id": "string",
  "timestamp": "ISO8601",
  "role": "user|assistant",
  "content": {
    "type": "text|audio",
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

## 待讨论

1. 哪些字段是必须记录的？
2. 哪些字段是可选的？
3. 不同 processor 是否需要不同的过滤条件？
4. MD 模板格式是否需要统一？
