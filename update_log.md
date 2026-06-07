# Update Log

## 2026-06-07 - P1-3 到 P1-6 Runtime Hardening

- 标记 `docs/p1-runtime-hardening-plan.md` 的 P1-3、P1-4、P1-5、P1-6 为 done。
- 增强 monitor 可观测性：
  - `processor_runs.jsonl` 支持 `artifact_paths`，并对旧 `output_path` 记录做兼容回填。
  - `/api/admin/monitor` 支持按 `mode` 与 `session_uuid` 过滤 processor/subagent/trigger decision。
  - 新增 `expected_triggers`，展示每个触发器的 disabled/skipped/failed/done/no_recent_activity 状态和最新证据。
- 加固 LLM Wiki pipeline：
  - Wiki patch/page frontmatter 增加 `memory_status`。
  - 低置信或疑似矛盾候选进入 `persona/wiki/state/queue.jsonl`，不直接污染长期记忆正文。
  - Wiki sync 记录 `review_queued`。
  - Wiki lint 增加 source refs、sidecar fact sources、memory status、schema projection noise 检查。
  - 增加 basketball、Paris、Arsenal、travel、IELTS fluency 的 freechat golden test。
- 加固 Be Native runtime flow：
  - 新增 `persona/benative/sessions/{session_uuid}/summary.json`。
  - 用户回答后立即刷新 session summary，不等待 `benative_review`。
  - `benative_review` session-local review artifacts 改为去重追加，并刷新同一 summary。
- 增加/更新 P1 regression tests：
  - monitor skipped trigger 可解释性。
  - wiki review queue 与 semantic lint。
  - Be Native 练习不阻塞下一句、session summary、review dedupe。

---

## 2026-06-07 - P1-2 Processor Cursor And Delta Semantics

- 标记 `docs/p1-runtime-hardening-plan.md` 的 P1-2 为 done。
- 增强 `bot/nanobot/utils/processor_monitor.py`：
  - processor cursor 文件升级为 versioned envelope。
  - cursor 记录包含 `trigger_id`、`offsets`、以及每个输入的 `input_path`、`last_line`、`input_fingerprint`、`updated_at`。
  - delta materialization 的 input record 增加 `last_line` 和 `input_fingerprint`，方便 monitor/debug 解释“处理了哪些新增内容”。
- 更新 `bot/nanobot/agent/loop.py`，成功完成 processor 后写入标准 cursor records；失败时仍只记录 error run，不推进 cursor。
- 增强 `subagent/_shared/base.py`：
  - JSONL artifact 写入改为读取已有行、过滤重复记录、写临时文件再 replace。
  - Markdown artifact 写入也使用临时文件 replace，降低半写入风险。
- 增加测试：
  - 同一个 processor 重复处理同一批输入不会重复追加 artifact rows。
  - processor cursor payload 包含标准 envelope 与 input fingerprint。
- 验证通过：
  - `uv run pytest bot/tests/subagent/test_processor_cursor.py bot/tests/subagent/test_data_processor_runtime.py bot/tests/subagent/test_processor_gated_subagent_runtime.py -q`
  - `uv run pytest bot/tests/config bot/tests/wiki bot/tests/subagent bot/tests/counter -q`
  - `uv run python scripts/validate_subagent_config.py`

---

## 2026-06-07 - P1-1 Registry Control Plane

- 扩展 `config/capabilities.yaml`：
  - 新增 `models.deepseek-v4-flash` 注册信息，作为 processor/subagent trigger 的模型 allowlist。
  - 为所有 processor 增加 `artifact_type`，让输出契约从隐式路径变为显式配置。
- 增强 `scripts/validate_subagent_config.py`：
  - processor/subagent trigger 必须声明可注册模型。
  - trigger 的 `output_path` 必须匹配 processor 的 `artifact_type`。
  - trigger prompt_file 必须和 subagent registry prompt 一致。
  - subagent prompt 必须位于对应 `subagent/{scope}/{name}/` 目录下。
  - cross-session subagent 默认禁止声明 session-only writes，除非显式允许。
- 增加 registry 反向测试：
  - 未注册模型。
  - processor 输出后缀和 artifact type 不一致。
  - prompt 位于错误 subagent 目录。
  - disabled trigger 仍引用 deprecated subagent。
- 更新 `docs/p1-runtime-hardening-plan.md`，将 P1-1 标记为 done。

---

## 2026-06-07 - P1/P2 后续更新计划

- 新增 `docs/p1-runtime-hardening-plan.md`：
  - 聚焦 registry control plane、processor cursor/delta、monitor session/mode 可观测性、LLM Wiki pipeline、Be Native runtime flow、P1 regression matrix。
  - 所有任务保持未完成状态，作为下一轮实现 checklist。
- 新增 `docs/p2-product-polish-plan.md`：
  - 聚焦 WebUI graph/artifact navigation、agentic tool layer、cost/token/model governance、data lifecycle/export、browser smoke tests、channel expansion。
  - 所有任务保持未完成状态，作为产品化和规模化 checklist。

---

## 2026-06-07 - P0 Runtime 稳定性清理

- 新增 `docs/p0-stability-cleanup-plan.md`，把 P0 项按顺序记录并全部标记完成。
- 将旧 Be Native prompt-only subagent 归档到 `docs/deprecated/subagents/`，并从 `subagent/` 运行路径移除，避免旧能力被误认为仍可调用。
- 新增根目录 `pytest.ini`，并移除 `bot/pyproject.toml` 中在当前根环境会产生 warning 的 `asyncio_mode` 配置；`uv run pytest ...` 现在不再出现 unknown config warning。
- LLM Wiki ingest 增加内容噪声过滤，默认跳过 slash command、测试短句、错误栈和 system-like 文本，减少长期记忆污染。
- 扩展 `scripts/validate_subagent_config.py`：
  - 禁止 trigger 重新引用 deprecated subagent。
  - 校验 `persona/processor/{mode}/...` output path 与 trigger 所属 mode 一致。
  - 校验 processor 的 `mode_outputs` 与 trigger output path 一致。
- 验证通过：
  - `uv run python scripts/validate_subagent_config.py`
  - `uv run pytest bot/tests/wiki/test_wiki_sync.py -q`
  - `uv run pytest bot/tests/wiki/test_wiki_core_pipeline.py bot/tests/wiki/test_wiki_sync.py bot/tests/config/test_capabilities_registry.py bot/tests/counter/test_benative_triggers.py -q`

---

## 2026-06-05 - Capability Registry 一致性校验

- 将 `config/capabilities.yaml` 从单纯能力索引进一步收束为 agent control plane：
  - `mode.default.subagents` 显式登记 `memory_cron`、`daily_consolidator`。
  - `mode.ielts.subagents` 显式登记 `ielts_feedback`。
- 清理 `mode/default/trigger/triggers.json` 中已废弃的 `benative_article_fetcher` 和 `benative_translator` cron trigger。
- 增强 `scripts/validate_subagent_config.py`：
  - 校验 trigger 引用的 subagent / processor 是否已注册。
  - 校验 enabled trigger 使用的 subagent 是否属于当前 mode。
  - 校验 `execution_mode` 是否被 subagent 允许。
  - 校验 trigger tools 是否存在且属于该 subagent / execution mode 的 allowlist。
  - 校验 `depends_on`、prompt 路径、processor 路径。
- 增加测试覆盖，确保 registry 与 trigger target 不再静默漂移。
- 更新简历和面试 summary，将该机制表述为多 Agent 系统的 registry validation / control plane 设计。

---

## 2026-06-05 - Wiki Graph 层级与聚焦视图

- WebUI Wiki Graph 从单一全局力导向图扩展为两种视角：
  - `层级`：默认按 `All Wiki -> domain -> topic -> entity/concept -> wiki page` 展示。
  - `总览`：保留全局力导向布局，用于观察整体关系。
- 增加聚焦子图能力：点击任意 topic、subtopic、entity、concept 或 page 后，可将其作为当前起点，只查看两跳内相关节点。
- 修复 graph hover 抖动：hover / selected 高亮改用 refs 管理，避免 mousemove 触发 React state 变化后重启 D3 simulation。
- 更新简历与面试 summary 文档，补充分层可聚焦知识图谱、topic-level summary 输入范围等叙事。
- 更新 `docs/wiki-memory-implementation.md`，同步当前 `d3-force` + Canvas 实现、graph 视图能力、以及 Wiki sync 默认读取 `persona/events/thread.jsonl` 且仅接收 `freechat` user turns 的规则。

---

## 2026-05-31 - Runtime 数据目录收束

- 将用户运行数据的 canonical root 收束到 `persona/`：
  - session 原始记录：`persona/sessions/`
  - 长期记忆：`persona/memory/`
  - 全局派生事件流：`persona/events/thread.jsonl`
  - cron/count 运行状态：`persona/trigger/`
- 保留根目录 `monitor/` 作为系统观测日志，不放入 `persona/`。
- 删除无实际意义的测试数据和旧重复目录：
  - `data/`
  - `sessions/`
  - `memory/`
  - `trigger/`
  - `persona/cron/`
  - 旧 session / progress / IELTS exam 样例数据
- 更新 memory、cron、count cursor、derived thread log 的代码路径。
- 更新 `docs/08-project-structure-review.md` 和 `.gitignore` 的目录策略。

---

## 2026-05-31 - Wiki 页面目录收束

- 确认 `persona/wiki/pages/` 与 `persona/wiki/wiki/` 内容完全一致。
- 将 `persona/wiki/wiki/` 定为唯一 canonical wiki page root。
- 删除旧原型目录 `persona/wiki/pages/`。
- 删除只服务旧目录的 `scripts/migrate_wiki_pages.py`。
- 移除 `WikiStore` 对 legacy `pages/` 的 fallback 读取逻辑，避免后续读写路径分叉。
- 更新 wiki 相关文档，把页面路径统一为 `persona/wiki/wiki/`。

---

## 2026-05-26 - Subagent 模型统一配置

本次更新添加了 subagent 模型配置机制，允许在 `config.json` 中统一配置每个 subagent 使用的模型。

---

## 1. 配置变更

### config/schema.py

在 `AgentsConfig` 中添加 `subagent_defaults` 字段：

```python
class AgentsConfig(Base):
    defaults: AgentDefaults = Field(default_factory=AgentDefaults)
    subagent_defaults: dict[str, str] = Field(
        default_factory=dict,
        description="Default model for each subagent. Maps subagent label to model name.",
    )
```

### config.json 配置示例

```json
{
  "agents": {
    "subagent_defaults": {
      "IELTS Score": "gpt-4o-mini",
      "notes_ai": "deepseek-chat",
      "vocabulary": "gpt-4o",
      "default": "claude-opus-4-5"
    }
  }
}
```

---

## 2. 代码变更

### agent/subagent.py

- `SubagentManager.__init__` 添加 `subagent_defaults` 参数
- `SubagentManager.spawn()` 添加自动模型查找逻辑

### agent/loop.py

- `AgentLoop.__init__` 添加 `subagent_defaults` 参数
- `AgentLoop.from_config()` 传递 `subagent_defaults` 到 SubagentManager

---

## 3. 模型选择优先级

1. `spawn()` 调用时显式传入的 `model` 参数
2. `subagent_defaults` 中 label 对应的模型（如 `"IELTS Score"`）
3. `subagent_defaults` 中 `"default"` 对应的模型
4. 系统默认模型

---

## 4. 使用示例

```python
# 不需要显式指定模型，只需 label 匹配 config 中的 key
task_id = await loop.subagents.spawn(
    task=task_prompt,
    label="IELTS Score",  # 会自动查找 subagent_defaults["IELTS Score"]
    ...
)
```

---

## 5. 其他修复

- `builtin.py` 删除 3 处重复的 `import json`（保留模块级别的一处）

---

## 2026-05-26 - Trigger 整合到 Per-Mode 配置

本次更新将所有 trigger 配置迁移到 per-mode `triggers.json` 文件，实现 Mode 统一管理调度。

---

## 1. 架构变更

### 设计原则

- **Subagent** 只负责执行，不关心何时被调用
- **Processor** 是 Subagent 内部的 LLM 交互层（过滤输入、解析输出）
- **Mode** 是编排层，决定何时调用哪个 Subagent
- **Context** 注入到 Subagent（`subagent/*/context/` 目录）

### 目录结构

```
mode/
├── default/                    ← 内部使用，不暴露给用户
│   ├── context/
│   └── trigger/
│       └── triggers.json      ← 全局 triggers (cron + file_line_count)
│
├── freechat/                   ← 用户 mode
│   ├── context/
│   └── trigger/
│       └── triggers.json      ← vocab, polisher (turn_count)
│
└── ielts/
    ├── context/
    └── trigger/
        └── triggers.json      ← vocab, polisher, ielts_feedback (turn_count)

subagent/
├── single_session/
│   ├── vocab/
│   │   ├── context/
│   │   │   └── vocab_subagent.md  ← 注入的上下文
│   │   └── processor/
│   │       └── processor.py
│   ├── polisher/
│   ├── quiz/
│   └── notes/
│
└── cross_session/
    ├── kg/
    │   ├── context/
    │   └── processor/
    ├── review/
    ├── memory_cron/
    ├── daily_consolidator/
    └── ...
```

### CounterEngine 加载逻辑

```
CounterEngine 初始化
    ↓
_load_default_triggers() → mode/default/trigger/triggers.json (始终加载)
    ↓
set_mode("freechat")
    ↓
_load_mode_triggers() → mode/freechat/trigger/triggers.json (覆盖)
    ↓
所有 triggers (default + current mode) 都会被 check_triggers() 检查
```

---

## 2. triggers.json 文件

### mode/default/trigger/triggers.json

| Trigger ID | Kind | 说明 |
|------------|------|------|
| memory_cron | cron | 每天 00:00 更新用户记忆 |
| daily_consolidator | cron | 每 8 小时汇总 vocab/polisher |
| progress_tracker | file_line_count | user_responses.jsonl 满 20 条 |
| benative_article_fetcher | cron | 每天 12:00 抓取文章 |
| benative_translator | cron | 每天 13:00 翻译文章 |

### mode/freechat/trigger/triggers.json

| Trigger ID | Kind | 说明 |
|------------|------|------|
| vocab_analysis | turn_count | 每 2 句话分析词汇 |
| polish_feedback | turn_count | 每 3 句话分析语法 |

### mode/ielts/trigger/triggers.json

| Trigger ID | Kind | 说明 |
|------------|------|------|
| vocab_analysis | turn_count | 每 2 句话分析词汇 |
| polish_feedback | turn_count | 每 3 句话分析语法 |
| ielts_feedback | turn_count | 每 5 句话分析 IELTS |

---

## 3. Subagent 目录变更

### md/ → context/

所有 `md/` 目录重命名为 `context/`：

```bash
subagent/single_session/vocab/md → subagent/single_session/vocab/context
subagent/cross_session/kg/md → subagent/cross_session/kg/context
# ... 以此类推
```

### 旧文件删除

- `subagent/*/triggers.json` → 已删除，trigger 配置移到 mode 目录
- `subagent/_trigger/triggers.yaml` → 已删除

---

## 4. CounterEngine 更新

### 变更内容

```python
class CounterEngine:
    def __init__(self, workspace):
        self._default_triggers_file = workspace / "mode" / "default" / "trigger" / "triggers.json"
        self._load_default_triggers()  # 始终加载

    def set_mode(self, mode):
        self._load_mode_triggers(mode)  # 加载当前 mode triggers
        # default triggers 始终保留
```

### prompt_file 路径更新

```python
# 旧路径
subagent/{category}/{name}/md/{name}_subagent.md
# 新路径
subagent/{category}/{name}/context/{name}_subagent.md
```

---

## 5. 流程总结

```
用户切换 mode (/freechat → /ielts)
    ↓
session.metadata["mode"] = "ielts"
loop.counter_engine.set_mode("ielts")
    ↓
CounterEngine 重新加载:
    - mode/default/trigger/triggers.json (不变)
    - mode/ielts/trigger/triggers.json (新加载)
    ↓
CounterEngine.check_triggers() 检查所有 triggers
    ↓
满足条件 → spawn 对应 subagent
    ↓
Subagent 执行:
    - 加载 context/context.md 注入上下文
    - 使用 processor 处理 LLM 交互
    - 写入 data/ 目录
```

---

## 2. CounterEngine 更新

### 变更内容

