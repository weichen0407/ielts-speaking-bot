# Daily Summary Format

JSON structure for `daily/daily_{date}.md` files.

## File Location

```
persona/daily/
  daily_2026-05-21.md
  daily_2026-05-20.md
  daily.md  (latest summary)
```

## JSON Schema

```json
{
  "date": "YYYY-MM-DD",
  "generated_at": "ISO timestamp",
  "vocabulary": {
    "new_words": [
      {
        "session": "session_uuid",
        "topic": "Topic Name",
        "word": "the vocabulary word or phrase",
        "context": "Original phrase from user's conversation",
        "notes": "How to practice or notes"
      }
    ],
    "topic_distribution": {
      "Topic Name": count,
      ...
    }
  },
  "grammar_patterns": {
    "issues_observed": [
      {
        "session": "session_uuid",
        "issue": "short description of issue",
        "example": "original text",
        "correction": "corrected text",
        "frequency": number
      }
    ]
  },
  "polish_suggestions": [
    {
      "session": "session_uuid",
      "topic": "Topic Name",
      "original": "original user text",
      "polished": "improved version",
      "focus": "what was changed"
    }
  ],
  "stats": {
    "total_sessions": number,
    "total_messages": number,
    "new_vocabulary_items": number,
    "grammar_issues_flagged": number
  }
}
```

## Fields

### date
- Date of the summary (YYYY-MM-DD format)

### generated_at
- ISO 8601 timestamp when summary was generated

### vocabulary.new_words
- Array of new vocabulary items learned/practiced
- Each entry links to session for context

### vocabulary.topic_distribution
- Count of vocabulary items per topic
- Shows which topics were most discussed

### grammar_patterns.issues_observed
- Grammar issues noticed in user speech
- frequency shows how often the issue occurred

### polish_suggestions
- Original vs polished versions of user expressions
- Shows concrete improvements

### stats
- Aggregate statistics for the day
