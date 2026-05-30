"""LLM Wiki Memory System.

A lightweight long-term memory store backed by Markdown files with SQLite FTS search index.

Directory structure:
    subagent/cross_session/wiki/
        context/       - Subagent prompt templates
        processor/    - Core wiki logic (store, index, search, etc.)
        data/         - Runtime data (cursors, etc.)
"""