- `_DEFAULT_TRIGGERS_PATH` 删除，不再使用单一 YAML 文件
- `_load_all_triggers()` 改为扫描 `subagent/single_session/*/triggers.json` 和 `subagent/cross_session/*/triggers.json`
- cursor 状态从 `triggers.json` 的 `cursor` 字段读取和写入
- `_update_trigger_cursor()` 直接更新对应 trigger 的 cursor

### 扫描目录

```
subagent/
├── single_session/
│   ├── vocab/triggers.json
│   ├── polisher/triggers.json
│   ├── quiz/triggers.json
│   └── notes/triggers.json
└── cross_session/
    ├── kg/triggers.json
    ├── review/triggers.json
    ├── progress_tracker/triggers.json
    ├── memory_cron/triggers.json
    ├── daily_consolidator/triggers.json
    └── benative_article_fetcher/triggers.json
```

---

## 3. 数据目录重组

### thread.jsonl 位置

`thread.jsonl` 已移动到 `data/thread.jsonl`：
- `bot/nanobot/session/manager.py` 中 `_append_to_shared_interaction_log` 写入 `data/thread.jsonl`
- `.gitignore` 已包含 `data/thread.jsonl`

### .gitignore 更新

```
# Session data (dynamically created)
data/thread.jsonl
thread.jsonl
```

---

## 4. 清理内容

| 原路径 | 说明 |
|--------|------|
| `subagent/_trigger/triggers.yaml` | 已删除，改用 per-subagent triggers.json |
| `global/trigger/` | 目录不存在（已清理） |

---

## 2026-05-26 - Processor Trigger 执行机制 + Level 2/3 Processors 更新

本次更新实现了 processor trigger 的自动执行机制，完善了 Level 2 和 Level 3 的 processors。

---

## 1. Processor Trigger 执行机制

### 架构设计

```
CounterEngine.check_triggers() → _spawn_counter_subagent()
                                        │
                    ┌───────────────────┴───────────────────┐
                    ▼                                       ▼
           trigger.target.processor               trigger.target.subagent
                    │                                       │
                    ▼                                       ▼
         _execute_processor()                    subagents.spawn()
         - discover_processors()                - load_prompt()
         - processor.process_all()            - build_task()
         - chain dependents                     - chain dependents
```

### 新增文件/改动

| 文件 | 改动 |
|------|------|
| `bot/nanobot/agent/loop.py` | 新增 `_execute_processor()` 方法，修改 `_spawn_counter_subagent()` 支持 processor/subagent 分流 |
| `bot/nanobot/counter/types.py` | `CounterTarget` 新增 `processor`、`input_path`、`output_path`、`batch_size` 字段 |

### 处理流程

1. **Processor Trigger** (`trigger.target.processor` 存在)：
   - 通过 `discover_processors()` 加载对应 processor 类
   - 调用 `processor.process_all(input_path, output_path, batch_size, format="both")`
   - 自动 chain `depends_on` 中依赖它的 triggers

2. **Subagent Trigger** (`trigger.target.subagent` 存在)：
   - 通过 `subagents.spawn()` 执行（现有逻辑）
   - 等待 task_id 完成
   - 自动 chain `depends_on` 中依赖它的 triggers

---

## 2. Level 2 Processors 更新

### 设计原则

- **两层工程**：
  - 第一工程层：预处理，提取有用字段，减少 token
  - 第二工程层：解析 LLM tab-separated 输出
- **LLM 输出格式**：tab 分隔，纯文本，方便解析
- **Processor Registry**：`discover_processors()` 自动发现 `subagent/single_session/*/processor/`

### 更新的 Processors

| Processor | 路径 | 输出字段 |
|-----------|------|----------|
| Vocab | `subagent/single_session/vocab/processor/` | `original`, `improved`, `type`, `reason` |
| Polisher | `subagent/single_session/polisher/processor/` | `original`, `improved`, `grammar_type`, `explanation` |
| Notes | `subagent/single_session/notes/processor/` | `title`, `content`, `category`, `reference`, `context` |
| Quiz | `subagent/single_session/quiz/processor/` | `question`, `answer`, `difficulty`, `topic` |

### System Prompt 格式 (Tab-Separated)

```markdown
You are a vocabulary analysis expert.
Given user's conversation content, extract words and expressions that need improvement.
Output format: tab-separated fields, one improvement per line.

Format: original\timproved\ttype\treason

Example:
3 points	three-point shot	expression	在篮球语境中更专业
is good	is on fire	collocation	更生动的表达
```

---

## 3. Level 3 Subagents 更新

### 更新的 Subagents

| Subagent | 路径 | 输出格式 |
|----------|------|----------|
| KG Builder | `subagent/cross_session/kg/md/kg_subagent.md` | `{label}\t{entity_type}\t{topics}` |
| Review Builder | `subagent/cross_session/review/md/review_subagent.md` | `{review_point}\t{question_type}\t{familiarity_hint}\t{topic}` |

---

## 4. Trigger YAML 配置

### Processor Trigger 示例

```yaml
- id: vocab_processor
  name: "Vocab Processor"
  enabled: true
  condition:
    kind: file_line_count
    count: 50
    path: data/thread.jsonl
  target:
    processor: vocab
    input_path: data/thread.jsonl
    output_path: subagent/single_session/vocab/data/vocab.jsonl
    batch_size: 50
```

### Subagent Trigger 示例 (with depends_on)

```yaml
- id: kg_builder
  name: "Knowledge Graph Builder"
  enabled: true
  condition:
    kind: file_line_count
    count: 50
    path: subagent/single_session/vocab/data/vocab.jsonl
  target:
    subagent: kg_subagent
    prompt_file: subagent/cross_session/kg/md/kg_subagent.md
    depends_on:
      - vocab_processor
      - polisher_processor
      - notes_processor
    model: "gpt-4o-mini"
```

---

## 5. .gitignore 更新

新增 Python 字节码缓存忽略：

```gitignore
# Python bytecode cache
__pycache__/
**/__pycache__/
*.pyc
*.pyo
```

---

## 2026-05-26 - Trigger 整合 + global/ 目录清理

本次更新将所有 trigger 配置整合到 `subagent/_trigger/triggers.yaml`，并清理了废弃的 `global/` 目录。

---

## 1. Trigger 配置整合

### 变更说明

将 `global/trigger/count/count.yaml` 的内容移动到 `subagent/_trigger/triggers.yaml`，实现 subagent 自包含配置。

### 文件变更

| 文件 | 改动 |
|------|------|
| `subagent/_trigger/triggers.yaml` | 新建，整合所有 triggers |
| `bot/nanobot/counter/engine.py` | `_DEFAULT_TRIGGERS_PATH` 改为 `subagent/_trigger/triggers.yaml` |

---

## 2. 数据目录重组

### thread.jsonl 移动

`thread.jsonl` 从项目根目录移动到 `data/thread.jsonl`，统一数据入口。

| 文件 | 改动 |
|------|------|
| `bot/nanobot/session/manager.py` | `_append_to_shared_interaction_log` 写入 `data/thread.jsonl` |
| `.gitignore` | 新增 `data/thread.jsonl`，移除 `thread.jsonl` |

---

## 3. global/ 目录清理

### 删除内容

| 原路径 | 说明 |
|--------|------|
| `global/trigger/` | 已整合到 `subagent/_trigger/triggers.yaml` |
| `global/formats/daily_format.md` | 未使用，删除 |
| `global/formats/polisher_format.md` | 未使用，删除 |
| `global/formats/vocab_format.md` | 未使用，删除 |
| `global/context/` | 空目录，删除 |

### 迁移内容

| 原路径 | 新路径 |
|--------|--------|
| `global/formats/memory_format.md` | `subagent/cross_session/memory_cron/formats/memory_format.md` |

### 更新的引用

| 文件 | 改动 |
|------|------|
| `bot/nanobot/agent/loop.py` | memory_format.md 路径更新为 `subagent/cross_session/memory_cron/formats/memory_format.md` |

---

## 2026-05-25 - Subagent 目录重组 + 数据迁移

本次更新将 `subagents/` 重组为 `subagent/`，按照 single_session / cross_session 分类，每个 subagent 自包含 processor、md、data 三个子目录。同时整理了 shared/ 目录，将数据迁移到 persona/ 和 mode/ 下。

---

## 1. Subagent 目录重组

### 新目录结构

```
subagent/
├── _shared/                    # 共享框架（base.py, manager.py, registry.py, utils.py）
├── _cursors/                  # cursor 状态文件
│   ├── single_session/
│   │   ├── vocab/
│   │   ├── polisher/
│   │   └── ...
│   └── cross_session/
│       ├── kg/
│       ├── review/
│       └── ...
├── single_session/            # 原 subagents/session/
│   ├── vocab/
│   │   ├── processor/         # vocab processor 代码
│   │   ├── md/               # vocab_subagent.md
│   │   └── data/             # 产出数据
│   ├── polisher/
│   ├── quiz/
│   ├── notes/
│   ├── ielts_feedback/
│   └── benative_review/
└── cross_session/             # 原 subagents/cross_session/
    ├── kg/
    │   ├── processor/         # kg processor 代码
    │   ├── md/               # kg_subagent.md
    │   └── data/             # 产出数据
    ├── review/
    ├── memory_cron/
    ├── daily_consolidator/
    ├── progress_tracker/
    ├── benative_article_fetcher/
    ├── benative_translator/
    ├── notes_ai_assistant/
    └── progress_organizer/
```

### 改动说明

- `subagents/session/` → `subagent/single_session/`
- `subagents/cross_session/` → `subagent/cross_session/`
- kg_subagent.md、review_subagent.md 从 `shared/subagents/` 合并到 `subagent/cross_session/{name}/md/`
- `_shared/registry.py` 更新 import 路径：`nanobot.data_processor` → `subagent.single_session.{name}.processor`

---

## 2. shared/ 目录清理

### 删除的内容

| 原路径 | 说明 |
|--------|------|
| `shared/level2/data_processor/` | 已拆分到各 subagent/processor/ |
| `shared/level3/kg/` | 已移到 subagent/cross_session/kg/processor/ |
| `shared/level3/review/` | 已移到 subagent/cross_session/review/processor/ |
| `shared/subagents/` | 已合并到 subagent/ |
| `shared/memory/` | 改用 persona/memory/ |
| `shared/.cursor_*.json` | 改用 subagent/_cursors/ |

### 迁移到 persona/

| 原路径 | 新路径 |
|--------|--------|
| `shared/progress.json` | `persona/progress.json` |
| `shared/progress_bank.jsonl` | `persona/progress_bank.jsonl` |
| `shared/user_responses.jsonl` | `persona/user_responses.jsonl` |

### 迁移到 mode/

| 原路径 | 新路径 |
|--------|--------|
| `shared/benative/` | `mode/benative/data/` |
| `shared/freechat/` | `mode/freechat/data/` |

### 迁移到 subagent/

| 原路径 | 新路径 |
|--------|--------|
| `shared/daily/` | `subagent/cross_session/daily_consolidator/data/` |

---

## 3. 目录结构总览

```
项目根目录/
├── persona/           # 用户数据
│   ├── memory/       # 用户记忆（memory agent 管理）
│   ├── sessions/     # session 记录（每个 session 有 thread.jsonl）
│   ├── progress.json
│   ├── progress_bank.jsonl
│   └── user_responses.jsonl
├── mode/             # 模式编排
│   ├── benative/
│   │   ├── context/
│   │   ├── trigger/
│   │   └── data/    # benative 数据
│   ├── freechat/
│   │   ├── context/
│   │   ├── trigger/
│   │   └── data/    # freechat 数据
│   └── ielts/
├── subagent/         # agent 模块
│   ├── _shared/     # 共享框架
│   ├── _cursors/    # cursor 状态
│   ├── single_session/
│   │   ├── vocab/
│   │   ├── polisher/
│   │   └── ...
│   └── cross_session/
│       ├── kg/
│       ├── review/
│       └── ...
```

---

## 4. 更新的文件

| 文件 | 改动 |
|------|------|
| `subagent/_shared/registry.py` | import 路径更新 |
| `global/trigger/count/count.yaml` | prompt_file 路径更新、processor input/output 路径更新、task_template 路径更新 |
| `bot/nanobot/session/manager.py` | thread.jsonl 改为项目根目录 |
| `.gitignore` | 新增 subagent 数据路径忽略规则 |

### count.yaml 路径更新汇总

| 字段 | 原路径 | 新路径 |
|------|--------|--------|
| `path` (vocab/polisher/quiz/notes) | `shared/thread.jsonl` | `thread.jsonl` |
| `output_path` (vocab) | `shared/vocab.jsonl` | `subagent/single_session/vocab/data/vocab.jsonl` |
| `output_path` (polisher) | `shared/polisher.jsonl` | `subagent/single_session/polisher/data/polisher.jsonl` |
| `output_path` (quiz) | `shared/knowledge_pool.jsonl` | `subagent/single_session/quiz/data/knowledge_pool.jsonl` |
| `output_path` (notes) | `shared/notes.jsonl` | `subagent/single_session/notes/data/notes.jsonl` |
| `path` (kg_builder/review_builder) | `shared/vocab.jsonl` | `subagent/single_session/vocab/data/vocab.jsonl` |
| kg task_template | `{workspace}/kg/` | `{workspace}/subagent/cross_session/kg/data/` |
| review task_template | `{workspace}/shared/review/` | `{workspace}/subagent/cross_session/review/data/` |
| memory_cron task_template | `{workspace}/shared/memory/` | `{workspace}/persona/memory/` |
| daily_consolidator task_template | `{workspace}/shared/daily/` | `{workspace}/subagent/cross_session/daily_consolidator/data/` |
| progress_tracker path | `shared/user_responses.jsonl` | `persona/user_responses.jsonl` |
| benative paths | `{workspace}/shared/benative/` | `{workspace}/mode/benative/data/benative/` |

---

## 2026-05-25 - Phase 1 & 2: Unified Interaction Store + Data Processor Framework

本次更新实现了文档中规划的 Phase 1 和 Phase 2 核心功能。

---

## Phase 1: Unified Interaction Store

### 功能概述

建立统一的交互日志 `thread.jsonl`（项目根目录），所有用户和 AI 的对话内容都记录其中，支持跨会话查询。

### 新增文件

| File | Description |
|------|-------------|
| `shared/thread.jsonl` | 统一交互日志（append-only，gitignore） |

### 修改文件

**`bot/nanobot/session/manager.py`**
- `Session._create_unified_interaction_record()`: 将 session message 转换为统一格式
- `SessionManager._append_to_shared_interaction_log()`: 原子化追加到 shared/thread.jsonl
- `SessionManager.save()`: 调用上述方法实现双写

### 统一交互格式

```json
{
  "id": "interaction_uuid",
  "timestamp": "2026-05-25T10:00:00Z",
  "source": {
    "type": "session",
    "mode": "ielts|freechat|benative|review",
    "session_uuid": "xxx",
    "message_index": 0
  },
  "role": "user|assistant",
  "content": {
    "type": "text|audio",
    "text": "content",
    "audio_url": null
  },
  "metadata": {
    "topic": "food",
    "intent": null,
    "channel": "telegram",
    "languages": ["en"]
  }
}
```

### 设计特点

- **Best-effort**: shared/thread.jsonl 写入失败不影响 session 保存
- **原子化**: 使用 temp file + rename 模式
- **向后兼容**: session thread.jsonl 保持不变

---

## Phase 2: Data Processor Framework

### 功能概述

建立数据处理框架，从 `shared/thread.jsonl` 读取数据，各 Processor 按需提取生成输出。

### 新增文件

| File | Description |
|------|-------------|
| `bot/nanobot/data_processor/__init__.py` | Package init |
| `bot/nanobot/data_processor/base.py` | BaseDataProcessor 抽象基类 |
| `bot/nanobot/data_processor/registry.py` | 自动发现机制 |
| `bot/nanobot/data_processor/manager.py` | ProcessorManager 管理器 |
| `bot/nanobot/data_processor/utils.py` | parse_kv_pairs 工具函数 |
| `bot/nanobot/data_processor/vocab/` | VocabProcessor (词汇处理) |
| `bot/nanobot/data_processor/polisher/` | PolisherProcessor (语法处理) |
| `bot/nanobot/data_processor/quiz/` | QuizProcessor (Quiz 生成) |
| `bot/nanobot/data_processor/notes/` | NotesProcessor (笔记处理) |

### 核心架构

