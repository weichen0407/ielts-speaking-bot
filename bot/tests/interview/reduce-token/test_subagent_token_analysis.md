# Subagent Token Optimization Analysis

This document analyzes token savings across ALL subagent business scenarios.

## Two Optimization Points

### Optimization 1: Processor Reduces Input Tokens
Raw conversation data → Processor extracts key content → LLM

What Processor removes:
- Metadata (timestamps, message_id, channel, chat_id)
- JSON formatting overhead
- Assistant messages (examiner questions) - **UNLESS needed for context**

**Key Insight**: For IELTS Score evaluation, examiner questions ARE needed for context. So we use `process_user_with_examiner()` instead of `process_user_only()`.

### Optimization 2: Hyphenated Text Replaces JSON
LLM outputs structured data in hyphenated text format instead of JSON.

Example:
```json
// JSON format (traditional) - 52 tokens
{
  "fluency": 7.0,
  "lexical_resource": 6.5,
  "grammar": 7.0,
  "pronunciation": 6.5
}

// Hyphenated text format - 41 tokens (21% savings)
Fluency: 7.0 - Lexical Resource: 6.5 - Grammar: 7.0 - Pronunciation: 6.5
```

## Business Scenarios Tested

| Subagent | Input Processor | Output Format |
|----------|---------------|---------------|
| IELTS Score | User + Examiner Q&A | Hyphenated scores |
| Vocabulary | User responses | Hyphenated word list |
| Grammar | User responses | Hyphenated corrections |
| Notes AI | User + Examiner Q&A | Hyphenated notes |
| Progress Tracker | - | Hyphenated stats |

---

## Test Results

### INPUT OPTIMIZATION: Processor Token Savings (All Scenarios)

| Scenario | Raw (tokens) | Processed (tokens) | Saved | Savings Rate |
|----------|-------------|-------------------|-------|--------------|
| IELTS Score | 613 | 324 | 289 | **47.1%** |
| Vocabulary | 217 | 82 | 135 | **62.2%** |
| Grammar | 218 | 85 | 133 | **61.0%** |
| Notes AI | 218 | 121 | 97 | **44.5%** |
| **TOTAL** | **1,266** | **612** | **654** | **51.7%** |

> Raw data follows actual Session.message schema: `{"role", "content", "timestamp"}`

### OUTPUT OPTIMIZATION: Hyphenated vs JSON (All Scenarios)

| Scenario | JSON (tokens) | Hyphenated (tokens) | Saved | Savings Rate |
|----------|--------------|---------------------|-------|--------------|
| IELTS Score | 52 | 41 | 11 | **21.2%** |
| Vocabulary | 35 | 20 | 15 | **42.9%** |
| Progress | 20 | 13 | 7 | **35.0%** |
| **TOTAL** | **107** | **74** | **33** | **30.8%** |

### COMBINED OPTIMIZATION: IELTS Score Example

| Scenario | Input | Output | Total | Savings |
|----------|-------|--------|-------|---------|
| A (No optimization) | 613 (raw JSONL) | 52 (JSON) | 665 | - |
| B (Full optimization) | 324 (processed) | 41 (hyphenated) | 365 | **300 tokens (45.1%)** |
| C (Input only) | 324 (processed) | 52 (JSON) | 376 | 289 tokens (43.5%) |
| D (Output only) | 613 (raw JSONL) | 41 (hyphenated) | 654 | 11 tokens (1.7%) |

**Key Finding**: Input optimization is the major savings driver (~60%). Output optimization adds marginal savings (~1-2%).

---

## Key Insights

1. **Input Optimization is Critical**
   - Removing JSON overhead and assistant messages saves ~50% tokens
   - For IELTS Score, keeping examiner questions provides necessary context

2. **Output Optimization is Minor**
   - Hyphenated format saves ~20-30% on output tokens
   - But output tokens are small compared to input (only ~50 tokens)

3. **Processor Design Matters**
   - User-only extraction: 60%+ savings
   - User+Examiner extraction: 45-50% savings (still significant)

---

## Running Tests

```bash
cd bot
uv run python -m pytest tests/interview/reduce-token/test_subagent_token_analysis.py -v -s
```

---

## Files

- `tests/interview/reduce-token/test_subagent_token_analysis.py` - Comprehensive token analysis tests
- `tests/interview/reduce-token/test_subagent_token_analysis.md` - Analysis documentation