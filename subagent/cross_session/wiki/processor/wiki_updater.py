"""WikiUpdater - cursor-based incremental updates from JSONL sources.

The updater:
1. Tracks line cursor per source file.
2. Reads only new lines on each run.
3. Advances cursor only after successful patch application.
4. Skips lines that fail to apply (cursor not advanced).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .schema import WikiPatch
from .wiki_processor import WikiProcessor

logger = logging.getLogger(__name__)

# Default JSONL sources to scan
DEFAULT_SOURCES: list[Path] = [
    Path("subagent/single_session/vocab/data/vocab.jsonl"),
    Path("subagent/single_session/polisher/data/polisher.jsonl"),
    Path("subagent/single_session/notes/data/notes.jsonl"),
    Path("subagent/cross_session/progress_tracker/data/progress_bank.jsonl"),
]


class WikiUpdater:
    """Track cursors and apply incremental patches from JSONL sources."""

    def __init__(self, wiki_root: Path, cursor_path: Path | None = None):
        self.wiki_root = Path(wiki_root)
        self.processor = WikiProcessor(wiki_root=self.wiki_root)
        self.cursor_path = cursor_path or (self.wiki_root / "updater_cursors.json")
        self._cursors: dict[str, int] = {}
        self._load_cursors()

    def _load_cursors(self) -> None:
        if self.cursor_path.exists():
            try:
                self._cursors = json.loads(self.cursor_path.read_text())
            except (json.JSONDecodeError, OSError):
                self._cursors = {}
        else:
            self._cursors = {}

    def _save_cursors(self) -> None:
        self.cursor_path.parent.mkdir(parents=True, exist_ok=True)
        self.cursor_path.write_text(json.dumps(self._cursors, indent=2))

    def get_cursor(self, source_path: Path) -> int:
        """Return the cursor (line number, 0-based) for a source file."""
        key = str(source_path.resolve())
        return self._cursors.get(key, 0)

    def set_cursor(self, source_path: Path, cursor: int) -> None:
        """Set cursor for a source file (in memory only; call save() to persist)."""
        key = str(source_path.resolve())
        self._cursors[key] = cursor

    def save(self) -> None:
        """Persist cursors to disk."""
        self._save_cursors()

    def scan_source(self, source_path: Path) -> list[WikiPatch]:
        """Scan one source file from current cursor to end.

        Returns patches applied. Cursor advances only for successfully applied patches.
        """
        source_path = Path(source_path).resolve()

        if not source_path.exists():
            logger.debug("Source file not found: %s", source_path)
            return []

        try:
            content = source_path.read_text()
        except OSError as e:
            logger.warning("Cannot read source %s: %s", source_path, e)
            return []

        lines = content.splitlines()
        cursor = self.get_cursor(source_path)

        if cursor >= len(lines):
            logger.debug("No new lines in %s (cursor=%d, lines=%d)", source_path, cursor, len(lines))
            return []

        applied: list[WikiPatch] = []
        pending_cursor = cursor

        for line_no, line in enumerate(lines[cursor:], start=cursor):
            line = line.strip()
            if not line:
                pending_cursor = line_no + 1
                continue

            # Parse and apply
            patch, error, is_validation_error = self._try_parse_line(line)
            if error:
                if is_validation_error:
                    # Validation error — stop processing, don't advance past this line
                    logger.warning("Validation error line %d in %s: %s — stopping", line_no, source_path, error)
                    break
                else:
                    # JSON parse error — skip and continue
                    logger.warning("Skipping invalid line %d in %s: %s", line_no, source_path, error)
                    pending_cursor = line_no + 1
                    continue

            if patch is None:
                # (none) or empty — treat as successful but don't advance cursor past it
                continue

            ok = self.processor.store.apply_patch(patch)
            if ok:
                self.processor.index.index_page(patch.slug)
                applied.append(patch)
                pending_cursor = line_no + 1
                logger.info("Applied patch from %s line %d: %s %s", source_path, line_no, patch.operation, patch.slug)
            else:
                # Patch rejected — stop processing, don't advance cursor past this line
                logger.warning("Patch rejected from %s line %d: %s %s — stopping", source_path, line_no, patch.operation, patch.slug)
                break

        # Advance cursor to last successfully processed line
        self.set_cursor(source_path, pending_cursor)
        self.save()

        return applied

    def _try_parse_line(self, line: str) -> tuple[WikiPatch | None, str | None, bool]:
        """Parse one JSONL line into a WikiPatch.

        Returns (patch, error, is_validation_error):
            (patch, None, False)       — valid patch
            (None, None, False)        — (none) sentinel
            (None, error_str, False)   — JSON parse error (caller should continue)
            (None, error_str, True)    — validation error (caller should break)
        """
        import json

        if line == "(none)":
            return None, None, False

        data = None
        try:
            data = json.loads(line)
        except json.JSONDecodeError as e:
            return None, str(e), False

        if not isinstance(data, dict):
            return None, f"expected JSON object, got {type(data).__name__}", False

        try:
            patch = WikiPatch(**data)
            return patch, None, False
        except Exception as e:
            # Validation error after successful JSON parse
            return None, str(e), True

    def scan_all(self, sources: list[Path] | None = None) -> list[WikiPatch]:
        """Scan all default sources (or provided list) from current cursor.

        Returns all patches applied across all sources.
        """
        if sources is None:
            sources = DEFAULT_SOURCES

        all_applied: list[WikiPatch] = []
        for source in sources:
            # Resolve relative to project root (parent of wiki_root which is persona/wiki)
            if not source.is_absolute():
                project_root = self.wiki_root.parent.parent
                source = project_root / source

            applied = self.scan_source(source)
            all_applied.extend(applied)

        return all_applied

    def reset_cursor(self, source_path: Path) -> None:
        """Reset cursor for a source to 0 (will re-process all lines)."""
        self.set_cursor(source_path, 0)
        self.save()