```
BaseDataProcessor (抽象基类)
    │
    ├── VocabProcessor    → shared/vocab.jsonl
    ├── PolisherProcessor → shared/polisher.jsonl
    ├── QuizProcessor    → shared/knowledge_pool.jsonl
    └── NotesProcessor   → shared/notes.jsonl
```

### 处理流程

```
shared/thread.jsonl
    ↓
read() → preprocess() → build_prompt() → call_llm() → parse_output() → serialize()
    ↓
shared/{processor}.jsonl
```

### Processor 触发配置

**`global/trigger/count/count.yaml`** 新增：
- `vocab_processor`: file_line_count >= 50 → shared/vocab.jsonl
- `polisher_processor`: file_line_count >= 50 → shared/polisher.jsonl
- `quiz_processor`: file_line_count >= 100 → shared/knowledge_pool.jsonl
- `notes_processor`: file_line_count >= 50 → shared/notes.jsonl

### Pydantic 验证

- **Input Schema**: preprocess() 中验证输入数据
- **Output Schema**: parse_llm_output() 中验证输出数据
- 类型错误记录会被跳过

---

## Phase 3a: Knowledge Graph (NetworkX)

### 功能概述

从 Level 2 文件提取实体和关系，构建用户知识图谱。

### 新增文件

| File | Description |
|------|-------------|
| `bot/nanobot/kg/__init__.py` | Package init |
| `bot/nanobot/kg/topics.py` | 预定义 IELTS topics 列表 |
| `bot/nanobot/kg/entity_store.py` | EntityStore 实体存储 |
| `bot/nanobot/kg/cursor.py` | CursorManager 增量追踪 |
| `bot/nanobot/kg/extractor.py` | EntityExtractor LLM 输出解析 |
| `bot/nanobot/kg/kg_updater.py` | KGUpdater 更新逻辑 |
| `subagents/cross_session/kg_subagent.md` | KG Subagent prompt |

### 数据结构

```json
// kg/entity_database.json
{
  "entities": [
    {"id": "e1", "label": "Jerry", "type": "person", "topics": ["sports", "food"]}
  ],
  "relations": [
    {"from": "e1", "to": "e2", "type": "likes", "topics": ["sports"]}
  ]
}
```

### Cursor 机制

cron 和 count 共用同一 cursor，保证幂等性。

---

## Phase 3b: Review Mode (Spaced Repetition)

### 功能概述

从 Level 2 文件提取知识要点，按熟悉度抽样出题复习。

### 新增文件

| File | Description |
|------|-------------|
| `shared/review/__init__.py` | Package init |
| `shared/review/store.py` | ReviewStore 知识点存储 |
| `shared/review/cursor.py` | ReviewCursorManager 独立 cursor |
| `shared/review/extractor.py` | ReviewExtractor LLM 输出解析 |
| `shared/review/selector.py` | ReviewSelector 按熟悉度抽样 |
| `subagents/cross_session/review_subagent.md` | Review Subagent prompt |

### 数据结构

```json
// shared/review/review_points.jsonl
{"id": "rp1", "content": "be quite fond of", "type": "expression", "topic": "food"}

// shared/review/review_index.json
{
  "points": {
    "rp1": {"familiarity": 0, "attempts": 2, "question_type": "sentence_use"}
  }
}
```

### 规则

- **familiarity += 1**（答对）/ **+0**（答错）
- **attempts += 1**（每次答题）
- **threshold = 3**（变量，后续可能用于优先选择）
- **不归零**

---

## Summary of Files Changed

| File | Changes |
|------|---------|
| `.gitignore` | 添加 shared/thread.jsonl |
| `bot/nanobot/session/manager.py` | Phase 1: 双写 shared/thread.jsonl |
| `bot/nanobot/data_processor/` | Phase 2: 完整框架 + 4 个 Processor |
| `bot/nanobot/kg/` | Phase 3a: 知识图谱模块 |
| `shared/review/` | Phase 3b: 复习模式模块 |
| `global/trigger/count/count.yaml` | 新增 KG/Review 触发器 |

---

*Update created: 2026-05-25*

## 2026-05-24 - AI 回复笔记 / QuickNote Session 过滤

本次更新为全局笔记本添加了 AI 智能回复生成功能，并修复了 QuickNote 面板的 session 过滤问题。

---

## 1. AI 回复笔记功能

### 功能概述

用户可以点击笔记卡片的 "AI Reply" 按钮，系统会异步生成针对该笔记的鼓励/建议/纠错回复，并自动关联到对应笔记。

### 后端修改

**`bot/nanobot/agent/loop.py`**
- 修复 `_check_notes_ai_queue()` 中的变量遮蔽问题：`task` → `task_prompt`
- 修复错误引用变量：`task` → `task_item`
- 队列任务处理逻辑正确更新 task_item 状态

**`bot/nanobot/channels/websocket.py`**
- 新增 `_handle_notes_ai_reply_request()`：接收 AI 回复请求，写入队列
- 新增 `_handle_notes_ai_reply_status()`：查询任务状态
- 新增 `_handle_notes_ai_replies_list()`：获取 AI 回复列表
- 修复字段映射：index.json 的 `id` → `noteId`，`timestamp` ISO 字符串 → 毫秒，`date` 字段提取
- 修改 `_generate_notes_markdown()`：markdown 头部包含 `[id:xxx]` 用于 ID 持久化

### 前端修改

**`bot/webui/src/components/NotesBookSheet.tsx`**
- 新增 `triggerNotesAiReply()` 调用触发 AI 回复
- 新增轮询逻辑：每 2 秒查询任务状态，完成后重新获取数据刷新 UI
- 导入 `fetchNotesAiReplyStatus` API
- 绿色 Check 图标：有 AI 回复的笔记显示绿色对勾

**`bot/webui/src/components/GlobalNotes.tsx`**
- `parseNotesContent()` 支持从 markdown 提取 `[id:xxx]` 格式的 ID
- `GlobalNotesPanel` 支持按 sessionTitle 过滤笔记

### 数据流

```
1. 用户点击 AI Reply → POST /api/notes/ai-reply?note_id=xxx&...
2. 后端写入 .notes_ai_queue.json (status: pending)
3. AgentLoop 定时检查队列 → spawn subagent 生成回复
4. Subagent 写入 user-notes/ai-replies/index.json
5. 前端轮询状态 → 完成则重新获取笔记和 AI 回复
6. 前端匹配 note.id === aiReply.noteId → 显示回复
```

### 存储结构

```
user-notes/
├── .notes_ai_queue.json          # AI 回复任务队列
└── ai-replies/
    ├── index.json                # AI 回复索引
    └── by-date/                  # 按日期的回复文件
        └── ai-reply-YYYY-MM-DD.md
```

---

## 2. QuickNote Session 过滤

### 问题

切换 session 后，QuickNote 悬浮面板仍然显示所有 session 的笔记。

### 修复

**`bot/webui/src/components/GlobalNotes.tsx`**
- `GlobalNotesPanel` 接收 `sessionTitle` prop
- 新增 `displayEntries` 过滤：仅当 `entry.sessionTitle === 当前 sessionTitle` 时显示
- 空 sessionTitle 时显示所有笔记（保持原有行为）

---

## 3. 修复的其他问题

- `parseNotesContent` 每次解析都生成新 ID → 改为从 markdown 提取持久化的 ID
- AI 回复字段映射：后端返回 `id` 而非 `noteId`，ISO 时间戳未转换
- 前端触发 AI 回复后不刷新 → 添加轮询和 UI 更新

---

## Summary of Files Changed

| File | Changes |
|------|---------|
| `bot/nanobot/agent/loop.py` | 修复变量遮蔽、错误引用 |
| `bot/nanobot/channels/websocket.py` | 新增 AI reply API、markdown 含 ID、字段映射 |
| `bot/webui/src/components/NotesBookSheet.tsx` | AI 回复轮询、绿色对勾图标 |
| `bot/webui/src/components/GlobalNotes.tsx` | ID 提取、session 过滤 |
| `bot/webui/src/lib/api.ts` | 新增 fetchNotesAiReplyStatus |

---

*Update created: 2026-05-24*

## 2026-05-23 - 全局笔记本（Global Notes）

本次更新在 WebUI 中添加了一个全局悬浮笔记本功能，用户可以在任何对话中快速记录笔记，支持引用消息内容和 ASR 时间戳。

---

## 1. 全局笔记本组件

### 新增文件

**`bot/webui/src/components/GlobalNotes.tsx`**
- `useGlobalNotes` hook：管理笔记状态、通过 API 持久化到后端
- `GlobalNotesPanel` 组件：笔记本面板 UI，支持添加/编辑/删除笔记
- `GlobalNotesFloatingButton` 组件：右下角悬浮按钮
- `QuoteProvider` / `useQuote` context：管理消息引用状态
- 支持功能：
  - 点击消息的 Quote 按钮添加引用（临时状态）
  - 录音时可添加 ASR 时间戳
  - 笔记按时间倒序显示
  - 编辑和删除单条笔记

### UI 特性

- 笔记本面板：宽度 384px，最大高度 576px
- 悬浮按钮：右下角固定位置，点击展开/收起
- 引用预览：在输入框上方显示待添加的引用内容
- 引用样式：紫色左边框 + 浅紫色背景

---

## 2. 消息引用功能

### 修改文件

**`bot/webui/src/components/MessageBubble.tsx`**
- 用户消息和助手消息添加 Quote 按钮
- 鼠标悬停时显示引用按钮
- 点击后自动打开笔记本面板
- 引用作为临时状态，只有点击 "Add" 才保存

### 交互流程

```
1. 鼠标悬停在消息上 → 显示 Quote 按钮
2. 点击 Quote 按钮 → 笔记本面板自动打开
3. 输入框上方显示引用的内容（带 X 可移除）
4. 可选：在输入框写备注
5. 点击 Add → 笔记保存，包含引用内容
```

---

## 3. 后端笔记 API

### 修改文件

**`bot/nanobot/channels/websocket.py`**
- 新增 `_handle_global_notes()` 处理函数
- 新增 `_generate_notes_markdown()` 生成 markdown 格式
- GET `/api/notes?date=YYYY-MM-DD` - 读取指定日期的笔记
- POST `/api/notes?date=...&data=...` - 保存笔记（通过 query 参数传递数据，因为 WsRequest 不直接暴露 body）

### 存储结构

```
ielts-speaking-bot/user-notes/
├── notes.json                              # 原始数据 (source of truth)
├── by-date/
│   └── user-note-2026-05-23.md          # 按日期组织的笔记
└── by-session/
    └── My_Session.md                      # 按 session 组织的笔记
```

### 笔记 JSON 格式

```json
{
  "date": "2026-05-23",
  "entries": [
    {
      "id": "...",
      "timestamp": 1747992000000,
      "sessionTitle": "Family",
      "content": "123",
      "quotedContent": "A cat counts as a family member too"
    }
  ]
}
```

### Markdown 格式

```markdown
# Notes - 2026-05-23

---
**[2026-05-23 20:01:04]** | Family

> A cat counts as a family member too

123

---
```

---

## 4. SessionManager 修复

### 修改文件

**`bot/nanobot/channels/websocket.py`**
- 修复两处 `.sessions` 属性访问错误（第 1435 和 1508 行）
- `SessionManager` 使用 `_cache` 而非 `sessions` 属性
- 涉及函数：
  - `_handle_session_benative_progress`
  - `_handle_session_benative_responses`

---

## 5. 其他更新

**`bot/webui/src/lib/api.ts`**
- 新增 `fetchGlobalNotes()` 和 `saveGlobalNotes()` API 函数
- 保存时使用 query 参数传递数据

**`.gitignore`**
- 添加 `user-notes/` 目录

**`bot/webui/src/i18n/locales/en/common.json`**
- 新增 `globalNotes.*` 翻译文案

---

## Summary of Files Changed

| File | Changes |
|------|---------|
| `bot/webui/src/components/GlobalNotes.tsx` | 新增：全局笔记本组件、QuoteProvider、useQuote hook |
| `bot/webui/src/components/MessageBubble.tsx` | 新增：Quote 按钮和引用功能 |
| `bot/webui/src/App.tsx` | 集成 GlobalNotes 和 QuoteProvider |
| `bot/webui/src/lib/api.ts` | 新增：fetchGlobalNotes、saveGlobalNotes API |
| `bot/nanobot/channels/websocket.py` | 新增：_handle_global_notes、_generate_notes_markdown；修复：.sessions → _cache |
| `bot/webui/src/i18n/locales/en/common.json` | 新增：globalNotes.* 翻译 |
| `.gitignore` | 新增：user-notes/ |

---

*Update created: 2026-05-23*

## 2026-05-22 - WhisperLiveKit 本地语音输入集成

本次更新将 WhisperLiveKit 本地实时转写能力接入 nanobot WebUI，使 `uv run nanobot gateway` 可以在本机自动启动 WhisperLiveKit，并在聊天输入框中提供带声音波纹状态的麦克风输入体验。

---

## 1. WhisperLiveKit 自动启动接入

### 启动方式调整

**`bot/nanobot/cli/commands.py`**
- 将原先依赖 PATH 中 `wlk` 命令的启动方式，改为使用当前 uv 环境的 Python 解释器启动：
  - `sys.executable -c "from whisperlivekit.cli import main; main()" serve ...`
- 保证用户执行 `uv run nanobot gateway` 时，WhisperLiveKit 子进程与 nanobot 使用同一个虚拟环境。
- 启动参数新增 `--pcm-input`，让 WhisperLiveKit 服务端返回 `useAudioWorklet: true`，前端稳定走 PCM AudioWorklet 流式输入。

### 本机服务管理

- WhisperLiveKit 固定绑定 `127.0.0.1`，符合当前“仅本机使用”的需求。
- 从 `channels.whisperlivekit_url` 解析端口，默认使用 `8000`。
- 启动前检查 `http://127.0.0.1:{port}/health`：
  - 如果已有 WhisperLiveKit 服务在运行，则复用已有服务。
  - 如果没有运行，则由 gateway 启动并托管子进程。
- 启动后轮询 `/health`，替代固定 sleep，提高模型加载较慢时的可靠性。
- gateway 退出时只关闭自己托管的 WhisperLiveKit 子进程，不会误杀外部手动启动的服务。

### 依赖接入

**`bot/pyproject.toml`**
- 新增 `whisperlivekit>=0.2.20` 依赖。
- 新增 uv 本地源：
  - `whisperlivekit = { path = "../WhisperLiveKit", editable = true }`
- 这样 bot 项目会直接使用仓库内顶层 `WhisperLiveKit/` 源码。

---

## 2. Voice Settings API 完善

**`bot/nanobot/channels/websocket.py`**

新增/完善 WebUI voice settings 的读取与保存能力：

- settings payload 中返回：
  - `provider`
  - `whisperlivekit_autostart`
  - `whisperlivekit_url`
  - `whisperlivekit_language`
  - `whisperlivekit_model`
- 新增 `/api/settings/voice/update` 更新入口。
- 保存 voice 配置时增加 URL 校验：
  - scheme 必须是 `ws` 或 `wss`
  - path 必须是 `/asr`
  - autostart 开启时 host 必须是 `localhost`、`127.0.0.1` 或 `::1`
- 对会影响 WhisperLiveKit 子进程的配置变更返回 `requires_restart=True`，例如：
  - provider 切换
  - autostart 切换
  - model / language 变更
  - WhisperLiveKit URL host / port / path 变更

---

## 3. WebUI 语音状态统一

### 统一 voice settings store

**`bot/webui/src/hooks/useVoiceSettings.ts`**
- 默认 provider 改为 `whisperlivekit`。
- 作为 WebUI 内部统一 voice settings store，避免设置页和语音 hook 使用不同默认值。

**`bot/webui/src/components/settings/SettingsView.tsx`**
- 加载 settings payload 时同步写入 voice settings store。
- 保存 voice settings 后同步更新 store，使麦克风输入无需刷新页面即可读取最新配置。

### Provider 分流与状态透出

**`bot/webui/src/hooks/useVoiceInput.ts`**
- 保留 Deepgram / WhisperLiveKit 双 provider 分支。
- WhisperLiveKit 作为默认本地 provider。
- 新增向 UI 暴露的状态：
  - `isProcessing`
  - `status`
  - `recordingStartedAt`
  - `provider`
- 让 composer 能显示“连接中 / 正在聆听 / 正在处理最后音频 / 错误”等状态。

---

## 4. WhisperLiveKit 浏览器 Hook 强化

