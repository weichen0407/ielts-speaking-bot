import { useCallback, useEffect, useMemo, useState } from "react";
import { BookOpen, Calendar, Trash2, Edit3, Quote, Check } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { parseNotesContent, type NoteEntry } from "@/components/GlobalNotes";
import { fetchAllGlobalNotes, saveGlobalNotes, triggerNotesAiReply, fetchNotesAiReplies, fetchNotesAiReplyStatus, type AiReplyEntry } from "@/lib/api";
import { useClient } from "@/providers/ClientProvider";
import { cn } from "@/lib/utils";

interface NotesBookSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAiReplyComplete?: () => void;
}

interface AllNotesEntry extends NoteEntry {
  sourceDate: string;
  aiReply?: AiReplyEntry;
}

export function NotesBookSheet({ open, onOpenChange, onAiReplyComplete }: NotesBookSheetProps) {
  const { t } = useTranslation();
  const { token } = useClient();
  const [allNotes, setAllNotes] = useState<AllNotesEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [selectedDate, setSelectedDate] = useState<string>("");
  const [selectedNote, setSelectedNote] = useState<AllNotesEntry | null>(null);
  const [aiReplyLoading, setAiReplyLoading] = useState<string | null>(null); // noteId of note being processed

  // Fetch all notes when sheet opens
  useEffect(() => {
    if (!open || !token) return;

    setIsLoading(true);

    // Fetch notes and AI replies in parallel
    Promise.all([
      fetchAllGlobalNotes(token),
      fetchNotesAiReplies(token, "").catch(() => ({ date: "", replies: [] as AiReplyEntry[] }))
    ])
      .then(([notesData, aiRepliesData]) => {
        console.log("[NotesBook] fetchNotesAiReplies response:", aiRepliesData);
        // Build a map of noteId -> aiReply
        const aiReplyMap = new Map<string, AiReplyEntry>();
        for (const reply of aiRepliesData.replies) {
          console.log("[NotesBook] Setting aiReplyMap:", reply.noteId, reply);
          aiReplyMap.set(reply.noteId, reply);
        }

        // Parse content from each date into entries
        const entries: AllNotesEntry[] = [];
        for (const item of notesData.dates) {
          const parsed = parseNotesContent(item.content);
          for (const entry of parsed) {
            console.log("[NotesBook] Entry id:", entry.id, "aiReply:", aiReplyMap.get(entry.id));
            entries.push({
              ...entry,
              sourceDate: item.date,
              aiReply: aiReplyMap.get(entry.id),
            });
          }
        }
        // Sort by timestamp descending
        entries.sort((a, b) => b.timestamp - a.timestamp);
        setAllNotes(entries);
      })
      .catch(() => {
        setAllNotes([]);
      })
      .finally(() => setIsLoading(false));
  }, [open, token]);

  // Get all unique dates from notes
  const allDates = useMemo(() => {
    const dateSet = new Set<string>();
    allNotes.forEach((entry) => {
      dateSet.add(entry.sourceDate);
    });
    return Array.from(dateSet).sort().reverse();
  }, [allNotes]);

  // Filter notes by selected date
  const filteredNotes = useMemo(() => {
    if (!selectedDate) return allNotes;
    return allNotes.filter((entry) => entry.sourceDate === selectedDate);
  }, [allNotes, selectedDate]);

  // Group notes by date for display
  const groupedNotes = useMemo(() => {
    const groups: Record<string, AllNotesEntry[]> = {};
    filteredNotes.forEach((entry) => {
      if (!groups[entry.sourceDate]) groups[entry.sourceDate] = [];
      groups[entry.sourceDate].push(entry);
    });
    // Sort entries within each group by timestamp descending
    Object.keys(groups).forEach((key) => {
      groups[key].sort((a, b) => b.timestamp - a.timestamp);
    });
    return groups;
  }, [filteredNotes]);

  const handleDeleteNote = useCallback((note: AllNotesEntry) => {
    // Delete from state immediately (optimistic update)
    setAllNotes((prev) => prev.filter((n) => n.id !== note.id));
    // Also delete from the backend
    if (token) {
      // We need to fetch the current date's notes, remove the entry, and save
      fetchAllGlobalNotes(token).then((data) => {
        const dateItem = data.dates.find((d) => d.date === note.sourceDate);
        if (!dateItem) return;

        const entries = parseNotesContent(dateItem.content);
        const filtered = entries.filter((e) => e.id !== note.id);
        saveGlobalNotes(token, note.sourceDate, filtered).catch(() => {
          // Revert on error
          setAllNotes((prev) => [...prev, note]);
        });
      });
    }
  }, [token]);

  const handleUpdateNote = useCallback((note: AllNotesEntry, content: string) => {
    // Update in state
    setAllNotes((prev) =>
      prev.map((n) => (n.id === note.id ? { ...n, content } : n))
    );
    // Also update in backend
    if (token) {
      fetchAllGlobalNotes(token).then((data) => {
        const dateItem = data.dates.find((d) => d.date === note.sourceDate);
        if (!dateItem) return;

        const entries = parseNotesContent(dateItem.content);
        const updated = entries.map((e) =>
          e.id === note.id ? { ...e, content } : e
        );
        saveGlobalNotes(token, note.sourceDate, updated).catch(() => {
          // Revert on error
          setAllNotes((prev) =>
            prev.map((n) => (n.id === note.id ? note : n))
          );
        });
      });
    }
  }, [token]);

  const handleAiReply = useCallback((note: AllNotesEntry) => {
    if (!token) return;

    setAiReplyLoading(note.id);
    triggerNotesAiReply(
      token,
      note.id,
      note.sourceDate,
      note.content,
      note.quotedContent || null,
      "encouragement"
    )
      .then((data) => {
        console.log("[NotesBook] AI reply triggered:", data);
        // Poll for AI reply status until done
        const pollStatus = () => {
          fetchNotesAiReplyStatus(token, data.task_id)
            .then((status) => {
              if (status.status === "done") {
                // AI reply is ready, refetch all notes with AI replies
                Promise.all([
                  fetchAllGlobalNotes(token),
                  fetchNotesAiReplies(token, "").catch(() => ({ date: "", replies: [] as AiReplyEntry[] }))
                ])
                  .then(([notesData, aiRepliesData]) => {
                    const aiReplyMap = new Map<string, AiReplyEntry>();
                    for (const reply of aiRepliesData.replies) {
                      aiReplyMap.set(reply.noteId, reply);
                    }
                    const entries: AllNotesEntry[] = [];
                    for (const item of notesData.dates) {
                      const parsed = parseNotesContent(item.content);
                      for (const entry of parsed) {
                        entries.push({
                          ...entry,
                          sourceDate: item.date,
                          aiReply: aiReplyMap.get(entry.id),
                        });
                      }
                    }
                    entries.sort((a, b) => b.timestamp - a.timestamp);
                    setAllNotes(entries);
                  })
                  .finally(() => {
                    setAiReplyLoading(null);
                    onAiReplyComplete?.();
                  });
              } else if (status.status === "error") {
                console.error("[NotesBook] AI reply error:", status.error);
                setAiReplyLoading(null);
              } else {
                // Still running, poll again
                setTimeout(pollStatus, 1000);
              }
            })
            .catch((err) => {
              console.error("[NotesBook] Status poll error:", err);
              setAiReplyLoading(null);
            });
        };
        // Start polling after a short delay (give subagent time to start)
        setTimeout(pollStatus, 2000);
      })
      .catch((err) => {
        console.error("[NotesBook] AI reply error:", err);
      })
      .finally(() => {
        // Don't reset loading here, let poll handle it
      });
  }, [token, onAiReplyComplete]);

  return (
    <>
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent
          side="left"
          className="flex flex-col p-0 sm:max-w-md"
        >
          <SheetHeader className="border-b border-border/50 p-4">
            <div className="flex items-center gap-2">
              <BookOpen className="h-5 w-5 text-primary" />
              <SheetTitle>{t("notesBook.title")}</SheetTitle>
            </div>
            <SheetDescription className="sr-only">
              {t("notesBook.description", "Browse saved notes and AI replies across sessions.")}
            </SheetDescription>

            {/* Date filter */}
            <div className="flex items-center gap-2 pt-2">
              <Calendar className="h-4 w-4 text-muted-foreground" />
              <select
                value={selectedDate}
                onChange={(e) => setSelectedDate(e.target.value)}
                className="flex-1 rounded-md border border-border bg-background px-2 py-1.5 text-sm"
              >
                <option value="">{t("notesBook.allDates")}</option>
                {allDates.map((date) => (
                  <option key={date} value={date}>
                    {date}
                  </option>
                ))}
              </select>
              {selectedDate && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setSelectedDate("")}
                  className="h-7 px-2 text-xs"
                >
                  {t("notesBook.clearFilter")}
                </Button>
              )}
            </div>
          </SheetHeader>

          {/* Notes list */}
          <div className="flex-1 overflow-y-auto p-4">
            {isLoading ? (
              <div className="flex items-center justify-center py-12">
                <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
              </div>
            ) : filteredNotes.length === 0 ? (
              <div className="py-12 text-center text-sm text-muted-foreground">
                <BookOpen className="mx-auto mb-2 h-10 w-10 opacity-20" />
                <p>{t("notesBook.empty")}</p>
              </div>
            ) : (
              <div className="space-y-6">
                {Object.entries(groupedNotes)
                  .sort(([a], [b]) => b.localeCompare(a))
                  .map(([dateKey, entries]) => (
                    <div key={dateKey}>
                      <h3 className="mb-3 text-xs font-medium text-muted-foreground">
                        {dateKey}
                      </h3>
                      <div className="space-y-3">
                        {entries.map((entry) => (
                          <NoteCard
                            key={entry.id}
                            entry={entry}
                            onClick={() => setSelectedNote(entry)}
                            onDelete={() => handleDeleteNote(entry)}
                            onAiReply={() => handleAiReply(entry)}
                            isAiReplying={aiReplyLoading === entry.id}
                          />
                        ))}
                      </div>
                    </div>
                  ))}
              </div>
            )}
          </div>
        </SheetContent>
      </Sheet>

      {/* Note detail dialog */}
      {selectedNote && (
        <NoteDetailDialog
          open={!!selectedNote}
          onOpenChange={(open) => !open && setSelectedNote(null)}
          entry={selectedNote}
          onUpdate={(content) => handleUpdateNote(selectedNote, content)}
          onDelete={() => {
            handleDeleteNote(selectedNote);
            setSelectedNote(null);
          }}
          onAiReply={() => handleAiReply(selectedNote)}
          isAiReplying={aiReplyLoading === selectedNote.id}
        />
      )}
    </>
  );
}

