# WhisperLiveKit 嵌入 nanobot Mic ASR 集成计划

## 1. 当前架构分析

### nanobot 现有语音输入流程

```
麦克风按钮 (ThreadComposer.tsx)
    │
    ▼
useVoiceInput hook (Deepgram)
    │  - 使用 @deepgram/sdk
    │  - WebSocket 流式传输到 Deepgram API
    │  - 返回 interim + final transcript
    ▼
transcript 累积到 textarea
用户发送消息
```

### WhisperLiveKit 独立架构

```
wlk serve (WhisperLiveKit 服务)
    │  - 监听 :8000/asr
    │  - 期望 PCM s16le 输入
    ▼
WebSocket /asr
    │
    ▼
AudioProcessor 流水线
    (FFmpeg → VAD → ASR → FrontData)
```

### 目标：融合两者

```
麦克风按钮
    │
    ├──[模式A: Deepgram 云端]──────────────► Deepgram API
    │                                           (现有流程)
    │
    └──[模式B: WhisperLiveKit 本地]────────► WhisperLiveKit 服务
         (新集成)                              (WhisperLiveKit 服务)
              │                                    │
              │ PCM s16le WebSocket              ▼
              │◄──────────────────────────────────┘
              │  返回 FrontData JSON
              ▼
         解析 transcript
              │
              ▼
         textarea 显示
```

---

## 2. 关键发现

### 2.1 WhisperLiveKit 关键文件

| 文件 | 用途 |
|------|------|
| `WhisperLiveKit/whisperlivekit/basic_server.py` | WebSocket 服务器 (`/asr` 端点) |
| `WhisperLiveKit/whisperlivekit/audio_processor.py` | 核心音频处理 |
| `WhisperLiveKit/whisperlivekit/web/pcm_worklet.js` | AudioWorklet (PCM 提取) |
| `WhisperLiveKit/whisperlivekit/web/recorder_worker.js` | Web Worker (降采样 + PCM 编码) |
| `WhisperLiveKit/whisperlivekit/web/live_transcription.js` | 完整前端示例 |

### 2.2 nanobot 关键文件

| 文件 | 用途 |
|------|------|
| `bot/webui/src/hooks/useVoiceInput.ts` | 现有 Deepgram 语音输入 hook |
| `bot/webui/src/components/thread/ThreadComposer.tsx` | 包含麦克风按钮的输入组件 |
| `bot/webui/src/lib/nanobot-client.ts` | WebSocket 客户端 (不同用途) |

### 2.3 数据格式对比

**WhisperLiveKit 接收 (PCM)**:
```javascript
// recorder_worker.js 发送
websocket.send(arrayBuffer)  // PCM s16le 16kHz mono
```

**WhisperLiveKit 返回 (FrontData)**:
```json
{
  "status": "active_transcription",
  "lines": [{ "speaker": 1, "text": "...", "start": "0:00:00", "end": "0:00:03" }],
  "buffer_transcription": "partial text",
  "remaining_time_transcription": 1.2
}
```

---

## 3. 集成方案

### 3.1 方案选择：双模式并行

在 `useVoiceInput` 中新增 WhisperLiveKit 模式，与 Deepgram 并行存在，通过配置切换。

**优点**:
- 不破坏现有 Deepgram 流程
- 用户可选择本地或云端
- 易于 A/B 测试

### 3.2 配置项

在 `config.json` 中新增:
```json
{
  "channels": {
    "transcriptionProvider": "whisperlivekit",  // "deepgram" | "whisperlivekit"
    "whisperlivekitEnabled": true,
    "whisperlivekitModelSize": "base",
    "whisperlivekitLanguage": "auto",
    "whisperlivekitUrl": "ws://localhost:8000/asr"  // 可配置地址
  }
}
```

---

## 4. 实施步骤

### Phase 1: 前端 - 新增 WhisperLiveKit 模式支持

**文件**: `bot/webui/src/hooks/useVoiceInput.ts`

#### 1.1 新增 WhisperLiveKitClient 类

参考 `WhisperLiveKit/whisperlivekit/web/live_transcription.js` 实现:

```typescript
class WhisperLiveKitClient {
  private ws: WebSocket | null = null;
  private audioContext: AudioContext | null = null;
  private workletNode: AudioWorkletNode | null = null;
  private recorderWorker: Worker | null = null;

  async connect(url: string, language: string): Promise<void>;
  disconnect(): void;
  onTranscript(callback: (text: string, isFinal: boolean) => void): void;
  onError(callback: (error: string) => void): void;
}
```

