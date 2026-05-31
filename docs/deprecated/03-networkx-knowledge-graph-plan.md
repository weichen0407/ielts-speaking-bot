# Phase 3a: Knowledge Graph (NetworkX)

> **⚠️ DEPRECATED** — This module is superseded by the LLM Wiki Memory System (`subagent/cross_session/wiki/`). It is kept in place for reference only. Do not use for new development.

## 实施顺序

本模块是 **Phase 3a**，可与 Phase 3b 并行开发。

| Phase | 模块 | 依赖 |
|-------|------|------|
| 1 | Unified Interaction Store (thread.jsonl) | 无 |
| 2 | Data Processor Framework | Phase 1 |
| 3a | Knowledge Graph (NetworkX) | Phase 1 |
| 3b | Review Mode (Spaced Repetition) | Phase 2 |

## Context

构建用户知识图谱系统，将用户的个人信息、兴趣爱好、IELTS 话题等所有内容建模为图结构。这可以实现：
- 基于用户兴趣生成更个性化的 IELTS 话题
- 连接用户背景与相关词汇/短语
- 在对话中引用用户的具体经历
- 跟踪学习进度和薄弱点

## 架构概览

```
knowledge_graph/
├── __init__.py              # 公共 API 导出
├── node_types.py            # 节点类型定义 (Enum + dataclass)
├── edge_types.py            # 边类型定义 (Enum + dataclass)
├── graph_store.py           # NetworkX 图持久化 (pickle + JSON backup)
├── entity_extractor.py      # 从对话中提取实体
├── graph_query.py           # Subagent 查询接口
└── knowledge_graph.pkl      # 图数据文件
```

**与现有系统共存**：MEMORY.md 保留为人类可读格式，知识图谱提供程序化查询能力。

---

## 详细实现

### 1. 节点类型 (`node_types.py`)

```python
from enum import Enum
from dataclasses import dataclass, field

class NodeType(Enum):
    USER_PERSON = "user_person"           # 用户本人
    USER_INTEREST = "user_interest"       # 兴趣/爱好
    USER_EXPERIENCE = "user_experience"   # 个人经历
    VOCAB_ITEM = "vocab_item"             # 词汇/短语
    IELTS_TOPIC = "ielts_topic"            # IELTS 话题
    IELTS_SUBTOPIC = "ielts_subtopic"      # Part 1/2/3 子话题
    SESSION = "session"                   # 会话
    GRAMMAR_PATTERN = "grammar_pattern"    # 语法模式
    WEAKNESS = "weakness"                # 薄弱点

@dataclass
class KGNode:
    node_id: str
    node_type: NodeType
    label: str
    properties: dict = field(default_factory=dict)
    # properties 可包含: confidence, source_session, first_mentioned, last_updated
```

### 2. 边类型 (`edge_types.py`)

```python
from enum import Enum

class EdgeType(Enum):
    HAS_INTEREST = "has_interest"           # person → interest
    EXPERIENCED_IN = "experienced_in"       # person → topic (用户谈论过)
    RELATED_TO = "related_to"               # topic ↔ topic
    ASSOCIATED_WITH = "associated_with"     # vocab → topic
    WEAKNESS_IN = "weakness_in"            # person → weakness
    SESSION_COVERED = "session_covered"    # session → topic
    CONFUSED_WITH = "confused_with"        # vocab ↔ vocab
    IMPROVED_FROM = "improved_from"        # weak → improved
```

### 3. 图持久化 (`graph_store.py`)

核心类 `KnowledgeGraphStore`：
- **Primary**: pickle 格式（NetworkX 原生，高效）
- **Backup**: JSON 格式（可读，可 git diff）
- **Lock file**: `.lock` 文件用于并发安全
- **Atomic write**: 先写临时文件，成功后 rename

关键方法：
- `load() / save(graph)` - 加载/保存图
- `add_node(node) / add_edge(edge)` - 添加节点/边
- `query_nodes(node_type, **filters)` - 按类型和属性查询
- `get_related_topics(topic_id, max_depth)` - 图遍历找相关话题

