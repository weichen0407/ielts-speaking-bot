"""Test script for IELTS exam and score command handlers."""

import sys
import os
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch


def test_ielts_exam_command_random():
    """Test /ielts_exam random command flow."""
    print("\n" + "=" * 60)
    print("Testing /ielts_exam random command")
    print("=" * 60)

    # Mock the necessary components
    mock_session = MagicMock()
    mock_session.metadata = {}
    mock_session.key = "test_key"

    mock_loop = MagicMock()
    mock_loop.workspace = Path("/Users/jerry/Develop/ielts-speaking-bot")
    mock_loop.sessions = MagicMock()
    mock_loop.sessions.save = MagicMock()
    mock_loop.sessions.get_or_create = MagicMock(return_value=mock_session)

    mock_msg = MagicMock()
    mock_msg.channel = "websocket"
    mock_msg.chat_id = "test_chat"
    mock_msg.metadata = {}

    mock_ctx = MagicMock()
    mock_ctx.loop = mock_loop
    mock_ctx.msg = mock_msg
    mock_ctx.args = "random"
    mock_ctx.key = "test_key"

    # Import and test
    from nanobot.command.builtin import cmd_ielts_exam

    import asyncio
    result = asyncio.run(cmd_ielts_exam(mock_ctx))

    # After the command, ctx.msg.content should be the injected prompt
    # and ctx.msg.metadata should contain ielts_exam info
    print(f"Command returned: {result}")
    print(f"ctx.msg.content type: {type(mock_ctx.msg.content)}")
    print(f"ctx.msg.metadata: {mock_ctx.msg.metadata}")

    # The content should contain the topic
    if mock_ctx.msg.content:
        print(f"Prompt length: {len(mock_ctx.msg.content)} chars")
        print(f"Prompt preview: {mock_ctx.msg.content[:200]}...")
        assert "Part 1" in mock_ctx.msg.content or "IELTS" in mock_ctx.msg.content, "Prompt should contain IELTS content"
        print("✓ Prompt was injected correctly")
    else:
        print("✗ Prompt was not injected")

    if "ielts_exam" in mock_ctx.msg.metadata:
        print(f"✓ ielts_exam metadata: {mock_ctx.msg.metadata['ielts_exam']}")
    else:
        print("✗ ielts_exam metadata missing")

    print("✓ /ielts_exam random test completed")


def test_ielts_exam_command_topic_not_found():
    """Test /ielts_exam with non-existent topic."""
    print("\n" + "=" * 60)
    print("Testing /ielts_exam <invalid_topic> command")
    print("=" * 60)

    mock_session = MagicMock()
    mock_session.metadata = {}

    mock_loop = MagicMock()
    mock_loop.workspace = Path("/Users/jerry/Develop/ielts-speaking-bot")
    mock_loop.sessions = MagicMock()
    mock_loop.sessions.save = MagicMock()
    mock_loop.sessions.get_or_create = MagicMock(return_value=mock_session)

    mock_msg = MagicMock()
    mock_msg.channel = "websocket"
    mock_msg.chat_id = "test_chat"
    mock_msg.metadata = {}

    mock_ctx = MagicMock()
    mock_ctx.loop = mock_loop
    mock_ctx.msg = mock_msg
    mock_ctx.args = "99"  # Non-existent topic
    mock_ctx.key = "test_key"

    from nanobot.command.builtin import cmd_ielts_exam

    import asyncio
    result = asyncio.run(cmd_ielts_exam(mock_ctx))

    print(f"Command returned: {result}")
    if result and "not found" in result.content:
        print("✓ Topic not found message displayed correctly")
    elif result:
        print(f"Content: {result.content[:200]}")
    else:
        print("✗ No response returned")

    print("✓ /ielts_exam <invalid_topic> test completed")


def test_ielts_score_command_no_history():
    """Test /ielts_score command with no conversation history."""
    print("\n" + "=" * 60)
    print("Testing /ielts_score command (no history)")
    print("=" * 60)

    mock_session = MagicMock()
    mock_session.metadata = {}
    mock_session.key = "test_key"

    mock_loop = MagicMock()
    mock_loop.workspace = Path("/Users/jerry/Develop/ielts-speaking-bot")
    mock_loop.sessions = MagicMock()
    mock_loop.sessions._get_session_path = MagicMock(return_value=Path("/tmp/nonexistent_thread.jsonl"))
    mock_loop.sessions.get_or_create = MagicMock(return_value=mock_session)

    mock_msg = MagicMock()
    mock_msg.channel = "websocket"
    mock_msg.chat_id = "test_chat"
    mock_msg.metadata = {}

    mock_ctx = MagicMock()
    mock_ctx.loop = mock_loop
    mock_ctx.msg = mock_msg
    mock_ctx.args = ""
    mock_ctx.key = "test_key"

    from nanobot.command.builtin import cmd_ielts_score

    import asyncio
    result = asyncio.run(cmd_ielts_score(mock_ctx))

    print(f"Command returned: {result}")
    if result and "No conversation history" in result.content:
        print("✓ Correct message for no history")
    elif result:
        print(f"Content: {result.content}")
    else:
        print("✗ Unexpected result")

    print("✓ /ielts_score (no history) test completed")