#### 1.2 修改 useVoiceInput hook

```typescript
export function useVoiceInput(): UseVoiceInputApi {
  // ... 现有 Deepgram 逻辑 ...

  const startRecording = useCallback(async () => {
    const provider = getConfig().transcriptionProvider;

    if (provider === 'whisperlivekit') {
      // 使用 WhisperLiveKit
      await startWhisperLiveKitRecording();
    } else {
      // 使用 Deepgram (现有逻辑)
      await startDeepgramRecording();
    }
  }, [/* deps */]);

  // ...
}
```

#### 1.3 复用 WhisperLiveKit Web Worker 文件

将以下文件复制到 nanobot webui:
- `WhisperLiveKit/whisperlivekit/web/pcm_worklet.js`
- `WhisperLiveKit/whisperlivekit/web/recorder_worker.js`

或在 build 时从 WhisperLiveKit 目录引用。

### Phase 2: 后端 - WhisperLiveKit 服务集成

**文件**: `bot/nanobot/channels/websocket.py` 或新增 channel

#### 2.1 选项 A: 作为独立服务运行 (推荐)

 WhisperLiveKit 以独立进程运行:
```bash
wlk serve --model base --language en --host 0.0.0.0 --port 8000
```

nanobot WebUI 直接连接 `ws://localhost:8000/asr`。

**优点**: 简单，不影响 nanobot 主服务
**缺点**: 需要用户额外启动 WhisperLiveKit

#### 2.2 选项 B: 嵌入 nanobot 进程

在 nanobot 中新增 WhisperLiveKit channel/extension，共享进程。

**优点**: 一键启动
**缺点**: 复杂度高，依赖冲突风险

### Phase 3: 配置与 UI

#### 3.1 设置页面

在 `SettingsView.tsx` 中新增:
- 转写提供商选择 (Deepgram / WhisperLiveKit 本地)
- WhisperLiveKit 模型选择 (base, small, medium...)
- WhisperLiveKit 地址配置

#### 3.2 状态同步

通过 nanobot 的 `/api/settings` 端点返回当前转写配置。

---

## 5. 数据流详解

### 5.1 WhisperLiveKit 模式完整流程

```
┌─────────────────────────────────────────────────────────────────┐
│                        Browser (nanobot WebUI)                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│ 麦克风按钮点击                                                     │
│       │                                                          │
│       ▼                                                          │
│ useVoiceInput.startRecording()                                   │
│       │                                                          │
│       ├─► 创建 AudioContext (48kHz)                             │
│       │                                                          │
│       ├─► navigator.mediaDevices.getUserMedia({ audio: true })   │
│       │                                                          │
│       ├─► audioWorklet.addModule('/web/pcm_worklet.js')          │
│       │       │                                                  │
│       │       ▼                                                  │
│       │   AudioWorkletNode('pcm-forwarder')                       │
│       │       │                                                  │
│       │       ▼                                                  │
│       │   recorder_worker.js (Web Worker)                         │
│       │       │  1. resample: 48000 → 16000 Hz                   │
│       │       │  2. toPCM: Float32 → Int16 s16le                 │
│       │       │                                                  │
│       │       ▼                                                  │
│       │   WebSocket.send(arrayBuffer)                            │
│       │                                                          │
│       ▼                                                          │
│  ws://localhost:8000/asr?language=en                             │
│       │                                                          │
└───────┼──────────────────────────────────────────────────────────┘
        │
        │ WebSocket (PCM s16le bytes)
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                   WhisperLiveKit Server (:8000)                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  WebSocket /asr 接收 bytes                                       │
│       │                                                          │
│       ▼                                                          │
│  AudioProcessor.process_audio(bytes)                             │
│       │  (pcm_input=True 时直接使用)                            │
│       │                                                          │
│       ├──► Silero VAD (语音活动检测)                            │
│       ├──► Whisper ASR (转写)                                    │
│       ├──► Diarization (说话人分离, 可选)                        │
│       └──► Translation (翻译, 可选)                               │
│       │                                                          │
│       ▼                                                          │
│  websocket.send_json(FrontData.to_dict())                        │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
        │
        │ JSON WebSocket 消息
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Browser (nanobot WebUI)                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ws.onmessage(event)                                             │
│       │                                                          │
│       ▼                                                          │
│  WhisperLiveKitClient.handleMessage(data)                         │
│       │                                                          │
│       ├─ data.type === 'config'                                  │
│       │       └── 记录 useAudioWorklet 标志                       │
│       │                                                          │
│       ├─ data.type === 'ready_to_stop'                           │
│       │       └── 录音结束                                        │
│       │                                                          │
│       └─ 其他 (转写结果)                                          │
│               ├── data.buffer_transcription → interim transcript │
│               └── data.lines[].text → final transcript           │
│               │                                                  │
│               ▼                                                  │
│  setTranscript(accumulatedText)                                   │
│       │                                                          │
│       ▼                                                          │
│  textarea 显示转写文字                                            │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 6. 关键代码片段

### 6.1 recorder_worker.js (核心降采样逻辑)

```javascript
// 48kHz → 16kHz 线性插值降采样
function resample(buffer, from, to) {
    if (from === to) return buffer;
    const ratio = from / to;  // 3.0
    const newLength = Math.round(buffer.length / ratio);
    const result = new Float32Array(newLength);

    for (let i = 0; i < newLength; i++) {
        const start = Math.round(i * ratio);
        const end = Math.round((i + 1) * ratio);
        let accum = 0, count = 0;
        for (let j = start; j < end && j < buffer.length; j++) {
            accum += buffer[j];
            count++;
        }
        result[i] = accum / count;
    }
    return result;
}