### 4. 实体提取 (`entity_extractor.py`)

从用户对话中提取结构化实体：

```python
class EntityExtractor:
    PERSONAL_PATTERNS = [
        (r"I'm a(?:n)? (\w+)", "occupation"),
        (r"I work as (?:a |an )?(\w+)", "occupation"),
        (r"I study (\w+)", "field_of_study"),
        (r"I'm from ([A-Z][a-z]+)", "hometown"),
    ]

    INTEREST_PATTERNS = [
        (r"I (?:really |very much )?(?:like|enjoy|love|am into) ([^\n,]+)", "interest"),
        (r"My favorite (?:\w+ )?(?:is|are) ([^\n,]+)", "favorite"),
    ]

    def extract_from_text(self, text: str, session_uuid: str) -> list[ExtractedEntity]
    def extract_from_thread(self, thread_path: Path, session_uuid: str) -> list[ExtractedEntity]
```

### 5. 图查询接口 (`graph_query.py`)

为 subagent 提供高级查询：

```python
class GraphQuery:
    def get_user_interests(self) -> list[dict]
    def get_user_topics_discussed(self) -> list[dict]
    def get_topic_vocabulary(self, topic_id: str) -> list[dict]
    def get_user_weaknesses(self) -> list[dict]
    def get_related_topics(self, topic_id: str) -> list[str]
    def get_personalization_context(self, topic_id: str) -> str
    # 例: "User enjoys volleyball and plays weekly. User mentioned 'spike' but may need sports-specific vocabulary."
```

---

## 修改现有文件

### 1. 新增 `knowledge_graph/` 目录

所有新文件在此目录下。

### 2. 修改 `subagents/cross_session/memory_cron_subagent.md`

在更新 MEMORY.md 后，添加实体提取和图更新指令。

### 3. 新增 `subagents/cross_session/graph_builder_subagent.md`

负责根据提取的实体更新图结构。

### 4. 新增 `persona/TOOLS.md` (或扩展现有)

文档化 `read_knowledge_graph` 工具供 subagent 使用。

---

## 初始化

首次启动时，从 topic-bank 构建初始图结构：

```python
def initialize_graph(workspace: Path):
    graph = nx.MultiDiGraph()

    # 从 topic-bank/index.json 加载话题节点
    # 创建 category 节点和 topic 之间的关系
    # 保存图
```

---

## 依赖

添加到 `bot/pyproject.toml` 或根目录 `requirements.txt`：

```
networkx>=3.4.0
```

---

## 验证方式

1. **单元测试**：测试 `KnowledgeGraphStore` 的持久化、节点/边操作
2. **集成测试**：运行一次会话后查询图，确认实体被正确提取和存储
3. **Subagent 测试**：触发 `graph_builder_subagent`，验证图更新
4. **手动验证**：
   ```python
   from knowledge_graph import KnowledgeGraphStore
   store = KnowledgeGraphStore(Path("knowledge_graph/knowledge_graph.pkl"))
   graph = store.load()
   print(f"Nodes: {graph.number_of_nodes()}, Edges: {graph.number_of_edges()}")
   ```

---

## 关键文件路径

| 文件 | 用途 |
|------|------|
| `knowledge_graph/__init__.py` | 公共 API |
| `knowledge_graph/node_types.py` | 节点类型定义 |
| `knowledge_graph/edge_types.py` | 边类型定义 |
| `knowledge_graph/graph_store.py` | 核心持久化层 |
| `knowledge_graph/entity_extractor.py` | 实体提取 |
| `knowledge_graph/graph_query.py` | 查询接口 |
| `subagents/cross_session/memory_cron_subagent.md` | 修改：添加图更新 |
| `subagents/cross_session/graph_builder_subagent.md` | 新增：图构建 subagent |
| `shared/memory/MEMORY.md` | 现有记忆（不修改） |
| `topic-bank/index.json` | 现有话题库（不修改） |
