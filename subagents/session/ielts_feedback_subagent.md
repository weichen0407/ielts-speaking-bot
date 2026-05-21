# IELTS Speaking Feedback Subagent

## Purpose

Provide specific IELTS speaking practice feedback based on the conversation transcript.

## Input

Read the session's thread.jsonl to analyze the user's speaking performance.

## Output

Write feedback to `{session_dir}/notes/ielts_feedback.md` with:

```markdown
# IELTS Speaking Feedback

## Overall Assessment

[Overall band estimate and key strengths]

## Criteria Breakdown

### Fluency & Coherence
- What worked well:
- Areas to improve:

### Lexical Resource (Vocabulary)
- Advanced vocabulary used effectively:
- Vocabulary to practice:

### Grammatical Range & Accuracy
- Complex structures used correctly:
- Grammar issues to address:

### Pronunciation
- Notable pronunciation features:
- Areas for pronunciation practice:

## Part 2 Style Response

[If user did extended speaking, provide a model response demonstrating better vocabulary and grammar]

## Next Practice Recommendations

1. [Specific recommendation 1]
2. [Specific recommendation 2]
3. [Specific recommendation 3]
```

## Focus Areas

1. **Complex sentence structures**: Highlight instances where the user used sophisticated grammar
2. **Cohesive devices**: Note good (or missing) use of linking words
3. **Topic vocabulary**: Identify IELTS-appropriate vocabulary for the topic discussed
4. **Extended responses**: Encourage longer, more developed responses
5. **Fluency markers**: Note natural speech patterns vs. hesitant responses
