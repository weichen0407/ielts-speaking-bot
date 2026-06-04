# Middleware-Gated Subagent Architecture

> Draft for discussion. This document describes the intended architecture before implementation.

## Core Idea

The project should not treat `processor` and `subagent` as two separate alternatives.

The intended design is:

```text
raw conversation / artifacts
-> task-specific processor middleware
-> subagent execution
   -> api mode
   -> agentic mode
-> processor output validation
-> artifact persistence
-> monitor / webui rendering
```

In this model, a processor is the engineering middleware around an LLM task. A subagent is the semantic worker that performs language analysis, feedback, diagnosis, memory extraction, or research.

The processor should make every LLM/subagent call cheaper, cleaner, and more controllable. The subagent should make the task feel like an agent, not just a raw prompt sent to an LLM API.

## Why Processor Middleware Exists

Raw `thread.jsonl` is noisy. It may contain assistant messages, system prompts, metadata, repeated turns, tool messages, timestamps, audio fields, and fields that are not useful for the current task.

Before a task reaches a model, the processor should:

```text
read incremental source data
filter irrelevant rows
select useful fields
compress context
inject task metadata
build a strict subagent input contract
reduce token cost
improve output stability
```

After a subagent returns, the processor should:

```text
parse output
validate schema
deduplicate records
normalize to jsonl / md
update cursor
write monitor logs
trigger webui refresh / toast
```

So processor is not just a simple parser. It is an LLM-call middleware and artifact materialization layer.

## Subagent Execution Modes

Each subagent should support two execution modes.

### API Mode

API mode is the lightweight path.

```text
processor prepares compact input
-> subagent runs as constrained LLM call
-> returns structured output
-> processor validates and persists
```

This is useful when:

```text
the task has fixed input/output
the output schema is simple
tool use is unnecessary
cost and latency matter
```

Example:

```text
User: I always say "good" and "interesting" when I talk about movies.
```

Vocab subagent in API mode may return:

```text
good -> impressive / enjoyable / memorable
interesting -> thought-provoking / engaging / captivating
talk about movies -> discuss films / describe a film experience
```

This is close to current processor-powered LLM analysis, but the conceptual boundary changes: the processor prepares and validates; the subagent performs the language judgment.

### Agentic Mode

Agentic mode is the tool-enabled path.

```text
processor prepares compact input
-> subagent receives available tool manifest
-> subagent may call tools
-> subagent combines current input with retrieved context
-> returns structured output
-> processor validates and persists
```

This is useful when:

```text
the task benefits from personal context
the subagent needs historical artifacts
the task needs external information
the agent should reason over multiple sources
the output should be personalized
```

For the same input:

```text
User: I always say "good" and "interesting" when I talk about movies.
```

In agentic mode, the vocab subagent may use tools to check:

```text
user profile
past vocab mistakes
recent freechat topics
LLM Wiki memory
notes
previous Arsenal / football / travel mentions
```

Then it can decide:

```text
The user repeatedly overuses generic adjectives.
The user has recently talked about films and travel, so suggest topic-specific alternatives.
The user should practice replacing weak adjectives with precise collocations.
```

This makes it more like a real learning agent rather than a stateless LLM API.

## Tool Layer

The tool layer should be abstracted away from individual processors and subagents.

Tools should be registered in one place and exposed to subagents through a controlled manifest and a hard runtime allowlist.

Possible tool groups:

```text
artifact_read:
read vocab / polisher / review / progress artifacts

thread_query:
read recent or historical conversation turns

wiki_query:
search LLM Wiki pages, graph, entities, concepts, gaps

user_profile:
read stable user preferences, habits, goals, recurring mistakes

notes_read:
read user notes and AI replies

external_search:
use configured search / scraping APIs when allowed

file_read:
read approved project files or persona files
```

Tool access should be scoped per subagent.

In the current implementation, `SubagentManager.spawn(..., allowed_tools=[...])`
filters the actual `ToolRegistry` before the agent loop starts. This means the
configured tool list is not merely prompt text; tools outside the allowlist are
not exposed to the model at all.

For example:

```text
vocab agentic mode:
thread_query, artifact_read, user_profile, wiki_query

expression polish agentic mode:
thread_query, artifact_read, user_profile

llm wiki research mode:
wiki_query, thread_query, external_search, file_read
```

The subagent should not automatically get every tool. Tool availability is part of the task design.

## Freechat Mode Draft

