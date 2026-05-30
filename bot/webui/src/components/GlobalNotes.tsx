import { useCallback, useEffect, useRef, useState } from "react";
import { FileText, Mic, Plus, Quote, Trash2, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { fetchGlobalNotes, fetchNotesAiReplies, saveGlobalNotes, type AiReplyEntry } from "@/lib/api";
import { useClient } from "@/providers/ClientProvider";

export interface NoteEntry {
  id: string;
  timestamp: number;
  sessionKey: string | null;
  sessionTitle: string | null;
  content: string;
  asrTimestamp?: number;
  /** Reference to a message, format: "user:{index}" or "assistant:{index}" */
  messageRef?: string;
  /** Quoted content when referencing a message */
  quotedContent?: string;
  /** AI reply generated from the notes book, if available */
  aiReply?: AiReplyEntry;
}

export interface GlobalNotesData {
  entries: NoteEntry[];
  lastUpdated: number;
}

const MAX_ENTRIES = 500;

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function getDateKey(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

// Parse markdown content back to entries
export function parseNotesContent(content: string): NoteEntry[] {
  if (!content.trim()) return [];

  const entries: NoteEntry[] = [];
  // Split by --- that marks new entries
  const blocks = content.split(/^---$/gm);

  for (const block of blocks) {
    if (!block.trim() || block.trim().startsWith('# ')) continue;

    const lines = block.trim().split('\n');
    let id = generateId();
    let timestamp = Date.now();
    let sessionKey: string | null = null;
    let sessionTitle: string | null = null;
    let noteContent = "";
    let asrTimestamp: number | undefined;
    let messageRef: string | undefined;
    let quotedContent: string | undefined;
    let isCapturingQuote = false;
    let quoteLines: string[] = [];

    for (const line of lines) {
      // Parse header like: **[2024-01-15 14:30:45] | Session Title** [id:xxx]
      if (line.startsWith('**[') && line.includes(']**')) {
        // Extract id first
        const idMatch = line.match(/\[id:([^\]]+)\]/);
        if (idMatch) {
          id = idMatch[1];
          console.log('[GlobalNotes] Extracted ID from markdown:', id, 'from line:', line);
        }
        const match = line.match(/\*\*\[([^\]]+)\]\s*\|?\s*([^*]*)\*\*/);
        if (match) {
          const dateStr = match[1];
          timestamp = new Date(dateStr).getTime() || Date.now();
          sessionTitle = match[2].trim() || null;
        }
        // Check for ASR timestamp in header
        const asrMatch = line.match(/ASR:\s*\[([^\]]+)\]/);
        if (asrMatch) {
          asrTimestamp = new Date(asrMatch[1]).getTime();
        }
      } else if (line.startsWith('*Session:')) {
        sessionKey = line.slice(10).trim() || null;
      } else if (line.startsWith('*ASR:')) {
        // Already handled in header
      } else if (line.startsWith('> ')) {
        // Quoted content
        const quoteText = line.slice(2);
        quoteLines.push(quoteText);
        if (!isCapturingQuote) {
          isCapturingQuote = true;
          // Check for message ref in quoted content
          const refMatch = quoteText.match(/\[(user|assistant):(\d+)\]/);
          if (refMatch) {
            messageRef = `${refMatch[1]}:${refMatch[2]}`;
          }
        }
      } else if (!line.startsWith('*') && line.trim() !== '') {
        // Regular content
        if (isCapturingQuote && quoteLines.length > 0) {
          quotedContent = quoteLines.join('\n');
          isCapturingQuote = false;
        }
        noteContent += (noteContent ? '\n' : '') + line;
      }
    }

    // Capture quote if still capturing at end
    if (isCapturingQuote && quoteLines.length > 0) {
      quotedContent = quoteLines.join('\n');
    }

    if (noteContent.trim() || quotedContent) {
      entries.push({
        id,
        timestamp,
        sessionKey,
        sessionTitle,
        content: noteContent.trim() || (quotedContent ? '' : ''),
        asrTimestamp,
        messageRef,
        quotedContent,
      });
    }
  }

  return entries;
}

// Note: Markdown generation is now handled by the backend in _generate_notes_markdown()

