"""WikiProcessor - parse LLM JSONL output and apply WikiPatch objects.

The processor:
1. Parses JSONL line-by-line.
2. Ignores "(none)" lines.
3. Rejects invalid JSON lines (logged).
4. Applies valid patches through WikiStore.
5. Calls WikiIndex.index_page(slug) after each successful patch.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .schema import WikiPatch
from .wiki_index import WikiIndex
from .wiki_store import WikiStore

logger = logging.getLogger(__name__)


class WikiProcessor:
    """Parse and apply WikiPatch JSONL from LLM output."""

    def __init__(self, wiki_root: Path):
        self.wiki_root = Path(wiki_root)
        self.store = WikiStore(workspace=self.wiki_root.parent, wiki_root=self.wiki_root)
        self.index = WikiIndex(wiki_root=self.wiki_root)

    def process_jsonl(self, jsonl_text: str) -> list[WikiPatch]:
        """Parse JSONL text and apply all valid patches.

        Returns list of successfully applied patches.
        Invalid lines are logged and skipped.
        """
        applied: list[WikiPatch] = []

        for line_no, line in enumerate(jsonl_text.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue

            # Skip (none) sentinel
            if line == "(none)":
                logger.debug("Line %d: skipped (none)", line_no)
                continue

            # Parse JSON
            try:
                data = json.loads(line)
            except json.JSONDecodeError as e:
                logger.warning("Line %d: invalid JSON — %s: %s", line_no, e, line[:100])
                continue

            # Validate and apply patch
            patch, error = self._try_build_patch(data)
            if error:
                logger.warning("Line %d: invalid patch — %s: %s", line_no, error, line[:100])
                continue

            if patch is None:
                logger.warning("Line %d: unexpected None patch", line_no)
                continue

            # Apply
            ok = self.store.apply_patch(patch)
            if ok:
                # Re-index the page
                self.index.index_page(patch.slug)
                applied.append(patch)
                logger.info("Applied patch: %s %s", patch.operation, patch.slug)
            else:
                logger.warning("Patch rejected: %s %s", patch.operation, patch.slug)

        return applied

    def _try_build_patch(self, data: dict) -> tuple[WikiPatch | None, str | None]:
        """Build WikiPatch from dict, returning (patch, error)."""
        try:
            patch = WikiPatch(**data)
            return patch, None
        except Exception as e:
            return None, str(e)
