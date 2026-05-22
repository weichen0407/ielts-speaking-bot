# WhisperLiveKit 集成文档

## 1. 命令行入口

```bash
# 安装后通过 pip 安装的入口命令
wlk --model base --language en

# 等价于
wlk serve --model base --lan en
```

**入口定义** 在 `pyproject.toml`:
```toml
[project.scripts]
wlk = "whisperlivekit.cli:main"
```

`wlk` 命令通过 `whisperlivekit/cli.py` 的 `main()` 函数分发子命令:
- `wlk serve` / `wlk` (默认) → 启动 WebSocket 服务器
- `wlk listen` → 本地麦克风实时转写
- `wlk run` → 自动拉取模型 + 启动服务器
- `wlk transcribe` → 离线文件转写
- `wlk bench` → 基准测试

---

## 2. 服务端架构

### 2.1 服务器启动路径

```
wlk --model base --language en
  └─> cli.main()
        └─> parse_args() → WhisperLiveKitConfig
        └─> cmd_serve(args) 或直接 serve(args)
              └─> basic_server.main()
                    └─> uvicorn.run(app, host, port)
```

关键文件:
- `whisperlivekit/basic_server.py` — FastAPI + WebSocket 服务器
- `whisperlivekit/audio_processor.py` — 核心音频处理流水线
- `whisperlivekit/core.py` — TranscriptionEngine 单例
- `whisperlivekit/parse_args.py` — CLI 参数解析

### 2.2 WebSocket 端点

**默认地址**: `ws://localhost:8000/asr`

| 端点 | 协议 | 用途 |
|------|------|------|
| `/asr` | WebSocket | 主转写接口 |
| `/v1/listen` | WebSocket | Deepgram 兼容接口 |
| `/v1/audio/transcriptions` | REST | OpenAI 兼容批量转写 |
| `/health` | HTTP GET | 健康检查 |
| `/` | HTTP GET | 内置 Web UI |

### 2.3 查询参数

```
ws://host:port/asr?language=en&mode=full
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `language` | (服务器配置) | 每会话语言覆盖，ISO 639-1 如 `en`, `fr`, `auto` |
| `mode` | `full` | `full`=全量状态推送, `diff`=增量差分 |

---

## 3. 数据协议详解

### 3.1 客户端 → 服务端

#### PCM 输入模式 (`useAudioWorklet: true`)

当服务器以 `--pcm-input` 启动时，客户端发送:

- **格式**: PCM s16le (带符号 16-bit 小端序), 16kHz, 单声道
- **字节计算**: `采样率 × 通道数 × 2 bytes × 时长`
  - 16kHz 单声道 0.1s = 3200 bytes
  - 16kHz 单声道 1.0s = 32000 bytes

#### MediaRecorder 模式 (`useAudioWorklet: false`, 默认)

发送 FFmpeg 可解码的任意编码格式 (WebM/Opus, MP3, WAV 等)。

#### 结束信号

发送**空字节帧** `b""` 表示音频流结束。

### 3.2 服务端 → 客户端

#### Config 消息 (连接建立后立即发送)

```json
{
  "type": "config",
  "useAudioWorklet": true,
  "mode": "full"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | string | 固定为 `"config"` |
| `useAudioWorklet` | bool | `true`=需要 PCM s16le, `false`=需要编码音频 |
| `mode` | string | `"full"` 或 `"diff"` |

#### 转写更新消息 (full 模式)

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
  "buffer_transcription": "partial",
  "buffer_diarization": "",
  "buffer_translation": "",
  "remaining_time_transcription": 1.2,
  "remaining_time_diarization": 0.5
}
```

#### ready_to_stop 消息

所有音频处理完成后发送:

```json
{
  "type": "ready_to_stop"
}
```

---

## 4. 前端音频采集与处理

### 4.1 文件位置

```
whisperlivekit/web/
├── live_transcription.html   # 主页面
├── live_transcription.js     # 核心逻辑
├── live_transcription.css     # 样式
├── pcm_worklet.js            # AudioWorklet 处理器
├── recorder_worker.js        # Web Worker (降采样 + PCM 编码)
└── src/                      # 图标等资源
```

### 4.2 麦克风采集流程

```
navigator.mediaDevices.getUserMedia({ audio: true })
  └─> AudioContext.createMediaStreamSource(stream)
        ├─> 分析器连接: createAnalyser() → 波形显示
        └─> 音频输入分支:
              ├─ AudioWorklet 模式 (useAudioWorklet: true)
              │    └─ AudioWorkletNode(pcm-forwarder)
              │         └─ recorder_worker.js (Web Worker)
              │              ├─ 降采样: 48000 → 16000
              │              ├─ PCM 编码: Float32 → Int16 s16le
              │              └─ websocket.send(ArrayBuffer)
              │
              └─ MediaRecorder 模式 (useAudioWorklet: false)
                   └─ MediaRecorder(stream, { mimeType: "audio/webm" })
                        └─ recorder.ondataavailable → websocket.send(Blob)
