# Phase 2: Data Processor Framework

## 实施顺序

本模块是 **Phase 2**，依赖于 Phase 1 的 `thread.jsonl`。

| Phase | 模块 | 依赖 |
|-------|------|------|
| 1 | Unified Interaction Store (thread.jsonl) | 无 |
| 2 | Data Processor Framework | Phase 1 |
| 3a | Knowledge Graph (NetworkX) | Phase 1 |
| 3b | Review Mode (Spaced Repetition) | Phase 2 |

---

## 核心概念

### 什么是 Data Processor Framework？

**Data Processor Framework** 是一个**机制/框架**，用于规范新功能的数据处理方式。

当创建一个新功能时，如果需要处理 `thread.jsonl` 中的数据，就创建一个对应的 **Processor**：
- 定义自己的 **Schema**（Pydantic）来验证输入输出
- 实现自己的处理逻辑
- 通过 **trigger**（count/cron）触发执行

### 机制设计

```
┌─────────────────────────────────────────────────────────────┐
│                    thread.jsonl                              │
│              (统一的原始数据，所有功能共享)                    │
└─────────────────────────────┬───────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐     ┌───────────────┐     ┌───────────────┐
│ VocabProcessor│     │PolisherProcessor│     │ QuizProcessor │
│               │     │               │     │               │
│ schema.py    │     │ schema.py    │     │ schema.py    │
│ processor.py │     │ processor.py │     │ processor.py │
└───────┬───────┘     └───────┬───────┘     └───────┬───────┘
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐     ┌───────────────┐     ┌───────────────┐
│  vocab.jsonl  │     │polisher.jsonl │     │knowledge_pool │
└───────────────┘     └───────────────┘     └───────────────┘
```

### 如何新增一个功能

1. 在 `data_processor/` 下创建 `{功能名}/` 目录
2. 创建 `schema.py`：定义该功能的输入输出 Schema（Pydantic）
3. 创建 `processor.py`：
   - 继承 `BaseDataProcessor`
   - 定义唯一的 `name` 属性（如 `name = "vocab"`）
4. 系统启动时自动发现并注册（无需手动注册）
5. 在 trigger 配置中启用该 Processor

---

## 设计方案

### 类层次结构

```
BaseDataProcessor (抽象基类)
    │
    ├── VocabProcessor
    │       │
    │       └── VocabDailyProcessor (可选，进一步特化)
    │
    ├── PolisherProcessor
    │
    ├── QuizProcessor
    │
    └── NotesProcessor
```

### BaseDataProcessor 设计