**`bot/webui/src/hooks/useWhisperLiveKit.ts`**

对 WhisperLiveKit 前端 WebSocket 与录音生命周期进行了加固：

- 连接 `ws://localhost:8000/asr?language=...&mode=full`。
- 处理服务端消息：
  - `config`
  - `active_transcription`
  - `no_audio_detected`
  - `ready_to_stop`
- 支持 AudioWorklet PCM 流式输入：
  - `/web/pcm_worklet.js`
  - `/web/recorder_worker.js`
- 增加 config 消息超时，避免服务端连接异常时麦克风状态卡住。
- 修复 MediaRecorder fallback 的生命周期管理：
  - 独立保存 `MediaRecorder` ref
  - stop 时正确停止 recorder
  - 清理 stream、worklet、worker、AudioContext
- 启动失败会 reject 给上层 `useVoiceInput`，便于 UI 展示错误。
- 结束录音时发送空 `ArrayBuffer`，等待 `ready_to_stop` 后完成最终转写。

---

## 5. Composer 中加入 WhisperLiveKit 风格声音波纹

**`bot/webui/src/components/thread/ThreadComposer.tsx`**

新增 `VoiceInputStatus` 状态条，参考 WhisperLiveKit 原始 Web UI 的录音体验，但以 React/Tailwind 方式集成到 nanobot composer 中。

### UI 行为

- 录音、处理中或出错时显示状态条。
- 显示当前 provider：
  - `WhisperLiveKit local`
  - `Deepgram cloud`
- 显示录音计时器。
- 显示当前状态文本或错误信息。
- 麦克风按钮 aria label 改为 i18n 文案。

### 声音波纹

**`bot/webui/tailwind.config.js`**
- 新增 `voice-wave` keyframe 与 animation。
- 将原先的简单柱状动画改为更接近 WhisperLiveKit 的连续 SVG 波形：
  - 双层曲线
  - 横向流动
  - 轻微振幅变化
  - processing 状态下使用 pulse

---

## 6. Worker 资源与本地化

### WhisperLiveKit Worker 资源

确认以下 WebUI public 资源与顶层 WhisperLiveKit 源文件一致：

- `bot/webui/public/web/pcm_worklet.js`
- `bot/webui/public/web/recorder_worker.js`

这些文件负责浏览器端 PCM 提取、降采样和发送给 WhisperLiveKit WebSocket。

### i18n 文案补齐

更新所有 locale：

- `bot/webui/src/i18n/locales/en/common.json`
- `bot/webui/src/i18n/locales/es/common.json`
- `bot/webui/src/i18n/locales/fr/common.json`
- `bot/webui/src/i18n/locales/id/common.json`
- `bot/webui/src/i18n/locales/ja/common.json`
- `bot/webui/src/i18n/locales/ko/common.json`
- `bot/webui/src/i18n/locales/vi/common.json`
- `bot/webui/src/i18n/locales/zh-CN/common.json`
- `bot/webui/src/i18n/locales/zh-TW/common.json`

新增文案包括：
- Voice 设置分区
- voice provider / WhisperLiveKit URL / model / language / autostart
- 麦克风 start / stop aria label
- WhisperLiveKit local / Deepgram cloud
- listening / processing / error 状态

---

## 7. 测试与验证

### 已通过的检查

- `uv --project bot run python -m compileall bot/nanobot/cli/commands.py bot/nanobot/channels/websocket.py`
- `uv --project bot run python -c "import whisperlivekit; from whisperlivekit.cli import main; print(whisperlivekit.__file__)"`
- `bun run --cwd bot/webui test`
- `bun run --cwd bot/webui test src/tests/thread-composer.test.tsx`
- `bun run --cwd bot/webui test src/tests/i18n.test.tsx`
- `bun run --cwd bot/webui build`

### 测试修复

- `bot/webui/src/tests/thread-composer.test.tsx`
  - 更新麦克风按钮 aria label 断言。
- `bot/webui/src/tests/app-layout.test.tsx`
  - 补齐 `NanobotClient` mock 中缺失的 `onSubagentStatus`，避免 App layout 测试在 React effect 阶段报错。

---

## Summary of Files Changed

| File | Changes |
|------|---------|
| `bot/pyproject.toml` | 新增 whisperlivekit 依赖和 uv 本地 editable source |
| `bot/nanobot/cli/commands.py` | WhisperLiveKit 使用 uv 当前 Python 自动启动，加入 `--pcm-input`、health check、托管退出 |
| `bot/nanobot/channels/websocket.py` | 新增 voice settings payload/update，URL 校验和 restart 提示 |
| `bot/nanobot/config/schema.py` | voice provider 与 WhisperLiveKit 默认配置 |
| `bot/webui/src/hooks/useVoiceSettings.ts` | 新增/统一 voice settings store，默认 WhisperLiveKit |
| `bot/webui/src/hooks/useVoiceInput.ts` | provider 分流、读取 voice settings、向 UI 暴露 status / processing / startedAt |
| `bot/webui/src/hooks/useWhisperLiveKit.ts` | WhisperLiveKit WebSocket + AudioWorklet 生命周期加固 |
| `bot/webui/src/components/settings/SettingsView.tsx` | Voice 设置 UI 和 store 同步 |
| `bot/webui/src/components/thread/ThreadComposer.tsx` | 新增 VoiceInputStatus 和 WhisperLiveKit 风格声音波纹 |
| `bot/webui/tailwind.config.js` | 新增 `voice-wave` 动画 |
| `bot/webui/public/web/pcm_worklet.js` | WhisperLiveKit PCM AudioWorklet 资源 |
| `bot/webui/public/web/recorder_worker.js` | WhisperLiveKit PCM 降采样 Worker 资源 |
| `bot/webui/src/i18n/locales/*/common.json` | 补齐 voice 设置与 composer 语音状态文案 |
| `bot/webui/src/lib/api.ts` | Voice settings update API 类型与调用 |
| `bot/webui/src/lib/types.ts` | SettingsPayload 增加 voice 配置类型 |
| `bot/webui/src/tests/thread-composer.test.tsx` | 更新语音按钮测试 |
| `bot/webui/src/tests/app-layout.test.tsx` | 补齐 NanobotClient mock |

---

*Update created: 2026-05-22*

## 2026-05-21 - 项目结构清理与配置重构

本次更新对项目目录结构进行了清理，移除了重复和废弃的文件，统一了 trigger 配置管理，并泛化了 mode-specific 的后端逻辑。

---

## 1. 清理 `persona/` 目录

`persona/` 目录是在引入 `mode/` 架构之前的旧结构，其中大量文件与新的 `mode/` 和 `subagents/` 目录重复。

### 删除的文件

**重复的 bootstrap 文件**（已被 `mode/{mode}/context/` 替代）：
- `persona/AGENTS.md`
- `persona/SOUL.md`
- `persona/USER.md`
- `persona/HEARTBEAT.md`
- `persona/TOOLS.md`
- `persona/topic_bank.md`

**重复的 subagent 文件**（已被顶层 `subagents/` 替代）：
- `persona/subagents/session/vocab_subagent.md`
- `persona/subagents/session/polisher_subagent.md`
- `persona/subagents/session/memory_subagent.md`
- `persona/subagents/cross_session/daily_consolidator_subagent.md`
- `persona/subagents/cross_session/memory_cron_subagent.md`
- `persona/subagents/cross_session/progress_organizer_subagent.md`
- `persona/subagents/cross_session/progress_tracker_subagent.md`

**废弃的 trigger 配置**（已被 `global/trigger/` 和 `mode/*/trigger/` 替代）：
- `persona/trigger/count/count.yaml`
- `persona/trigger/count/.cursor_progress_organizer.json`
- `persona/trigger/count/.cursor_progress_tracker.json`
- `persona/trigger/cron/cron.yaml`
- `persona/trigger/cron/jobs.json`

### 保留的文件

**用户级格式文档**（迁移到 `global/formats/`）：
- `persona/formats/daily_format.md`
- `persona/formats/memory_format.md`
- `persona/formats/polisher_format.md`
- `persona/formats/vocab_format.md`

**运行时数据**：
- `persona/memory/` — 用户记忆数据
- `persona/sessions/` — 会话数据（已在 `.gitignore`）
- `persona/session_index.jsonl` — 会话索引（已在 `.gitignore`）

### 同步更新的引用路径

**`bot/nanobot/agent/loop.py`**
- 更新 memory subagent 任务模板中的格式文件路径：
  - 从 `{workspace}/formats/memory_format.md`
  - 改为 `{workspace}/global/formats/memory_format.md`

---

## 2. 清理 Git 跟踪的运行时文件

以下文件是运行时生成的状态数据，不应纳入版本控制：
- `shared/.cursor_progress_organizer.json`
- `shared/.cursor_progress_tracker.json`
- `persona/trigger/count/.cursor_progress_organizer.json`
- `persona/trigger/count/.cursor_progress_tracker.json`
- `persona/memory/history.jsonl`

**`.gitignore` 更新**：
- 新增 `persona/memory/*.jsonl`
- 新增 `shared/.cursor_*.json`

---

## 3. WebUI 包管理器统一为 Bun

- 删除 `bot/webui/package-lock.json`
- 仅保留 `bot/webui/bun.lock`

---

## 4. Trigger 配置统一管理

### 新增 `global/trigger/defaults.yaml`

集中管理所有 trigger 的默认参数，避免在每个 trigger 中重复书写：

```yaml
version: 1
defaults:
  target:
    silent: true
```

### CounterEngine 支持默认值合并

**`bot/nanobot/counter/engine.py`**
- 新增 `_load_defaults()` — 加载 `global/trigger/defaults.yaml`
- 新增 `_apply_defaults(trigger_dict)` — 将默认值合并到 trigger，但允许 trigger 级别覆盖
- 全局 trigger 和 mode-specific trigger 加载时自动应用默认值

### Trigger YAML 简化

移除了 `silent: true` 的重复书写。需要 `model: "gpt-4o-mini"` 的 cross-session subagent 仍显式保留 model 字段；session-level subagent（vocab、polish）继续使用主模型，不设置 model。

**简化的文件**：
- `global/trigger/count/count.yaml`
- `mode/freechat/trigger/count/count.yaml`
- `mode/ielts/trigger/count/count.yaml`

**恢复 model 字段的 trigger**（cross-session 级别）：
- `memory_cron`
- `daily_consolidator`
- `progress_tracker`
- `benative_article_fetcher`
- `benative_translator`
- `ielts_feedback`

---

## 5. Mode Trigger 目录结构补全

每个 mode 现在具备完整的 trigger 目录结构：

```
mode/{mode}/
└── trigger/
    ├── count/count.yaml   # turn_count / file_line_count 触发器
    └── cron/cron.yaml     # cron 调度配置
```

**新建/恢复的文件**：
- `mode/freechat/trigger/cron/cron.yaml` — 空配置（之前被误删）
- `mode/ielts/trigger/cron/cron.yaml` — 空配置（之前被误删）
- `mode/benative/trigger/cron/cron.yaml` — 新建空配置

---

## 6. Session Manager 泛化

**`bot/nanobot/session/manager.py`**

将 mode-specific 的 `append_benative_response()` 和 `append_freechat_response()` 泛化为统一的 `append_mode_response()`：

```python
def append_mode_response(
    self,
    session: Session,
    round_num: int,
    **fields: Any,
) -> None
```

**改动点**：
- `_get_mode_responses_path()` 改为通用路径构建：`shared/{mode}/sessions/{uuid}/responses.jsonl`
- `append_mode_response()` 接受 `**fields` 参数，任何 mode 都可以调用
- 旧的 `append_benative_response()` 和 `append_freechat_response()` 保留为 wrapper（标记为 deprecated），确保向后兼容

---

## Summary of Files Changed

| File | Changes |
|------|---------|
| `.gitignore` | +persona/memory, +shared/.cursor_*.json |
| `bot/nanobot/agent/loop.py` | 更新 formats 路径引用 |
| `bot/nanobot/counter/engine.py` | +_load_defaults, +_apply_defaults |
| `bot/nanobot/session/manager.py` | +append_mode_response, 泛化 _get_mode_responses_path |
| `global/trigger/defaults.yaml` | 新建：统一默认配置 |
| `global/trigger/count/count.yaml` | 简化：移除重复 silent，cross-session 保留 model |
| `global/formats/*.md` | 从 persona/formats/ 迁移 |
| `mode/freechat/trigger/count/count.yaml` | 简化：移除重复 silent |
| `mode/freechat/trigger/cron/cron.yaml` | 恢复（空配置） |
| `mode/ielts/trigger/count/count.yaml` | 简化：移除重复 silent，ielts_feedback 保留 model |
| `mode/ielts/trigger/cron/cron.yaml` | 恢复（空配置） |
| `mode/benative/trigger/cron/cron.yaml` | 新建（空配置） |
| `bot/webui/package-lock.json` | 删除 |

---

*Update created: 2026-05-21*

## 2026-05-21 - Be Native Mode

This update adds a new "be native" mode for authentic expression practice through real-world English content.

### Overview

Benative mode enables users to practice English translation by:
1. Fetching news articles daily (12:00) via web search + web fetch
2. Translating articles into Chinese sentence pairs
3. Practicing by translating Chinese back to English sentence by sentence
4. Reviewing translations with word/structure comparison every N sentences

### New Files

**`mode/benative/`** - Benative mode configuration
```
mode/benative/
├── context/
│   ├── AGENTS.md      # Sentence-by-sentence practice instructions
│   ├── SOUL.md        # Native speaker coach personality
│   ├── USER.md
│   ├── HEARTBEAT.md
│   └── TOOLS.md
└── trigger/
    └── count/count.yaml  # benative_review trigger (turn_count: 10)
```

**`subagents/cross_session/benative_article_fetcher_subagent.md`**
- Fetches news articles via web_search + web_fetch
- Extracts entities (persons, organizations, locations)
- Stores to `shared/benative/articles/{uuid}.json`

**`subagents/cross_session/benative_translator_subagent.md`**
- Translates articles sentence by sentence
- Stores English-Chinese pairs to `shared/benative/pairs/{uuid}.jsonl`

**`subagents/session/benative_review_subagent.md`**
- Reviews user responses vs original English
- Outputs word-level and structure analysis
- Writes to `session/notes/benative_review.md`

### Updated Files

**`global/trigger/count/count.yaml`** - Added benative triggers:
- `benative_article_fetcher`: cron at 12:00 daily
- `benative_translator`: cron at 13:00 daily

**`global/trigger/cron/cron.yaml`** - Added benative cron jobs

**`bot/nanobot/command/builtin.py`** - Added `cmd_benative()` and `/benative` command

### Session Flow

```
/benative → 显示文章列表 → 用户选择 → 逐句显示中文 → 用户翻译 → 每10句 review
```

### Data Storage

- `shared/benative/articles/` - Original English articles (JSON)
- `shared/benative/pairs/` - Sentence pairs (JSONL: `{"en": "...", "zh": "..."}`)
- `shared/benative/sessions/{uuid}/responses.jsonl` - User responses per session
- `session/notes/benative_review.md` - AI review output
- `session/notes/benative_progress.json` - Current progress

### Backend Changes

**`bot/nanobot/session/manager.py`**
- Added `append_benative_response()` - writes to shared/benative/sessions/{uuid}/responses.jsonl
- Added `append_freechat_response()` - writes to shared/freechat/sessions/{uuid}/responses.jsonl
- Added `_get_mode_responses_path()` - returns mode-specific responses path

**`bot/nanobot/channels/websocket.py`**
- Added `_handle_benative_articles()` - GET /api/benative/articles
- Added `_handle_session_benative()` - GET /api/sessions/{key}/benative
- Added `_handle_session_benative_article()` - GET /api/sessions/{key}/benative/article
- Added `_handle_session_benative_responses()` - GET /api/sessions/{key}/benative/responses

### WebUI Changes

**New Components:**
- `ArticleSelectDialog.tsx` - Modal for selecting articles
- `BenativeProgressIndicator.tsx` - Shows "10/123" progress badge
- `BenativeNotesSheet.tsx` - Session notes panel with responses and review tabs

**New Hooks:**
- `useBenativeArticles.ts` - Fetches available articles
- `useBenativeProgress.ts` - Fetches session progress
- `useBenativeResponses.ts` - Fetches user responses

**New API Functions:**
- `fetchBenativeArticles()` - GET /api/benative/articles
- `fetchBenativeProgress()` - GET /api/sessions/{key}/benative
- `fetchBenativeArticle()` - GET /api/sessions/{key}/benative/article
- `fetchBenativeResponses()` - GET /api/sessions/{key}/benative/responses

