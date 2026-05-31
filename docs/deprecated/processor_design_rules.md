# Processor 设计规则

## 核心理念

1. **Thread.jsonl 是数据湖**：记录所有原始字段，供下游不同 processor 按需提取
2. **第一工程层**：按需提取有用字段，减少 token
3. **LLM 输出**：用特殊分隔符（非 JSON），工程层解析
4. **第二工程层**：解析 + 拼接原数据 + 输出

## 数据流

```
thread.jsonl (原始)
    ↓
[第一工程层] 提取字段 → 构建 prompt
    ↓
[LLM] 返回 tab 分隔的文本
    ↓
[第二工程层] parse → 拼接原数据 → 输出
    ↓
┌─────────────┬─────────────┐
│  JSONL     │  MD        │
│  (下游用)  │  (用户体验) │
└─────────────┴─────────────┘
```

## Pydantic 的作用

Pydantic 用于：

| 用途 | 说明 |
|------|------|
| 输入 Schema | 定义 `get_input_schema()`，告诉 LLM 需要处理哪些字段 |
| 输出 Schema | 定义 `get_output_schema()`，告诉 LLM 输出几个字段 |
| 数据验证 | `parse_llm_output()` 后用 Pydantic model 验证 |

```python
class VocabOutput(BaseModel):
    original: str
    improved: str
    type: str
    reason: str

# LLM 输出: "3 points\tthree-point shot\texpression\t更专业"
# parse 后: VocabOutput(original="3 points", improved="three-point shot", ...)
```

## LLM 输出格式规范

### 分隔符选择

使用 `\t`（tab）作为字段分隔符，比 `|` 更明确：

```
original\tthree-point shot\texpression\t在篮球语境中更专业
```

如果一条消息有多个提升点，用 `\n---\n` 分隔：

```
original\tthree-point shot\texpression\t...
original\tis good\tis on fire\tcollocation\t...

---

original\tate rice\thad dinner\tcollocation\t...
```

### 字段数量可变

- 一条用户消息可能没有提升点（输出为空或特定标记如 `(none)`）
- 一条用户消息可能有 1-N 个提升点
- 每个提升点的字段数量应该固定（便于 parse）

## 第二工程层输出

### JSONL 输出

```json
{
  "id": "msg-001",
  "role": "user",
  "content": "curry's 3 points is good",
  "metadata": {"topic": "basketball", "mode": "freechat"},
  "improvements": [
    {"original": "3 points", "improved": "three-point shot", "type": "expression", "reason": "..."},
    {"original": "is good", "improved": "is on fire", "type": "collocation", "reason": "..."}
  ]
}
```

### MD 输出接口

每个 Processor 需要定义自己的 MD 格式，实现 `to_md()` 方法：

```python
def to_md(self, parsed_data: list[U]) -> str:
    """子类实现，定义自己的 MD 输出格式"""
    pass
```

Base 类提供 `serialize()` 方法支持同时写两种：

```python
def serialize(
    self,
    data: list[U],
    jsonl_path: Path,
    md_path: Path,
    format: str = "both"  # "jsonl" | "md" | "both"
):
    if format in ("jsonl", "both"):
        # 写 jsonl
    if format in ("md", "both"):
        md_content = self.to_md(data)
        # 写 md
```

## Thread.jsonl 设计原则

Thread.jsonl 的字段设计要考虑下游 processor 的需求：

| 字段 | 说明 | 用途 |
|------|------|------|
| id | 消息唯一标识 | 拼接、追溯 |
| timestamp | 时间戳 | 时间序列分析 |
| role | user/assistant | 区分来源 |
| mode | freechat/ielts/benative | 模式筛选 |
| session_uuid | 所属 session | 跨 session 分析 |
| message_index | 消息序号 | 顺序、对话流 |
| topic | 话题 | 按话题聚合 |
| content.text | 消息内容 | 主要输入 |
| content.type | 内容类型 | 区分 text/audio |

## Processor 实现检查清单

设计新 Processor 时需要明确：

1. **入参字段**：需要 thread.jsonl 的哪些字段？
2. **过滤条件**：哪些消息需要处理？（如 role=user）
3. **LLM 输出格式**：几个字段，用什么分隔符
4. **输出 Schema**：用 Pydantic 定义几个字段？
5. **JSONL 输出**：包含哪些字段供下游用？
6. **MD 输出**：定义 `to_md()` 方法，指定格式