```python
from abc import ABC, abstractmethod
from typing import TypeVar, Generic
from pydantic import BaseModel
from pathlib import Path


class BaseDataProcessor(ABC, Generic[T, U]):
    """
    DataProcessor 基类

    定义通用流程：
    1. read()        - 读取 thread.jsonl
    2. preprocess()  - 预处理（去无用字段，过滤）
    3. build_prompt()- 组装 prompt
    4. call_llm()   - 调用 LLM
    5. parse_output()- 解析 LLM 输出
    6. serialize()   - 写回 jsonl 或生成 md

    子类必须实现：
    - get_input_schema()  - 返回输入 Schema
    - get_output_schema() - 返回输出 Schema
    - build_user_prompt() - 组装用户 prompt
    - parse_llm_output()  - 解析 LLM 输出
    """

    # ==================== Abstract Methods ====================

    @abstractmethod
    def get_input_schema(self) -> type[T]:
        """子类返回输入 Schema"""
        pass

    @abstractmethod
    def get_output_schema(self) -> type[U]:
        """子类返回输出 Schema"""
        pass

    @abstractmethod
    def build_user_prompt(self, data: list[T]) -> str:
        """子类实现具体的 prompt 组装逻辑"""
        pass

    @abstractmethod
    def parse_llm_output(self, raw_output: str) -> list[U]:
        """子类实现 LLM 输出的解析逻辑"""
        pass

    # ==================== Batching ====================

    def process_all(
        self,
        input_path: Path,
        output_path: Path,
        batch_size: int = 50,
        format: str = "jsonl"
    ):
        """
        处理所有批次

        读取 input_path 中的所有记录，按 batch_size 分批处理，
        直到所有记录处理完毕。
        """
        all_data = self.read(input_path)
        total = len(all_data)

        for start in range(0, total, batch_size):
            end = min(start + batch_size, total)
            batch = all_data[start:end]

            # 1. Preprocess
            processed = self.preprocess(batch)

            # 2. Build Prompt
            user_prompt = self.build_user_prompt(processed)
            system_prompt = self.get_system_prompt()

            # 3. Call LLM
            raw_output = self._call_llm(system_prompt, user_prompt)

            # 4. Parse Output
            parsed = self.parse_llm_output(raw_output)

            # 5. Serialize
            self.serialize(parsed, output_path, format)

    # ==================== Template Methods ====================

    def read(self, path: Path) -> list[dict]:
        """读取 jsonl，返回原始 dict 列表"""
        with open(path, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f]

    def preprocess(self, raw_data: list[dict]) -> list[T]:
        """
        预处理：
        1. 过滤无用字段（id, ts, _type 等）
        2. 验证 schema
        3. 返回 Pydantic 模型列表
        """
        schema = self.get_input_schema()
        processed = []
        for item in raw_data:
            filtered = self._filter_fields(item)
            try:
                processed.append(schema(**filtered))
            except Exception:
                # 跳过不符合 schema 的记录
                continue
        return processed

    def _filter_fields(self, item: dict) -> dict:
        """过滤通用字段，子类可 override"""
        excluded = {"id", "ts", "_type", "timestamp", "metadata"}
        return {k: v for k, v in item.items() if k not in excluded}

    def serialize(
        self,
        data: list[U],
        output_path: Path,
        format: str = "jsonl"
    ):
        """
        序列化输出
        - format="jsonl": 追加到 jsonl
        - format="md": 生成 markdown
        """
        if format == "jsonl":
            with open(output_path, "a", encoding="utf-8") as f:
                for item in data:
                    f.write(item.model_dump_json() + "\n")
        elif format == "md":
            self._serialize_md(data, output_path)

    def _serialize_md(self, data: list[U], path: Path):
        """生成 markdown，子类可 override"""
        lines = ["# Output\n"]
        for item in data:
            lines.append(f"- {item.model_dump()}")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def get_system_prompt(self) -> str:
        """默认 system prompt，子类可 override"""
        return "你是一个数据处理专家。"

    # ==================== Helper Methods ====================

    def _call_llm(self, system: str, user: str) -> str:
        """
        调用 LLM via SubagentManager
        子类可 override 以更换实现
        """
        pass
```

### 注册机制

参考 nanobot 的 channel 注册机制，Data Processor 采用类似的自动发现模式：

```python
# data_processor/registry.py

_INTERNAL = frozenset({"base", "registry", "utils"})


def discover_processors() -> dict[str, type[BaseDataProcessor]]:
    """扫描 data_processor 目录，自动发现所有 Processor 子类"""
    import data_processor as pkg
    processors = {}
    for _, name, ispkg in pkgutil.iter_modules(pkg.__path__):
        if name in _INTERNAL or ispkg:
            continue
        try:
            cls = load_processor_class(name)
            processors[name] = cls
        except ImportError:
            continue
    return processors


def load_processor_class(module_name: str) -> type[BaseDataProcessor]:
    """加载指定模块，返回 BaseDataProcessor 子类"""
    from data_processor.base import BaseDataProcessor as _Base
    mod = importlib.import_module(f"data_processor.{module_name}")
    for attr in dir(mod):
        obj = getattr(mod, attr)
        if isinstance(obj, type) and issubclass(obj, _Base) and obj is not _Base:
            return obj
    raise ImportError(f"No BaseDataProcessor subclass in data_processor.{module_name}")
```

### Processor 基类（带注册）

```python
# data_processor/base.py

class BaseDataProcessor(ABC, Generic[T, U]):
    """
    所有 Processor 必须定义 name 属性，用于注册表标识
    """
    name: str = "base"  # 子类必须定义唯一的 name

    @abstractmethod
    def get_input_schema(self) -> type[T]: pass

    @abstractmethod
    def get_output_schema(self) -> type[U]: pass

    @abstractmethod
    def build_user_prompt(self, data: list[T]) -> str: pass

    @abstractmethod
    def parse_llm_output(self, raw_output: str) -> list[U]: pass

    def process_all(self, input_path: Path, output_path: Path, batch_size: int = 50, format: str = "jsonl"):
        # ... 处理逻辑
        pass
```

