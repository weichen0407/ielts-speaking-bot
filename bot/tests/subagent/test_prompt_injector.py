"""Test script for PromptInjector module."""

import tempfile
import os
from pathlib import Path


def test_prompt_injector_basic():
    """Test basic prompt injection."""
    from nanobot.prompt_injector import PromptInjector

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        # Create the correct directory structure: nanobot/templates/prompts/
        templates_dir = workspace / "nanobot" / "templates" / "prompts"
        templates_dir.mkdir(parents=True)

        # Create a test template
        template_content = """Hello {{name}}!

You are talking about {{topic}}.
Your score is {{score}}.
"""
        (templates_dir / "test.md").write_text(template_content)

        injector = PromptInjector(workspace)

        # Test basic injection
        result = injector.inject("test", {
            "name": "Alice",
            "topic": "Python",
            "score": "95",
        })

        expected = """Hello Alice!

You are talking about Python.
Your score is 95.
"""
        assert result == expected, f"Expected:\n{expected}\n\nGot:\n{result}"
        print("✓ Basic injection works")


def test_prompt_injector_list():
    """Test list injection."""
    from nanobot.prompt_injector import PromptInjector

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        templates_dir = workspace / "nanobot" / "templates" / "prompts"
        templates_dir.mkdir(parents=True)

        # Create a test template with list
        template_content = """Items:
{{items}}"""
        (templates_dir / "list_test.md").write_text(template_content)

        injector = PromptInjector(workspace)

        # Test list injection
        result = injector.inject("list_test", {
            "items": ["apple", "banana", "cherry"],
        })

        expected = """Items:
apple
banana
cherry"""
        assert result == expected, f"Expected:\n{expected}\n\nGot:\n{result}"
        print("✓ List injection works")


def test_prompt_injector_missing_var():
    """Test that missing variables are preserved."""
    from nanobot.prompt_injector import PromptInjector

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        templates_dir = workspace / "nanobot" / "templates" / "prompts"
        templates_dir.mkdir(parents=True)

        template_content = """Hello {{name}}, you are {{age}} years old.
Unknown: {{unknown_var}}"""
        (templates_dir / "missing.md").write_text(template_content)

        injector = PromptInjector(workspace)

        result = injector.inject("missing", {
            "name": "Bob",
            # "age" is missing
        })

        expected = """Hello Bob, you are {{age}} years old.
Unknown: {{unknown_var}}"""
        assert result == expected, f"Expected:\n{expected}\n\nGot:\n{result}"
        print("✓ Missing variables preserved correctly")


def test_prompt_injector_file_not_found():
    """Test error on missing template."""
    from nanobot.prompt_injector import PromptInjector

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        # Create empty nanobot/templates/prompts structure
        templates_dir = workspace / "nanobot" / "templates" / "prompts"
        templates_dir.mkdir(parents=True)

        injector = PromptInjector(workspace)

        try:
            injector.inject("nonexistent", {})
            assert False, "Should have raised FileNotFoundError"
        except FileNotFoundError:
            print("✓ FileNotFoundError raised for missing template")


def test_freechat_template():
    """Test freechat template loading."""
    from nanobot.prompt_injector import PromptInjector

    workspace = Path("/Users/jerry/Develop/ielts-speaking-bot/bot")
    injector = PromptInjector(workspace)

    try:
        result = injector.inject("freechat", {
            "topic": "Hobbies",
            "question": "What do you like to do in your free time?",
        })
        assert "Hobbies" in result
        assert "What do you like to do" in result
        assert "{{topic}}" not in result
        print("✓ freechat template loads correctly")
    except FileNotFoundError as e:
        print(f"✗ freechat template not found: {e}")


def test_ielts_exam_template():
    """Test ielts_exam template loading."""
    from nanobot.prompt_injector import PromptInjector

    workspace = Path("/Users/jerry/Develop/ielts-speaking-bot/bot")
    injector = PromptInjector(workspace)

    try:
        result = injector.inject("ielts_exam", {
            "topic_title": "Animals",
            "topic_content": "## Topic: Animals\n\nPart 1 questions...",
        })
        assert "Animals" in result
        assert "{{topic_title}}" not in result
        assert "{{topic_content}}" not in result
        print("✓ ielts_exam template loads correctly")
    except FileNotFoundError as e:
        print(f"✗ ielts_exam template not found: {e}")


if __name__ == "__main__":
    print("=" * 60)
    print("Testing PromptInjector Module")
    print("=" * 60)

    test_prompt_injector_basic()
    test_prompt_injector_list()
    test_prompt_injector_missing_var()
    test_prompt_injector_file_not_found()
    test_freechat_template()
    test_ielts_exam_template()

    print()
    print("=" * 60)
    print("All PromptInjector tests passed!")
    print("=" * 60)
