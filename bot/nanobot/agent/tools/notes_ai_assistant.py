"""Notes AI Assistant Tool - spawns subagent to generate AI replies for user notes."""

from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.context import ContextAware, RequestContext
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager


@tool_parameters(
    tool_parameters_schema(
        note_id=StringSchema("Unique identifier for the note"),
        note_date=StringSchema("Date of the note (YYYY-MM-DD)"),
        note_content=StringSchema("Content of the user's note"),
        quoted_content=StringSchema("Original quoted content if any", nullable=True),
        session_title=StringSchema("Session title if any", nullable=True),
        reply_type=StringSchema(
            "Type of reply: encouragement, suggestion, question, or correction",
            enum=["encouragement", "suggestion", "question", "correction"],
        ),
        required=["note_id", "note_date", "note_content"],
    )
)
class NotesAiAssistantTool(Tool, ContextAware):
    """Spawn a subagent to generate an AI reply for a user note.

    This tool triggers an asynchronous AI assistant that:
    1. Reads the note content
    2. Generates a helpful reply (encouragement, suggestion, question, or correction)
    3. Writes the reply to ai-replies storage
    4. Updates the index for lookups
    """

    def __init__(self, manager: "SubagentManager"):
        self._manager = manager
        self._origin_channel: ContextVar[str] = ContextVar("spawn_origin_channel", default="cli")
        self._origin_chat_id: ContextVar[str] = ContextVar("spawn_origin_chat_id", default="direct")
        self._session_key: ContextVar[str] = ContextVar("spawn_session_key", default="cli:direct")
        self._origin_message_id: ContextVar[str | None] = ContextVar(
            "spawn_origin_message_id",
            default=None,
        )

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        return cls(manager=ctx.subagent_manager)

    def set_context(self, ctx: RequestContext) -> None:
        """Set the origin context for subagent announcements."""
        self._origin_channel.set(ctx.channel)
        self._origin_chat_id.set(ctx.chat_id)
        self._session_key.set(ctx.session_key or f"{ctx.channel}:{ctx.chat_id}")
        self._origin_message_id.set(ctx.message_id)

    @property
    def name(self) -> str:
        return "notes_ai_assistant"

    @property
    def description(self) -> str:
        return (
            "Generate an AI reply for a user note. The AI reply is written directly to "
            "the notes files (user-notes/ai-replies/). "
            "Use this when the user wants encouragement, suggestions, or follow-up questions "
            "about their IELTS speaking practice notes. "
            "The reply is generated asynchronously - check the notes later for the result."
        )

    async def execute(
        self,
        note_id: str,
        note_date: str,
        note_content: str,
        quoted_content: str | None = None,
        session_title: str | None = None,
        reply_type: str = "encouragement",
        **kwargs: Any,
    ) -> str:
        """Spawn a subagent to generate AI reply for the note."""
        # Validate reply_type
        valid_types = {"encouragement", "suggestion", "question", "correction"}
        if reply_type not in valid_types:
            reply_type = "encouragement"

        # Read the subagent definition
        workspace = Path(__file__).resolve().parent.parent.parent.parent.parent
        subagent_file = workspace / "subagents" / "cross_session" / "notes_ai_assistant_subagent.md"

        if not subagent_file.exists():
            return f"Error: Subagent definition not found at {subagent_file}"

        subagent_content = subagent_file.read_text()

        # Build the task prompt with the note data
        # Replace template variables
        task = subagent_content.replace("{{ workspace }}", str(workspace))

        # Prepend the input data as context
        context = f"""# Input Data for AI Reply Generation

Note ID: {note_id}
Date: {note_date}
Session: {session_title or "General"}
Reply Type: {reply_type}

Note Content:
{note_content}

{f'Original Quoted Content:\n{quoted_content}' if quoted_content else ''}

---

"""

        # Prepend context to the subagent task
        full_task = context + task

        task_id = await self._manager.spawn(
            task=full_task,
            label=f"AI Reply for note",
            origin_channel=self._origin_channel.get(),
            origin_chat_id=self._origin_chat_id.get(),
            session_key=self._session_key.get(),
            origin_message_id=self._origin_message_id.get(),
            announce_result=False,  # Silent - writes to files only
        )

        return f"AI reply generation started (task: {task_id[:8]}...)"