```

### 4.3 降采样算法 (recorder_worker.js)

```javascript
// 48kHz → 16kHz (3:1 降采样)
// 线性插值平均法
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
```

### 4.4 PCM 编码 (recorder_worker.js)

```javascript
// Float32 (-1.0 ~ 1.0) → Int16 s16le
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

### 4.5 pcm_worklet.js (AudioWorkletProcessor)

```javascript
class PCMForwarder extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0];
    if (input && input[0] && input[0].length) {
      // 提取单声道 (channel 0)
      const channelData = input[0];
      const copy = new Float32Array(channelData.length);
      copy.set(channelData);
      this.port.postMessage(copy, [copy.buffer]);  // 传给 recorder_worker
    }
    return true;
  }
}
registerProcessor('pcm-forwarder', PCMForwarder);
```

### 4.6 WebSocket 消息发送

```javascript
recorderWorker.onmessage = (e) => {
  if (websocket && websocket.readyState === WebSocket.OPEN) {
    websocket.send(e.data.buffer);  // 直接发送 ArrayBuffer
  }
};
```

---

## 5. 嵌入 nanobot Web 页面方案

### 5.1 需要复用的核心组件

| 组件 | 文件 | 用途 |
|------|------|------|
| AudioWorklet | `pcm_worklet.js` | 原始 PCM 提取 |
| Web Worker | `recorder_worker.js` | 降采样 + PCM 编码 |
| WebSocket 逻辑 | `live_transcription.js` 中相关函数 | 音频发送、结果接收 |

### 5.2 集成步骤

#### Step 1: 引入必要的 JS

```html
<script src="/web/pcm_worklet.js"></script>
<script src="/web/recorder_worker.js"></script>
```

#### Step 2: 初始化 AudioContext 和 AudioWorklet

```javascript
const audioContext = new AudioContext({ sampleRate: 16000 });
await audioContext.audioWorklet.addModule('/web/pcm_worklet.js');
```

#### Step 3: 连接麦克风 → Worklet → Worker → WebSocket

```javascript
// 获取麦克风流
const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
const source = audioContext.createMediaStreamSource(stream);

// 创建 AudioWorkletNode
const workletNode = new AudioWorkletNode(audioContext, 'pcm-forwarder', {
  numberOfInputs: 1,
  numberOfOutputs: 0,
  channelCount: 1
});
source.connect(workletNode);

// 创建 Web Worker
const recorderWorker = new Worker('/web/recorder_worker.js');
recorderWorker.postMessage({
  command: 'init',
  config: {
    sampleRate: audioContext.sampleRate,  // 48000
    targetSampleRate: 16000
  }
});

recorderWorker.onmessage = (e) => {
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(e.data.buffer);  // PCM s16le ArrayBuffer
  }
};

workletNode.port.onmessage = (e) => {
  const data = e.data;
  const ab = data instanceof ArrayBuffer ? data : data.buffer;
  recorderWorker.postMessage({ command: 'record', buffer: ab }, [ab]);
};
```

#### Step 4: 连接 WebSocket

```javascript
const ws = new WebSocket('ws://localhost:8000/asr?language=en');

ws.onopen = () => {
  console.log('Connected');
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);

  if (data.type === 'config') {
    console.log('Server config:', data);
    return;
  }

  if (data.type === 'ready_to_stop') {
    console.log('Transcription complete');
    return;
  }

  // 处理转写结果
  // data.lines, data.buffer_transcription, etc.
  console.log('Transcript:', data.buffer_transcription || data.lines);
};

ws.onerror = (err) => {
  console.error('WebSocket error:', err);
};
```

#### Step 5: 发送结束信号

```javascript
// 停止录音时发送空帧
ws.send(new Blob([], { type: 'audio/webm' }));
// 或直接发送空 ArrayBuffer
ws.send(new ArrayBuffer(0));
```

### 5.3 完整示例代码