export interface UseGlobalNotesApi {
  notes: GlobalNotesData;
  isOpen: boolean;
  isLoading: boolean;
  toggle: () => void;
  open: () => void;
  close: () => void;
  addNote: (content: string, sessionKey: string | null, sessionTitle: string | null) => void;
  addNoteWithAsr: (content: string, sessionKey: string | null, sessionTitle: string | null, asrTimestamp: number) => void;
  addNoteWithQuote: (content: string, sessionKey: string | null, sessionTitle: string | null, messageRef: string, quotedContent: string) => void;
  deleteNote: (id: string) => void;
  updateNote: (id: string, content: string) => void;
  clearNotes: () => void;
  refresh: () => Promise<void>;
  dateKey: string;
}

export function useGlobalNotes(): UseGlobalNotesApi {
  const { token } = useClient();
  const [notes, setNotes] = useState<GlobalNotesData>({ entries: [], lastUpdated: Date.now() });
  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const dateKey = getDateKey();
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSavedRef = useRef<string>("");

  const loadNotes = useCallback(() => {
    if (!token) return Promise.resolve();

    setIsLoading(true);
    return Promise.all([
      fetchGlobalNotes(token, dateKey),
      fetchNotesAiReplies(token, "").catch(() => ({ date: "", replies: [] as AiReplyEntry[] })),
    ])
      .then(([data, aiRepliesData]) => {
        const aiReplyMap = new Map<string, AiReplyEntry>();
        for (const reply of aiRepliesData.replies) {
          aiReplyMap.set(reply.noteId, reply);
        }
        const entries = parseNotesContent(data.content).map((entry) => ({
          ...entry,
          aiReply: aiReplyMap.get(entry.id),
        }));
        setNotes({ entries, lastUpdated: Date.now() });
        lastSavedRef.current = data.content;
      })
      .catch(() => {
        // Ignore errors, start with empty notes
        setNotes({ entries: [], lastUpdated: Date.now() });
      })
      .finally(() => setIsLoading(false));
  }, [token, dateKey]);

  // Load notes from server on mount
  useEffect(() => {
    void loadNotes();
  }, [loadNotes]);

  // While the floating notes panel is open, lightly refresh so Notes Book AI
  // replies appear here after the background subagent finishes.
  useEffect(() => {
    if (!isOpen) return;
    const id = window.setInterval(() => {
      void loadNotes();
    }, 5000);
    return () => window.clearInterval(id);
  }, [isOpen, loadNotes]);

  // Save notes to server immediately (real-time)
  const saveNotes = useCallback((entries: NoteEntry[]) => {
    if (!token) return;

    // Skip if entries haven't changed (compare as JSON)
    const entriesJson = JSON.stringify(entries);
    if (entriesJson === lastSavedRef.current) return;

    // Clear existing timeout
    if (saveTimeoutRef.current) {
      clearTimeout(saveTimeoutRef.current);
      saveTimeoutRef.current = null;
    }

    // Save immediately (no debounce for real-time feel)
    // Send entries as structured data, backend generates markdown files
    saveGlobalNotes(token, dateKey, entries)
      .then(() => {
        lastSavedRef.current = entriesJson;
      })
      .catch(() => {
        // Ignore save errors
      });
  }, [token, dateKey]);

  const toggle = useCallback(() => {
    setIsOpen((prev) => !prev);
  }, []);

  const open = useCallback(() => {
    setIsOpen(true);
  }, []);

  const close = useCallback(() => {
    setIsOpen(false);
  }, []);

  const addNote = useCallback(
    (content: string, sessionKey: string | null, sessionTitle: string | null) => {
      if (!content.trim()) return;
      const entry: NoteEntry = {
        id: generateId(),
        timestamp: Date.now(),
        sessionKey,
        sessionTitle,
        content: content.trim(),
      };
      setNotes((prev) => {
        const newEntries = [entry, ...prev.entries].slice(0, MAX_ENTRIES);
        saveNotes(newEntries);
        return { entries: newEntries, lastUpdated: Date.now() };
      });
    },
    [saveNotes],
  );

  const addNoteWithAsr = useCallback(
    (content: string, sessionKey: string | null, sessionTitle: string | null, asrTimestamp: number) => {
      if (!content.trim()) return;
      const entry: NoteEntry = {
        id: generateId(),
        timestamp: Date.now(),
        sessionKey,
        sessionTitle,
        content: content.trim(),
        asrTimestamp,
      };
      setNotes((prev) => {
        const newEntries = [entry, ...prev.entries].slice(0, MAX_ENTRIES);
        saveNotes(newEntries);
        return { entries: newEntries, lastUpdated: Date.now() };
      });
    },
    [saveNotes],
  );

  const addNoteWithQuote = useCallback(
    (content: string, sessionKey: string | null, sessionTitle: string | null, messageRef: string, quotedContent: string) => {
      const entry: NoteEntry = {
        id: generateId(),
        timestamp: Date.now(),
        sessionKey,
        sessionTitle,
        content: content.trim(),
        messageRef,
        quotedContent,
      };
      setNotes((prev) => {
        const newEntries = [entry, ...prev.entries].slice(0, MAX_ENTRIES);
        saveNotes(newEntries);
        return { entries: newEntries, lastUpdated: Date.now() };
      });
    },
    [saveNotes],
  );

  const deleteNote = useCallback((id: string) => {
    setNotes((prev) => {
      const newEntries = prev.entries.filter((e) => e.id !== id);
      saveNotes(newEntries);
      return { entries: newEntries, lastUpdated: Date.now() };
    });
  }, [saveNotes]);

  const updateNote = useCallback((id: string, content: string) => {
    setNotes((prev) => {
      const newEntries = prev.entries.map((e) =>
        e.id === id ? { ...e, content } : e,
      );
      saveNotes(newEntries);
      return { entries: newEntries, lastUpdated: Date.now() };
    });
  }, [saveNotes]);

  const clearNotes = useCallback(() => {
    setNotes({ entries: [], lastUpdated: Date.now() });
    saveNotes([]);
  }, [saveNotes]);

  return {
    notes,
    isOpen,
    isLoading,
    toggle,
    open,
    close,
    addNote,
    addNoteWithAsr,
    addNoteWithQuote,
    deleteNote,
    updateNote,
    clearNotes,
    refresh: loadNotes,
    dateKey,
  };
}

