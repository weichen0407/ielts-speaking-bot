# Data Lifecycle And Export

Date: 2026-06-07

This project separates runtime data into four layers so test/demo data can be reset without accidentally deleting real learning memory.

## Data Classes

- Raw user events: `persona/events/thread.jsonl`, `persona/sessions/`, `persona/benative/sessions/`
- Derived learning artifacts: `persona/processor/`, session `notes/*.md`, Be Native review files
- Long-term memory: `persona/memory/`, `persona/wiki/wiki/`, `persona/wiki/raw/`
- Observability logs: `monitor/`, `persona/wiki/state/sync_log.jsonl`, trigger/processor/subagent run logs

## Reset Commands

Use `scripts/data_lifecycle.py reset-dev` for development cleanup.

```bash
uv run python scripts/data_lifecycle.py reset-dev --monitor --processors --wiki-index
```

This clears monitor logs, processor artifacts, and derived wiki indexes while keeping user memory and raw wiki sources.

To explicitly clear user memory/test conversations:

```bash
uv run python scripts/data_lifecycle.py reset-dev --clear-user-memory
```

`--clear-user-memory` is intentionally explicit because it removes raw session data, memory files, wiki pages/raw sources, and Be Native session data.

## Export Commands

Export one session:

```bash
uv run python scripts/data_lifecycle.py export-session websocket:chat-id --output-dir exports
```

Export mode artifacts:

```bash
uv run python scripts/data_lifecycle.py export-mode-artifacts freechat --output-dir exports
```

Export LLM Wiki pages, raw sources, sync log, and review queue:

```bash
uv run python scripts/data_lifecycle.py export-wiki --output-dir exports
```

Each export writes a `manifest.json` with source workspace, export kind, timestamp, and copied paths.

## Backup Strategy

Minimal user backup:

- `persona/events/`
- `persona/sessions/`
- `persona/memory/`
- `persona/wiki/wiki/`
- `persona/wiki/raw/`
- `persona/benative/sessions/`

Full developer backup:

- Minimal user backup
- `persona/processor/`
- `persona/wiki/state/`
- `monitor/`
- `mode/`
- `config/capabilities.yaml`

## Restore Notes

Restore raw events and long-term memory before derived artifacts. Derived indexes such as `persona/wiki/index/` can be rebuilt, so they are not required for a minimal backup.