```javascript
class WhisperLiveKitClient {
  constructor(wsUrl = 'ws://localhost:8000/asr') {
    this.wsUrl = wsUrl;
    this.ws = null;
    this.audioContext = null;
    this.workletNode = null;
    this.recorderWorker = null;
    this.isRecording = false;
  }

  async connect(language = 'en') {
    this.audioContext = new AudioContext({ sampleRate: 16000 });

    // 加载 AudioWorklet
    if (!this.audioContext.audioWorklet) {
      throw new Error('AudioWorklet not supported');
    }
    await this.audioContext.audioWorklet.addModule('/web/pcm_worklet.js');

    // 获取麦克风
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const source = this.audioContext.createMediaStreamSource(stream);

    // 创建 AudioWorkletNode
    this.workletNode = new AudioWorkletNode(this.audioContext, 'pcm-forwarder', {
      numberOfInputs: 1,
      numberOfOutputs: 0,
      channelCount: 1
    });
    source.connect(this.workletNode);

    // 创建 Web Worker
    this.recorderWorker = new Worker('/web/recorder_worker.js');
    this.recorderWorker.postMessage({
      command: 'init',
      config: {
        sampleRate: this.audioContext.sampleRate,
        targetSampleRate: 16000
      }
    });

    this.recorderWorker.onmessage = (e) => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(e.data.buffer);
      }
    };

    this.workletNode.port.onmessage = (e) => {
      const data = e.data;
      const ab = data instanceof ArrayBuffer ? data : data.buffer;
      this.recorderWorker.postMessage({ command: 'record', buffer: ab }, [ab]);
    };

    // 建立 WebSocket
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(`${this.wsUrl}?language=${language}`);

      this.ws.onopen = () => resolve();
      this.ws.onerror = reject;
      this.ws.onmessage = (event) => this.handleMessage(event);
    });
  }

  handleMessage(event) {
    const data = JSON.parse(event.data);

    if (data.type === 'config') {
      console.log('Connected, useAudioWorklet:', data.useAudioWorklet);
      return;
    }

    if (data.type === 'ready_to_stop') {
      console.log('Done');
      return;
    }

    // 转写结果
    const text = data.buffer_transcription || data.lines?.map(l => l.text).join(' ');
    console.log('Transcript:', text);
  }

  stop() {
    if (this.ws) {
      this.ws.send(new ArrayBuffer(0));  // 结束信号
    }
    // 清理资源...
  }
}
```

---

## 6. 关键参数速查

| 参数 | 值 | 说明 |
|------|-----|------|
| 采样率 | 16000 Hz | Whisper 模型期望输入 |
| 量化位数 | 16-bit | s16le 格式 |
| 通道数 | 1 (单声道) | mono |
| 编码格式 | PCM s16le | 有符号 16-bit 小端 |
| WebSocket 路径 | `/asr` | 主转写接口 |
| 默认端口 | 8000 | 服务器监听端口 |
| chunk 大小 | 0.1s (1600 bytes) | 每帧音频时长 |

---

## 7. 音频数据流图

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Browser (Frontend)                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  getUserMedia()                                                     │
│       │                                                             │
│       ▼                                                             │
│  MediaStream (48kHz float) ─────────────────────────────────┐       │
│       │                                               │       │
│       │  createMediaStreamSource()                     │       │
│       ▼                                               │       │
│  MediaStreamSource                                    │       │
│       │                                               │       │
│       │  connect(workletNode)                         │       │
│       ▼                                               │       │
│  AudioWorkletNode('pcm-forwarder')  ───────────────────────┐ │
│       │  (pcm_worklet.js)                            │ │       │
│       │                                               ▼ │       │
│       │  port.postMessage(Float32Array)               │ │       │
│       │                                               │ │       │
│       ▼                                               │ │       │
│  recorderWorker (Web Worker)  ◄──────────────────────────┘ │       │
│       │  (recorder_worker.js)                             │       │
│       │                                                    │       │
│       │  1. resample: 48000 → 16000 Hz                    │       │
│       │  2. toPCM: Float32 → Int16 s16le                   │       │
│       │  3. postMessage(ArrayBuffer)                       │       │
│       ▼                                                    │       │
│  onmessage(arrayBuffer) ─────────────────────────────────────────►│
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              │ WebSocket.send(ArrayBuffer)
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Server (Backend)                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  WebSocket /asr                                                     │
│       │                                                             │
│       ▼                                                             │
│  audio_processor.process_audio(bytes)                               │
│       │                                                             │
│       ├── is_pcm_input=True? ──► 直接使用 PCM                       │
│       │                                                             │
│       └── is_pcm_input=False? ──► FFmpeg 解码                      │
│                                       (支持任意格式输入)            │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ AudioProcessor 流水线:                                      │   │
│  │   1. VAD (Silero) — 语音活动检测                          │   │
│  │   2. ASR (Whisper/Voxtral/Qwen) — 转写                    │   │
│  │   3. Diarization — 说话人分离 (可选)                       │   │
│  │   4. Translation — 翻译 (可选)                            │   │
│  └─────────────────────────────────────────────────────────────┘   │
│       │                                                             │
│       ▼                                                             │
│  FrontData.to_dict()                                                │
│       │                                                             │
│       ▼                                                             │
│  websocket.send_json(response)                                       │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```