interface GlobalNotesFloatingButtonProps {
  api: UseGlobalNotesApi;
}

export function GlobalNotesFloatingButton({
  api,
}: GlobalNotesFloatingButtonProps) {
  const { t } = useTranslation();
  const todayCount = api.notes.entries.length;

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col items-end gap-2">
      {/* Floating Action Button */}
      <Button
        onClick={api.toggle}
        size="icon"
        className={cn(
          "h-14 w-14 rounded-full shadow-xl transition-all",
          api.isOpen
            ? "bg-muted text-muted-foreground hover:bg-muted/80"
            : "bg-primary text-primary-foreground hover:bg-primary/90",
        )}
        aria-label={api.isOpen ? t("globalNotes.close") : t("globalNotes.open")}
      >
        {api.isOpen ? (
          <X className="h-6 w-6" />
        ) : (
          <FileText className="h-6 w-6" />
        )}
      </Button>

      {/* Note count badge */}
      {!api.isOpen && todayCount > 0 && (
        <div className="absolute -top-1 -right-1 flex h-6 min-w-6 items-center justify-center rounded-full bg-primary px-1.5 text-xs font-medium text-primary-foreground">
          {todayCount}
        </div>
      )}
    </div>
  );
}

interface GlobalNotesPanelProps {
  api: UseGlobalNotesApi;
  sessionKey: string | null;
  sessionTitle: string | null;
  isRecording?: boolean;
  recordingStartedAt?: number | null;
}

