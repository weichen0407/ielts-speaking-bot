"""WikiRetriever - fetch wiki content for LLM context prompts."""

from __future__ import annotations

from pathlib import Path

from .wiki_search import WikiSearch


DEFAULT_MAX_CHARS = 4000


def read_wiki_context(
    query: str,
    *,
    mode: str | None = None,
    topic: str | None = None,
    page_type: str | None = None,
    tags: list[str] | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
    wiki_root: Path | None = None,
) -> str:
    """Search wiki and return a prompt-ready context string.

    Combines the top matching chunks into a single Markdown string
    that fits within max_chars.

    If no wiki_root is provided, returns "(none)".
    If no results match, returns "(none)".
    """
    if wiki_root is None:
        return "(none)"

    searcher = WikiSearch(wiki_root=wiki_root)
    results = searcher.search(
        query,
        mode=mode,
        topic=topic,
        page_type=page_type,
        tags=tags,
        limit=10,
    )

    if not results:
        return "(none)"

    lines: list[str] = []
    current_len = 0

    for result in results:
        chunk_lines = [
            f"## {result.slug}",
            f"**Section:** {result.section}",
            f"{result.snippet}",
            "",
        ]
        chunk_text = "\n".join(chunk_lines)
        if current_len + len(chunk_text) > max_chars:
            # Try to fit just the slug and title
            header = f"- **{result.title}** (`{result.slug}`) — {result.section}\n"
            if current_len + len(header) <= max_chars:
                lines.append(header)
                current_len += len(header)
            break

        lines.extend(chunk_lines)
        current_len += len(chunk_text)

    if not lines:
        return "(none)"

    return (
        "<!-- WIKI CONTEXT -->\n"
        + f"<!-- Query: {query} -->\n"
        + "\n".join(lines)
    )
