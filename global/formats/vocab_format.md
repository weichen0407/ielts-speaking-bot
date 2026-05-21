# Vocabulary Output Format

Write your vocabulary suggestions to `{session_dir}/notes/vocab.md` in this format:

```markdown
# Vocabulary Suggestions

## Session: [Topic]

### Words That Can Be Optimized

| Your Word | Better Alternative | Why |
|-----------|-------------------|-----|
| important | crucial, significant | More precise, formal |
| good | excellent, outstanding | More impactful |
| many | numerous, substantial | Academic tone |

### Professional Vocabulary by Topic

#### [Topic]
- **word** (type): definition
  - Usage: "example sentence..."

### Useful Linking Phrases
- "There's no denying that..."
- "From my perspective..."
- "It seems to me that..."

### Collocations to Remember
- **make** a decision / progress / an effort
- **take** into account / advantage / action
```

## Instructions

1. Read: `{session_dir}/thread.jsonl` (conversation history)
2. Read: `{session_dir}/notes/vocab.md` (existing notes to append to)
3. Write: `{session_dir}/notes/vocab.md` (your new analysis)

## Rules

- Use write_file tool to write the complete file
- APPEND to existing content, don't overwrite without reading first
- Focus on IELTS speaking context
- Suggest 3-5 key vocabulary improvements per update
- Focus on words that appear frequently or are high-impact
- Skip basic words (good, bad, important) unless there's a better alternative