interface NoteCardProps {
  entry: AllNotesEntry;
  onClick: () => void;
  onDelete: () => void;
  onAiReply: () => void;
  isAiReplying: boolean;
}

function NoteCard({ entry, onClick, onDelete, onAiReply, isAiReplying }: NoteCardProps) {
  const { t } = useTranslation();
  const [showActions, setShowActions] = useState(false);
  const time = new Date(entry.timestamp).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <div
      className="group relative cursor-pointer rounded-lg border border-border/50 bg-muted/20 p-3 transition-colors hover:bg-muted/30"
      onClick={onClick}
      onMouseEnter={() => setShowActions(true)}
      onMouseLeave={() => setShowActions(false)}
    >
      {/* Quote preview */}
      {entry.quotedContent && (
        <div className="mb-2 flex items-start gap-2 rounded-md border-l-2 border-primary/30 bg-primary/5 px-2 py-1.5">
          <Quote className="h-3 w-3 shrink-0 translate-y-0.5 text-primary/60" />
          <p className="line-clamp-2 text-xs text-muted-foreground">
            {entry.quotedContent}
          </p>
        </div>
      )}

      {/* Content */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-[10px] text-muted-foreground">
            <span className="font-medium">{time}</span>
            {entry.sessionTitle && ` • ${entry.sessionTitle}`}
            {entry.aiReply && (
              <span title="AI reply ready">
                <Check className="ml-1 inline-block h-3 w-3 text-green-500" />
              </span>
            )}
          </p>
          {entry.content && (
            <p className="mt-1 line-clamp-3 whitespace-pre-wrap text-sm leading-relaxed">
              {entry.content}
            </p>
          )}
        </div>
      </div>

      {/* Actions */}
      <div
        className={cn(
          "absolute right-2 top-2 flex gap-1 transition-opacity",
          showActions ? "opacity-100" : "opacity-0",
        )}
      >
        <Button
          variant="ghost"
          size="sm"
          onClick={(e) => {
            e.stopPropagation();
            onAiReply();
          }}
          className={cn(
            "h-6 px-2 text-xs",
            isAiReplying ? "text-primary" : "text-muted-foreground hover:text-primary"
          )}
          title={t("notesBook.aiReply")}
          disabled={isAiReplying}
        >
          {isAiReplying ? (
            <>
              <div className="mr-1 h-3 w-3 animate-spin rounded-full border border-primary border-t-transparent" />
              {t("notesBook.aiReplying")}
            </>
          ) : (
            t("notesBook.aiReply")
          )}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          className="h-6 w-6 p-0 text-muted-foreground hover:text-destructive"
          title={t("notesBook.delete")}
        >
          <Trash2 className="h-3 w-3" />
        </Button>
      </div>
    </div>
  );
}

