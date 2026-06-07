# Channel Event Contract

Date: 2026-06-07

This project keeps channels as rendering and transport adapters. Processor, subagent, and wiki logic should consume channel-neutral events.

## Canonical Event Shapes

User message:

```json
{
  "event": "message",
  "role": "user",
  "channel": "websocket",
  "chat_id": "chat-id",
  "session_uuid": "session-uuid",
  "mode": "freechat",
  "text": "I like basketball and Arsenal.",
  "media": [],
  "timestamp": "2026-06-07T10:00:00+08:00"
}
```

Assistant message:

```json
{
  "event": "message",
  "role": "assistant",
  "channel": "websocket",
  "chat_id": "chat-id",
  "session_uuid": "session-uuid",
  "mode": "freechat",
  "text": "Nice, football is a rich topic to practice.",
  "timestamp": "2026-06-07T10:00:05+08:00"
}
```

Progress/tool event:

```json
{
  "event": "tool_hint",
  "channel": "websocket",
  "chat_id": "chat-id",
  "session_uuid": "session-uuid",
  "name": "wiki_query",
  "phase": "running",
  "detail": "Searching user football preferences"
}
```

Processor status:

```json
{
  "event": "processor_status",
  "trigger_id": "freechat_vocab",
  "processor": "vocab",
  "subagent": "vocab",
  "phase": "done",
  "mode": "freechat",
  "session_uuid": "session-uuid",
  "input_rows": 1,
  "output_rows": 1,
  "artifact_paths": ["persona/processor/freechat/vocab.jsonl"]
}
```

Subagent status:

```json
{
  "event": "subagent_status",
  "task_id": "agentic-abc123",
  "label": "polisher",
  "phase": "done",
  "mode": "freechat",
  "session_uuid": "session-uuid",
  "tools": ["thread_query", "user_profile"]
}
```

## Rendering Rules

- User/assistant messages are rendered in the main conversation.
- Processor and subagent status should render as transient toast/activity indicators.
- Tool hints are visible in WebUI and developer surfaces; external chat channels may suppress them unless explicitly enabled.
- Artifact updates should render in mode-specific panels:
  - Freechat: vocab, polisher
  - Be Native: review
  - IELTS: feedback/review, vocab, polisher
- Wiki updates should render through the Wiki Memory panel, not as forced chat replies.

## Channel Adapter Boundary

New channels should implement only:

- inbound message normalization
- outbound message rendering
- progress/tool visibility policy
- media upload/download mapping
- auth/pairing rules

They should not rewrite:

- processor middleware
- subagent registry
- wiki sync
- Be Native session artifacts
- monitor/cost logging
