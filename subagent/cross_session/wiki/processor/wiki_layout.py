"""Filesystem layout helpers for the LLM wiki.

The wiki keeps raw evidence separate from crystallized Markdown pages:

    persona/wiki/
        raw/       # immutable or append-only source material
        wiki/      # human-readable pages grouped by page type
        index/     # derived search indexes
        state/     # cursors and queues
        schema/    # JSON schemas and processor contracts
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WikiLayout:
    """Resolved paths for one wiki root."""

    root: Path
    raw_root: Path
    raw_sources_root: Path
    raw_thread_root: Path
    pages_root: Path
    index_root: Path
    state_root: Path
    schema_root: Path
    log_path: Path
    graph_path: Path
    ingest_cursor_path: Path
    review_queue_path: Path


def resolve_wiki_layout(wiki_root: Path) -> WikiLayout:
    root = Path(wiki_root)
    return WikiLayout(
        root=root,
        raw_root=root / "raw",
        raw_sources_root=root / "raw" / "sources",
        raw_thread_root=root / "raw" / "thread",
        pages_root=root / "wiki",
        index_root=root / "index",
        state_root=root / "state",
        schema_root=root / "schema",
        log_path=root / "wiki" / "log.md",
        graph_path=root / "wiki" / "graph.json",
        ingest_cursor_path=root / "state" / "ingest_cursor.json",
        review_queue_path=root / "state" / "queue.jsonl",
    )


def ensure_wiki_layout(wiki_root: Path) -> WikiLayout:
    """Create the canonical wiki directories and return their paths."""

    layout = resolve_wiki_layout(wiki_root)
    for path in (
        layout.raw_root,
        layout.raw_sources_root,
        layout.raw_thread_root,
        layout.pages_root,
        layout.index_root,
        layout.state_root,
        layout.schema_root,
    ):
        path.mkdir(parents=True, exist_ok=True)
    return layout
