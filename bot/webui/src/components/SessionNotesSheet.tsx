import { BookOpen, Loader2, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useSessionNotes } from "@/hooks/useSessionNotes";
import MarkdownTextRenderer from "@/components/MarkdownTextRenderer";
import React from "react";

interface SessionNotesSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sessionKey: string | null;
  sessionTitle?: string;
}

type Tab = "vocab" | "polisher" | "review";

export function SessionNotesSheet({
  open,
  onOpenChange,
  sessionKey,
  sessionTitle,
}: SessionNotesSheetProps) {
  const { t } = useTranslation();
  const { notes, loading, error } = useSessionNotes(
    open ? sessionKey : null,
    open,
  );
  const [activeTab, setActiveTab] = React.useState<Tab>("vocab");
  const isBenative = notes.mode === "benative";
  const availableTabs = React.useMemo<Tab[]>(
    () => (isBenative ? ["review"] : ["vocab", "polisher"]),
    [isBenative],
  );
  const hasAnyNotes = Boolean(notes.vocab || notes.polisher || notes.review);

  // Reset to the mode-appropriate tab when sheet opens or session changes.
  React.useEffect(() => {
    if (open) {
      setActiveTab(isBenative ? "review" : "vocab");
    }
  }, [open, sessionKey, isBenative]);

  React.useEffect(() => {
    if (!availableTabs.includes(activeTab)) {
      setActiveTab(availableTabs[0]);
    }
  }, [activeTab, availableTabs]);

  const renderContent = () => {
    if (loading && !notes.vocab && !notes.polisher && !notes.review) {
      return (
        <div className="flex flex-1 items-center justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      );
    }

    if (error) {
      return (
        <div className="flex flex-1 items-center justify-center py-12 text-sm text-destructive">
          {error}
        </div>
      );
    }

    const content =
      activeTab === "vocab"
        ? notes.vocab
        : activeTab === "polisher"
          ? notes.polisher
          : notes.review;

    if (!content || content.trim() === "") {
      const modeLabel = isBenative ? "Be Native" : "Freechat";
      const artifactLabel = activeTab === "vocab"
        ? "vocab"
        : activeTab === "polisher"
          ? "polisher"
          : "review";
      return (
        <div className="flex flex-1 flex-col items-center justify-center py-12 text-center text-sm text-muted-foreground">
          <BookOpen className="mb-2 h-4 w-4" />
          <p>
            {activeTab === "vocab"
              ? t("notes.emptyVocab", "No vocabulary notes yet")
              : activeTab === "polisher"
                ? t("notes.emptyGrammar", "No grammar notes yet")
                : t("notes.emptyReview", "No review notes yet")}
          </p>
          <p className="mt-1 max-w-xs text-xs">
            {t(
              "notes.emptyReason",
              "{{mode}} {{artifact}} artifact has not been created yet. Check monitor for trigger disabled, no new input, or processor failure.",
              { mode: modeLabel, artifact: artifactLabel },
            )}
          </p>
        </div>
      );
    }

    return <MarkdownTextRenderer className="text-sm">{content}</MarkdownTextRenderer>;
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="flex flex-col bg-background/95 backdrop-blur-xlsupports-[backdrop-filter]:bg-background/80"
        style={{ width: "min(600px, 95vw)" }}
      >
        <SheetHeader className="flex-row items-center justify-between space-y-0 pb-4">
          <SheetTitle className="text-base font-semibold">
            {sessionTitle || t("notes.title", "Session Notes")}
          </SheetTitle>
          <SheetDescription className="sr-only">
            {t("notes.description", "Mode-specific learning artifacts for this session.")}
          </SheetDescription>
          {loading && hasAnyNotes && (
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          )}
        </SheetHeader>

        <div className="flex gap-1 border-b border-border/50">
          {availableTabs.map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`flex items-center gap-1.5 border-b-2 px-4 py-2.5 text-sm font-medium transition-colors ${
                activeTab === tab
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {tab === "vocab" ? <BookOpen className="h-4 w-4" /> : null}
              {tab === "vocab"
                ? t("notes.vocabulary", "Vocabulary")
                : tab === "polisher"
                  ? t("notes.grammar", "Grammar")
                  : t("notes.review", "Review")}
            </button>
          ))}
        </div>

        <div className="mt-4 flex-1 overflow-y-auto pr-2">
          {renderContent()}
        </div>

        <div className="mt-4 flex items-center justify-between border-t border-border/50 pt-4 text-xs text-muted-foreground">
          <span>{t("notes.hint", "Use ==word== to highlight key words")}</span>
          <button
            onClick={() => onOpenChange(false)}
            className="flex items-center gap-1 hover:text-foreground"
          >
            <X className="h-3 w-3" />
            {t("notes.close", "Close")}
          </button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