### 具体 Processor 示例

```python
# data_processor/vocab/processor.py

class VocabProcessor(BaseDataProcessor[VocabInput, VocabOutput]):
    name = "vocab"  # 注册表中的唯一标识

    def get_input_schema(self) -> type[VocabInput]: return VocabInput
    def get_output_schema(self) -> type[VocabOutput]: return VocabOutput
    def build_user_prompt(self, data: list[VocabInput]) -> str: ...
    def parse_llm_output(self, raw_output: str) -> list[VocabOutput]: ...
```

### Processor 管理器

```python
# data_processor/manager.py

class ProcessorManager:
    """管理所有注册的 Processor"""

    def __init__(self):
        self.processors: dict[str, BaseDataProcessor] = {}
        self._discover()

    def _discover(self):
        """启动时自动发现所有 Processor"""
        for name, cls in discover_processors().items():
            self.processors[name] = cls()

    def get(self, name: str) -> BaseDataProcessor | None:
        """根据 name 获取 Processor"""
        return self.processors.get(name)

    def list_processors(self) -> list[str]:
        """列出所有已注册的 Processor"""
        return list(self.processors.keys())
```

### 配置驱动启用

在 trigger 配置中指定启用的 Processor：

```yaml
# global/trigger/count/count.yaml
processors:
  vocab:
    enabled: true
    batch_size: 50
  polisher:
    enabled: true
    batch_size: 50
```

---

### 子类实现示例：VocabProcessor

```python
# data_processor/vocab/schema.py
from pydantic import BaseModel


class VocabInput(BaseModel):
    """VocabProcessor 输入 Schema"""
    role: str
    content: str
    topic: str | None = None


class VocabOutput(BaseModel):
    """VocabProcessor 输出 Schema"""
    original: str
    improved: str
    word_type: str
    notes: str | None = None
```

```python
# data_processor/vocab/processor.py
from data_processor.base import BaseDataProcessor
from .schema import VocabInput, VocabOutput


class VocabProcessor(BaseDataProcessor[VocabInput, VocabOutput]):
    """词汇处理器"""

    def get_input_schema(self) -> type[VocabInput]:
        return VocabInput

    def get_output_schema(self) -> type[VocabOutput]:
        return VocabOutput

    def get_system_prompt(self) -> str:
        return """你是一个词汇分析专家。
给定用户的对话内容，提取需要改进的词汇和表达。
输出格式为无冒号键值对，每行一个。"""

    def build_user_prompt(self, data: list[VocabInput]) -> str:
        lines = []
        for item in data:
            if item.role == "user":
                lines.append(f"用户说: {item.content}")
        return "\n".join(lines)

    def parse_llm_output(self, raw_output: str) -> list[VocabOutput]:
        results = []
        for line in raw_output.strip().split("\n"):
            if not line.strip():
                continue
            # 解析无冒号键值对
            # 例如: original=hello improved=hi word_type=adjective
            parts = line.split()
            kwargs = {}
            for part in parts:
                if "=" in part:
                    key, value = part.split("=", 1)
                    kwargs[key] = value
            results.append(VocabOutput(**kwargs))
        return results
```

---

## LLM 输出格式

### 无冒号键值对格式

LLM 返回精简的键值对，不需要引号：

```
original=i like humburgers improved=I'm quite fond of hamburgers word_type=expression notes=food preference
original=i study ai improved=I'm majoring in AI word_type=expression notes=education
```

### 解析逻辑

```python
def parse_kv_pairs(line: str) -> dict:
    """解析无冒号键值对"""
    result = {}
    parts = line.split()
    for part in parts:
        if "=" in part:
            key, value = part.split("=", 1)
            result[key] = value
    return result
```

### 为什么不用冒号？

1. **节省 token**：`key=value` 比 `{"key": "value"}` 更短
2. **结构简单**：不需要处理嵌套和转义
3. **便于解析**：split("=") 即可

---

## 数据流