// Float32 (-1.0~1.0) → Int16 s16le
function toPCM(input) {
  const buffer = new ArrayBuffer(input.length * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]));
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
  }
  return buffer;
}
```

### 6.2 WhisperLiveKit WebSocket 协议

**连接**: `ws://localhost:8000/asr?language=en`

**服务端配置消息**:
```json
{
  "type": "config",
  "useAudioWorklet": true,
  "mode": "full"
}
```

**转写结果消息**:
```json
{
  "status": "active_transcription",
  "lines": [
    {
      "speaker": 1,
      "text": "Hello world",
      "start": "0:00:00",
      "end": "0:00:03"
    }
  ],
  "buffer_transcription": "And you",
  "remaining_time_transcription": 0.5
}
```

**结束消息**:
```json
{
  "type": "ready_to_stop"
}
```

---

## 7. 文件变更清单

### 新增文件

| 路径 | 说明 |
|------|------|
| `bot/webui/src/hooks/useWhisperLiveKit.ts` | WhisperLiveKit 客户端封装 |
| `bot/webui/src/web/pcm_worklet.js` | AudioWorklet 处理器 |
| `bot/webui/src/web/recorder_worker.js` | Web Worker (降采样 + PCM) |

### 修改文件

| 路径 | 修改内容 |
|------|----------|
| `bot/webui/src/hooks/useVoiceInput.ts` | 新增 WhisperLiveKit 模式分支 |
| `bot/webui/src/lib/types.ts` | 新增配置类型定义 |
| `bot/nanobot/config/schema.py` | 新增 whisperlivekit 配置项 |
| `bot/nanobot/channels/websocket.py` | (可选) 新增 WhisperLiveKit 代理端点 |

---

## 8. 测试计划

### 8.1 单元测试

- [ ] `useWhisperLiveKit` hook 基本连接/断开
- [ ] PCM 降采样精度验证
- [ ] WebSocket 消息解析

### 8.2 集成测试

- [ ] WhisperLiveKit 服务启动 (`wlk serve`)
- [ ] 麦克风录音 → 转写文字端到端
- [ ] 模式切换 (Deepgram ↔ WhisperLiveKit)
- [ ] 配置持久化

### 8.3 性能测试

- [ ] 延迟对比 (WhisperLiveKit vs Deepgram)
- [ ] 内存占用
- [ ] CPU/GPU 利用率

---

## 9. 风险与缓解

| 风险 | 级别 | 缓解措施 |
|------|------|----------|
| 用户需额外启动 WhisperLiveKit | 中 | 提供一键启动脚本或选项 B 嵌入方案 |
| Web Worker 跨域加载 | 低 | 将 worker 文件打包到 nanobot webui |
| WhisperLiveKit 模型下载 | 中 | 预下载 base 模型，提供进度提示 |
| 音频格式兼容性 | 低 | 参考 WhisperLiveKit 现有实现 |

---

## 10. 后续扩展

- [ ] 支持 WhisperLiveKit 的 VAD 事件回调
- [ ] 说话人分离 (diarization) 集成
- [ ] 实时翻译支持
- [ ] 多语言自动检测
