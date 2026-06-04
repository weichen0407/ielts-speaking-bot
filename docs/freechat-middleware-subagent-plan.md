# Freechat Middleware + Subagent Migration Plan

> Phase 1 implementation plan. Scope: freechat mode only, with `vocab` and `polisher`.

## Goal

Move freechat learning tasks from:

```text
trigger -> processor directly calls LLM -> artifact
```

to:

```text
trigger
-> task processor middleware
-> subagent execution
   -> api mode
   -> agentic mode
-> processor validates and persists artifacts
-> monitor / webui visibility
```

The first phase should prove the architecture without rewriting every mode or every subagent.

## Phase 1 Scope

Freechat mode gets two processor-gated subagents:

```text
vocab:
focus on lexical resource, word choice, phrases, collocations, topic vocabulary

polisher:
focus on grammar, sentence structure, fluency, coherence, natural expression
```

Out of scope for phase 1:

```text
IELTS mode migration
LLM Wiki agentic research
review/progress pipeline rewrite
external web search tools
multi-step async finalization
```

## Current State

Existing pieces that can be reused:

```text
mode/freechat/trigger/triggers.json
subagent/single_session/vocab/context/vocab_subagent.md
subagent/single_session/vocab/processor
subagent/single_session/polisher/context/polisher_subagent.md
subagent/single_session/polisher/processor
subagent/_shared/base.py
subagent/_shared/registry.py
bot/nanobot/agent/loop.py
monitor/processor_runs.jsonl
monitor/subagent_runs.jsonl
webui processor/subagent toasts
```

Current limitation:

```text
freechat vocab/polisher triggers execute processors directly.
processors call provider.chat_with_retry() internally.
they do not spawn or record a processor-mediated subagent execution.
```

## Target Concepts

### Mode Registers Subagents

Each mode should declare which subagents are available for that mode.

For phase 1:

```text
freechat:
  subagents:
    vocab
    polisher
```

This can initially live in `config/capabilities.yaml` and be referenced by trigger config.

### Subagent Registers Tools

Each subagent should declare its allowed tools.

For phase 1:

```text
vocab api mode:
  tools: []

vocab agentic mode:
  tools:
    - thread_query
    - artifact_read
    - user_profile
    - wiki_query

polisher api mode:
  tools: []

polisher agentic mode:
  tools:
    - thread_query
    - artifact_read
    - user_profile
```

The first implementation can register the tool names and pass a manifest into the subagent prompt. The actual tool implementations can be minimal and read-only.

### Processor Is Middleware

Processor responsibilities:

```text
read incremental thread rows
filter only useful user messages and metadata
build compact subagent input
wrap input with schema/output constraints
parse subagent output
validate result schema
deduplicate
write jsonl/md
update cursor
log processor run
emit processor toast
```

Subagent responsibilities:

```text
perform semantic analysis
optionally use tools in agentic mode
return structured output only
```

## Proposed Config Shape

Update freechat trigger targets from processor-only to middleware + subagent.

Example vocab:

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
    "execution_mode": "api",
    "agentic": false,
    "tools": [],
    "input_path": "persona/events/thread.jsonl",
    "output_path": "persona/processor/freechat/vocab.jsonl",
    "batch_size": 20,
    "model": "deepseek-v4-flash"
  }
}
```

Example polisher:

```json
{
  "id": "freechat_polisher",
  "name": "Freechat Polisher",
  "enabled": true,
  "condition": {
    "kind": "file_line_count",
    "count": 1,
    "scope": "global",
    "path": "persona/events/thread.jsonl"
  },
  "target": {
    "processor": "polisher",
    "subagent": "polisher",
    "execution_mode": "api",
    "agentic": false,
    "tools": [],
    "input_path": "persona/events/thread.jsonl",
    "output_path": "persona/processor/freechat/polisher.jsonl",
    "batch_size": 20,
    "model": "deepseek-v4-flash"
  }
}
```

Agentic test mode can be enabled by changing:

```json
{
  "execution_mode": "agentic",
  "agentic": true,
  "tools": ["thread_query", "artifact_read", "user_profile", "wiki_query"]
}
```

## Implementation Steps

### Step 1. Extend Trigger Target Schema

Status: done.

Add fields to the trigger target model:

```text
subagent: optional string
execution_mode: "api" | "agentic"
agentic: optional bool
tools: list[string]
```

Compatibility rule:

```text
If target.processor exists and target.subagent is missing:
  keep current behavior.

