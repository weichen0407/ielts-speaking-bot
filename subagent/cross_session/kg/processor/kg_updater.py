"""KG Updater - processes new content and updates the knowledge graph."""

import json
from pathlib import Path

from .entity_store import EntityStore
from .cursor import CursorManager
from .extractor import EntityExtractor


class KGUpdater:
    """
    Updates knowledge graph by processing new content from Level 2 files.

    Process:
    1. Read cursor to determine where we left off
    2. Read new lines from each source file
    3. Call LLM to extract entities (via subagent)
    4. Parse LLM output and update entity store
    5. Update cursor
    """

    def __init__(self, kg_dir: Path):
        self.kg_dir = Path(kg_dir)
        self.store = EntityStore(self.kg_dir)
        self.cursor = CursorManager(self.kg_dir)
        self.extractor = EntityExtractor()

    def get_source_path(self, source_name: str) -> Path | None:
        """Get full path for a source file."""
        # Source names are relative to workspace, e.g., "shared/vocab.jsonl"
        # We need to resolve this relative to the workspace parent
        workspace = self.kg_dir.parent
        return workspace / source_name

    def read_new_lines(self, source: str) -> list[dict]:
        """Read new lines from a source file since last cursor."""
        source_path = self.get_source_path(source)
        if not source_path or not source_path.exists():
            return []

        source_cursor = self.cursor.get_source_cursor(source)
        new_lines = []

        with open(source_path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i < source_cursor.processed_lines:
                    continue
                if line.strip():
                    try:
                        new_lines.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        return new_lines

    def process_source(self, source: str, content: list[dict]) -> tuple[int, str | None]:
        """
        Process content from a source.

        Returns (lines_processed, last_timestamp).
        """
        if not content:
            return 0, None

        last_timestamp = None
        if content:
            last_timestamp = content[-1].get("timestamp")

        # For now, just return the count - actual LLM extraction happens in subagent
        return len(content), last_timestamp

    def update_from_subagent_output(self, source: str, llm_output: str) -> tuple[list, list]:
        """
        Update entity store from subagent LLM output.

        This is called after the subagent processes the content.
        """
        created_entities, created_relations = self.extractor.extract_to_store(
            llm_output, self.store
        )
        self.store.save()
        return created_entities, created_relations

    def get_pending_sources(self) -> list[str]:
        """Get list of source files that have new content."""
        sources = [
            "shared/vocab.jsonl",
            "shared/polisher.jsonl",
            "shared/quiz.jsonl",
            "shared/notes.jsonl",
        ]

        pending = []
        for source in sources:
            source_path = self.get_source_path(source)
            if not source_path or not source_path.exists():
                continue

            # Count total lines
            with open(source_path, "r", encoding="utf-8") as f:
                total_lines = sum(1 for _ in f if _.strip())

            cursor = self.cursor.get_source_cursor(source)
            if total_lines > cursor.processed_lines:
                pending.append(source)

        return pending

    def get_new_content_for_source(self, source: str) -> list[dict]:
        """Get new content for a source that hasn't been processed yet."""
        return self.read_new_lines(source)
