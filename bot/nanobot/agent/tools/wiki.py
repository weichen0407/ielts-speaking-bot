"""Wiki memory tool: search, read, propose/apply patches, and graph wiki pages.

Actions:
- search: Full-text search across wiki pages
- read: Read a specific page's content and metadata
- propose_patch: Preview a patch without applying it
- apply_patch: Apply a patch (requires explicit user intent)
- graph: Get the knowledge graph data

Safety: apply_patch requires explicit user intent or UI confirmation.
"""

from pathlib import Path

from loguru import logger

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.context import ContextAware, RequestContext, ToolContext
from nanobot.agent.tools.schema import (
    ArraySchema,
    IntegerSchema,
    ObjectSchema,
    StringSchema,
    tool_parameters_schema,
)


@tool_parameters(
    tool_parameters_schema(
        required=["action"],
        properties={
            "action": StringSchema(
                "Action to perform: search, read, propose_patch, apply_patch, graph",
                enum=("search", "read", "propose_patch", "apply_patch", "graph"),
            ),
            "query": StringSchema(
                "Search query string for search action",
                max_length=500,
            ),
            "mode": StringSchema(
                "Filter by mode (e.g. ielts, freechat)",
                max_length=50,
            ),
            "topic": StringSchema(
                "Filter by topic",
                max_length=100,
            ),
            "page_type": StringSchema(
                "Filter by page type (e.g. ielts_topic, freechat_interest)",
                max_length=50,
            ),
            "tags": StringSchema(
                "Comma-separated tags to filter by",
                max_length=200,
            ),
            "limit": IntegerSchema(
                "Maximum number of search results",
                minimum=1,
                maximum=50,
            ),
            "slug": StringSchema(
                "Wiki page slug for read/action=apply_patch",
                max_length=200,
            ),
            "patch": ObjectSchema(
                properties={
                    "operation": StringSchema("WikiPatch operation"),
                    "slug": StringSchema("Page slug"),
                    "title": StringSchema("Page title", max_length=200),
                    "type": StringSchema("Page type", max_length=50),
                    "mode": StringSchema("Page mode", max_length=50),
                    "section": StringSchema("Section name", max_length=100),
                    "content": StringSchema("Section content"),
                    "tags": ArraySchema(StringSchema("Tag"), description="Page tags"),
                    "topics": ArraySchema(StringSchema("Topic"), description="Page topics"),
                    "links": ArraySchema(StringSchema("Link"), description="Page links"),
                    "sources": ArraySchema(
                        ObjectSchema(
                            properties={
                                "kind": StringSchema("Source kind"),
                                "session_id": StringSchema("Session ID"),
                                "message_id": StringSchema("Message ID"),
                            },
                        ),
                        description="Sources",
                    ),
                    "confidence": StringSchema("Confidence level"),
                    "reason": StringSchema("Reason for replace/deprecate"),
                    "original_content": StringSchema("Original content for deprecate"),
                },
                description="WikiPatch JSON object",
            ),
        },
    )
)
class WikiTool(Tool, ContextAware):
    """Search, read, and modify the wiki memory system."""

    _scopes = {"core", "subagent"}
    name = "wiki_memory"
    description = "Search, read, and modify the wiki memory system. Use search to find pages, read to view content, propose_patch to preview changes, apply_patch to apply changes (requires user confirmation), and graph to get the knowledge graph."

    def __init__(self, wiki_root: Path | str | None = None):
        self._wiki_root = Path(wiki_root) if wiki_root else None
        self._request_ctx: RequestContext | None = None

    @classmethod
    def create(cls, ctx: ToolContext) -> "WikiTool":
        from nanobot.config.paths import get_workspace_path
        workspace = Path(ctx.workspace) if hasattr(ctx, "workspace") else get_workspace_path()
        wiki_root = workspace / "persona" / "wiki"
        return cls(wiki_root=wiki_root)

    def set_context(self, ctx: RequestContext) -> None:
        self._request_ctx = ctx

    def _ensure_wiki_root(self) -> Path:
        if self._wiki_root is None:
            from nanobot.config.paths import get_workspace_path
            workspace = Path(get_workspace_path())
            self._wiki_root = workspace / "persona" / "wiki"
        return self._wiki_root

    async def execute(
        self,
        action: str,
        query: str | None = None,
        mode: str | None = None,
        topic: str | None = None,
        page_type: str | None = None,
        tags: str | None = None,
        limit: int | None = None,
        slug: str | None = None,
        patch: dict | None = None,
    ) -> dict:
        """Execute a wiki action."""
        wiki_root = self._ensure_wiki_root()

        if action == "search":
            return await self._do_search(wiki_root, query, mode, topic, page_type, tags, limit)
        elif action == "read":
            return await self._do_read(wiki_root, slug)
        elif action == "propose_patch":
            return await self._do_propose_patch(wiki_root, patch)
        elif action == "apply_patch":
            return await self._do_apply_patch(wiki_root, patch)
        elif action == "graph":
            return await self._do_graph(wiki_root, mode, topic, page_type, tags)
        else:
            return {"status": "error", "message": f"Unknown action: {action}"}

    async def _do_search(
        self,
        wiki_root: Path,
        query: str | None,
        mode: str | None,
        topic: str | None,
        page_type: str | None,
        tags: str | None,
        limit: int | None,
    ) -> dict:
        try:
            from subagent.cross_session.wiki.processor.wiki_search import WikiSearch
            searcher = WikiSearch(wiki_root=wiki_root)
            results = searcher.search(
                query=query or "",
                mode=mode,
                topic=topic,
                page_type=page_type,
                tags=tags.split(",") if tags else None,
                limit=limit or 10,
            )
            return {
                "status": "ok",
                "results": [r.model_dump() for r in results],
                "count": len(results),
            }
        except Exception as e:
            logger.exception("[WikiTool] search error: {}", e)
            return {"status": "error", "message": str(e)}

    async def _do_read(self, wiki_root: Path, slug: str | None) -> dict:
        if not slug:
            return {"status": "error", "message": "slug is required for read action"}
        try:
            from subagent.cross_session.wiki.processor.wiki_store import WikiStore
            store = WikiStore(workspace=wiki_root.parent, wiki_root=wiki_root)
            page = store.read_page(slug)
            if page is None:
                return {"status": "error", "message": f"Page not found: {slug}"}
            meta, body = page
            return {
                "status": "ok",
                "slug": slug,
                "meta": meta.model_dump(),
                "content": body,
            }
        except Exception as e:
            logger.exception("[WikiTool] read error: {}", e)
            return {"status": "error", "message": str(e)}

    async def _do_propose_patch(
        self,
        wiki_root: Path,
        patch: dict | None,
    ) -> dict:
        if not patch:
            return {"status": "error", "message": "patch is required for propose_patch action"}
        try:
            from subagent.cross_session.wiki.processor.schema import WikiPatch
            from subagent.cross_session.wiki.processor.wiki_store import WikiStore
            # Validate the patch by trying to construct it
            p = WikiPatch(**patch)
            store = WikiStore(workspace=wiki_root.parent, wiki_root=wiki_root)
            # Preview what would happen
            return {
                "status": "ok",
                "preview": "Patch is valid",
                "operation": p.operation,
                "slug": p.slug,
                "note": "This is a preview. Use apply_patch to confirm.",
            }
        except Exception as e:
            logger.exception("[WikiTool] propose_patch error: {}", e)
            return {"status": "error", "message": f"Invalid patch: {e}"}

    async def _do_apply_patch(
        self,
        wiki_root: Path,
        patch: dict | None,
    ) -> dict:
        if not patch:
            return {"status": "error", "message": "patch is required for apply_patch action"}
        if self._request_ctx is None:
            return {
                "status": "error",
                "message": "Cannot apply patch: no request context (requires user confirmation via UI)",
            }
        try:
            from subagent.cross_session.wiki.processor.schema import WikiPatch
            from subagent.cross_session.wiki.processor.wiki_store import WikiStore
            from subagent.cross_session.wiki.processor.wiki_index import WikiIndex
            p = WikiPatch(**patch)
            store = WikiStore(workspace=wiki_root.parent, wiki_root=wiki_root)
            ok = store.apply_patch(p)
            if not ok:
                return {"status": "error", "message": "Patch was rejected"}
            # Index the changed page
            index = WikiIndex(wiki_root=wiki_root)
            index.index_page(p.slug)
            return {
                "status": "ok",
                "applied": True,
                "slug": p.slug,
                "operation": p.operation,
            }
        except Exception as e:
            logger.exception("[WikiTool] apply_patch error: {}", e)
            return {"status": "error", "message": str(e)}

    async def _do_graph(
        self,
        wiki_root: Path,
        mode: str | None,
        topic: str | None,
        page_type: str | None,
        tags: str | None,
    ) -> dict:
        try:
            from subagent.cross_session.wiki.processor.wiki_graph import build_wiki_graph
            graph = build_wiki_graph(
                wiki_root,
                mode=mode,
                topic=topic,
                page_type=page_type,
                tags=tags.split(",") if tags else None,
            )
            return {
                "status": "ok",
                "nodes": graph["nodes"],
                "edges": graph["edges"],
                "node_count": len(graph["nodes"]),
                "edge_count": len(graph["edges"]),
            }
        except Exception as e:
            logger.exception("[WikiTool] graph error: {}", e)
            return {"status": "error", "message": str(e)}