If both target.processor and target.subagent exist:
  use processor as middleware and execute subagent through selected mode.
```

Acceptance:

```text
existing triggers still parse
new freechat trigger shape parses
old processor-only tests still pass
```

### Step 2. Add Subagent Capability Registry Fields

Status: done.

Update `config/capabilities.yaml`:

```text
modes.freechat.subagents: [vocab, polisher]
subagents.vocab.execution_modes: [api, agentic]
subagents.vocab.default_execution_mode: api
subagents.vocab.tools.agentic: [...]
subagents.polisher.execution_modes: [api, agentic]
subagents.polisher.default_execution_mode: api
subagents.polisher.tools.agentic: [...]
```

Acceptance:

```text
registry documents mode -> subagent relation
registry documents subagent -> tool relation
```

### Step 3. Split Processor Into Middleware Interface

Status: done.

Add methods to `BaseDataProcessor` without breaking current processors:

```text
prepare_subagent_input(processed_batch, *, mode, tools, context) -> str
parse_subagent_output(raw_output) -> list[OutputSchema]
```

Default behavior:

```text
prepare_subagent_input uses build_user_prompt()
parse_subagent_output uses parse_llm_output()
```

This keeps current processor subclasses working while giving the runtime a middleware boundary.

Acceptance:

```text
vocab and polisher can prepare compact subagent input
existing process_all/aprocess_all behavior still works
```

### Step 4. Implement API Mode Runtime

Status: done.

For phase 1, API mode should be a constrained subagent call, not a full tool loop.

Runtime:

```text
processor prepares compact input
runtime loads subagent prompt
runtime calls provider.chat_with_retry()
processor parses returned output
processor persists artifact
```

Important distinction:

```text
The LLM call is still lightweight,
but the task is now identified as a subagent execution in config and monitor.
```

Acceptance:

```text
freechat_vocab with execution_mode=api produces vocab.jsonl
freechat_polisher with execution_mode=api produces polisher.jsonl
processor_runs.jsonl records middleware run
subagent_runs.jsonl or an equivalent subagent execution log records api-mode subagent call
webui toast shows processor + subagent/api task status
```

### Step 5. Implement Minimal Agentic Mode Runtime

Status: done.

For phase 1, agentic mode should use the existing Nanobot subagent runtime, with both a restricted prompt and a hard runtime tool allowlist.

Runtime:

```text
processor prepares compact input
runtime loads subagent prompt
runtime adds tool manifest and compact input
runtime filters ToolRegistry to the configured tool list
runtime spawn subagent
runtime waits for result
processor parses result
processor persists artifact
```

Tool implementations can start read-only:

```text
thread_query:
read recent user turns from persona/events/thread.jsonl

artifact_read:
read processor artifacts such as vocab.jsonl and polisher.jsonl

user_profile:
read persona/memory/MEMORY.md or future user profile file

wiki_query:
query local LLM Wiki index
```

Current implementation:

```text
bot/nanobot/agent/tools/subagent_context.py
  thread_query
  artifact_read
  user_profile
  wiki_query

bot/nanobot/agent/tools/registry.py
  ToolRegistry.filtered()

bot/nanobot/agent/subagent.py
  spawn(..., allowed_tools=[...])