## 2026-05-21 - Mode Architecture

This update implements a modular mode architecture that decouples freechat from the core and enables adding new modes (ielts, etc.). Global functionality runs regardless of mode, while mode-specific features only run when that mode is active.

---

## 1. New Directory Structure

### `global/` — Global Shared (Always Runs)
```
global/
├── trigger/
│   ├── count/count.yaml    # Global triggers (memory_cron, daily_consolidator, progress_tracker)
│   └── cron/cron.yaml
└── (triggers only, no subagents)
```

### `mode/` — Mode Configurations
```
mode/
├── freechat/
│   ├── context/           # Bootstrap files (AGENTS.md, SOUL.md, etc.)
│   │   ├── AGENTS.md
│   │   ├── SOUL.md
│   │   ├── USER.md
│   │   ├── HEARTBEAT.md
│   │   ├── TOOLS.md
│   │   └── topic_bank.md
│   └── trigger/
│       └── count/count.yaml  # Mode-specific triggers (vocab, polish)
└── ielts/
    ├── context/
    │   ├── AGENTS.md
    │   ├── SOUL.md
    │   ├── USER.md
    │   └── HEARTBEAT.md
    └── trigger/
        └── count/count.yaml  # Mode-specific triggers (vocab, polish, ielts_feedback)
```

### `subagents/` — Centralized Subagent Prompts
```
subagents/
├── session/               # Mode-specific subagents
│   ├── vocab_subagent.md
│   ├── polisher_subagent.md
│   └── ielts_feedback_subagent.md
└── cross_session/         # Global subagents
    ├── memory_cron_subagent.md
    ├── daily_consolidator_subagent.md
    └── progress_tracker_subagent.md
```

### `shared/` — Shared Data (Mode-Independent)
```
shared/
├── memory/MEMORY.md
├── daily/daily_*.md
├── progress.json
├── progress_bank.jsonl
├── user_responses.jsonl
└── .cursor_*.json
```

---

## 2. CounterEngine — Global + Mode Triggers

**`bot/nanobot/counter/engine.py`**

- `_load_global_config()` — Loads global triggers from `global/trigger/count/count.yaml` (always active)
- `_load_config()` — Loads mode-specific triggers from `mode/{mode}/trigger/count/count.yaml` and merges with global
- `set_mode(mode)` — Switches mode and reloads config
- `load_prompt()` — Searches `subagents/{prompt_file}` first, then mode-specific paths

### Global Triggers (always run)
| ID | Condition | Subagent |
|----|-----------|----------|
| memory_cron | cron: 0 0 * * * | memory_cron_subagent |
| daily_consolidator | cron: 0 */8 * * * | daily_consolidator_subagent |
| progress_tracker | file_line_count: 2 | progress_tracker_subagent |

### Mode Triggers (only when mode active)
**freechat:** vocab_analysis (turn_count: 2), polish_feedback (turn_count: 3)
**ielts:** vocab_analysis (turn_count: 2), polish_feedback (turn_count: 3), ielts_feedback (turn_count: 5)

---

## 3. ContextBuilder — Mode-Aware Bootstrap Loading

**`bot/nanobot/agent/context.py`**

- `_mode: str | None` — Stored mode for context building
- `_load_bootstrap_files(mode)` — Loads AGENTS.md, SOUL.md, USER.md, TOOLS.md from `mode/{mode}/context/`
- Falls back to workspace root if mode context doesn't exist

---

## 4. AgentLoop — Mode Propagation

**`bot/nanobot/agent/loop.py`**

- `_state_build()` — Reads `session.metadata["mode"]` and passes to ContextBuilder
- Sets `ctx.initial_messages` with mode-aware context

---

## 5. Command Updates

**`bot/nanobot/command/builtin.py`**

- `cmd_freechat()` — Sets `session.metadata["mode"] = "freechat"`, updates counter_engine, selects topic
- `cmd_ielts()` — Sets `session.metadata["mode"] = "ielts"`, updates counter_engine

**`bot/nanobot/cli/commands.py`**

- `on_cron_job()` — Enhanced to handle global cron triggers (memory_cron, daily_consolidator, progress_organizer)

---

## 6. Removed Old Triggers Location