export function GlobalNotesPanel({
  api,
  sessionKey,
  sessionTitle,
  isRecording,
  recordingStartedAt,
}: GlobalNotesPanelProps) {
  const { t } = useTranslation();
  const [newNote, setNewNote] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingContent, setEditingContent] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { pendingQuote, clearQuote } = useQuote() ?? {};

  const handleAddNote = useCallback(() => {
    // If there's a pending quote, add with quote
    if (pendingQuote) {
      api.addNoteWithQuote(
        newNote.trim(),
        sessionKey,
        sessionTitle,
        pendingQuote.ref,
        pendingQuote.content,
      );
      clearQuote?.();
    } else if (newNote.trim()) {
      api.addNote(newNote, sessionKey, sessionTitle);
    }
    setNewNote("");
  }, [newNote, sessionKey, sessionTitle, api, pendingQuote, clearQuote]);

  const handleAddWithTimestamp = useCallback(() => {
    if (pendingQuote) {
      api.addNoteWithQuote(
        newNote.trim(),
        sessionKey,
        sessionTitle,
        pendingQuote.ref,
        pendingQuote.content,
      );
      clearQuote?.();
    } else if (newNote.trim()) {
      api.addNoteWithAsr(newNote, sessionKey, sessionTitle, recordingStartedAt || Date.now());
    }
    setNewNote("");
  }, [newNote, sessionKey, sessionTitle, recordingStartedAt, api, pendingQuote, clearQuote]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        handleAddNote();
      }
    },
    [handleAddNote],
  );

  const startEditing = useCallback((id: string, content: string) => {
    setEditingId(id);
    setEditingContent(content);
  }, []);

  const saveEdit = useCallback(() => {
    if (editingId && editingContent.trim()) {
      api.updateNote(editingId, editingContent.trim());
    }
    setEditingId(null);
    setEditingContent("");
  }, [editingId, editingContent, api]);

  const cancelEdit = useCallback(() => {
    setEditingId(null);
    setEditingContent("");
  }, []);

  // Filter entries by session when sessionTitle is provided
  const displayEntries = sessionTitle
    ? api.notes.entries.filter((entry) => entry.sessionTitle === sessionTitle)
    : api.notes.entries;

  if (!api.isOpen) return null;

  return (
    <div className="fixed bottom-24 right-4 z-50 w-96 max-w-[calc(100vw-2rem)]">
      <div className="flex flex-col rounded-2xl border bg-background/98 shadow-2xl backdrop-blur-sm dark:border-white/10 dark:bg-background/95">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border/50 px-4 py-3">
          <div className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-primary" />
            <span className="font-semibold">{t("globalNotes.title")}</span>
            <span className="text-xs text-muted-foreground">({api.dateKey})</span>
          </div>
          <div className="flex items-center gap-2">
            {api.isLoading && (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
            )}
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

        {/* Session info */}
        {sessionTitle && (
          <div className="border-b border-border/50 px-4 py-2">
            <p className="text-xs text-muted-foreground">
              {t("globalNotes.currentSession")}: <span className="font-medium text-foreground">{sessionTitle}</span>
            </p>
          </div>
        )}

        {/* Notes list - show older entries at top */}
        <div className="max-h-96 min-h-[200px] overflow-y-auto p-3">
          {displayEntries.length === 0 && !api.isLoading ? (
            <div className="py-12 text-center text-sm text-muted-foreground">
              <FileText className="mx-auto mb-2 h-10 w-10 opacity-20" />
              <p>{t("globalNotes.empty")}</p>
            </div>
          ) : (
            <div className="space-y-3">
              {displayEntries.map((entry) => (
                <div
                  key={entry.id}
                  className="group rounded-lg border border-border/50 bg-muted/20 p-3"
                >
                  {editingId === entry.id ? (
                    <div className="space-y-2">
                      <Textarea
                        value={editingContent}
                        onChange={(e) => setEditingContent(e.target.value)}
                        rows={3}
                        className="min-h-[60px] resize-none text-sm"
                        autoFocus
                      />
                      <div className="flex justify-end gap-1">
                        <Button size="sm" variant="ghost" onClick={cancelEdit} className="h-7 text-xs">
                          {t("globalNotes.cancel")}
                        </Button>
                        <Button size="sm" onClick={saveEdit} className="h-7 text-xs">
                          {t("globalNotes.save")}
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <>
                      {/* Quote if present */}
                      {entry.quotedContent && (
                        <div className="mb-2 flex items-start gap-2 rounded-md border-l-2 border-primary/30 bg-primary/5 px-2 py-1.5">
                          <Quote className="h-3 w-3 shrink-0 translate-y-0.5 text-primary/60" />
                          <p className="text-xs text-muted-foreground whitespace-pre-wrap">
                            {entry.quotedContent}
                          </p>
                        </div>
                      )}

                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0 flex-1">
                          <p className="text-[10px] text-muted-foreground">
                            <span className="font-medium">{new Date(entry.timestamp).toLocaleTimeString()}</span>
                            {entry.sessionTitle && ` • ${entry.sessionTitle}`}
                            {entry.asrTimestamp && (
                              <span className="ml-1 text-red-500/70">
                                [ASR: {new Date(entry.asrTimestamp).toLocaleTimeString()}]
                              </span>
                            )}
                          </p>
                          {entry.content && (
                            <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed">{entry.content}</p>
                          )}
                          {entry.aiReply && (
                            <div className="mt-2 rounded-md border border-emerald-500/20 bg-emerald-500/5 px-2 py-1.5">
                              <p className="text-[10px] font-medium uppercase tracking-wide text-emerald-600">
                                AI Reply
                              </p>
                              <p className="mt-1 whitespace-pre-wrap text-xs leading-relaxed text-foreground">
                                {entry.aiReply.replyContent}
                              </p>
                            </div>
                          )}
                        </div>
                        <div className="flex gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => startEditing(entry.id, entry.content)}
                            className="h-6 w-6 p-0 text-muted-foreground"
                            title={t("globalNotes.edit")}
                          >
                            <span className="text-xs">Edit</span>
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => api.deleteNote(entry.id)}
                            className="h-6 w-6 p-0 text-muted-foreground hover:text-destructive"
                            title={t("globalNotes.delete")}
                          >
                            <Trash2 className="h-3 w-3" />
                          </Button>
                        </div>
                      </div>
                    </>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Input area */}
        <div className="border-t border-border/50 p-3 space-y-2">
          {/* Pending quote preview */}
          {pendingQuote && (
            <div className="flex items-start gap-2 rounded-md border border-primary/30 bg-primary/5 p-2">
              <Quote className="h-3 w-3 shrink-0 translate-y-0.5 text-primary/60" />
              <p className="flex-1 text-xs text-muted-foreground line-clamp-2 whitespace-pre-wrap">
                {pendingQuote.content}
              </p>
              <button
                type="button"
                onClick={clearQuote}
                className="shrink-0 text-muted-foreground hover:text-foreground"
                title={t("globalNotes.clearQuote")}
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          )}
          <Textarea
            ref={textareaRef}
            value={newNote}
            onChange={(e) => setNewNote(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={pendingQuote ? t("globalNotes.placeholderWithQuote") : t("globalNotes.placeholder")}
            rows={3}
            className="min-h-[70px] resize-none text-sm"
          />
          <div className="flex items-center justify-between">
            <p className="text-[10px] text-muted-foreground">
              {t("globalNotes.cmdEnter")}
            </p>
            <div className="flex gap-1">
              {isRecording && recordingStartedAt && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleAddWithTimestamp}
                  disabled={!newNote.trim() && !pendingQuote}
                  className="h-8 gap-1.5 rounded-full bg-red-50 text-xs dark:bg-red-950/30"
                >
                  <Mic className="h-3 w-3 text-red-500" />
                  <span>{t("globalNotes.withTimestamp")}</span>
                </Button>
              )}
              <Button
                size="sm"
                onClick={handleAddNote}
                disabled={!newNote.trim() && !pendingQuote}
                className="h-8 rounded-full px-4 text-xs"
              >
                <Plus className="mr-1 h-3 w-3" />
                {t("globalNotes.add")}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// Context for quote selection
import { createContext, useContext, type ReactNode } from "react";

interface QuoteContextValue {
  startQuote: (messageRef: string, content: string) => void;
  pendingQuote: { ref: string; content: string } | null;
  clearQuote: () => void;
}

const QuoteContext = createContext<QuoteContextValue | null>(null);

export function QuoteProvider({
  children,
  onQuote,
}: {
  children: ReactNode;
  onQuote?: (ref: string, content: string) => void;
}) {
  const [pendingQuote, setPendingQuote] = useState<{ ref: string; content: string } | null>(null);

  const startQuote = useCallback((messageRef: string, content: string) => {
    // Only set pending quote, don't save yet
    setPendingQuote({ ref: messageRef, content });
    onQuote?.(messageRef, content);
  }, [onQuote]);

  const clearQuote = useCallback(() => {
    setPendingQuote(null);
  }, []);

  return (
    <QuoteContext.Provider value={{ startQuote, pendingQuote, clearQuote }}>
      {children}
    </QuoteContext.Provider>
  );
}

export function useQuote() {
  return useContext(QuoteContext);
}