```

Acceptance:

```text
freechat_vocab execution_mode=agentic spawns a visible subagent
subagent status appears in webui toast
subagent run appears in monitor
processor still controls final artifact write
tools are scoped to the configured tool list
```

### Step 6. Rewrite Vocab Prompt Contract

Status: done.

Update vocab prompt so it focuses only on lexical resource.

Vocab should extract:

```text
stronger word choices
topic-specific vocabulary
collocations
phrases
idiomatic but appropriate expressions
overused generic words
```

Vocab should avoid:

```text
grammar correction
sentence restructuring
full answer rewriting
fluency scoring
```

Output contract:

```text
original<TAB>improved<TAB>type<TAB>reason
```

Types:

```text
word_choice
collocation
phrase
topic_vocabulary
idiom
register
```

Acceptance:

```text
vocab output maps cleanly to VocabOutput schema
vocab examples do not correct grammar or sentence structure
```

### Step 7. Rewrite Polisher Prompt Contract

Status: done.

Update polisher prompt so it focuses on expression quality.

Polisher should improve:

```text
grammar
sentence structure
word order
natural phrasing
fluency
coherence
spoken English clarity
```

Polisher may include vocabulary changes only when they are part of a sentence-level rewrite.

Output contract:

```text
original<TAB>improved<TAB>grammar_type<TAB>explanation
```

Types:

```text
grammar
sentence_structure
word_order
tense
article
preposition
natural_expression
coherence
other
```

Acceptance:

```text
polisher output maps cleanly to PolisherOutput schema
polisher examples include grammar/sentence improvements, not isolated vocabulary lists
```

### Step 8. Update Freechat Trigger Config

Status: done.

Change the two first freechat triggers:

```text
freechat_vocab_processor -> freechat_vocab
freechat_polisher_processor -> freechat_polisher
```

Initial defaults:

```text
count: 1 for testing
execution_mode: api
agentic: false
tools: []
model: deepseek-v4-flash
```

Keep dependent triggers stable where possible:

```text
notes/review/quiz dependencies should reference the new trigger ids or use a compatibility alias.
```

Acceptance:

```text
one new user reply can trigger vocab
polisher can trigger independently or after vocab, depending on final dependency decision
monitor shows clear trigger decisions
```

### Step 9. Observability

Status: done.

Add monitor visibility for processor-mediated subagent execution.

Minimum logs:

```text
processor_runs.jsonl:
  trigger_id
  processor
  subagent
  execution_mode
  tools
  input_rows
  output_rows
  status

subagent_runs.jsonl or new subagent_execution_runs.jsonl:
  trigger_id
  subagent
  execution_mode
  model
  tools
  status
  raw_output_preview
```

WebUI:

```text
toast shows:
  vocab middleware running
  vocab subagent api/agentic running
  vocab completed

monitor shows:
  trigger decision
  processor run
  subagent execution details
```

Acceptance:

```text
user can tell whether vocab/polisher was not triggered, triggered but skipped, API-mode completed, or agentic-mode spawned
```

### Step 10. Tests

Status: done.

Backend tests:

```text
trigger target parses new fields
processor-only backward compatibility still works
api mode writes vocab artifact
api mode writes polisher artifact
agentic mode uses configured tool allowlist
no old artifact rows are reprocessed twice
processor/subagent monitor logs are written
```

Frontend tests:

```text
processor toast still renders
subagent/api status event renders
monitor displays execution_mode/tools
```

Acceptance:

```text
uv run pytest targeted tests pass
bun run check passes
```

## Suggested Commit Split

1. Config/schema support for middleware-gated subagent targets.
2. Base processor middleware interface.
3. API mode runtime for freechat vocab/polisher.
4. Minimal agentic mode runtime and tool manifest.
5. Prompt cleanup for vocab and polisher.
6. Monitor/WebUI observability.
7. Tests and docs.

## Main Risks

### Risk 1. Subagent Output Becomes Less Stable

Mitigation:

```text
processor remains the only writer
processor validates schema
bad output is logged but not persisted
```

### Risk 2. Agentic Mode Costs Too Much

Mitigation:

```text
api mode remains default
agentic mode is explicit per trigger
tool results are capped and summarized
```

### Risk 3. Tool Access Becomes Too Broad

Mitigation:

```text
tools are allowlisted per subagent
phase 1 tools are read-only
external_search is out of scope
```

### Risk 4. Existing Processor Chains Break

Mitigation:

```text
keep processor-only compatibility
update dependencies carefully
run processor cursor tests
```

## Phase 1 Done Means

Phase 1 is complete when:

```text
freechat vocab and polisher are configured as middleware-gated subagents
api mode works by default
agentic mode can be enabled by config
processor still handles filtering, parsing, cursor, and artifact writing
subagent/tool relation is visible in registry/config
monitor and webui make the execution path visible
tests pass
```
