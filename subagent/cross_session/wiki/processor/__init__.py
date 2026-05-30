"""Wiki processor modules.

    schema.py        - Pydantic models (Phase 1)
    wiki_store.py    - Markdown page read/write/store (Phase 1)
    wiki_index.py    - SQLite FTS indexing (Phase 2)
    wiki_search.py   - Search interface (Phase 2)
    wiki_retriever.py - Context retrieval for agent prompts (Phase 2)
    wiki_processor.py - LLM-to-patch pipeline (Phase 3)
    wiki_updater.py   - Cursor-based incremental updates (Phase 3)
"""