```
┌─────────────────────────────────────────────────────────────────┐
│                     shared/thread.jsonl                          │
│                  (id, ts, role, content, ...)                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   VocabProcessor.process_all()                    │
│                                                                 │
│  total_records = 120, batch_size = 50                          │
│  → 自动分 3 批处理 (0-49, 50-99, 100-119)                    │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┬───────────────┐
              ▼               ▼               ▼
    ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
    │  preprocess()   │  │  preprocess()   │  │  preprocess()   │
    │  过滤字段       │  │  过滤字段       │  │  过滤字段       │
    │  验证 Schema   │  │  验证 Schema   │  │  验证 Schema   │
    └────────┬────────┘  └────────┬────────┘  └────────┬────────┘
             │                     │                     │
             ▼                     ▼                     ▼
    ┌─────────────────────────────────────────────────────────────┐
    │               VocabProcessor.build_prompt()                  │
    │            组装 system + user prompt                        │
    └─────────────────────────────────────────────────────────────┘
                              │
                              ▼
    ┌─────────────────────────────────────────────────────────────┐
    │              SubagentManager.spawn() (LLM 调用)              │
    │       返回无冒号键值对                                       │
    │       original=i like improved=I'm fond of ...               │
    └─────────────────────────────────────────────────────────────┘
                              │
                              ▼
    ┌─────────────────────────────────────────────────────────────┐
    │               VocabProcessor.parse_llm_output()             │
    │            解析为 list[VocabOutput]                         │
    └─────────────────────────────────────────────────────────────┘
                              │
                              ▼
    ┌─────────────────────────────────────────────────────────────┐
    │                 VocabProcessor.serialize()                  │
    │           写回 shared/vocab.jsonl                          │
    └─────────────────────────────────────────────────────────────┘
```

---

## 目录结构

```
data_processor/                                    [核心框架]
├── __init__.py
├── base.py                                       # BaseDataProcessor (必须定义 name 属性)
├── registry.py                                   # 自动发现机制
├── manager.py                                    # Processor 管理器
├── utils.py                                      # 通用工具函数
│
vocab/                                           [词汇处理]
├── __init__.py
├── schema.py                                     # VocabInput, VocabOutput
└── processor.py                                  # VocabProcessor (name="vocab")
│
polisher/                                        [语法处理]
├── __init__.py
├── schema.py                                     # PolisherInput, PolisherOutput
└── processor.py                                  # PolisherProcessor (name="polisher")
│
quiz/                                            [Quiz 处理]
├── __init__.py
├── schema.py
└── processor.py                                  # QuizProcessor (name="quiz")
│
notes/                                           [笔记处理]
├── __init__.py
├── schema.py
└── processor.py                                  # NotesProcessor (name="notes")
```

---

## 与 Trigger 集成

每个 Processor 通过 trigger 触发执行：

```yaml
# global/trigger/count/count.yaml
vocab_processor:
  enabled: true
  condition:
    kind: file_line_count
    count: 50
    path: shared/thread.jsonl
  target:
    subagent: vocab_processor_subagent

polisher_processor:
  enabled: true
  condition:
    kind: file_line_count
    count: 50
    path: shared/thread.jsonl
  target:
    subagent: polisher_processor_subagent
```

---

## 文件清单

### 新增文件

```
data_processor/                              [核心框架]
├── __init__.py
├── base.py                                 # BaseDataProcessor (定义 name 属性)
├── registry.py                             # 自动发现机制
├── manager.py                              # Processor 管理器
├── utils.py
│
vocab/                                     [词汇处理]
├── __init__.py
├── schema.py                               # VocabInput, VocabOutput
└── processor.py                           # VocabProcessor (name="vocab")
│
polisher/                                  [语法处理]
├── __init__.py
├── schema.py
└── processor.py                           # PolisherProcessor (name="polisher")
│
quiz/                                      [Quiz 处理]
├── __init__.py
├── schema.py
└── processor.py                           # QuizProcessor (name="quiz")
│
notes/                                     [笔记处理]
├── __init__.py
├── schema.py
└── processor.py                           # NotesProcessor (name="notes")
```

### 修改文件

```
global/trigger/count/count.yaml            [MODIFY] 添加各 Processor 的触发配置
```
