import { BookOpen, CheckCircle, FileText, Loader2, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useBenativeProgress, useBenativeResponses } from "@/hooks/useBenative";
import React from "react";

interface BenativeNotesSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sessionKey: string | null;
  sessionTitle?: string;
  onSelectArticle?: () => void;
}

type Tab = "review" | "responses";

export function BenativeNotesSheet({
  open,
  onOpenChange,
  sessionKey,
  sessionTitle,
}: BenativeNotesSheetProps) {
  const { t } = useTranslation();
  const { progress } = useBenativeProgress(sessionKey ?? null, open);
  const { responses, loading: responsesLoading } = useBenativeResponses(
    sessionKey ?? null,
    open,
  );
  const [activeTab, setActiveTab] = React.useState<Tab>("responses");

  // Reset to responses tab when sheet opens
  React.useEffect(() => {
    if (open) {
      setActiveTab("responses");
    }
  }, [open]);

  const hasProgress = progress?.article_id;
  const reviewedCount = responses.filter((r) => r.round % 10 === 0).length;

  const renderResponses = () => {
    if (!hasProgress) {
      return (
        <div className="flex flex-1 items-center justify-center py-12 text-sm text-muted-foreground">
          <BookOpen className="mr-2 h-4 w-4" />
          {t("benative.noArticleSelected", "No article selected yet")}
        </div>
      );
    }

    if (responsesLoading && responses.length === 0) {
      return (
        <div className="flex flex-1 items-center justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      );
    }

    if (responses.length === 0) {
      return (
        <div className="flex flex-1 items-center justify-center py-12 text-sm text-muted-foreground">
          <FileText className="mr-2 h-4 w-4" />
          {t("benative.noResponses", "No responses yet")}
        </div>
      );
    }

    return (
      <div className="space-y-4">
        {responses.map((response, index) => (
          <div
            key={index}
            className="rounded-lg border border-border/50 bg-card p-3"
          >
            <div className="flex items-center gap-2 text-xs text-muted-foreground mb-2">
              <span>#{response.round}</span>
              <span>•</span>
              <span>{new Date(response.timestamp).toLocaleTimeString()}</span>
            </div>
            <div className="space-y-2">
              <div className="rounded bg-muted/50 p-2">
                <p className="text-xs text-muted-foreground mb-1">中文:</p>
                <p className="text-sm">{response.zh}</p>
              </div>
              <div className="rounded bg-primary/5 p-2">
                <p className="text-xs text-muted-foreground mb-1">Your translation:</p>
                <p className="text-sm">{response.user_en}</p>
              </div>
            </div>
          </div>
        ))}
      </div>
    );
  };

  const renderReview = () => {
    if (!hasProgress) {
      return (
        <div className="flex flex-1 items-center justify-center py-12 text-sm text-muted-foreground">
          <BookOpen className="mr-2 h-4 w-4" />
          {t("benative.noArticleSelected", "No article selected yet")}
        </div>
      );
    }

    // For now, show a placeholder since review comes from subagent
    return (
      <div className="flex flex-col items-center justify-center py-12 text-sm text-muted-foreground">
        <CheckCircle className="mb-3 h-10 w-10 text-muted-foreground/50" />
        <p>{t("benative.reviewHint", "Review is generated every 10 sentences")}</p>
        <p className="mt-1 text-xs">
          {reviewedCount > 0
            ? `${reviewedCount} reviews available`
            : "Complete 10 sentences to get your first review"}
        </p>
      </div>
    );
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
            {sessionTitle || t("benative.title", "Benative Practice")}
          </SheetTitle>
          <SheetDescription className="sr-only">
            {t("benative.notesDescription", "Current Be Native article progress, responses, and review artifacts.")}
          </SheetDescription>
          {responsesLoading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
        </SheetHeader>

        {hasProgress && (
          <div className="mb-4 rounded-lg bg-muted/50 p-3">
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">
                {t("benative.progress", "Progress")}
              </span>
              <span className="font-mono font-medium">
                {progress.current_sentence || 0}/{progress.total_sentences || 0}
              </span>
            </div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted-foreground/20">
              <div
                className="h-full rounded-full bg-primary transition-all"
                style={{
                  width: `${
                    progress.total_sentences
                      ? Math.round(
                          ((progress.current_sentence || 0) / progress.total_sentences) * 100,
                        )
                      : 0
                  }%`,
                }}
              />
            </div>
          </div>
        )}

        <div className="flex gap-1 border-b border-border/50">
          <button
            onClick={() => setActiveTab("responses")}
            className={`flex items-center gap-1.5 border-b-2 px-4 py-2.5 text-sm font-medium transition-colors ${
              activeTab === "responses"
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            <FileText className="h-4 w-4" />
            {t("benative.responses", "Responses")}
          </button>
          <button
            onClick={() => setActiveTab("review")}
            className={`flex items-center gap-1.5 border-b-2 px-4 py-2.5 text-sm font-medium transition-colors ${
              activeTab === "review"
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            <CheckCircle className="h-4 w-4" />
            {t("benative.review", "Review")}
          </button>
        </div>

        <div className="mt-4 flex-1 overflow-y-auto pr-2">
          {activeTab === "responses" ? renderResponses() : renderReview()}
        </div>

        <div className="mt-4 flex items-center justify-between border-t border-border/50 pt-4 text-xs text-muted-foreground">
          <span>
            {t(
              "benative.hint",
              "Compare your translations with the original English",
            )}
          </span>
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
