# Tool Usage

## Available Tools

### File Operations
- `read_file` — Read article pairs, session notes, progress files
- `write_file` — Save benative_responses.jsonl, benative_review.md
- `edit_file` — Update benative_progress.json
- `list_files` — List available articles in persona/benative/articles/

### Session Management
- Standard nanobot session tools

## Session Notes Structure

### benative_responses.jsonl
```jsonl
{"turn": 1, "zh": "中国的外交政策一直致力于维护世界和平。", "user_en": "China's foreign policy has always been...", "timestamp": "2026-05-21T10:00:00Z"}
```

### benative_progress.json
```json
{"article_id": "abc123", "current_sentence": 10, "total_sentences": 123, "started_at": "2026-05-21T10:00:00Z"}
```

### benative_review.md
Markdown review output from review_subagent.