For the first implementation target, focus on `freechat`.

Freechat should have two primary subagents:

```text
vocab
expression_polisher
```

### Vocab Task

Purpose:

```text
extract stronger words, phrases, collocations, and topic-specific lexical alternatives
```

Middleware:

```text
VocabProcessor
```

Subagent:

```text
VocabSubagent
```

API mode:

```text
only current delta user messages
fixed output schema
low cost
```

Agentic mode:

```text
current delta user messages
past vocab mistakes
user profile
related wiki memory
recurring language habit detection
```

### Expression Polisher Task

Purpose:

```text
polish grammar, sentence structure, fluency, and natural expression
```

Middleware:

```text
ExpressionProcessor / PolisherProcessor
```

Subagent:

```text
ExpressionPolisherSubagent
```

API mode:

```text
current user sentence -> polished sentence + explanation
```

Agentic mode:

```text
current sentence
conversation topic
past expression patterns
user's preferred tone
IELTS speaking style constraints
```

## Draft Config Shape

The trigger should describe both the processor middleware and the subagent execution mode.

Example:

```json
{
  "id": "freechat_vocab",
  "name": "Freechat Vocab",
  "enabled": true,
  "condition": {
    "kind": "file_line_count",
    "count": 1,
    "scope": "global",
    "path": "persona/events/thread.jsonl"
  },
  "target": {
    "processor": "vocab",
    "subagent": "vocab",
    "execution_mode": "agentic",
    "input_path": "persona/events/thread.jsonl",
    "output_path": "persona/processor/freechat/vocab.jsonl",
    "batch_size": 20,
    "model": "deepseek-v4-flash",
    "tools": [
      "thread_query",
      "artifact_read",
      "user_profile",
      "wiki_query"
    ]
  }
}
```

For API mode:

```json
{
  "target": {
    "processor": "vocab",
    "subagent": "vocab",
    "execution_mode": "api",
    "tools": []
  }
}
```

## Runtime Flow

```text
CounterEngine checks trigger
-> trigger matches freechat_vocab
-> AgentLoop starts processor middleware
-> processor reads only new thread.jsonl rows
-> processor filters fields and builds compact task input
-> runtime checks execution_mode
   -> api: call subagent as constrained LLM task
   -> agentic: spawn tool-enabled subagent runtime
-> subagent returns raw structured output
-> processor parses and validates output
-> processor writes jsonl/md artifacts
-> processor updates cursor
-> processor logs processor_runs.jsonl
-> subagent logs subagent_runs.jsonl when agentic runtime is used
-> websocket emits toast / monitor updates
```

## Difference From Current Implementation

Current implementation:

```text
trigger
-> processor
-> processor directly calls provider.chat_with_retry()
-> processor parses and writes output
```

Desired implementation:

```text
trigger
-> processor middleware
-> subagent execution mode
   -> api mode: constrained LLM subagent call
   -> agentic mode: tool-enabled subagent runtime
-> processor output validation and persistence
```

The current version already has useful pieces:

```text
trigger frequency
file_line_count cursor
incremental materialization
processor registry
LLM-backed processor calls
processor run monitor
webui processor toast
```

But it does not yet fully express:

```text
processor as universal middleware
subagent as semantic worker
api vs agentic execution mode
tool manifest per subagent
subagent run visibility for processor-mediated tasks
```

## Design Principle

The architecture should separate deterministic engineering from semantic reasoning.

```text
Processor middleware:
deterministic, schema-aware, cheap, auditable

Subagent:
semantic, adaptive, tool-aware, personalized

Tool layer:
explicitly registered, permissioned, scoped by task
```

This gives the project a clearer agent architecture:

```text
task-specific middleware + mode-specific subagents + scoped tool runtime + artifact memory
```

## Open Questions Before Implementation

1. Should API mode still be logged as a `subagent_run`, or only as a `processor_run`?

2. Should API mode use the same subagent prompt file as agentic mode, or a smaller prompt template?

3. Should `execution_mode` live inside each trigger target, or in a shared subagent registry?

4. Should tools be configured per trigger, per subagent, or both?

5. Should agentic mode wait synchronously for subagent output before writing artifacts, or run asynchronously and finalize later?

6. Should `vocab` and `expression_polisher` be implemented first as freechat-only, then generalized to IELTS mode?

## Phase Plans

- [Freechat Middleware + Subagent Migration Plan](freechat-middleware-subagent-plan.md)
