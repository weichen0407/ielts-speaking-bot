import { useCallback, useEffect, useState } from "react";
import { BookOpen, Filter, RefreshCw, Search, Send, X } from "lucide-react";
import { WikiGraphView } from "@/components/WikiGraphView";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import {
  fetchWikiSearch,
  fetchWikiPage,
  applyWikiPatch,
  rebuildWikiIndex,
  type WikiSearchResult,
  type WikiPageResponse,
} from "@/lib/api";
import { useClient } from "@/providers/ClientProvider";

type ViewTab = "search" | "page" | "patch" | "graph";

interface WikiMemoryPanelApi {
  isOpen: boolean;
  open: () => void;
  close: () => void;
  toggle: () => void;
}

export function useWikiMemoryPanel(): WikiMemoryPanelApi {
  const [isOpen, setIsOpen] = useState(false);
  const open = useCallback(() => setIsOpen(true), []);
  const close = useCallback(() => setIsOpen(false), []);
  const toggle = useCallback(() => setIsOpen((p) => !p), []);
  return { isOpen, open, close, toggle };
}

interface WikiMemoryPanelProps {
  api: WikiMemoryPanelApi;
}

export function WikiMemoryPanel({ api }: WikiMemoryPanelProps) {
  const { token } = useClient();

  // Search state
  const [query, setQuery] = useState("");
  const [modeFilter, setModeFilter] = useState("");
  const [topicFilter, setTopicFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [tagsFilter, setTagsFilter] = useState("");
  const [searchResults, setSearchResults] = useState<WikiSearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  // Page viewer state
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [pageData, setPageData] = useState<WikiPageResponse | null>(null);
  const [isLoadingPage, setIsLoadingPage] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);

  // Patch editor state
  const [patchJson, setPatchJson] = useState("");
  const [patchError, setPatchError] = useState<string | null>(null);
  const [patchSuccess, setPatchSuccess] = useState<string | null>(null);
  const [isApplyingPatch, setIsApplyingPatch] = useState(false);

  // Rebuild state
  const [isRebuilding, setIsRebuilding] = useState(false);
  const [rebuildMessage, setRebuildMessage] = useState<string | null>(null);

  // Tab
  const [activeTab, setActiveTab] = useState<ViewTab>("search");

  const handleGraphFilterClick = useCallback(
    (kind: string, value: string) => {
      if (kind === "mode") setModeFilter(value);
      if (kind === "topic") setTopicFilter(value);
      if (kind === "tag") setTagsFilter(value);
    },
    [],
  );

  const doSearch = useCallback(async () => {
    if (!token) return;
    setIsSearching(true);
    setSearchError(null);
    try {
      const result = await fetchWikiSearch(token, {
        q: query || undefined,
        mode: modeFilter || undefined,
        topic: topicFilter || undefined,
        type: typeFilter || undefined,
        tags: tagsFilter || undefined,
        limit: 20,
      });
      if (result.error) {
        setSearchError(result.error);
        setSearchResults([]);
      } else {
        setSearchResults(result.results);
      }
    } catch (e) {
      setSearchError(String(e));
      setSearchResults([]);
    } finally {
      setIsSearching(false);
    }
  }, [token, query, modeFilter, topicFilter, typeFilter, tagsFilter]);

  const doLoadPage = useCallback(
    async (slug: string) => {
      if (!token) return;
      setSelectedSlug(slug);
      setIsLoadingPage(true);
      setPageError(null);
      setActiveTab("page");
      try {
        const data = await fetchWikiPage(token, slug);
        setPageData(data);
      } catch (e) {
        setPageError(String(e));
        setPageData(null);
      } finally {
        setIsLoadingPage(false);
      }
    },
    [token],
  );

  const doApplyPatch = useCallback(async () => {
    if (!token || !patchJson.trim()) return;
    setIsApplyingPatch(true);
    setPatchError(null);
    setPatchSuccess(null);
    try {
      const patch = JSON.parse(patchJson);
      const result = await applyWikiPatch(token, patch);
      if (result.ok) {
        setPatchSuccess(`Patch applied to ${result.slug}`);
        setPatchJson("");
        // Refresh search if on search tab
        if (activeTab === "search") {
          doSearch();
        }
      } else {
        setPatchError(`Patch failed for ${result.slug}`);
      }
    } catch (e) {
      if (e instanceof SyntaxError) {
        setPatchError(`Invalid JSON: ${e.message}`);
      } else {
        setPatchError(String(e));
      }
    } finally {
      setIsApplyingPatch(false);
    }
  }, [token, patchJson, activeTab, doSearch]);

  const doRebuildIndex = useCallback(async () => {
    if (!token) return;
    setIsRebuilding(true);
    setRebuildMessage(null);
    try {
      const result = await rebuildWikiIndex(token);
      setRebuildMessage(`Indexed ${result.chunks_indexed} chunks`);
    } catch (e) {
      setRebuildMessage(`Error: ${String(e)}`);
    } finally {
      setIsRebuilding(false);
    }
  }, [token]);

  // Auto-search when filters change
  useEffect(() => {
    if (api.isOpen) {
      doSearch();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api.isOpen, modeFilter, topicFilter, typeFilter, tagsFilter]);

  if (!api.isOpen) return null;

  return (
    <div className="fixed bottom-24 right-4 z-50 flex h-[600px] w-[520px] max-w-[calc(100vw-2rem)] flex-col rounded-2xl border bg-background/98 shadow-2xl backdrop-blur-sm dark:border-white/10 dark:bg-background/95">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border/50 px-4 py-3">
        <div className="flex items-center gap-2">
          <BookOpen className="h-5 w-5 text-primary" />
          <span className="font-semibold">Wiki Memory</span>
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            onClick={doRebuildIndex}
            disabled={isRebuilding}
            className="h-7 gap-1 text-xs"
            title="Rebuild search index"
          >
            <RefreshCw className={cn("h-3 w-3", isRebuilding && "animate-spin")} />
            {rebuildMessage ? (
              <span className="max-w-32 truncate text-muted-foreground">{rebuildMessage}</span>
            ) : null}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={api.close}
            className="h-7 w-7 p-0"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-border/50 px-2">
        {(["search", "page", "patch", "graph"] as ViewTab[]).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={cn(
              "px-3 py-2 text-xs font-medium capitalize transition-colors",
              activeTab === tab
                ? "border-b-2 border-primary text-primary"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Search Tab */}
      {activeTab === "search" && (
        <div className="flex flex-1 flex-col overflow-hidden">
          {/* Search bar */}
          <div className="flex gap-2 border-b border-border/30 p-3">
            <div className="relative flex-1">
              <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && doSearch()}
                placeholder="Search wiki..."
                className="pl-8 h-8 text-xs"
              />
            </div>
            <Button size="sm" onClick={doSearch} disabled={isSearching} className="h-8 gap-1">
              <Search className="h-3 w-3" />
              Search
            </Button>
          </div>

          {/* Filters */}
          <div className="flex flex-wrap gap-2 border-b border-border/30 p-2">
            <div className="flex items-center gap-1">
              <Filter className="h-3 w-3 text-muted-foreground" />
              <span className="text-[10px] text-muted-foreground">Filters:</span>
            </div>
            <Input
              value={modeFilter}
              onChange={(e) => setModeFilter(e.target.value)}
              placeholder="mode"
              className="h-6 w-16 text-[10px]"
            />
            <Input
              value={topicFilter}
              onChange={(e) => setTopicFilter(e.target.value)}
              placeholder="topic"
              className="h-6 w-16 text-[10px]"
            />
            <Input
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              placeholder="type"
              className="h-6 w-16 text-[10px]"
            />
            <Input
              value={tagsFilter}
              onChange={(e) => setTagsFilter(e.target.value)}
              placeholder="tags"
              className="h-6 w-16 text-[10px]"
            />
          </div>

          {/* Results */}
          <div className="flex-1 overflow-y-auto p-2">
            {isSearching && (
              <div className="flex items-center justify-center py-8">
                <RefreshCw className="h-4 w-4 animate-spin text-muted-foreground" />
              </div>
            )}
            {searchError && (
              <div className="rounded-md border border-destructive/30 bg-destructive/10 p-2 text-xs text-destructive">
                {searchError}
              </div>
            )}
            {!isSearching && searchResults.length === 0 && !searchError && (
              <div className="py-8 text-center text-xs text-muted-foreground">
                No results. Try adjusting filters or search query.
              </div>
            )}
            {searchResults.map((result) => (
              <button
                key={result.slug}
                onClick={() => doLoadPage(result.slug)}
                className="w-full rounded-md border border-border/30 bg-muted/20 p-2 text-left transition-colors hover:bg-muted/40"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-medium">{result.title}</p>
                    <p className="truncate text-[10px] text-muted-foreground">{result.slug}</p>
                  </div>
                  <div className="flex flex-col items-end gap-0.5">
                    <span className="rounded bg-primary/10 px-1 py-0.5 text-[9px] font-medium text-primary">
                      {result.type}
                    </span>
                    {result.mode && (
                      <span className="text-[9px] text-muted-foreground">{result.mode}</span>
                    )}
                  </div>
                </div>
                {result.snippet && (
                  <p className="mt-1 line-clamp-2 text-[10px] text-muted-foreground">
                    {result.snippet}
                  </p>
                )}
                {result.tags.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {result.tags.slice(0, 5).map((tag) => (
                      <span
                        key={tag}
                        className="rounded bg-muted px-1 py-0.5 text-[9px] text-muted-foreground"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Page Tab */}
      {activeTab === "page" && (
        <div className="flex flex-1 flex-col overflow-hidden">
          {selectedSlug && (
            <div className="border-b border-border/30 px-3 py-1.5">
              <span className="text-[10px] text-muted-foreground">Viewing: </span>
              <span className="text-xs font-medium">{selectedSlug}</span>
            </div>
          )}
          <div className="flex-1 overflow-y-auto p-3">
            {isLoadingPage && (
              <div className="flex items-center justify-center py-8">
                <RefreshCw className="h-4 w-4 animate-spin text-muted-foreground" />
              </div>
            )}
            {pageError && (
              <div className="rounded-md border border-destructive/30 bg-destructive/10 p-2 text-xs text-destructive">
                {pageError}
              </div>
            )}
            {pageData && !isLoadingPage && (
              <div className="space-y-3">
                {/* Meta info */}
                <div className="flex flex-wrap gap-2">
                  <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                    {pageData.meta.type}
                  </span>
                  {pageData.meta.mode && (
                    <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px] text-secondary-foreground">
                      {pageData.meta.mode}
                    </span>
                  )}
                  {pageData.meta.confidence && (
                    <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                      {pageData.meta.confidence}
                    </span>
                  )}
                </div>

                {/* Tags and topics */}
                {(pageData.meta.tags.length > 0 || pageData.meta.topics.length > 0) && (
                  <div className="flex flex-wrap gap-1">
                    {pageData.meta.topics.map((topic) => (
                      <span
                        key={topic}
                        className="rounded bg-blue-100 px-1 py-0.5 text-[9px] text-blue-700 dark:bg-blue-900/30 dark:text-blue-300"
                      >
                        {topic}
                      </span>
                    ))}
                    {pageData.meta.tags.map((tag) => (
                      <span
                        key={tag}
                        className="rounded bg-muted px-1 py-0.5 text-[9px] text-muted-foreground"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                )}

                {/* Links */}
                {pageData.meta.links.length > 0 && (
                  <div className="text-[10px] text-muted-foreground">
                    Links: {pageData.meta.links.join(", ")}
                  </div>
                )}

                {/* Content */}
                <div className="prose prose-sm dark:prose-invert max-w-none rounded-md border border-border/30 bg-muted/20 p-3">
                  <pre className="whitespace-pre-wrap text-xs">{pageData.content}</pre>
                </div>
              </div>
            )}
            {!selectedSlug && !isLoadingPage && (
              <div className="py-8 text-center text-xs text-muted-foreground">
                Select a page from search results to view it.
              </div>
            )}
          </div>
        </div>
      )}

      {/* Graph Tab */}
      {activeTab === "graph" && (
        <div className="flex-1 overflow-hidden">
          <WikiGraphView
            filterMode={modeFilter || undefined}
            filterTopic={topicFilter || undefined}
            filterType={typeFilter || undefined}
            filterTags={tagsFilter || undefined}
            onPageClick={(slug) => doLoadPage(slug)}
            onFilterClick={handleGraphFilterClick}
            interactive={true}
          />
        </div>
      )}

      {/* Patch Tab */}
      {activeTab === "patch" && (
        <div className="flex flex-1 flex-col overflow-hidden p-3">
          <p className="mb-2 text-[10px] text-muted-foreground">
            Paste a WikiPatch JSON object. See schema for valid operations.
          </p>
          <Textarea
            value={patchJson}
            onChange={(e) => setPatchJson(e.target.value)}
            placeholder={'{\n  "operation": "merge_section",\n  "slug": "topic/name",\n  ...\n}'}
            className="flex-1 resize-none font-mono text-[10px]"
          />
          {patchError && (
            <div className="mt-2 rounded-md border border-destructive/30 bg-destructive/10 p-2 text-xs text-destructive">
              {patchError}
            </div>
          )}
          {patchSuccess && (
            <div className="mt-2 rounded-md border border-green-500/30 bg-green-500/10 p-2 text-xs text-green-600 dark:text-green-400">
              {patchSuccess}
            </div>
          )}
          <div className="mt-3 flex justify-end gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setPatchJson("");
                setPatchError(null);
                setPatchSuccess(null);
              }}
              className="h-8 text-xs"
            >
              Clear
            </Button>
            <Button
              size="sm"
              onClick={doApplyPatch}
              disabled={isApplyingPatch || !patchJson.trim()}
              className="h-8 gap-1 text-xs"
            >
              <Send className="h-3 w-3" />
              Apply Patch
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

interface WikiMemoryFloatingButtonProps {
  api: WikiMemoryPanelApi;
}

export function WikiMemoryFloatingButton({ api }: WikiMemoryFloatingButtonProps) {
  return (
    <div className="fixed bottom-24 right-4 z-50">
      <Button
        onClick={api.toggle}
        size="icon"
        className={cn(
          "h-14 w-14 rounded-full shadow-xl transition-all",
          api.isOpen
            ? "bg-muted text-muted-foreground hover:bg-muted/80"
            : "bg-primary text-primary-foreground hover:bg-primary/90",
        )}
        aria-label={api.isOpen ? "Close Wiki Memory" : "Open Wiki Memory"}
      >
        {api.isOpen ? (
          <X className="h-6 w-6" />
        ) : (
          <BookOpen className="h-6 w-6" />
        )}
      </Button>
    </div>
  );
}