def test_prompt_injector_ielts_exam_template():
    """Test that ielts_exam template has all required variables."""
    print("\n" + "=" * 60)
    print("Testing ielts_exam template structure")
    print("=" * 60)

    from nanobot.prompt_injector import PromptInjector

    workspace = Path("/Users/jerry/Develop/ielts-speaking-bot/bot")
    injector = PromptInjector(workspace)

    # Try to load the template
    template_path = workspace / "nanobot" / "templates" / "prompts" / "ielts_exam.md"
    content = template_path.read_text()

    # Check for required placeholders
    required_vars = ["{{topic_title}}", "{{topic_content}}"]
    for var in required_vars:
        if var in content:
            print(f"✓ Found {var} in template")
        else:
            print(f"✗ Missing {var} in template")

    # Try injection
    try:
        result = injector.inject("ielts_exam", {
            "topic_title": "Test Topic",
            "topic_content": "## Test Content\n\nSome test content here.",
        })
        print(f"✓ Template injection successful ({len(result)} chars)")

        # Check that variables were replaced
        if "{{topic_title}}" not in result and "{{topic_content}}" not in result:
            print("✓ All variables replaced correctly")
        else:
            print("✗ Some variables not replaced")
    except Exception as e:
        print(f"✗ Template injection failed: {e}")

    print("✓ ielts_exam template test completed")


def test_ielts_score_subagent_template():
    """Test that ielts_score_subagent template exists and is valid."""
    print("\n" + "=" * 60)
    print("Testing ielts_score_subagent template")
    print("=" * 60)

    subagent_path = Path("/Users/jerry/Develop/ielts-speaking-bot/subagent/cross_session/ielts_exam/context/ielts_score_subagent.md")

    if not subagent_path.exists():
        print(f"✗ Template not found at {subagent_path}")
        return

    print(f"✓ Template found at {subagent_path}")
    content = subagent_path.read_text()

    # Check for required sections
    required_sections = [
        "## Role",
        "## Scoring Criteria",
        "Fluency",
        "Lexical",
        "Grammatical",
        "Pronunciation",
        "{{conversation}}",
    ]

    for section in required_sections:
        if section in content:
            print(f"✓ Found '{section}' in template")
        else:
            print(f"✗ Missing '{section}' in template")

    print(f"✓ Template size: {len(content)} chars")
    print("✓ ielts_score_subagent template test completed")


def identify_code_issues():
    """Identify potential issues in the code."""
    print("\n" + "=" * 60)
    print("Code Issue Analysis")
    print("=" * 60)

    issues = []

    # Issue 1: Check if topic-bank exists
    topic_bank_path = Path("/Users/jerry/Develop/ielts-speaking-bot/topic-bank")
    if not topic_bank_path.exists():
        issues.append("❌ topic-bank directory not found at project root")
    else:
        topics = list(topic_bank_path.glob("*.md"))
        if not topics:
            issues.append("❌ No topic files found in topic-bank/")
        else:
            print(f"✓ Found {len(topics)} topics in topic-bank/")

    # Issue 2: Check if templates exist
    templates_path = Path("/Users/jerry/Develop/ielts-speaking-bot/bot/nanobot/templates/prompts")
    for template in ["freechat.md", "ielts.md", "ielts_exam.md"]:
        template_file = templates_path / template
        if template_file.exists():
            print(f"✓ {template} exists")
        else:
            issues.append(f"❌ {template} not found at {template_file}")

    # Issue 3: Check if subagent files exist
    subagent_path = Path("/Users/jerry/Develop/ielts-speaking-bot/subagent/cross_session/ielts_exam/context")
    for subagent_file in ["ielts_exam_subagent.md", "ielts_score_subagent.md"]:
        subagent_file_path = subagent_path / subagent_file
        if subagent_file_path.exists():
            print(f"✓ {subagent_file} exists")
        else:
            issues.append(f"❌ {subagent_file} not found at {subagent_file_path}")

    # Issue 4: Check ielts_exam_subagent.md content - it's currently the examiner prompt
    examiner_prompt = subagent_path / "ielts_exam_subagent.md"
    if examiner_prompt.exists():
        content = examiner_prompt.read_text()
        if "## Your Task" in content and "Ask questions" in content:
            print("⚠️  ielts_exam_subagent.md appears to be an examiner prompt, not an evaluator")
            print("   This is used by the main agent (LLM) for asking questions")
        if "Band" in content or "Score" in content:
            print("⚠️  ielts_exam_subagent.md contains scoring criteria")
            print("   Note: scoring info is duplicated in ielts_score_subagent.md")

    # Issue 5: Check builtin.py imports
    builtin_path = Path("/Users/jerry/Develop/ielts-speaking-bot/bot/nanobot/command/builtin.py")
    content = builtin_path.read_text()

    # Check if PromptInjector import is used
    if "from nanobot.prompt_injector import PromptInjector" in content:
        print("✓ PromptInjector import found in builtin.py")
    else:
        issues.append("❌ PromptInjector import not found in builtin.py")

    # Issue 6: Check for duplicate json imports
    json_import_count = content.count("import json")
    if json_import_count > 1:
        print(f"⚠️  Multiple 'import json' statements found ({json_import_count})")
        print("   Consider consolidating at module level")

    print("\n--- Issues Found ---")
    if issues:
        for issue in issues:
            print(issue)
    else:
        print("No critical issues found!")

    return issues


if __name__ == "__main__":
    print("=" * 60)
    print("IELTS Exam & Score Test Suite")
    print("=" * 60)

    # Run tests
    try:
        test_prompt_injector_ielts_exam_template()
    except Exception as e:
        print(f"✗ Test failed: {e}")

    try:
        test_ielts_score_subagent_template()
    except Exception as e:
        print(f"✗ Test failed: {e}")

    try:
        test_ielts_exam_command_random()
    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()

    try:
        test_ielts_exam_command_topic_not_found()
    except Exception as e:
        print(f"✗ Test failed: {e}")

    try:
        test_ielts_score_command_no_history()
    except Exception as e:
        print(f"✗ Test failed: {e}")

    issues = identify_code_issues()

    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    print("All synchronous tests completed.")
    print("Note: Full integration testing requires running the actual bot service.")
