import { BookOpen, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useBenativeProgress } from "@/hooks/useBenative";

interface BenativeProgressIndicatorProps {
  sessionKey: string | null;
  className?: string;
}

export function BenativeProgressIndicator({
  sessionKey,
  className = "",
}: BenativeProgressIndicatorProps) {
  const { t } = useTranslation();
  const { progress, loading } = useBenativeProgress(sessionKey ?? null, !!sessionKey);

  if (!sessionKey || !progress?.article_id) {
    return null;
  }

  const current = progress.current_sentence || 0;
  const total = progress.total_sentences || 0;

  // Calculate progress percentage
  const percentage = total > 0 ? Math.round((current / total) * 100) : 0;

  return (
    <div
      className={`flex items-center gap-2 rounded-full bg-muted px-3 py-1.5 text-xs font-medium ${className}`}
    >
      {loading ? (
        <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
      ) : (
        <BookOpen className="h-3 w-3 text-primary" />
      )}
      <span className="text-muted-foreground">
        {t("benative.sentenceProgress", "Sentence")}
      </span>
      <span className="font-mono text-foreground">
        {current}/{total}
      </span>
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-muted-foreground/20">
        <div
          className="h-full rounded-full bg-primary transition-all duration-300"
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
}
