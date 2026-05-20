"""Progress bank tool: save analyzed user expression highlights to progress_bank.jsonl.

Uses a cursor to track progress — never deletes user_responses.jsonl, just reads
from the last processed offset each time.

Engineering layer extracts content from user_responses.jsonl BEFORE sending to LLM.
LLM only sees content strings. LLM returns highlights with index alignment.
Engineering layer zips results with original meta_info (session_uuid, round, topic, timestamp).
"""

import json
from pathlib import Path

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.context import ContextAware
from nanobot.agent.tools.schema import ArraySchema, ObjectSchema, StringSchema, tool_parameters_schema


@tool_parameters(
    tool_parameters_schema(
        contents=ArraySchema(
            StringSchema(
                "Extracted content string from user_responses.jsonl at cursor position."
            ),
            description=(
                "Array of content strings aligned to user_responses.jsonl by position. "
                "LLM analyzes these. Engineering layer extracts before LLM call."
            ),
        ),
        entries=ArraySchema(
            ArraySchema(
                ObjectSchema(
                    properties={
                        "category": StringSchema("Category label: emotion, description, experience, habit, opinion, goal, comparison, cause."),
                        "intent": StringSchema("Intent tag: positive, negative, preference, habit, frequency, reason, etc."),
                        "expression": StringSchema("The extracted expression or phrase from the user's original content."),
                    },
                    required=["category", "intent", "expression"],
                ),
                description="List of highlights for ONE content string. Empty if no highlights found.",
            ),
            description=(
                "Array of highlight arrays aligned to contents by position. "
                "entries[i] corresponds to the i-th content string. "
                "Each entries[i] is an array of {category, intent, expression} objects. "
                "If a content string has no highlights, use an empty array [] at that position."
            ),
        ),
        required=["contents", "entries"],
    )
)
class ProgressBankTool(Tool, ContextAware):
    """Save user expression highlights to progress_bank.jsonl using cursor tracking."""

    _scopes = {"core", "subagent"}
    name = "save_progress_entries"
    description = "Save analyzed user expression highlights to progress_bank.jsonl and advance the cursor. LLM only receives content strings; engineering layer preserves meta_info."

    def __init__(self, workspace: Path | str):
        self._workspace = Path(workspace)

    @classmethod
    def create(cls, ctx) -> "ProgressBankTool":
        from nanobot.config.paths import get_workspace_path
        workspace = ctx.workspace if hasattr(ctx, "workspace") else get_workspace_path()
        return cls(workspace=workspace)

    # Cursor filename key must match the file_line_count trigger id in triggers.yaml
    _CURSOR_TRIGGER_ID = "progress_tracker"

    def _cursor_path(self) -> Path:
        # Must match the naming convention used by CounterEngine._read_cursor
        return self._workspace / f".cursor_{self._CURSOR_TRIGGER_ID}.json"

    def _read_cursor(self) -> int:
        """Read current cursor offset. Returns 0 if no cursor file exists."""
        cursor_path = self._cursor_path()
        if cursor_path.exists():
            try:
                data = json.loads(cursor_path.read_text(encoding="utf-8"))
                return data.get("offset", 0)
            except (json.JSONDecodeError, IOError):
                return 0
        return 0

    def _write_cursor(self, offset: int) -> None:
        """Write new cursor offset."""
        cursor_path = self._cursor_path()
        cursor_path.write_text(json.dumps({"offset": offset}, ensure_ascii=False), encoding="utf-8")

    async def execute(self, contents: list[str], entries: list[list[dict]]) -> dict:
        """Write entries to progress_bank.jsonl and advance cursor.

        contents: Array of content strings extracted by engineering layer before LLM call.
        entries: Array of highlight arrays from LLM, aligned 1:1 with contents by position.
        Source meta_info (session_uuid, round, topic, timestamp) is read from user_responses.jsonl.
        Cursor is advanced to the end of file after successful processing.
        """
        from loguru import logger

        try:
            logger.info(
                "save_progress_entries EXECUTE: workspace={}, contents_len={}, entries_len={}",
                self._workspace, len(contents), len(entries),
            )

            expr_path = self._workspace / "user_responses.jsonl"
            if not expr_path.exists():
                logger.error("save_progress_entries: user_responses.jsonl not found at {}", expr_path)
                return {"status": "error", "message": "user_responses.jsonl not found"}

            cursor_offset = self._read_cursor()
            logger.info("save_progress_entries: cursor_offset={}", cursor_offset)

            # Read source info from cursor position onward (for meta_info preservation)
            source_lines: list[dict] = []
            with open(expr_path, encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if i < cursor_offset:
                        continue
                    line = line.strip()
                    if line:
                        source_lines.append(json.loads(line))

            logger.info(
                "save_progress_entries: source_lines={}, contents={}, entries={}",
                len(source_lines), len(contents), len(entries),
            )

            if len(entries) != len(source_lines):
                logger.error(
                    "save_progress_entries: mismatch source_lines={} vs entries={}",
                    len(source_lines), len(entries),
                )
                return {
                    "status": "error",
                    "message": f"Entry count mismatch: expected {len(source_lines)}, got {len(entries)}",
                }

            if len(contents) != len(source_lines):
                logger.error(
                    "save_progress_entries: mismatch source_lines={} vs contents={}",
                    len(source_lines), len(contents),
                )
                return {
                    "status": "error",
                    "message": f"Contents count mismatch: expected {len(source_lines)}, got {len(contents)}",
                }

            # Build entries with content + meta_info preserved by engineering layer
            progress_path = self._workspace / "progress_bank.jsonl"
            written = 0
            with open(progress_path, "a", encoding="utf-8") as f:
                for content, highlights, source in zip(contents, entries, source_lines):
                    for h in highlights:
                        entry = {
                            "category": h.get("category", ""),
                            "intent": h.get("intent", ""),
                            "expression": h.get("expression", ""),
                            "content": content,  # original user content, preserved by engineering
                            "meta": {
                                "session_uuid": source.get("session_uuid", ""),
                                "round": source.get("round", 0),
                                "topic": source.get("topic", ""),
                                "timestamp": source.get("timestamp", ""),
                            },
                        }
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                        written += 1

            # Advance cursor to end of file
            new_offset = cursor_offset + len(source_lines)
            self._write_cursor(new_offset)
            logger.info("save_progress_entries: SUCCESS written={}, new_cursor={}", written, new_offset)

            return {"status": "ok", "count": written, "cursor": new_offset}
        except Exception as e:
            logger.exception("save_progress_entries EXCEPTION: {}", e)
            return {"status": "error", "message": str(e)}
