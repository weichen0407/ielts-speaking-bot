import { BookOpen, FileText, Globe, Loader2, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useBenativeArticles } from "@/hooks/useBenative";

interface ArticleSelectDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSelect: (articleId: string) => void;
}

export function ArticleSelectDialog({
  open,
  onOpenChange,
  onSelect,
}: ArticleSelectDialogProps) {
  const { t } = useTranslation();
  const { articles, loading, error } = useBenativeArticles(open);

  const getTopicIcon = (topic: string) => {
    switch (topic.toLowerCase()) {
      case "politics":
        return <Globe className="h-4 w-4 text-blue-500" />;
      case "economy":
        return <FileText className="h-4 w-4 text-green-500" />;
      case "sports":
        return <Globe className="h-4 w-4 text-orange-500" />;
      case "technology":
        return <Globe className="h-4 w-4 text-purple-500" />;
      default:
        return <BookOpen className="h-4 w-4 text-gray-500" />;
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-2xl max-h-[80vh] overflow-hidden flex flex-col"
      >
        <DialogHeader className="flex-row items-center justify-between space-y-0">
          <DialogTitle className="text-lg font-semibold">
            {t("benative.selectArticle", "Select an Article to Practice")}
          </DialogTitle>
          <DialogDescription className="sr-only">
            {t(
              "benative.hint",
              "Practice translating Chinese to English sentence by sentence",
            )}
          </DialogDescription>
          <button
            onClick={() => onOpenChange(false)}
            className="rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100"
          >
            <X className="h-4 w-4" />
            <span className="sr-only">Close</span>
          </button>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto">
          {loading && articles.length === 0 && (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          )}

          {error && (
            <div className="flex items-center justify-center py-12 text-sm text-destructive">
              {error}
            </div>
          )}

          {!loading && articles.length === 0 && !error && (
            <div className="flex flex-col items-center justify-center py-12 text-sm text-muted-foreground">
              <BookOpen className="mb-3 h-10 w-10 opacity-50" />
              <p>{t("benative.noArticles", "No articles available")}</p>
              <p className="mt-1 text-xs">
                {t(
                  "benative.articlesFetched",
                  "Add sources and let the Be Native Article processor generate sentence pairs.",
                )}
              </p>
            </div>
          )}

          {articles.length > 0 && (
            <div className="space-y-2 p-1">
              {articles.map((article, index) => (
                <button
                  key={article.id}
                  onClick={() => {
                    onSelect(article.id);
                    onOpenChange(false);
                  }}
                  className="w-full text-left rounded-lg border border-border/50 bg-card p-4 transition-colors hover:bg-accent/50 hover:border-border"
                >
                  <div className="flex items-start gap-3">
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-muted">
                      <span className="text-sm font-medium text-muted-foreground">
                        {index + 1}
                      </span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        {getTopicIcon(article.topic)}
                        <span className="text-xs font-medium text-muted-foreground uppercase">
                          {article.topic}
                        </span>
                        <span className="text-xs text-muted-foreground">
                          • {article.source}
                        </span>
                      </div>
                      <h3 className="mt-1 font-medium leading-snug line-clamp-2">
                        {article.title}
                      </h3>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {article.sentence_count}{" "}
                        {t("benative.sentences", "sentences")}
                      </p>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="mt-4 flex items-center justify-between border-t border-border/50 pt-4 text-xs text-muted-foreground">
          <span>
            {t(
              "benative.hint",
              "Practice translating Chinese to English sentence by sentence",
            )}
          </span>
        </div>
      </DialogContent>
    </Dialog>
  );
}
