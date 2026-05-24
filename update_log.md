# Update Log

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
