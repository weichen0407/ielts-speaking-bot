"""Subagent Token Optimization Analysis.

Comprehensive test covering ALL subagent business scenarios.
Tests two optimization points:
1. Processor reduces input tokens
2. Hyphenated text replaces JSON output

Usage:
    cd bot
    uv run python tests/interview/reduce-token/test_subagent_token_analysis.py
"""

import json
from pathlib import Path

import pytest
import tiktoken

# Initialize tokenizer
try:
    enc = tiktoken.encoding_for_model("gpt-4o")
except:
    enc = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Count tokens using tiktoken."""
    return len(enc.encode(text))


# =============================================================================
# OPTIMIZATION 1: Processor Reduces Input Tokens
# =============================================================================

def simulate_raw_conversation(role: str = "user", content: str = "") -> str:
    """Create a raw JSON message (simulates thread.jsonl format)."""
    msg = {
        "role": role,
        "content": content,
        "timestamp": "2024-01-01T10:00:00Z",
        "message_id": "msg_001",
        "channel": "websocket",
    }
    return json.dumps(msg, ensure_ascii=False)


def create_raw_thread_jsonl(messages: list[dict]) -> str:
    """Create raw thread.jsonl (actual Session.message schema).

    Actual schema from Session.add_message():
    {
        "role": str,
        "content": str,
        "timestamp": str,  # ISO format from datetime.now().isoformat()
        **kwargs  # optional extra fields
    }
    """
    lines = []
    for msg in messages:
        # Follow actual Session.message schema
        jsonl_msg = {
            "role": msg["role"],
            "content": msg["content"],
            "timestamp": "2024-01-01T10:00:00.000000",  # ISO format
        }
        lines.append(json.dumps(jsonl_msg, ensure_ascii=False))
    return "\n".join(lines)


def process_user_only(messages: list[dict]) -> str:
    """Processor: Extract only user responses (with separators)."""
    user_contents = [msg["content"] for msg in messages if msg["role"] == "user"]
    return "\n\n---\n\n".join(user_contents)


def process_user_with_examiner(messages: list[dict]) -> str:
    """Processor: Extract user responses + examiner questions (for IELTS Score)."""
    parts = []
    for msg in messages:
        if msg["role"] == "user":
            parts.append(f"CANDIDATE: {msg['content']}")
        elif msg["role"] == "assistant":
            parts.append(f"EXAMINER: {msg['content']}")
    return "\n\n---\n\n".join(parts)


# =============================================================================
# OPTIMIZATION 2: Hyphenated Text Replaces JSON Output
# =============================================================================

def format_as_json(data: dict) -> str:
    """Traditional JSON output format."""
    return json.dumps(data, indent=2, ensure_ascii=False)


def format_as_hyphenated(data: dict) -> str:
    """Hyphenated text format (no JSON overhead).

    Example:
        Fluency: 7.0 - Lexical Resource: 6.5 - Grammar: 7.0 - Pronunciation: 6.5
        Overall Band Score: 6.5

    Args:
        data: Dictionary with scoring results

    Returns:
        Hyphenated string
    """
    parts = []
    for key, value in data.items():
        if key == "overall_band":
            parts.append(f"Overall Band Score: {value}")
        else:
            # Convert camelCase to Title Case
            title = key.replace("_", " ").title()
            parts.append(f"{title}: {value}")
    return " - ".join(parts)


# =============================================================================
# TEST SCENARIOS: All Business Scenarios
# =============================================================================

def create_ielts_conversation() -> list[dict]:
    """Create realistic IELTS speaking exam conversation."""
    return [
        {"role": "assistant", "content": "Hello, I'm your IELTS examiner. Let's start with a few questions about yourself."},
        {"role": "user", "content": "Hello, my name is John and I'm from Beijing, China. I work as a software engineer at a tech company."},
        {"role": "assistant", "content": "Do you have a pet?"},
        {"role": "user", "content": "Yes, I have a golden retriever named Max. He's three years old and very friendly. I got him when I was in university, and he's been my companion ever since."},
        {"role": "assistant", "content": "What is a popular pet in your country?"},
        {"role": "user", "content": "In China, dogs and cats are very popular. Recently, cats have become especially popular among young people in apartments because they're easy to care for."},
        {"role": "assistant", "content": "Now let me give you a topic card. Describe an interesting animal."},
        {"role": "user", "content": "I'd like to talk about the giant panda. Pandas are one of the most beloved animals. I first learned about them watching nature documentaries. I would like to see them in their natural habitat in Sichuan Province."},
        {"role": "assistant", "content": "How can the elderly benefit from having a pet?"},
        {"role": "user", "content": "Pets provide companionship and reduce loneliness. They give elderly people a sense of purpose. Studies show pet owners have lower blood pressure and better mental health."},
        {"role": "assistant", "content": "Should the government protect wild animals?"},
        {"role": "user", "content": "Absolutely. First, biodiversity is crucial for ecosystem balance. Second, many species face threats from habitat loss. Third, protecting animals is our moral responsibility."},
    ]


def create_vocabulary_conversation() -> list[dict]:
    """Create conversation for vocabulary analysis."""
    return [
        {"role": "assistant", "content": "Tell me about your hometown."},
        {"role": "user", "content": "My hometown is a beautiful coastal city in southern China. The weather is mild and pleasant most of the year. I grew up near the beach and spent many weekends exploring tide pools and collecting seashells."},
        {"role": "assistant", "content": "That's wonderful! What do you do for work?"},
        {"role": "user", "content": "I'm a software developer specializing in artificial intelligence applications. I find the field fascinating because it combines mathematical principles with creative problem-solving. My work involves developing machine learning models that can understand and process natural language."},
    ]


def create_grammar_conversation() -> list[dict]:
    """Create conversation for grammar polishing."""
    return [
        {"role": "assistant", "content": "What did you do last weekend?"},
        {"role": "user", "content": "Last weekend I went to the mountains with my friends. We have been planning this trip for several weeks. When we arrived at the cabin, we realized we forgot to bring the food. So we had to drive back to the nearest town to buy some supplies."},
        {"role": "assistant", "content": "That sounds like quite an adventure!"},
        {"role": "user", "content": "It was! Although we were frustrated at first, looking back it was actually quite funny. We have learned to be more careful with our packing in the future."},
    ]


def create_notes_conversation() -> list[dict]:
    """Create conversation for notes AI."""
    return [
        {"role": "assistant", "content": "Let's discuss your travel experiences."},
        {"role": "user", "content": "I have traveled to several countries in Asia including Japan, Korea, Thailand, and Singapore. Each destination offered unique cultural experiences. In Japan, I was impressed by the efficient public transportation system and the respectful manner in which people interact with each other."},
        {"role": "assistant", "content": "What was your favorite destination?"},
        {"role": "user", "content": "Japan is definitely my favorite so far. The combination of ancient traditions and modern technology creates a fascinating atmosphere. I especially enjoyed visiting the ancient temples in Kyoto and experiencing a traditional tea ceremony."},
    ]


# =============================================================================
# TEST CLASSES
# =============================================================================

class TestInputOptimization:
    """Test Optimization 1: Processor reduces input tokens."""

    def test_ielts_score_with_examiner_questions(self):
        """IELTS Score: Include examiner questions (user requirement).

        This is the recommended approach for IELTS scoring as examiner
        questions provide context for evaluating answers.
        """
        messages = create_ielts_conversation()
        raw_jsonl = create_raw_thread_jsonl(messages)
        processed = process_user_with_examiner(messages)

        raw_tokens = count_tokens(raw_jsonl)
        processed_tokens = count_tokens(processed)
        saved = raw_tokens - processed_tokens
        savings_pct = (saved / raw_tokens * 100) if raw_tokens > 0 else 0

        print(f"\n  IELTS Score (with examiner questions):")
        print(f"    Raw: {raw_tokens} tokens")
        print(f"    Processed: {processed_tokens} tokens")
        print(f"    Saved: {saved} tokens ({savings_pct:.1f}%)")

        assert savings_pct > 0, "Should save tokens"

    def test_vocabulary_processor(self):
        """Vocabulary: User responses only."""
        messages = create_vocabulary_conversation()
        raw_jsonl = create_raw_thread_jsonl(messages)
        processed = process_user_only(messages)

        raw_tokens = count_tokens(raw_jsonl)
        processed_tokens = count_tokens(processed)
        saved = raw_tokens - processed_tokens
        savings_pct = (saved / raw_tokens * 100) if raw_tokens > 0 else 0

        print(f"\n  Vocabulary Processor:")
        print(f"    Raw: {raw_tokens} tokens")
        print(f"    Processed: {processed_tokens} tokens")
        print(f"    Saved: {saved} tokens ({savings_pct:.1f}%)")

        assert savings_pct > 0, "Should save tokens"

    def test_grammar_processor(self):
        """Grammar Polisher: User responses only."""
        messages = create_grammar_conversation()
        raw_jsonl = create_raw_thread_jsonl(messages)
        processed = process_user_only(messages)

        raw_tokens = count_tokens(raw_jsonl)
        processed_tokens = count_tokens(processed)
        saved = raw_tokens - processed_tokens
        savings_pct = (saved / raw_tokens * 100) if raw_tokens > 0 else 0

        print(f"\n  Grammar Polisher:")
        print(f"    Raw: {raw_tokens} tokens")
        print(f"    Processed: {processed_tokens} tokens")
        print(f"    Saved: {saved} tokens ({savings_pct:.1f}%)")

        assert savings_pct > 0, "Should save tokens"

    def test_notes_ai_processor(self):
        """Notes AI: User responses with examiner context."""
        messages = create_notes_conversation()
        raw_jsonl = create_raw_thread_jsonl(messages)
        processed = process_user_with_examiner(messages)

        raw_tokens = count_tokens(raw_jsonl)
        processed_tokens = count_tokens(processed)
        saved = raw_tokens - processed_tokens
        savings_pct = (saved / raw_tokens * 100) if raw_tokens > 0 else 0

        print(f"\n  Notes AI (with examiner context):")
        print(f"    Raw: {raw_tokens} tokens")
        print(f"    Processed: {processed_tokens} tokens")
        print(f"    Saved: {saved} tokens ({savings_pct:.1f}%)")

        assert savings_pct > 0, "Should save tokens"


class TestOutputOptimization:
    """Test Optimization 2: Hyphenated text replaces JSON output."""

    def test_ielts_score_output(self):
        """IELTS Score: Compare JSON vs Hyphenated output."""
        score_data = {
            "fluency": 7.0,
            "lexical_resource": 6.5,
            "grammar": 7.0,
            "pronunciation": 6.5,
            "overall_band": 6.75,
        }

        json_output = format_as_json(score_data)
        hyphenated_output = format_as_hyphenated(score_data)

        json_tokens = count_tokens(json_output)
        hyphenated_tokens = count_tokens(hyphenated_output)
        saved = json_tokens - hyphenated_tokens
        savings_pct = (saved / json_tokens * 100) if json_tokens > 0 else 0

        print(f"\n  IELTS Score Output Format:")
        print(f"    JSON: {json_tokens} tokens")
        print(f"    Hyphenated: {hyphenated_tokens} tokens")
        print(f"    Saved: {saved} tokens ({savings_pct:.1f}%)")
        print(f"    JSON preview: {json_output[:80]}...")
        print(f"    Hyphenated: {hyphenated_output}")

        assert savings_pct > 0, "Hyphenated should use fewer tokens"

    def test_vocabulary_output(self):
        """Vocabulary: Compare JSON vs Hyphenated output."""
        vocab_data = {
            "words": ["mild", "tide pools", "seashells", "fascinating"],
            "count": 4,
            "difficulty": "intermediate",
        }

        json_output = format_as_json(vocab_data)
        hyphenated_output = f"Words: {', '.join(vocab_data['words'])} - Count: {vocab_data['count']} - Difficulty: {vocab_data['difficulty']}"

        json_tokens = count_tokens(json_output)
        hyphenated_tokens = count_tokens(hyphenated_output)
        saved = json_tokens - hyphenated_tokens
        savings_pct = (saved / json_tokens * 100) if json_tokens > 0 else 0

        print(f"\n  Vocabulary Output Format:")
        print(f"    JSON: {json_tokens} tokens")
        print(f"    Hyphenated: {hyphenated_tokens} tokens")
        print(f"    Saved: {saved} tokens ({savings_pct:.1f}%)")

        assert savings_pct > 0, "Hyphenated should use fewer tokens"

    def test_progress_output(self):
        """Progress Tracker: Compare JSON vs Hyphenated output."""
        progress_data = {
            "total_sessions": 25,
            "average_band": 6.2,
            "weakest_area": "pronunciation",
            "strongest_area": "fluency",
        }

        json_output = format_as_json(progress_data)
        hyphenated_output = format_as_hyphenated(progress_data)

        json_tokens = count_tokens(json_output)
        hyphenated_tokens = count_tokens(hyphenated_output)
        saved = json_tokens - hyphenated_tokens
        savings_pct = (saved / json_tokens * 100) if json_tokens > 0 else 0

        print(f"\n  Progress Tracker Output Format:")
        print(f"    JSON: {json_tokens} tokens")
        print(f"    Hyphenated: {hyphenated_tokens} tokens")
        print(f"    Saved: {saved} tokens ({savings_pct:.1f}%)")

        assert savings_pct > 0, "Hyphenated should use fewer tokens"


class TestComprehensiveAnalysis:
    """Comprehensive analysis across all scenarios."""

    def test_all_scenarios_input_savings(self):
        """Test input optimization across all business scenarios."""
        scenarios = [
            ("IELTS Score", create_ielts_conversation(), "user_with_examiner"),
            ("Vocabulary", create_vocabulary_conversation(), "user_only"),
            ("Grammar", create_grammar_conversation(), "user_only"),
            ("Notes AI", create_notes_conversation(), "user_with_examiner"),
        ]

        print("\n" + "=" * 70)
        print("INPUT OPTIMIZATION: Processor Token Savings (All Scenarios)")
        print("=" * 70)
        print(f"\n{'Scenario':<20} {'Raw':>10} {'Processed':>12} {'Saved':>10} {'Rate':>8}")
        print("-" * 70)

        total_raw = 0
        total_processed = 0

        for name, messages, processor_type in scenarios:
            raw_jsonl = create_raw_thread_jsonl(messages)
            if processor_type == "user_only":
                processed = process_user_only(messages)
            else:
                processed = process_user_with_examiner(messages)

            raw_t = count_tokens(raw_jsonl)
            proc_t = count_tokens(processed)
            saved = raw_t - proc_t
            rate = (saved / raw_t * 100) if raw_t > 0 else 0

            total_raw += raw_t
            total_processed += proc_t

            print(f"{name:<20} {raw_t:>10,} {proc_t:>12,} {saved:>10,} {rate:>7.1f}%")

        total_saved = total_raw - total_processed
        total_rate = (total_saved / total_raw * 100) if total_raw > 0 else 0
        print("-" * 70)
        print(f"{'TOTAL':<20} {total_raw:>10,} {total_processed:>12,} {total_saved:>10,} {total_rate:>7.1f}%")
        print()

    def test_all_scenarios_output_savings(self):
        """Test output optimization across all business scenarios."""
        scenarios = [
            ("IELTS Score", {"fluency": 7.0, "lexical_resource": 6.5, "grammar": 7.0, "pronunciation": 6.5, "overall_band": 6.75}),
            ("Vocabulary", {"words": ["mild", "tide pools"], "count": 2, "difficulty": "intermediate"}),
            ("Progress", {"total_sessions": 25, "average_band": 6.2}),
        ]

        print("\n" + "=" * 70)
        print("OUTPUT OPTIMIZATION: Hyphenated vs JSON (All Scenarios)")
        print("=" * 70)
        print(f"\n{'Scenario':<20} {'JSON':>10} {'Hyphenated':>12} {'Saved':>10} {'Rate':>8}")
        print("-" * 70)

        total_json = 0
        total_hyphenated = 0

        for name, data in scenarios:
            json_out = format_as_json(data)
            hyphenated_out = format_as_hyphenated(data)

            json_t = count_tokens(json_out)
            hyphenated_t = count_tokens(hyphenated_out)
            saved = json_t - hyphenated_t
            rate = (saved / json_t * 100) if json_t > 0 else 0

            total_json += json_t
            total_hyphenated += hyphenated_t

            print(f"{name:<20} {json_t:>10,} {hyphenated_t:>12,} {saved:>10,} {rate:>7.1f}%")

        total_saved = total_json - total_hyphenated
        total_rate = (total_saved / total_json * 100) if total_json > 0 else 0
        print("-" * 70)
        print(f"{'TOTAL':<20} {total_json:>10,} {total_hyphenated:>12,} {total_saved:>10,} {total_rate:>7.1f}%")
        print()

    def test_combined_optimization(self):
        """Test combined input + output optimization."""
        print("\n" + "=" * 70)
        print("COMBINED OPTIMIZATION: Input + Output")
        print("=" * 70)

        # IELTS Score scenario
        messages = create_ielts_conversation()
        raw_jsonl = create_raw_thread_jsonl(messages)
        processed = process_user_with_examiner(messages)

        score_data = {
            "fluency": 7.0, "lexical_resource": 6.5, "grammar": 7.0,
            "pronunciation": 6.5, "overall_band": 6.75,
        }

        # Scenario A: No optimization (raw input + JSON output)
        raw_input_tokens = count_tokens(raw_jsonl)
        json_output_tokens = count_tokens(format_as_json(score_data))
        total_no_opt = raw_input_tokens + json_output_tokens

        # Scenario B: Full optimization (processed input + hyphenated output)
        processed_input_tokens = count_tokens(processed)
        hyphenated_output_tokens = count_tokens(format_as_hyphenated(score_data))
        total_full_opt = processed_input_tokens + hyphenated_output_tokens

        # Scenario C: Partial optimization (processed input only)
        total_input_only = processed_input_tokens + json_output_tokens

        # Scenario D: Partial optimization (output only)
        total_output_only = raw_input_tokens + hyphenated_output_tokens

        print(f"""
  IELTS Score Example:

  ┌─────────────────────────────────────────────────────────────────┐
  │  Scenario A (No optimization):                                   │
  │    Input (raw JSONL): {raw_input_tokens:>6,} tokens                          │
  │    Output (JSON):      {json_output_tokens:>6,} tokens                          │
  │    TOTAL:              {total_no_opt:>6,} tokens                          │
  ├─────────────────────────────────────────────────────────────────┤
  │  Scenario B (Full optimization):                                 │
  │    Input (processed):  {processed_input_tokens:>6,} tokens                          │
  │    Output (hyphenated): {hyphenated_output_tokens:>6,} tokens                          │
  │    TOTAL:              {total_full_opt:>6,} tokens                          │
  ├─────────────────────────────────────────────────────────────────┤
  │  Scenario C (Input only):                                        │
  │    Input (processed):  {processed_input_tokens:>6,} tokens                          │
  │    Output (JSON):      {json_output_tokens:>6,} tokens                          │
  │    TOTAL:              {total_input_only:>6,} tokens                          │
  ├─────────────────────────────────────────────────────────────────┤
  │  Scenario D (Output only):                                       │
  │    Input (raw JSONL): {raw_input_tokens:>6,} tokens                          │
  │    Output (hyphenated): {hyphenated_output_tokens:>6,} tokens                          │
  │    TOTAL:              {total_output_only:>6,} tokens                          │
  └─────────────────────────────────────────────────────────────────┘

  Savings vs No Optimization:
    Full optimization (B): {total_no_opt - total_full_opt:>6} tokens saved ({(total_no_opt - total_full_opt) / total_no_opt * 100:.1f}%)
    Input only (C):       {total_no_opt - total_input_only:>6} tokens saved ({(total_no_opt - total_input_only) / total_no_opt * 100:.1f}%)
    Output only (D):      {total_no_opt - total_output_only:>6} tokens saved ({(total_no_opt - total_output_only) / total_no_opt * 100:.1f}%)
""")


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("SUBAGENT TOKEN OPTIMIZATION ANALYSIS")
    print("=" * 70)

    pytest.main([__file__, "-v", "--tb=short"])
