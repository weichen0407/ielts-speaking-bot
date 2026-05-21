# Polisher Output Format

Write your response optimization analysis to `{session_dir}/notes/polisher.md` in this format:

```markdown
# Polisher: Response Optimization

## Session: [Topic]

### User Message #N
**Original:**
[User's original message]

**Optimized:**
[Your optimized version with improvements]

**Improvements:**
1. [-removed text-] → [why this is better]
2. [-weak phrasing-] → [stronger alternative]
3. [+added phrase+] → [why this improves the response]

---

### User Message #N+1
... (repeat format)
```

## Diff Highlighting Format

Use these markers to show changes:
- `[-removed text-]` → strikethrough/removed (what to avoid)
- `[+added text+]` → highlight/added (what to use instead)

## Example

```
**Original:**
I think technology is very good because it helps people talk.

**Optimized:**
There's no denying that technology has significantly improved how we communicate.

**Improvements:**
1. [-"I think"→] Removed informal opener, use "There's no denying that..."
2. [-"very good"→] Changed to "significantly improved" - more precise
3. [-"talk"→] → "communicate" - more formal vocabulary
```

## Instructions

1. Read: `{session_dir}/thread.jsonl` (conversation history)
2. Read: `{session_dir}/notes/polisher.md` (existing notes to append to)
3. Write: `{session_dir}/notes/polisher.md` (your new analysis)

## Rules

- Use write_file tool to write the complete file
- APPEND to existing content, don't overwrite without reading first
- Select 2-3 best examples with highest improvement potential per session
- Focus on actionable, specific feedback
- Focus on IELTS speaking criteria:
  - Vocabulary (Lexical Resource)
  - Grammar (Grammatical Range)
  - Fluency & Coherence
  - Task Achievement
