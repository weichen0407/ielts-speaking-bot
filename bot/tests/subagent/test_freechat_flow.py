"""Test script for freechat command with PromptInjector."""

import sys
import os
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch


def test_freechat_command():
    """Test /freechat command flow."""
    print("\n" + "=" * 60)
    print("Testing /freechat command")
    print("=" * 60)

    # Use the actual project root as workspace (real Path, not MagicMock)
    project_root = Path("/Users/jerry/Develop/ielts-speaking-bot")

    # Mock the necessary components
    mock_session = MagicMock()
    mock_session.metadata = {}
    mock_session.key = "test_key"

    # Create a real session manager mock that returns our mock_session
    mock_session_manager = MagicMock()
    mock_session_manager.save = MagicMock()
    mock_session_manager.get_or_create = MagicMock(return_value=mock_session)
    mock_session_manager._get_session_dir = lambda key: project_root / "sessions" / key

    mock_loop = MagicMock()
    # IMPORTANT: workspace must be a real Path object, not MagicMock
    mock_loop.workspace = project_root
    mock_loop.sessions = mock_session_manager
    mock_loop.counter_engine = MagicMock()
    mock_loop.counter_engine.set_mode = MagicMock()

    # ctx.session should be None so it falls through to get_or_create
    mock_ctx = MagicMock()
    mock_ctx.loop = mock_loop
    mock_ctx.msg = MagicMock()
    mock_ctx.msg.channel = "websocket"
    mock_ctx.msg.chat_id = "test_chat"
    mock_ctx.msg.metadata = {}
    mock_ctx.args = ""
    mock_ctx.key = "test_key"
    # Set session to None so the command uses get_or_create
    type(mock_ctx).session = property(lambda self: None)

    # Import and test
    from nanobot.command.builtin import cmd_freechat

    import asyncio
    result = asyncio.run(cmd_freechat(mock_ctx))

    # After the command, ctx.msg.content should be the injected prompt
    print(f"Command returned: {result}")
    print(f"ctx.msg.content type: {type(mock_ctx.msg.content)}")
    print(f"session.metadata: {mock_session.metadata}")

    # The content should contain the freechat prompt
    if mock_ctx.msg.content:
        print(f"Prompt length: {len(mock_ctx.msg.content)} chars")
        print(f"Prompt preview: {mock_ctx.msg.content[:300]}...")
        if "casual conversation" in mock_ctx.msg.content or "question" in mock_ctx.msg.content:
            print("✓ Freechat prompt injected correctly")
        else:
            print("⚠ Prompt doesn't contain expected content")
    else:
        print("✗ Prompt was not injected")

    print("✓ /freechat test completed")


if __name__ == "__main__":
    print("=" * 60)
    print("Freechat Command Test")
    print("=" * 60)

    try:
        test_freechat_command()
    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 60)
    print("Test Complete")
    print("=" * 60)