interface NoteDetailDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  entry: AllNotesEntry;
  onUpdate: (content: string) => void;
  onDelete: () => void;
  onAiReply: () => void;
  isAiReplying: boolean;
}

function NoteDetailDialog({
  open,
  onOpenChange,
  entry,
  onUpdate,
  onDelete,
  onAiReply,
  isAiReplying,
}: NoteDetailDialogProps) {
  const { t } = useTranslation();
  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState(entry.content);

  const handleSave = () => {
    if (editContent.trim()) {
      onUpdate(editContent.trim());
    }
    setIsEditing(false);
  };

  const datetime = new Date(entry.timestamp).toLocaleString();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent
          className="max-h-[80vh] overflow-y-auto"
        >
          <DialogHeader>
            <DialogTitle>{t("notesBook.noteDetail")}</DialogTitle>
            <DialogDescription className="sr-only">
              {t("notesBook.noteDetailDescription", "View, edit, delete, or ask AI about this saved note.")}
            </DialogDescription>
          </DialogHeader>

          {/* Meta info */}
          <div className="mb-4 space-y-1 text-xs text-muted-foreground">
            <p>{datetime}</p>
            {entry.sessionTitle && <p>{entry.sessionTitle}</p>}
            <p className="text-primary/70">{entry.sourceDate}</p>
          </div>

          {/* Quote */}
          {entry.quotedContent && (
            <div className="mb-4 flex items-start gap-2 rounded-md border-l-2 border-primary/30 bg-primary/5 p-3">
              <Quote className="h-4 w-4 shrink-0 translate-y-0.5 text-primary/60" />
              <p className="text-sm text-muted-foreground whitespace-pre-wrap">
                {entry.quotedContent}
              </p>
            </div>
          )}

          {/* Content */}
          {isEditing ? (
            <div className="space-y-3">
              <Textarea
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                rows={6}
                className="min-h-[120px] resize-none"
                autoFocus
              />
              <div className="flex justify-end gap-2">
                <Button variant="outline" size="sm" onClick={() => {
                  setIsEditing(false);
                  setEditContent(entry.content);
                }}>
                  {t("notesBook.cancel")}
                </Button>
                <Button size="sm" onClick={handleSave}>
                  {t("notesBook.save")}
                </Button>
              </div>
            </div>
          ) : (
            <p className="whitespace-pre-wrap text-sm leading-relaxed">
              {entry.content || t("notesBook.noContent")}
            </p>
          )}

          {/* AI Reply Section */}
          {entry.aiReply && (
            <div className="mt-4 rounded-lg border border-primary/30 bg-primary/5 p-4">
              <div className="mb-2 flex items-center gap-2">
                <span className="text-xs font-medium text-primary">AI 回复</span>
                <span className="text-xs text-muted-foreground">
                  {new Date(entry.aiReply.timestamp).toLocaleString()}
                </span>
              </div>
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">
                {entry.aiReply.replyContent}
              </p>
            </div>
          )}

          {/* Actions */}
          {!isEditing && (
            <div className="mt-6 flex justify-end gap-2 border-t border-border/50 pt-4">
              <Button
                variant="outline"
                size="sm"
                onClick={onAiReply}
                disabled={isAiReplying}
              >
                {isAiReplying ? (
                  <>
                    <div className="mr-1 h-4 w-4 animate-spin rounded-full border border-primary border-t-transparent" />
                    {t("notesBook.aiReplying")}
                  </>
                ) : (
                  t("notesBook.aiReply")
                )}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={onDelete}
                className="text-destructive hover:text-destructive"
              >
                <Trash2 className="mr-1 h-4 w-4" />
                {t("notesBook.delete")}
              </Button>
              <Button variant="outline" size="sm" onClick={() => {
                setEditContent(entry.content);
                setIsEditing(true);
              }}>
                <Edit3 className="mr-1 h-4 w-4" />
                {t("notesBook.edit")}
              </Button>
            </div>
          )}
        </DialogContent>
    </Dialog>
  );
}
