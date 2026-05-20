"""Progress organizer tool: refine and merge entries from progress_bank.jsonl.

Engineering layer extracts expression + content from progress_bank.jsonl BEFORE sending to LLM.
LLM only receives expression strings. Engineering layer preserves content + meta_info.
After LLM refinement, engineering layer zips results with original content + meta_info.
"""

import json
from pathlib import Path

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.context import ContextAware
from nanobot.agent.tools.schema import (
    ArraySchema,
    ObjectSchema,
    StringSchema,
    tool_parameters_schema,
)


@tool_parameters(
    tool_parameters_schema(
        contents=ArraySchema(
            StringSchema(
                "Extracted expression strings from progress_bank.jsonl at cursor position."
            ),
            description=(
                "Array of expression strings for refinement. "
                "Engineering layer extracts from progress_bank.jsonl before LLM call."
            ),
        ),
        entries=ArraySchema(
            ArraySchema(
                ObjectSchema(
                    properties={
                        "category": StringSchema("Refined category label."),
                        "intent": StringSchema("Refined intent tag."),
                        "expression": StringSchema("The expression string."),
                    },
                    required=["category", "intent", "expression"],
                ),
                description="List of refined highlight objects for entries processed this batch.",
            ),
            description="Array of refined highlight arrays from progress_bank.jsonl.",
        ),
        required=["contents", "entries"],
    )
)
class ProgressOrganizerTool(Tool, ContextAware):
    """Refine entries from progress_bank.jsonl and update progress.json summary."""

    _scopes = {"core", "subagent"}
    name = "save_progress_organizer_entries"
    description = "Refine and merge entries from progress_bank.jsonl into progress.json summary. LLM only receives expressions; engineering layer preserves content + meta_info."

    def __init__(self, workspace: Path | str):
        self._workspace = Path(workspace)

    @classmethod
    def create(cls, ctx) -> "ProgressOrganizerTool":
        from nanobot.config.paths import get_workspace_path
        workspace = ctx.workspace if hasattr(ctx, "workspace") else get_workspace_path()
        return cls(workspace=workspace)

    # Cursor filename key must match the file_line_count trigger id in triggers.yaml
    _CURSOR_TRIGGER_ID = "progress_organizer"

    def _cursor_path(self) -> Path:
        return self._workspace / f".cursor_{self._CURSOR_TRIGGER_ID}.json"

    def _read_cursor(self) -> int:
        cursor_path = self._cursor_path()
        if cursor_path.exists():
            try:
                data = json.loads(cursor_path.read_text(encoding="utf-8"))
                return data.get("offset", 0)
            except (json.JSONDecodeError, IOError):
                return 0
        return 0

    def _write_cursor(self, offset: int) -> None:
        cursor_path = self._cursor_path()
        cursor_path.write_text(json.dumps({"offset": offset}, ensure_ascii=False), encoding="utf-8")

    async def execute(self, contents: list[str], entries: list[list[dict]]) -> dict:
        """Read source info from progress_bank.jsonl from cursor, refine, update progress.json.

        contents: Array of expression strings extracted by engineering layer before LLM call.
        entries: Array of refined highlight arrays from LLM, aligned 1:1 with contents by position.
        Source content + meta_info is read from progress_bank.jsonl at cursor position.
        Merges into progress.json summary and advances cursor.
        """
        from loguru import logger

        bank_path = self._workspace / "progress_bank.jsonl"
        if not bank_path.exists():
            return {"status": "error", "message": "progress_bank.jsonl not found"}

        progress_path = self._workspace / "progress.json"

        cursor_offset = self._read_cursor()

        # Read source info from bank at cursor position (for content + meta preservation)
        source_lines: list[dict] = []
        with open(bank_path, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i < cursor_offset:
                    continue
                line = line.strip()
                if line:
                    source_lines.append(json.loads(line))

        if len(entries) != len(source_lines):
            return {
                "status": "error",
                "message": f"Entry count mismatch: expected {len(source_lines)}, got {len(entries)}",
            }

        if len(contents) != len(source_lines):
            return {
                "status": "error",
                "message": f"Contents count mismatch: expected {len(source_lines)}, got {len(contents)}",
            }

        # Load existing progress.json or initialize
        if progress_path.exists():
            try:
                progress_data = json.loads(progress_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, IOError):
                progress_data = {"last_processed_offset": 0, "categories": {}, "expression_count": 0}
        else:
            progress_data = {"last_processed_offset": 0, "categories": {}, "expression_count": 0}

        # Merge refined entries into categories, preserving content + meta_info
        merged_categories: dict[str, dict[str, list]] = progress_data.get("categories", {})
        for highlights, source in zip(entries, source_lines):
            for h in highlights:
                cat = h.get("category", "unknown")
                intent = h.get("intent", "unknown")
                expr = h.get("expression", "").strip().lower()
                if not expr:
                    continue
                if cat not in merged_categories:
                    merged_categories[cat] = {}
                if intent not in merged_categories[cat]:
                    merged_categories[cat][intent] = []
                # Store entry with content + meta preserved by engineering layer
                merged_categories[cat][intent].append({
                    "expression": h.get("expression", ""),
                    "content": source.get("content", ""),  # original user content
                    "meta": source.get("meta", {}),  # session_uuid, round, topic, timestamp
                })

        # Count total expressions
        expression_count = sum(
            len(exprs) for intents in merged_categories.values() for exprs in intents.values()
        )

        new_progress = {
            "last_processed_offset": cursor_offset + len(source_lines),
            "categories": merged_categories,
            "expression_count": expression_count,
            "last_updated": __import__("datetime").datetime.now().isoformat(),
        }

        progress_path.write_text(json.dumps(new_progress, ensure_ascii=False, indent=2), encoding="utf-8")

        # Advance cursor
        self._write_cursor(cursor_offset + len(source_lines))

        return {
            "status": "ok",
            "count": sum(len(e) for e in entries),
            "cursor": cursor_offset + len(source_lines),
            "total_expressions": expression_count,
        }
