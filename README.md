# IELTS Speaking Bot

An AI speaking-practice system built on top of Nanobot. The project turns a
general chat agent into an English-learning assistant with mode-specific
conversation flows, structured learning processors, long-term wiki memory, and
runtime observability.

## What It Does

- Runs IELTS and freechat speaking practice through Nanobot modes.
- Records per-session and cross-session conversation data under `persona/`.
- Triggers learning analysis processors from incremental conversation events.
- Produces vocabulary, grammar, notes, review, quiz, and progress artifacts.
- Builds an LLM Wiki style memory layer for long-term personal knowledge.
- Provides WebUI and monitor surfaces for chat, wiki, triggers, and subagent activity.

## Core Architecture

```text
user turn
  -> Nanobot agent loop
  -> persona/sessions/{session_uuid}/thread.jsonl
  -> persona/events/thread.jsonl
  -> counter trigger engine
  -> processor pipeline / subagents
  -> persona/processor/{mode}/
  -> persona/wiki/
  -> monitor/
```

## Main Components

| Area | Path | Purpose |
| --- | --- | --- |
| Agent runtime | `bot/nanobot/` | Nanobot core loop, channels, providers, sessions, triggers, WebUI APIs. |
| Modes | `mode/` | Mode prompts and trigger definitions for freechat, IELTS, benative, and default jobs. |
| Processors | `subagent/*/*/processor/` | Structured LLM processing pipeline for learning artifacts. |
| Wiki memory | `subagent/cross_session/wiki/processor/` | Taxonomy-guided memory extraction, crystallization, graph projection, and wiki sync. |
| Runtime data | `persona/` | Session history, global event stream, memory, wiki state, and processor outputs. |
| Observability | `monitor/` | Trigger and subagent runtime logs. |
| WebUI | `bot/webui/` | Browser UI for chat, monitor, notes, and wiki visualization. |

## Processor Pipeline

The learning pipeline uses a base processor abstraction:

```text
read JSONL
  -> schema-driven field extraction
  -> batch input
  -> LLM call
  -> parser
  -> JSONL and Markdown artifacts
```

Configured mode pipelines currently follow:

```text
thread delta
  -> vocab
  -> polisher
  -> notes
  -> progress_tracker
  -> review
  -> quiz
  -> progress_organizer
```

Trigger configuration lives in:

- `mode/freechat/trigger/triggers.json`
- `mode/ielts/trigger/triggers.json`
- `mode/default/trigger/triggers.json`

The current processor and subagent model override is `deepseek-v4-flash`.

## LLM Wiki Memory

The wiki system stores long-term memory as structured pages instead of treating
all history as a flat retrieval corpus. It keeps raw sources, wiki pages,
schemas, sync logs, and graph projections separate so that updates can be
audited and visualized.

Important paths:

- `config/wiki_taxonomy.yaml`
- `persona/wiki/`
- `subagent/cross_session/wiki/processor/`

The taxonomy-guided extractor constrains memory candidates into stable domains,
topics, subtypes, entities, and relations before they are written into wiki
artifacts.

## Running Locally

Install dependencies:

```bash
cd bot
uv sync
```

Start Nanobot gateway:

```bash
cd bot
uv run nanobot gateway
```

Check Nanobot workspace status:

```bash
cd bot
uv run nanobot status
```

Run focused tests:

```bash
cd bot
uv run pytest tests/counter tests/subagent tests/wiki
```

Run WebUI checks:

```bash
cd bot/webui
bun install
bun run check
```

## Runtime Data Policy

Runtime data is intentionally kept out of git. The canonical runtime root is
`persona/`, while `monitor/` stores system observability logs. Generated JSONL
logs, SQLite indexes, sessions, notes, and local CV drafts are ignored.

See also:

- `architecture.md`
- `docs/runtime-data-map.md`
- `docs/wiki-memory-implementation.md`