- `persona/counter/triggers.yaml` — Deleted (replaced by global/trigger/count/count.yaml + mode/*/trigger/count/count.yaml)
- `persona/cron/jobs.json` — Deleted (now in global/trigger/cron/cron.yaml)
- `global/subagents/` — Deleted (all subagents centralized in `subagents/`)

---

## Summary of Files Changed

| File | Changes |
|------|---------|
| bot/nanobot/agent/context.py | +mode-aware bootstrap loading |
| bot/nanobot/agent/loop.py | +mode propagation to context |
| bot/nanobot/command/builtin.py | +cmd_freechat, +cmd_ielts |
| bot/nanobot/cli/commands.py | +cron handlers for global triggers |
| bot/nanobot/counter/engine.py | +global/mode trigger merge, +set_mode() |
| global/trigger/count/count.yaml | new: global triggers |
| global/trigger/cron/cron.yaml | new: global cron jobs |
| mode/freechat/context/ | new: freechat bootstrap files |
| mode/freechat/trigger/count/count.yaml | new: freechat triggers |
| mode/ielts/context/ | new: ielts bootstrap files |
| mode/ielts/trigger/count/count.yaml | new: ielts triggers |
| subagents/session/ | new: vocab, polisher, ielts_feedback subagents |
| subagents/cross_session/ | new: memory, daily, progress subagents |
| shared/ | new: shared data directory |
| architecture.md | updated: full mode architecture docs |

## 2026-05-21 - Memory Cron + Daily Consolidator Cron

This update converts memory subagent from turn_count trigger to cron-based (24h), adds daily_consolidator cron that aggregates vocab.md and polisher.md into daily.md, and implements time-based cursor system for both.

---

## 1. Time-Based Cursor System

### New File: `bot/nanobot/cli/cron_utils.py`

Cursor utilities for cron-based subagents:
- `read_time_cursor(workspace, trigger_id)` — reads `.cursor_{trigger_id}.json`
- `write_time_cursor(workspace, trigger_id, timestamp)` — writes timestamp to cursor file
- `find_modified_sessions(sessions_dir, since_timestamp)` — finds sessions with thread.jsonl modified since cursor
- `find_sessions_with_modified_notes(sessions_dir, since_timestamp)` — finds sessions with vocab.md/polisher.md modified since cursor

### Cursor File Format

```json
{
  "last_processed_timestamp": "2026-05-21T00:00:00Z"
}
```

**Two separate cursors**:
- `.cursor_memory_cron.json` — tracks thread.jsonl modification
- `.cursor_daily_consolidator.json` — tracks notes modification

---

## 2. Memory Cron Subagent

### New File: `persona/subagents/cross_session/memory_cron_subagent.md`

- Reads sessions modified since last cron run
- Extracts NEW user facts/preferences from thread.jsonl
- Updates `memory/MEMORY.md` incrementally
- Engineering layer filters by timestamp, LLM only does semantic analysis

### Cron Schedule
Configured in `triggers.yaml` as `kind: cron, count: "0 0 * * *"` (midnight daily)

### Disabled Old Trigger
`memory_update` (turn_count based) is now `enabled: false`

---

## 3. Daily Consolidator Subagent

### New Files

**`persona/subagents/cross_session/daily_consolidator_subagent.md`**
- Aggregates vocab.md and polisher.md from all sessions modified since last run
- Writes to `daily/daily_{date}.md` with JSON structure

**`persona/formats/daily_format.md`**
- JSON structure specification for daily.md

### Daily.md Structure

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

### Cron Schedule
Configured in `triggers.yaml` as `kind: cron, count: "0 */8 * * *"` (every 8 hours)

---

## 4. CounterCondition — Added `cron` Kind

**`bot/nanobot/counter/types.py`**
- Added `cron` to `kind` literal: `Literal["turn_count", "file_line_count", "cron"]`
- Cron triggers use `count` field for cron expression (e.g., `"0 0 * * *"`)

---

## 5. on_cron_job Handler Extensions

**`bot/nanobot/cli/commands.py`**
- Added `memory_cron` handler: reads cursor, finds modified sessions, spawns subagent, updates cursor
- Added `daily_consolidator` handler: reads cursor, finds sessions with modified notes, spawns subagent, updates cursor

---

## Summary of Files Changed

| File | Changes |
|------|---------|
| bot/nanobot/counter/types.py | +cron to condition kind |
| bot/nanobot/cli/cron_utils.py | new: cursor utils, session discovery |
| bot/nanobot/cli/commands.py | +memory_cron, +daily_consolidator handlers |
| persona/subagents/cross_session/memory_cron_subagent.md | new |
| persona/subagents/cross_session/daily_consolidator_subagent.md | new |
| persona/formats/daily_format.md | new: daily.md JSON structure |
| persona/counter/triggers.yaml | +memory_cron, +daily_consolidator, disabled memory_update |
| persona/cron/jobs.json | +memory_cron, +daily_consolidator cron jobs |

---

## 2026-05-21 - Subagent Reorganization + Cron-Based Progress Organizer + Engineering Optimizations

---

## 1. Subagent Folder Reorganization

### New Directory Structure
```
persona/subagents/
  session/
    vocab_subagent.md
    polisher_subagent.md
    memory_subagent.md
  cross_session/
    progress_tracker_subagent.md
    progress_organizer_subagent.md   # NEW
```

### Changes
- Moved session-level subagents (vocab, polisher, memory) to `persona/subagents/session/`
- Moved cross-session subagents (progress_tracker) to `persona/subagents/cross_session/`
- Created new `persona/subagents/cross_session/progress_organizer_subagent.md`
- Updated `triggers.yaml` `prompt_file` paths to new directory structure

---

## 2. CounterTrigger Schema Enhancements

### New Fields in `CounterTarget`

**bot/nanobot/counter/types.py**
- Added `depends_on: str | None` — trigger ID that must complete before this fires
- Added `model: str | None` — override default model for this subagent (e.g., "gpt-4o-mini")

### Unified `count` Field
- Replaced deprecated `every` and `threshold` fields with unified `count` field
- `triggers.yaml` updated: `every: 2` → `count: 2`, `every: 3` → `count: 3`, etc.

---

## 3. SubagentManager — Awaitable Completion Handle

### New Features

**bot/nanobot/agent/subagent.py**
- Added `completion_event: asyncio.Event` to `SubagentStatus` — fires when subagent finishes
- Added `wait_for_subagent(task_id)` method — awaits completion event, returns final status
- `spawn()` now returns `task_id` (string) instead of human-readable message
- `spawn()` accepts `model: str | None` parameter to override default model
- `_run_subagent()` passes model to `AgentRunSpec`

### Completion Event Flow
```python
# SubagentStatus
completion_event: asyncio.Event  # set() when done

# wait_for_subagent
await status.completion_event.wait()
return status
```

---

## 4. Cron-Based Progress Organizer

### Change from depends_on to Cron

**`progress_organizer`** — now fires via cron at midnight daily instead of via depends_on chain
- Cron schedule: `0 0 * * *` (midnight every day)
- Disabled in triggers.yaml (still kept for prompt/task reference)
- Spawned directly by `on_cron_job` handler in commands.py

### Cron Service Integration

**bot/nanobot/cli/commands.py**
- Added special handling in `on_cron_job` for `job.name == "progress_organizer"`
- Finds trigger in `agent.counter_engine._triggers`
- Loads prompt via `counter_engine.load_prompt()`
- Builds task via `counter_engine.build_task()` with empty session_dir
- Spawns via `agent.subagents.spawn()` with `announce_result=False`
- Awaits completion via `agent.subagents.wait_for_subagent()`

**persona/cron/jobs.json**
- Added `progress_organizer` cron job with `kind: "cron"` and `expr: "0 0 * * *"`

---

## 5. Engineering Optimizations — Content-Only LLM Input

### Problem
Previously, LLM read `user_responses.jsonl` directly and saw all metadata fields (`session_uuid`, `round`, `topic`, `content`, `timestamp`). It only needed `content`, wasting tokens.

### Solution
Engineering layer extracts `content` before LLM call. LLM receives only content strings. After LLM returns highlights, engineering layer zips results with original `meta_info` using positional alignment.

### Data Flow
```
user_responses.jsonl
  └─> [Engineering: extract content] ──> LLM receives only content strings
       └─> [Engineering: zip with meta] ──> progress_bank.jsonl ({category, intent, expression, content, meta})

progress_bank.jsonl
  └─> [Engineering: extract expression+content] ──> LLM refines expressions only
       └─> [Engineering: zip with content+meta] ──> progress.json
```

### New Entry Formats

**progress_bank.jsonl:**
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

**progress.json** (under categories):
```json
{
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

### Files Changed

**bot/nanobot/agent/tools/progress_bank.py**
- Added `contents: list[str]` parameter — content strings extracted by engineering
- `execute()` zips `contents[i]` with `entries[i]` and source `meta`

**bot/nanobot/agent/tools/progress_organizer.py**
- Added `contents: list[str]` parameter — expression strings for refinement
- Reads full entries from `progress_bank.jsonl` to preserve `content` + `meta`

**persona/subagents/cross_session/progress_tracker_subagent.md**
- LLM receives `contents` via tool call — no file reading
- Passes back same `contents` array for engineering alignment

**persona/subagents/cross_session/progress_organizer_subagent.md**
- LLM receives `contents` (expressions) via tool call — no file reading

---

## Summary of Files Changed

| File | Changes |
|------|---------|
| bot/nanobot/agent/subagent.py | +completion_event, +wait_for_subagent, +model param, returns task_id |
| bot/nanobot/agent/loop.py | chained triggers via _schedule_background, model override pass-through |
| bot/nanobot/counter/types.py | +depends_on, +model fields, unified count |
| bot/nanobot/counter/engine.py | trigger chaining support |
| bot/nanobot/agent/tools/progress_bank.py | +contents param, new entry format with content+meta |
| bot/nanobot/agent/tools/progress_organizer.py | +contents param, preserve content+meta |
| bot/nanobot/cli/commands.py | +progress_organizer cron handler in on_cron_job |
| persona/counter/triggers.yaml | new paths, +progress_tracker, progress_organizer disabled (cron-based now) |
| persona/cron/jobs.json | +progress_organizer cron job at midnight daily |
| persona/subagents/session/ | new dir — vocab, polisher, memory subagents |
| persona/subagents/cross_session/ | new dir — progress_tracker, progress_organizer subagents |

---

*Update created: 2026-05-21*

## 2026-05-20 - Session Persistence: UUID, Round Tracking, and Session Index

This update adds session UUID tracking, round tracking in messages (for indexing word/expression to original sentences), and a session index file for fast lookup.

---

## 1. Session UUID and Round Tracking

### Backend Changes

**bot/nanobot/session/manager.py**
- Added `uuid` import
- Added `_current_round: int = 0` field to `Session` dataclass (internal counter, not persisted)
- Added `session_uuid` field to `Session` dataclass (stored in metadata)
- Modified `get_or_create()` to generate UUID on session creation:
  - Creates `session_uuid = str(uuid.uuid4())`
  - Stores in `session.metadata["session_uuid"]`
  - Calls `_update_session_index(session)` to update index
- Modified `_load()` to extract `session_uuid` from metadata

### Session Index Management

**bot/nanobot/session/manager.py**
- Added `_index_path` property returning `sessions_dir.parent / "session_index.jsonl"`
- Added `_load_session_index()` - loads index from JSONL file, returns list of entries
- Added `_save_session_index(index)` - atomically writes index to JSONL file
- Added `_update_session_index(session)` - updates or creates index entry with:
  - `session_uuid`: unique identifier
  - `path`: session directory path
  - `topic`: session topic/name
  - `created_at`: ISO timestamp
  - `updated_at`: ISO timestamp
  - `total_rounds`: cumulative round count

### Round Tracking in Messages

**bot/nanobot/agent/loop.py**
- Modified `_save_turn()` to track rounds:
  - Initializes `current_round = session._current_round`
  - Determines `prev_role` from last saved message (if any)
  - On role switch (user↔assistant), increments `current_round`
  - Adds `"round": current_round` field to each message entry
  - Persists `session._current_round = current_round` after loop

---

## Summary of Files Changed

| File | Changes |
|------|---------|
| bot/nanobot/session/manager.py | +45 lines: UUID, round field, session index management |
| bot/nanobot/agent/loop.py | +18 lines: round tracking in _save_turn |

---

## 2. Cross-Session User Expressions Log

### Purpose
Global `user_expressions.jsonl` file that collects all user responses across sessions for later processing by a subagent (to be implemented).

### File Location
`sessions/user_expressions.jsonl` (alongside `session_index.jsonl`)

### Entry Format
```json
{"session_uuid": "...", "round": 1, "topic": "...", "content": "...", "timestamp": "..."}
```

### Backend Changes

**bot/nanobot/session/manager.py**
- Added `_user_expressions_path` property returning `sessions_dir.parent / "user_expressions.jsonl"`
- Added `append_user_expression(session, round_num, content, topic)` method that appends a JSON line to the file

**bot/nanobot/agent/loop.py**
- Modified `_save_turn()` to call `self.sessions.append_user_expression()` when processing user messages

---

## 3. Progress Tracker Subagent

### Purpose
Analyze user expressions in batches to extract meaningful language highlights (phrases, collocations, expressions) and store them in `progress_bank.jsonl` for tracking expression breadth and improvement over time.

### Data Flow
```
user_expressions.jsonl (20 entries)
    ↓
progress_tracker subagent triggered (file_line_count condition)
    ↓
LLM: analyze 20 expressions → returns Array[20] of highlight arrays
    ↓
save_progress_entries tool: zip with source info, write to progress_bank.jsonl
    ↓
Clear user_expressions.jsonl
```

### New Condition Kind: file_line_count

**bot/nanobot/counter/types.py**
- Added `file_line_count` to `CounterCondition.kind`
- Added `path` and `threshold` fields for file-based condition

**bot/nanobot/counter/engine.py**
- Added `file_line_count` handling in `check_triggers()`
- Added `_fired_file_triggers` set to prevent re-firing until file is cleared
- Added `reset_file_trigger()` method

### New Tool: save_progress_entries

**bot/nanobot/agent/tools/progress_bank.py** (new file)
- `ProgressBankTool` with `save_progress_entries` function
- Schema: `entries: Array[Array[{category, intent, expression}]]`
- Reads source info from `user_expressions.jsonl` (positional alignment)
- Writes flat entries to `progress_bank.jsonl` with source info attached
- Clears `user_expressions.jsonl` after successful write

### Progress Bank Format

**progress_bank.jsonl** entries:
```json
{"category":"emotion","intent":"preference","expression":"be fond of","session_uuid":"...","round":4,"topic":"basketball"}
```

### Trigger Configuration

**persona/counter/triggers.yaml**
- Added `progress_tracker` trigger:
  - `kind: file_line_count`
  - `path: sessions/user_expressions.jsonl`
  - `threshold: 20`

### Subagent Prompt

**persona/subagents/progress_tracker_subagent.md** (new file)
- Reads `user_expressions.jsonl`
- LLM outputs `save_progress_entries` with nested array format
- Category taxonomy: emotion, description, experience, habit, opinion, goal, comparison, cause
- Intent tags: positive, negative, preference, habit, frequency, reason, etc.
- Positional alignment: `entries[i]` corresponds to line i of input file

---

## 2026-05-20 - Counter Engine, Subagent Status Notifications, and Session Path Fix

This update introduces a configurable counter-based trigger system for subagents, WebSocket notifications for subagent status, fixes session directory lookup for renamed sessions, and updates user memory profile.

---

## 1. Counter Engine (Configurable Subagent Triggers)

### New Files

**bot/nanobot/counter/** (new package)
- `__init__.py` - Package init
- `types.py` - Dataclasses for `CounterTrigger`, `CounterCondition`, `CounterTarget`
- `engine.py` - `CounterEngine` class that loads triggers from YAML and evaluates conditions

**persona/counter/triggers.yaml** (new file)
- YAML configuration for count-based trigger system
- Three default triggers:
  - `vocab_analysis`: every 2 turns, silent
  - `polish_feedback`: every 3 turns, silent
  - `memory_update`: every 10 turns, silent

### Backend Changes

**bot/nanobot/agent/loop.py**
- Replaced hardcoded `_spawn_session_subagents()` with `CounterEngine`-based approach
- `_spawn_counter_subagent()` spawns a single subagent from a counter trigger
- `counter_engine: CounterEngine` initialized in `__init__`
- `_maybe_spawn_periodic_subagents()` now uses `counter_engine.check_triggers()` instead of hardcoded interval
- Added `_on_subagent_status_change()` callback that broadcasts subagent status via message bus
- Added `on_status_change` parameter to `SubagentManager.__init__`

**bot/nanobot/agent/subagent.py**
- Added `on_status_change` callback to notify when subagents start/complete/fail
- Fires callback on task start and in `finally` block on completion/error

---

## 2. Subagent Status Notifications via WebSocket

### Backend

**bot/nanobot/channels/websocket.py**
- Added `send_subagent_status()` method to broadcast subagent status events
- Handles `_subagent_status` metadata and forwards to `send_subagent_status()`
- Sends `subagent_status` event with: `task_id`, `label`, `phase` (started/done/error), `error`

### Frontend

**bot/webui/src/lib/types.ts**
- Added `subagent_status` event type to `InboundEvent`

**bot/webui/src/lib/nanobot-client.ts**
- Added `onSubagentStatus()` handler registration
- Routes `subagent_status` events to registered handlers

**bot/webui/src/App.tsx**
- Added `subagentToasts` state to display subagent status notifications
- `useEffect` subscribes to `client.onSubagentStatus()` events
- Shows toast notifications: "vocab subagent running...", "vocab subagent completed", etc.
- Toasts auto-dismiss after 3 seconds
- Styled with color-coded borders: blue (started), green (done), red (error)

---

## 3. Session Directory Path Fix

**bot/nanobot/session/manager.py**
- Fixed `_get_session_dir()` to handle renamed sessions:
  - First tries cached metadata for custom folder name
  - Then tries expected path via `safe_key(key)`
  - Falls back to scanning all session directories to find matching key in metadata
- Added `_find_session_dir_by_key()` helper method for directory search
- This fixes the issue where clicking a renamed session (e.g., "Collecting") would create a new blank session

---

## 4. User Memory Updates

**persona/memory/MEMORY.md**
- Updated Music section with user's actual preferences:
  - Likes "We Believe" (anthemic track)
  - Fan of David Tao (陶喆) - Mandopop/R&B artist
  - Vocabulary notes: casual language, needs descriptive alternatives
  - Grammar notes: lowercase "i", filler "emm", short sentences
- Updated IELTS-Specific Patterns:
  - Vocabulary Gaps: "like" alternatives, casual slang upgrades
  - Grammar Issues: capitalization, fillers, sentence variety, run-on sentences, articles

---

## Summary of Files Changed

| File | Changes |
|------|---------|
| bot/nanobot/agent/loop.py | +162/-99 lines: CounterEngine integration, status callbacks |
| bot/nanobot/agent/subagent.py | +8 lines: on_status_change callback |
| bot/nanobot/channels/websocket.py | +36 lines: send_subagent_status |
| bot/nanobot/session/manager.py | +36 lines: session directory fallback search |
| bot/nanobot/counter/ | new package: types.py, engine.py |
| bot/webui/src/App.tsx | +47 lines: subagent toast notifications |
| bot/webui/src/lib/nanobot-client.ts | +16 lines: onSubagentStatus handler |
| bot/webui/src/lib/types.ts | +8 lines: subagent_status event type |
| persona/counter/triggers.yaml | new file: counter trigger configuration |
| persona/memory/MEMORY.md | updated: user preferences and IELTS patterns |

---

*Update created: 2026-05-20*

---

## 2026-05-31 - Trigger Decision Monitor

- Added append-only trigger decision logging to `monitor/trigger_decisions.jsonl`.
- Counter triggers now record `skipped`, `no_delta`, `eligible`, `spawned`, and `failed` decisions with reason, cursor, mode, session, subagent, and model context.
- Cron jobs `memory_cron` and `daily_consolidator` now log no-delta and subagent completion decisions.
- Admin monitor API now returns `trigger_decisions` alongside subagent runs, cost summary, wiki sync, and activity.
- WebUI monitor now includes a “触发决策” panel so each trigger check can be inspected separately from subagent replies.
- Hardened monitor cost summary so missing `_last_usage` does not crash the admin monitor.
- Subagent run logs now write to root `monitor/subagent_runs.jsonl`, matching the system-observability boundary.
- Rewrote `architecture.md` to match the current persona/monitor/wiki/trigger architecture.
- Updated `docs/runtime-data-map.md` and `docs/08-project-structure-review.md` with the resolved monitor and architecture decisions.

Validation:
- `uv run python -m py_compile bot/nanobot/utils/trigger_monitor.py bot/nanobot/counter/engine.py bot/nanobot/agent/loop.py bot/nanobot/cli/commands.py bot/nanobot/channels/websocket.py`
- `uv run python -m pytest bot/tests/utils/test_trigger_monitor.py bot/tests/counter/test_counter_engine_mode.py bot/tests/channels/test_admin_trigger_update.py`
- `uv run python -m py_compile bot/nanobot/agent/subagent.py bot/nanobot/channels/websocket.py bot/nanobot/utils/trigger_monitor.py`
- `uv run python -m pytest bot/tests/agent/test_subagent.py bot/tests/utils/test_trigger_monitor.py bot/tests/channels/test_admin_trigger_update.py`
- `pnpm run check` in `bot/webui`

---

## 2026-05-31 - Benative Runtime Path Cleanup

- Unified Benative business data paths under `persona/benative/`.
- Updated `/benative` command to list articles and count sentence pairs from `persona/benative`.
- Updated Benative article fetcher, translator, review prompts, and mode context files away from legacy `shared/benative`.
- Updated default cron trigger task templates to write articles, pairs, and cursors under `persona/benative`.
- Documented Benative article/pair/response ownership in `architecture.md` and `docs/runtime-data-map.md`.
- Removed unused empty `subagent/_cursors` and subagent placeholder `data/processor` directories.
- Marked `WikiUpdater` as a legacy explicit patch-source scanner with no default `subagent/*/data` sources.

Validation:
- `uv run python -m py_compile bot/nanobot/command/builtin.py bot/nanobot/channels/websocket.py bot/nanobot/session/manager.py`
- `uv run python -m pytest bot/tests/command/test_benative_command.py`
- `uv run python -m py_compile bot/nanobot/command/builtin.py subagent/cross_session/wiki/processor/wiki_updater.py`
- `uv run python -m pytest bot/tests/command/test_benative_command.py bot/tests/wiki/test_wiki_updater.py`

---

## 2026-05-30 - 当前 Git 工作树状态总结

本次记录用于同步当前 `git status`，工作树中包含一批功能开发、测试补充、运行态数据和待清理文件。整体状态是：已有较多未提交改动，建议下一步先按模块拆分 review，再分批提交。

---

## 1. Git Status 概览

当前工作树包含：

- 已修改文件：核心 agent loop、subagent manager、websocket API、counter engine、session manager、WebUI、trigger 配置、测试文件等。
- 已删除文件：旧的 per-mode `count.yaml` 计数配置，以及若干被清理的 `__pycache__` 文件。
- 新增未跟踪文件：wiki 工具与处理器、admin monitor WebUI、wiki WebUI、wiki 测试、运行态日志、根目录 agent 配置文件、脚本和文档。
- 前端依赖变更：`bot/webui/package.json`、`bun.lock`、`pnpm-lock.yaml` 均有变动。

主要统计：

```text
42 tracked files changed
1372 insertions
214 deletions
```

---

## 2. 核心功能改动

### Subagent 调用与监控

- `bot/nanobot/agent/subagent.py`
  - 增加 subagent run 持久化日志。
  - 记录调用结果、usage、tool events、artifact 快照和增量。
  - 输出到 `monitor/subagent_runs.jsonl` 或 persona 下对应 monitor 目录。

- `bot/nanobot/channels/websocket.py`
  - 增加 admin monitor API。
  - 增加 trigger 配置读取与更新 API。
  - 增加 wiki/notes 相关 API。
  - 改善非 JSON 响应导致前端报 `Unexpected token '<'` 的排查路径。

- `bot/webui/src/components/AdminMonitorView.tsx`
  - 新增后台监控页面。
  - 支持查看 trigger 配置、prompt 预览、subagent 调用记录和单次调用详情。

### Trigger 与 Counter

- `bot/nanobot/counter/engine.py`
  - 支持按当前 mode 加载 trigger。
  - 支持 trigger 文件变化后重新加载。
  - 解决 workspace 从 `persona` 切到项目根目录后的路径问题。

- `mode/freechat/trigger/triggers.json`
- `mode/ielts/trigger/triggers.json`
- `mode/default/trigger/triggers.json`
  - 调整 subagent 触发配置。
  - 移除部分硬编码模型配置。
  - 明确 subagent 只分析用户消息，assistant 内容只作为上下文。

- 删除旧计数配置：
  - `mode/benative/trigger/count/count.yaml`
  - `mode/freechat/trigger/count/count.yaml`
  - `mode/ielts/trigger/count/count.yaml`

### Session / Thread 日志

- `bot/nanobot/session/manager.py`
  - 在 workspace 为项目根目录时，继续把 persona/session 数据落到正确位置。
  - 修复 `data/thread.jsonl` 的跨会话同步逻辑，避免同一 session 的历史片段重复追加。

### Notes

- `bot/nanobot/agent/tools/notes_ai_assistant.py`
- `bot/nanobot/agent/loop.py`
- `bot/webui/src/components/GlobalNotes.tsx`
- `bot/webui/src/components/NotesBookSheet.tsx`
- `bot/webui/src/App.tsx`
  - 修复 notes AI subagent 路径。
  - 右下角浮动 notes 与 wiki 可以同时存在。
  - AI 生成的 note reply 完成后可刷新并显示在右侧浮动 notes 面板。

---

## 3. Wiki / LLM Wiki 相关新增

新增了 LLM Wiki 的第一版工程骨架：

- `bot/nanobot/agent/tools/wiki.py`
- `bot/nanobot/agent/wiki_sync.py`
- `subagent/cross_session/wiki/`
  - `context/wiki_subagent.md`
  - `processor/schema.py`
  - `processor/wiki_store.py`
  - `processor/wiki_processor.py`
  - `processor/wiki_index.py`
  - `processor/wiki_graph.py`
  - `processor/wiki_retriever.py`
  - `processor/wiki_search.py`
  - `processor/wiki_updater.py`

当前能力：

- 从 thread/session 增量提取候选 wiki patch。
- 写入 markdown wiki pages。
- 每页带 frontmatter。
- 支持 source sidecar、log、SQLite FTS index、graph 构建。
- WebSocket 暴露 wiki API。
- WebUI 有 `WikiMemoryPanel` 和 `WikiGraphView` 初版。

当前已识别的后续问题：

- wiki sync 目前仍和 subagent trigger 存在耦合，需要独立触发。
- page type 还需要升级为更成熟的 `source/entity/concept/comparison/question/synthesis/decision/gap/meta` 体系。
- 需要补充 raw sources、schema、lint、review、research/gap 流程。
- WebUI 知识图谱效果还需要重做，D3 相关依赖已经被安装到前端依赖中，但还未完成 UI 重构。

---

## 4. WebUI 改动

- `bot/webui/src/App.tsx`
- `bot/webui/src/components/Sidebar.tsx`
- `bot/webui/src/components/GlobalNotes.tsx`
- `bot/webui/src/components/NotesBookSheet.tsx`
- `bot/webui/src/components/AdminMonitorView.tsx`
- `bot/webui/src/components/WikiGraphView.tsx`
- `bot/webui/src/components/WikiMemoryPanel.tsx`
- `bot/webui/src/lib/api.ts`

主要变化：

- 增加 Admin Monitor 入口。
- 增加 subagent 调用记录展示。
- 增加 trigger 配置展示与更新接口调用。
- 增加 wiki memory / graph UI 初版。
- 修复 notes 和 wiki 浮动入口互相覆盖的问题。
- 对部分组件滚动区域做了修正。

---

## 5. 测试与脚本

新增或修改测试：

- `bot/tests/channels/test_admin_trigger_update.py`
- `bot/tests/counter/test_counter_engine_mode.py`
- `bot/tests/counter/test_counter_engine_reload.py`
- `bot/tests/wiki/*`
- 多个 agent、CLI、tool 测试适配 workspace root / persona path 变化。

新增脚本：

- `scripts/dedupe_thread_log.py`
- `scripts/validate_subagent_config.py`

已运行过的验证：

```text
uv run python -m pytest tests/counter/test_counter_engine_mode.py tests/counter/test_counter_engine_reload.py tests/session/test_session_fsync.py tests/agent/test_session_manager_history.py
结果：36 passed

pnpm run check
结果：163 passed，存在既有 warning

uv run python scripts/validate_subagent_config.py
结果：配置校验通过
```

---

## 6. 文档新增

- `docs/runtime-data-map.md`
- `docs/wiki-memory-implementation.md`
- `docs/05-llm-wiki-memory-system-plan.md`
- `docs/06-llm-wiki-implementation-roadmap.md`
- `docs/07-llm-wiki-test-plan.md`

这些文档主要记录：

- 运行态数据分布。
- LLM Wiki memory 的设计。
- wiki 实现路线图。
- wiki 测试计划。

---

## 7. 运行态和待清理文件

当前 `git status` 中有一些文件看起来更像运行态数据，提交前建议确认是否应该纳入版本管理：

- `monitor/subagent_runs.jsonl`
- `session_index.jsonl`
- `sessions/.../notes/*.md`
- `user_responses.jsonl`
- `memory/history.jsonl`
- `trigger/cron/jobs.json`

另外有若干根目录文件目前未跟踪，需要确认是否是项目规范文件还是本地 agent 配置：

- `AGENTS.md`
- `HEARTBEAT.md`
- `SOUL.md`
- `TOOLS.md`
- `USER.md`

建议下一步处理：

1. 决定运行态数据是否进入 `.gitignore`。
2. 清理或确认 `__pycache__` 删除项。
3. 将功能改动分成几个提交：
   - workspace/session/thread 修复
   - trigger/counter/subagent monitor
   - notes AI 修复
   - wiki core 初版
   - WebUI monitor/wiki 初版
   - docs/tests/scripts

---

*Update created: 2026-05-30*

---

## 2026-05-31 - Wiki Graph 关系视角优化

本次更新调整 Wiki Memory 的知识图谱展示逻辑：从“wiki schema 可视化”改为“用户知识关系可视化”。目标是让图谱更符合 IELTS/freechat/个人知识积累的浏览方式，而不是显示 tag、type、mode 等内部治理字段。

---

## 1. 后端 Graph 结构调整

### `subagent/cross_session/wiki/processor/wiki_graph.py`

主要变化：

- 不再生成以下 schema/internal 节点：
  - `type:*`
  - `tag:*`
  - `mode:*`
- 保留并强化用户可理解的知识节点：
  - `topic`
  - `page`
  - `entity`
  - `concept`
- 图谱边调整为：
  - `link`
  - `has_topic`
  - `mentions_entity`
  - `mentions_concept`

新的展示逻辑：

- IELTS 模式下，每个 topic 会成为一个大的聚类中心。
- freechat 模式下，内容按长期积累的话题聚合。
- global/personal 信息会归入个人相关 topic。
- 没有 topic 的页面会自动落入 fallback topic：
  - `ielts/general`
  - `freechat/topics`
  - `personal`
  - `{mode}/general`

---

## 2. 前端 D3 图谱稳定性优化

### `bot/webui/src/components/WikiGraphView.tsx`

主要变化：

- topic 节点变成更大的视觉中心。
- 页面节点围绕自己的 topic 分布。
- entity/concept 作为关系节点展示，不再显示 tag/type/mode。
- 不同 topic 会自然分区，减少所有节点混在一起的问题。
- 降低 D3 force 扰动：
  - 降低 alpha
  - 提高 velocity decay
  - 减弱 link/charge 对整体布局的影响
- 拖动节点后会固定在用户放置的位置。
- Reset 按钮会解除固定并重新布局。
- 图例更新为：
  - topic cluster
  - entity
  - concept
  - decision page
  - gap page

---

## 3. API Type 更新

### `bot/webui/src/lib/api.ts`

Wiki graph 类型调整：

- `WikiGraphNode.kind`
  - 旧：`page | type | tag | topic | mode`
  - 新：`page | topic | entity | concept`
- `WikiGraphEdge.kind`
  - 旧：`link | has_type | has_tag | has_topic | has_mode`
  - 新：`link | has_topic | mentions_entity | mentions_concept`

---

## 4. 测试更新

### `bot/tests/wiki/test_wiki_graph.py`

新增/更新测试：

- 验证 topic cluster 节点存在。
- 验证 schema 节点不会出现在 graph 中。
- 验证 fallback topic。
- 验证 entity/concept 节点来自 frontmatter。
- 验证 `mentions_entity`、`mentions_concept` 边。

---

## 5. 验证

后端：

```text
uv run python -m pytest tests/wiki
结果：125 passed
```

前端：

```text
pnpm run check
结果：163 passed
```

---

*Update created: 2026-05-31*

---

## 2026-05-31 - DeepSeek Flash 切换与 Monitor 成本估算

本次更新将运行模型统一切换到 `deepseek-v4-flash`，并在监控后台加入 token 与费用估算面板，用于观察 subagent 触发带来的额外消耗。

---

## 1. 模型配置调整

### 全局 Nanobot 配置

`/Users/jerry/.nanobot/config.json`：

```json
{
  "agents": {
    "defaults": {
      "provider": "deepseek",
      "model": "deepseek-v4-flash"
    }
  }
}
```

### Trigger 配置

以下 trigger 的显式模型从 `gpt-4o-mini` 改为 `deepseek-v4-flash`：

- `mode/ielts/trigger/triggers.json`
  - `ielts_feedback`
- `mode/benative/trigger/triggers.json`
  - `benative_review`

项目内运行配置已确认不再保留 `gpt-4o-mini` 或 `deepseek-chat`。

---

## 2. Monitor 成本估算

### Backend

`bot/nanobot/channels/websocket.py`

新增：

- `_estimate_llm_cost_usd()`
- `_normalize_cost_model()`
- `_monitor_cost_summary()`

Monitor API 返回新增字段：

```json
{
  "cost_summary": {
    "currency": "USD",
    "estimated_usd": 0,
    "prompt_tokens": 0,
    "cached_tokens": 0,
    "completion_tokens": 0,
    "models": [],
    "last_turn": {},
    "price_source": "https://api-docs.deepseek.com/quick_start/pricing",
    "note": "Local estimate from logged usage; official invoice is authoritative."
  }
}
```

估算逻辑：

- 从 `monitor/subagent_runs.jsonl` 中读取每次 subagent 的 `usage`。
- 聚合 prompt / cached / completion tokens。
- 按 DeepSeek 官方公开价格进行本地估算。
- `deepseek-chat` 会归一化为 `deepseek-v4-flash`，用于兼容旧日志。

注意：这是本地估算，官方 API 平台账单仍是最终依据。

### WebUI

`bot/webui/src/components/AdminMonitorView.tsx`

新增：

- 顶部指标：`估算花费`
- 面板：`Token / 花费`

可查看：

- subagent 总估算费用
- 各模型 token 与费用
- prompt / cached / completion token
- 最近主回复的估算费用

---

## 3. 类型更新

`bot/webui/src/lib/api.ts`

新增：

- `AdminCostSummary`
- `cost_summary` 字段

---

## 4. 验证

配置校验：

```text
uv run python scripts/validate_subagent_config.py
结果：ok true，errors []
```

后端测试：

```text
uv run python -m pytest tests/channels/test_admin_trigger_update.py tests/wiki/test_wiki_graph.py
结果：9 passed
```

前端测试：

```text
pnpm run check
结果：163 passed
```

---

*Update created: 2026-05-31*

---

## 2026-05-30 - LLM Wiki Core、Sync 与 WebUI 图谱升级

本次更新完成 LLM Wiki 的核心工程化改造，并把 wiki sync 从 subagent trigger 中解耦。现在 wiki 具备更清晰的 raw sources / wiki / schema 分层、独立 ingest/query/save/lint 流程，以及可在 monitor 中观察的 sync 运行记录。

---

## 1. LLM Wiki Core

新增核心模块：

- `subagent/cross_session/wiki/processor/wiki_layout.py`
- `subagent/cross_session/wiki/processor/wiki_ingest.py`
- `subagent/cross_session/wiki/processor/wiki_query.py`
- `subagent/cross_session/wiki/processor/wiki_crystallizer.py`
- `subagent/cross_session/wiki/processor/wiki_lint.py`

主要变化：

- `persona/wiki` 目录统一为 `raw/`、`wiki/`、`index/`、`state/`、`schema/`。
- 新页面写入 `persona/wiki/wiki/`，旧 `persona/wiki/pages/` 仍可兼容读取。
- 页面类型统一为：
  - `source`
  - `entity`
  - `concept`
  - `comparison`
  - `question`
  - `synthesis`
  - `decision`
  - `gap`
  - `meta`
- 旧类型会自动映射，例如 `ielts_topic -> concept`、`freechat_project -> entity`。
- frontmatter 增加治理字段：`status`、`sources`、`aliases`、`entities`、`concepts`、`created_at`、`last_reviewed_at`、`stability`、`version`。
- `WikiIngestor` 将 `data/thread.jsonl` 增量保存到 `raw/thread/*.jsonl`，再生成候选信号。
- `WikiQueryEngine` 提供本地混合检索：SQLite FTS + markdown scan + title/tag 权重 + link 扩展。
- `WikiCrystallizer` 将候选信号独立结晶为 `WikiPatch`，先查已有页面，能合并则合并。
- `WikiLinter` 提供结构层和语义层检查。

---

## 2. Wiki Sync 解耦

### `bot/nanobot/agent/loop.py`

- wiki sync 不再依赖 subagent trigger 是否命中。
- 每个真实用户 turn 后都会按 interval 判断是否运行 wiki sync。
- 默认 interval 为 `1`，即每轮用户回复后同步一次。
- 可通过环境变量调整：

```bash
NANOBOT_WIKI_SYNC_INTERVAL=1
NANOBOT_WIKI_SYNC_INTERVAL=2
NANOBOT_WIKI_SYNC_INTERVAL=3
NANOBOT_WIKI_SYNC_INTERVAL=0  # 关闭
```

### `bot/nanobot/agent/wiki_sync.py`

- 旧的 LLM 直接生成 patch 流程替换为本地 core pipeline：
  - ingest
  - analyze
  - crystallize/save
  - lint
- 每次运行写入 `persona/wiki/state/sync_log.jsonl`。
- sync log 记录：
  - session id
  - source id
  - message count
  - candidate count
  - patch count
  - applied count
  - lint finding count
  - error 信息

---

## 3. API 与 Monitor

### Wiki API

新增/更新：

- `/api/wiki/search`：改为使用 `WikiQueryEngine` 混合检索。
- `/api/wiki/lint`：返回结构和语义 lint findings。
- `/api/wiki/sync-log`：返回最近 wiki sync 记录。

### Admin Monitor

- `AdminMonitorPayload` 增加 `wiki_sync_runs`。
- `AdminMonitorView` 新增 Wiki Sync 面板。
- 可以看到每次 sync 的：
  - messages
  - candidates
  - applied
  - lint findings
  - applied slugs
  - error

---

## 4. WebUI 知识图谱升级

### `bot/webui/src/components/WikiGraphView.tsx`

- 从 `react-force-graph-2d` 组件切换为可控的 D3 force + canvas 实现。
- 支持：
  - D3 force layout
  - canvas 渲染
  - zoom
  - pan
  - drag node
  - selected node detail
  - highlighted nodes
  - page click / filter click
- 图谱节点增加 `type:*` 分类节点。
- 页面节点按 wiki page type 着色，例如 entity、concept、decision、gap。

### `bot/webui/src/components/WikiMemoryPanel.tsx`

- graph tab 现在使用新 D3 图谱组件。
- 点击 type/tag/topic/mode 节点可以回填筛选条件。
- page 详情展示 frontmatter 中的 status、stability、sources 等字段。

---

## 5. 收尾与运行态清理

### `.gitignore`

新增忽略：

- root runtime:
  - `session_index.jsonl`
  - `user_responses.jsonl`
  - `sessions/`
  - `monitor/*.jsonl`
  - `memory/*.jsonl`
  - `trigger/cron/jobs.json`
- wiki runtime:
  - `persona/wiki/raw/thread/*.jsonl`
  - `persona/wiki/state/*.jsonl`
  - `persona/wiki/state/ingest_cursor.json`
  - `persona/wiki/index/*.sqlite`

### Legacy Wiki Migration

新增：

- `scripts/migrate_wiki_pages.py`

已执行一次：

```text
Copied 10 legacy wiki file(s); skipped 0 existing file(s).
```

脚本只复制旧 `persona/wiki/pages` 到新 `persona/wiki/wiki`，不删除旧文件。

---

## 6. 验证

后端测试：

```text
uv run python -m pytest tests/wiki tests/counter/test_counter_engine_mode.py tests/counter/test_counter_engine_reload.py tests/session/test_session_fsync.py tests/agent/test_session_manager_history.py tests/channels/test_admin_trigger_update.py
结果：161 passed
```

前端测试：

```text
pnpm run check
结果：163 passed
```

Subagent 配置校验：

```text
uv run python scripts/validate_subagent_config.py
结果：ok true，errors []
```

浏览器可视检查说明：

- 尝试用 Codex in-app browser 打开 `http://127.0.0.1:5175/` 时被浏览器安全策略拦截。
- 因此本次没有完成真实浏览器截图验证。

---

*Update created: 2026-05-30*

This update adds Free Chat button to web UI, implements cross-session memory tracking, refactors subagent system for silent file-only output, and redesigns the topic bank.

---

## Architecture Flowchart

### 1. Free Chat Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FREE CHAT FLOW                                  │
└─────────────────────────────────────────────────────────────────────────────┘

  ┌──────────────┐      ┌──────────────┐      ┌──────────────────────────────┐
  │  Web UI      │      │  Backend     │      │  Topic Selection             │
  │  Sidebar     │      │  /freechat   │      │  (cmd_freechat)              │
  └──────┬───────┘      └──────┬───────┘      └──────────┬───────────────────┘
         │                      │                           │
         │  Click "Free Chat"   │                           │
         │  ─────────────────►  │                           │
         │                      │   Parse topic_bank.md      │
         │                      │   ─────────────────────►   │
         │                      │                           │
         │                      │   Read profile for         │
         │                      │   exploration status       │
         │                      │   ─────────────────────►   │
         │                      │                           │
         │                      │   Select topic:            │
         │                      │   Priority:                │
         │                      │   1. not_explored          │
         │                      │   2. in_progress (depth<4) │
         │                      │   ─────────────────────►   │
         │                      │                           │
         │                      │   Choose question by       │
         │                      │   depth level              │
         │                      │   ─────────────────────►   │
         │                      │                           │
         │                      │   Rename session folder    │
         │                      │   to topic name            │
         │                      │   ─────────────────────►   │
         │                      │                           │
         │                      │   Return intro_prompt       │
         │                      │   to LLM                   │
         │◄─────────────────────│                           │
         │                      │                           │
         │                      │   LLM asks first question  │
         │                      │   naturally                │
         ▼                      ▼                           ▼
```

### 2. Memory Update Flow (Session Change)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          MEMORY UPDATE FLOW                                  │
└─────────────────────────────────────────────────────────────────────────────┘

  ┌──────────────┐      ┌──────────────┐      ┌──────────────────────────────┐
  │  User        │      │  AgentLoop   │      │  Session Manager              │
  │  Action      │      │  _dispatch   │      │                                │
  └──────┬───────┘      └──────┬───────┘      └──────────┬───────────────────┘
         │                      │                           │
         │  Switch session      │                           │
         │  or close chat       │                           │
         │  ─────────────────►  │                           │
         │                      │   Detect session change    │
         │                      │   via _last_active_key    │
         │                      │   ─────────────────────►   │
         │                      │                           │
         │                      │   _on_session_inactive()   │
         │                      │   - Check message count    │
         │                      │   - 5min cooldown check    │
         │                      │   ─────────────────────►   │
         │                      │                           │
         │                      │   Spawn memory subagent    │
         │                      │   (announce_result=False)   │
         │                      │   ─────────────────────►   │
         │                      │                           │
         │                      │   Read thread.jsonl        │
         │                      │   ─────────────────────►   │
         │                      │                           │
         │                      │   Update MEMORY.md        │
         │                      │   (cross-session profile)   │
         │                      │   ─────────────────────►   │
         │                      │                           │
         │                      │   Topics: Status, Depth,   │
         │                      │   Key Facts, Vocab,       │
         │                      │   Grammar                  │
         ▼                      ▼                           ▼
```

### 3. Subagent Periodic Spawning

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        SUBAGENT SPAWNING FLOW                                │
└─────────────────────────────────────────────────────────────────────────────┘

  ┌──────────────┐      ┌──────────────┐      ┌──────────────────────────────┐
  │  User        │      │  AgentLoop   │      │  Subagent Manager             │
  │  Message     │      │  _maybe_     │      │  (background)                │
  │              │      │  spawn_      │      │                                │
  └──────┬───────┘      │  periodic_   │      └──────────┬───────────────────┘
         │              │  subagents   │                 │
         │  Send msg    │◄─────────────│                 │
         │  ─────────►  │              │                 │
         │              │  Increment   │                 │
         │              │  msg_count   │                 │
         │              │              │                 │
         │              │  Check:      │                 │
         │              │  - msg==1    │                 │
         │              │  - msg%3==0  │                 │
         │              │  - not /free │                 │
         │              │  chat        │                 │
         │              │  ─────────►  │                 │
         │              │              │   Spawn 3 subagents (silent):
         │              │              │   1. vocab
         │              │              │   2. polisher
         │              │              │   3. memory
         │              │              │   ──────────────►
         │              │              │                 │
         │              │              │   Read thread   │ ◄── thread.jsonl
         │              │              │   ──────────────►
         │              │              │                 │
         │              │              │   Write notes  │ ──► notes/vocab.md
         │              │              │   (silent)     │ ──► notes/polisher.md
         │              │              │                 │ ──► notes/profile.md
         │              │              │                 │
         │              │   UI does NOT wait             │
         │              │   (announce=False)             │
         ▼              ▼                                ▼
```

### 4. Session Directory Structure

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        SESSION DIRECTORY STRUCTURE                          │
└─────────────────────────────────────────────────────────────────────────────┘

  sessions/
  │
  ├── basketball/                    # Session folder (auto-renamed to topic)
  │   ├── thread.jsonl               # Conversation history
  │   └── notes/
  │       ├── vocab.md               # Vocabulary suggestions
  │       ├── polisher.md            # Grammar improvements
  │       └── profile.md             # Session user profile
  │
  ├── daily_routine/
  │   ├── thread.jsonl
  │   └── notes/
  │       └── ...
  │
  └── ... (more sessions)

  persona/
  │
  └── memory/
      └── MEMORY.md                  # Cross-session user profile (updated on
                                     # session change, not per-session)
```

---

## 1. Free Chat Feature

### Web UI Changes

**bot/webui/src/App.tsx**
- Added `onFreeChat` callback that:
  - Creates a new chat via API
  - Sets active key to the new session
  - Sends `/freechat` command to trigger topic selection
- Button added to Sidebar component

**bot/webui/src/components/Sidebar.tsx**
- Added `onFreeChat` prop to SidebarProps interface
- Added "Free chat" button with Sparkles icon (lucide-react)
- Button styling: ghost variant, 8 height, full width, rounded-full

**bot/webui/src/i18n/locales/en/common.json**
- Added `"freeChat": "Free chat"` translation key

### Backend Command

**bot/nanobot/command/builtin.py**
- Added new BuiltinCommandSpec for `/freechat` with sparkles icon
- Implemented `cmd_freechat()` handler that:
  - Parses topic_bank.md for topics with depth levels and question types
  - Reads session profile to determine exploration status (not_explored, in_progress)
  - Selects priority: not_explored topics first, then in_progress with depth < 4
  - For new topics: starts with depth level 1 question (simple preference)
  - For continuing topics: progresses to next depth level
  - Sets session title and renames folder to topic name
  - Returns an intro prompt instructing the agent to ask the selected question naturally

---

## 2. Session Directory Structure

**bot/nanobot/session/manager.py**
- Sessions now stored in directories: `sessions/{safe_topic_name}/`
- Each session directory contains:
  - `thread.jsonl` - conversation history
  - `notes/vocab.md` - per-session vocabulary notes
  - `notes/polisher.md` - per-session grammar notes
  - `notes/profile.md` - per-session user profile

**New Methods:**
- `_get_session_dir(key)` - returns Path to session directory, checks metadata for custom folder name
- `rename_session_dir(key, new_name)` - renames folder to topic-based name, stores mapping in metadata
- `_ensure_session_notes(key)` - creates notes directory with vocab.md, polisher.md, profile.md
- `get_session_notes(key)` - reads and returns vocab and polisher notes as dict
- `_migrate_legacy_session(legacy_path, new_dir)` - migrates flat .jsonl to directory structure

**Modified Methods:**
- `get_or_create(key)` - now calls `_ensure_session_notes()` to set up directory
- `delete_session(key)` - now deletes entire session directory (not just .jsonl file)
- `list_sessions()` - now iterates directories instead of .jsonl files

---

## 3. Subagent System Refactor

### Silent Operation (announce_result=False)

**bot/nanobot/agent/subagent.py**
- Added `announce_result: bool = True` field to SubagentStatus dataclass
- Modified `spawn()` to accept `extra_system_prompt` and `announce_result` parameters
- Modified `_run_subagent()` to conditionally call `_announce_result()` only when `announce_result=True`
- Added `get_announcing_count_by_session(session_key)` - counts only announcing subagents
- Modified `_build_subagent_prompt()` to append extra_system_prompt if provided

**bot/nanobot/agent/loop.py**
- Changed `_drain_pending` condition from `get_running_count_by_session` to `get_announcing_count_by_session`
  - This prevents UI from waiting for non-announcing (silent) subagents

### Periodic Subagent Spawning

**bot/nanobot/agent/loop.py**
- Added constants: `SUBAGENTS_SPAWNED_KEY`, `MESSAGE_COUNT_KEY`, `TITLE_KEY`, `SUBAGENTS_TRIGGER_INTERVAL = 3`
- Added `_spawn_session_subagents()` - spawns vocab, polisher, memory subagents with:
  - `announce_result=False` for silent operation
  - `extra_system_prompt` loaded from workspace subagent prompt files
  - Session directory and workspace path substitution in prompts
- Added `_maybe_spawn_periodic_subagents()` - spawns subagents:
  - On first message (current_count == 1)
  - Every 3 messages thereafter
  - Skips `/freechat` command (only real conversation triggers subagents)
- Added `_apply_session_title()` - generates title from first user message and renames session folder
- Added `_generate_session_title()` - extracts first 50 chars from first user message

### Session Title Auto-Generation

- Session folders now auto-renamed to topic-based titles
- Title generated from first user message content
- Uses `safe_filename()` to create filesystem-safe names

---

## 4. Memory System - Cross-Session User Profile

### User-Level Memory File

**persona/memory/MEMORY.md**
- Complete rewrite as cross-session user memory profile
- Organized by 7 topic_bank sections matching topic categories:
  - Section 1: Hobbies & Interests (Sport, Music, Collecting, Cooking)
  - Section 2: Daily Life & Lifestyle (Daily Routine, Weekend Activities, Work-Life Balance)
  - Section 3: Travel & Places (Travel Experience, Dream Destination, Hometown)
  - Section 4: People & Relationships (Family, Friendship, Person You Admire)
  - Section 5: Food & Culture (Food & Eating Habits, Local Culture)
  - Section 6: Learning & Growth (Education, Future Plans, Personal Growth)
  - Section 7: Opinions & Society (Social Issues, Values & Beliefs, Happiness & Success)

- Each topic tracks:
  - Status: not_explored | briefly_mentioned | well_explored
  - Depth Level: 1-5 (IELTS speaking depth)
  - Key Facts: user-provided information
  - Vocabulary Notes: words/phrases used
  - Grammar Patterns: observed patterns
  - Last Discussed: timestamp

- Global section includes:
  - Basic Info: MBTI, Energy Type, First Language, Target Score, Occupation
  - Personality Insights: Strengths, Areas for Improvement, Communication Style
  - IELTS-Specific Patterns: Vocabulary Gaps, Grammar Issues, Hesitation Topics, Confident Topics
  - Suggested Next Topics: for future sessions

### Memory Subagent Update

**persona/subagents/memory_subagent.md**
- Complete rewrite to write to `memory/MEMORY.md` instead of per-session notes
- Reads: topic_bank.md, thread.jsonl, memory_format.md
- Writes to: `{{ workspace }}/memory/MEMORY.md`
- Topic category mapping to 7 sections
- Depth assessment guidelines (1=simple preference, 5=philosophy/values)
- Updates exploration status and depth level for discussed topics

### Vocab Subagent Update

**persona/subagents/vocab_subagent.md**
- Updated to write vocabulary suggestions to `memory/MEMORY.md`
- Added IELTS-specific vocabulary improvement guidance
- Added professional vocabulary by topic category
- Added linking phrases and collocations

### Polisher Subagent Update

**persona/subagents/polisher_subagent.md**
- Updated to write grammar notes to `memory/MEMORY.md`
- Added grammar improvement focus areas:
  - Vocabulary (Lexical Resource): weak→strong, informal→formal
  - Grammar (Grammatical Range): simple→compound/complex, relative clauses, conditionals
  - Fluency & Coherence: linking phrases, discourse markers
  - Task Achievement: direct answers, developing ideas with examples

### Memory Format

**persona/formats/memory_format.md**
- New file with output format template for profile updates

---

## 5. Session Change Hook for Memory Updates

**bot/nanobot/agent/loop.py**
- Added `_last_active_session_key` tracking in `__init__`
- Added `_on_session_inactive(session_key)` method:
  - Triggered when user switches to a different session
  - Checks for minimum 2 messages (meaningful content)
  - 5-minute cooldown prevents excessive spawns
  - Spawns memory subagent to update user-level `memory/MEMORY.md`
- Added session switch detection in `_dispatch`:
  - Compares `_last_active_session_key` with `effective_key`
  - If different and new session not in `_pending_queues`, calls `_on_session_inactive()`
- After detection, updates `_last_active_session_key = effective_key`

---

## 6. Topic Bank Redesign

**persona/topic_bank.md**
- Complete rewrite in English
- Restructured with 7 sections matching memory categories
- Each topic now has:
  - Multiple questions with depth levels 1-5
  - Sub-topic tracking: reason, timeline, frequency, opinion, impact, comparison, etc.
  - Questions designed for IELTS speaking practice

**Depth Level Design:**
- Depth 1: Simple preference ("Do you like...?")
- Depth 2: Reason/timeline ("Why? When did you start?")
- Depth 3: Opinion/comparison ("What's your opinion? How does it compare to...?")
- Depth 4: Impact/analysis ("How has it affected your life?")
- Depth 5: Philosophy/values ("How would you be different without...? What does it mean to you?")

---

## 7. Session Notes in Context

**bot/nanobot/agent/context.py**
- Modified `build_system_prompt()` to accept `session_notes` parameter
- If session_notes provided, appends Vocabulary Notes and Polisher Notes sections
- Modified `build_messages()` to accept `session_notes` and `session_dir` parameters
- Appends "Session Notes Directory: {dir}/notes/" to runtime context

---

## Summary of Files Changed

| File | Changes |
|------|---------|
| bot/nanobot/agent/loop.py | +224 lines: session title, periodic subagents, session change hook |
| bot/nanobot/agent/subagent.py | +55 lines: announce_result flag, get_announcing_count_by_session |
| bot/nanobot/command/builtin.py | +184 lines: /freechat command with topic selection |
| bot/nanobot/session/manager.py | +144 lines: directory structure, rename, legacy migration |
| bot/nanobot/agent/context.py | +14 lines: session_notes in context building |
| bot/webui/src/App.tsx | +15 lines: onFreeChat handler |
| bot/webui/src/components/Sidebar.tsx | +10 lines: Free Chat button |
| bot/webui/src/i18n/locales/en/common.json | +1 line: freeChat translation |
| persona/memory/MEMORY.md | +253 lines: complete rewrite as user-level cross-session memory |
| persona/topic_bank.md | complete rewrite in English with depth levels |
| persona/formats/memory_format.md | new file: memory output format template |
| persona/subagents/*.md | complete rewrites: memory, vocab, polisher subagents |

---

## 2026-05-20 - Session Notes Panel and Highlighting Syntax

This update adds a Session Notes Panel to the WebUI for viewing vocab/polisher notes, implements keyword highlighting syntax (`==word==`), and fixes session deduplication.

---

## 1. Session Notes Panel

### New Files

**bot/webui/src/components/SessionNotesSheet.tsx** (134 lines)
- Sheet component that slides in from the right
- Two tabs: Vocabulary and Grammar
- Polls for updates every 5 seconds
- Renders markdown content with MarkdownTextRenderer
- Displays session title in header

**bot/webui/src/hooks/useSessionNotes.ts** (68 lines)
- Fetches session notes via API
- 5-second polling interval when panel is open
- Returns `notes.vocab` and `notes.polisher` strings

### Backend API Endpoint

**bot/nanobot/channels/websocket.py**
- Added `GET /api/sessions/<key>/notes` handler (`_handle_session_notes`)
- Returns `{"vocab": "...", "polisher": "..."}`
- Validates session key and authorization

### Frontend Integration

**bot/webui/src/App.tsx**
- Added `notesSheetState` for managing sheet open/close
- Added `handleOpenNotes` callback
- Closes notes sheet when switching sessions

**bot/nanobot/session/manager.py**
- Added `_find_session_notes_dir(key)` fallback method:
  - Scans session directories for matching key in metadata
  - Handles renamed sessions that don't use safe_key paths
- Fixed `get_session_notes()` to use fallback search

**bot/webui/src/lib/api.ts**
- Added `fetchSessionNotes(token, key)` function
- Added `SessionNotes` interface: `{ vocab: string, polisher: string }`

---

## 2. Highlighting Syntax

### Markdown Rendering

**bot/webui/src/components/MarkdownTextRenderer.tsx**
- Complete rewrite of highlight handling
- Uses `remark-directive` plugin for directive parsing
- Custom `remarkHighlight()` plugin transforms `==word==` to textDirective nodes
- Sets `hName: "mark"` and `hProperties` for directive conversion
- `<mark>` elements render with amber background:
  - Light mode: `bg-amber-200 text-amber-900`
  - Dark mode: `dark:bg-amber-700/50 dark:text-amber-100`

### Subagent Output Format

**persona/subagents/vocab_subagent.md**
- Added highlighting syntax documentation
- Sample output uses `==word==` for key vocabulary

**persona/subagents/polisher_subagent.md**
- Added highlighting syntax documentation

### CSS

**bot/webui/src/globals.css**
- Added `.highlight` class (backup for simple highlighting)

---

## 3. Session Deduplication

### Backend

**bot/nanobot/session/manager.py**
- `list_sessions()` now deduplicates by key:
  - Keeps first occurrence (most recent)
  - Prevents duplicate sessions in sidebar

### Frontend

**bot/webui/src/hooks/useSessions.ts**
- `refresh()` now deduplicates sessions client-side
- Uses `Set` to track seen keys

---

## Summary of Files Changed

| File | Changes |
|------|---------|
| bot/nanobot/channels/websocket.py | +18 lines: session notes API endpoint |
| bot/nanobot/session/manager.py | +32 lines: fallback search, deduplication |
| bot/webui/src/App.tsx | +33 lines: notes sheet state management |
| bot/webui/src/components/MarkdownTextRenderer.tsx | +83 lines: highlight syntax support |
| bot/webui/src/components/SessionNotesSheet.tsx | new file (134 lines) |
| bot/webui/src/components/thread/ThreadHeader.tsx | +15 lines: BookOpen icon button |
| bot/webui/src/components/thread/ThreadShell.tsx | +3 lines: onOpenNotes prop |
| bot/webui/src/globals.css | +13 lines: highlight CSS class |
| bot/webui/src/hooks/useSessionNotes.ts | new file (68 lines) |
| bot/webui/src/hooks/useSessions.ts | +9 lines: deduplication |
| bot/webui/src/i18n/locales/en/common.json | +10 lines: notes.* translations |
| bot/webui/src/lib/api.ts | +16 lines: fetchSessionNotes |
| persona/subagents/vocab_subagent.md | +20 lines: highlighting syntax |
| persona/subagents/polisher_subagent.md | +31 lines: highlighting syntax |
| persona/sessions/Collecting/notes/*.md | updated: ==word== highlighting |

---

*Update created: 2026-05-20*
