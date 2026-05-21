import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { DeleteConfirm } from "@/components/DeleteConfirm";
import { Sidebar } from "@/components/Sidebar";
import { SettingsView } from "@/components/settings/SettingsView";
import { ThreadShell } from "@/components/thread/ThreadShell";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { SessionNotesSheet } from "@/components/SessionNotesSheet";
import { ArticleSelectDialog } from "@/components/ArticleSelectDialog";
import { BenativeProgressIndicator } from "@/components/BenativeProgressIndicator";
import { BenativeNotesSheet } from "@/components/BenativeNotesSheet";

import { useSessions } from "@/hooks/useSessions";
import { useDeferredTitleRefresh } from "@/hooks/useDeferredTitleRefresh";
import { ThemeProvider, useTheme } from "@/hooks/useTheme";
import { cn } from "@/lib/utils";
import {
  clearSavedSecret,
  deriveWsUrl,
  fetchBootstrap,
  loadSavedSecret,
  saveSecret,
} from "@/lib/bootstrap";
import { deriveTitle } from "@/lib/format";
import { NanobotClient } from "@/lib/nanobot-client";
import { ClientProvider, useClient } from "@/providers/ClientProvider";
import type { ChatSummary } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type BootState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "auth"; failed?: boolean }
  | {
      status: "ready";
      client: NanobotClient;
      token: string;
      tokenExpiresAt: number;
      modelName: string | null;
    };

const SIDEBAR_STORAGE_KEY = "nanobot-webui.sidebar";
const RESTART_STARTED_KEY = "nanobot-webui.restartStartedAt";
const SIDEBAR_WIDTH = 272;
const TOKEN_REFRESH_MARGIN_MS = 30_000;
const TOKEN_REFRESH_MIN_DELAY_MS = 5_000;
type ShellView = "chat" | "settings";

function bootstrapTokenExpiresAt(expiresInSeconds: number): number {
  return Date.now() + Math.max(0, expiresInSeconds) * 1000;
}

function tokenRefreshDelayMs(expiresAt: number): number {
  const remaining = Math.max(0, expiresAt - Date.now());
  const margin = Math.min(
    TOKEN_REFRESH_MARGIN_MS,
    Math.max(1_000, remaining / 2),
  );
  return Math.max(TOKEN_REFRESH_MIN_DELAY_MS, remaining - margin);
}

function AuthForm({
  failed,
  onSecret,
}: {
  failed: boolean;
  onSecret: (secret: string) => void;
}) {
  const { t } = useTranslation();
  const [value, setValue] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const secret = value.trim();
    if (!secret) return;
    setSubmitting(true);
    onSecret(secret);
  };

  return (
    <div className="flex h-full w-full items-center justify-center px-6">
      <form
        onSubmit={handleSubmit}
        className="flex w-full max-w-sm flex-col gap-4"
      >
        <div className="flex flex-col items-center gap-1 text-center">
          <p className="text-lg font-semibold">{t("app.auth.title")}</p>
          <p className="text-sm text-muted-foreground">{t("app.auth.hint")}</p>
        </div>
        {failed && (
          <p className="text-center text-sm text-destructive">
            {t("app.auth.invalid")}
          </p>
        )}
        <Input
          type="password"
          placeholder={t("app.auth.placeholder")}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          disabled={submitting}
          autoFocus
        />
        <Button
          type="submit"
          className="w-full"
          disabled={!value.trim() || submitting}
        >
          {t("app.auth.submit")}
        </Button>
      </form>
    </div>
  );
}

function readSidebarOpen(): boolean {
  if (typeof window === "undefined") return true;
  try {
    const raw = window.localStorage.getItem(SIDEBAR_STORAGE_KEY);
    if (raw === null) return true;
    return raw === "1";
  } catch {
    return true;
  }
}

export default function App() {
  const { t } = useTranslation();
  const [state, setState] = useState<BootState>({ status: "loading" });
  const bootstrapSecretRef = useRef("");

  const bootstrapWithSecret = useCallback(
    (secret: string) => {
      let cancelled = false;
      (async () => {
        setState({ status: "loading" });
        try {
          const boot = await fetchBootstrap("", secret);
          if (cancelled) return;
          if (secret) saveSecret(secret);
          const url = deriveWsUrl(boot.ws_path, boot.token);
          let client: NanobotClient;
          client = new NanobotClient({
            url,
            onReauth: async () => {
              try {
                const refreshed = await fetchBootstrap("", bootstrapSecretRef.current);
                const refreshedUrl = deriveWsUrl(refreshed.ws_path, refreshed.token);
                const tokenExpiresAt = bootstrapTokenExpiresAt(refreshed.expires_in);
                setState((current) =>
                  current.status === "ready" && current.client === client
                    ? {
                        ...current,
                        token: refreshed.token,
                        tokenExpiresAt,
                        modelName: refreshed.model_name ?? current.modelName,
                      }
                    : current,
                );
                return refreshedUrl;
              } catch {
                return null;
              }
            },
          });
          bootstrapSecretRef.current = secret;
          client.connect();
          setState({
            status: "ready",
            client,
            token: boot.token,
            tokenExpiresAt: bootstrapTokenExpiresAt(boot.expires_in),
            modelName: boot.model_name ?? null,
          });
        } catch (e) {
          if (cancelled) return;
          const msg = (e as Error).message;
          if (msg.includes("HTTP 401") || msg.includes("HTTP 403")) {
            setState({ status: "auth", failed: true });
          } else {
            setState({ status: "error", message: msg });
          }
        }
      })();
      return () => {
        cancelled = true;
      };
    },
    [],
  );

  useEffect(() => {
    if (state.status !== "ready") return;
    const client = state.client;
    const timer = window.setTimeout(async () => {
      try {
        const boot = await fetchBootstrap("", bootstrapSecretRef.current);
        const url = deriveWsUrl(boot.ws_path, boot.token);
        const tokenExpiresAt = bootstrapTokenExpiresAt(boot.expires_in);
        client.updateUrl(url);
        setState((current) =>
          current.status === "ready" && current.client === client
            ? {
                ...current,
                token: boot.token,
                tokenExpiresAt,
                modelName: boot.model_name ?? current.modelName,
              }
            : current,
        );
      } catch (e) {
        const msg = (e as Error).message;
        if (msg.includes("HTTP 401") || msg.includes("HTTP 403")) {
          setState({ status: "auth", failed: true });
        }
      }
    }, tokenRefreshDelayMs(state.tokenExpiresAt));
    return () => window.clearTimeout(timer);
  }, [state]);

  useEffect(() => {
    const saved = loadSavedSecret();
    return bootstrapWithSecret(saved);
  }, [bootstrapWithSecret]);

  if (state.status === "loading") {
    return (
      <div className="flex h-full w-full items-center justify-center">
        <div className="flex flex-col items-center gap-3 animate-in fade-in-0 duration-300">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-foreground/40" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-foreground/60" />
            </span>
            {t("app.loading.connecting")}
          </div>
        </div>
      </div>
    );
  }
  if (state.status === "auth") {
    return (
      <AuthForm
        failed={!!state.failed}
        onSecret={(s) => bootstrapWithSecret(s)}
      />
    );
  }
  if (state.status === "error") {
    return (
      <div className="flex h-full w-full items-center justify-center px-4 text-center">
        <div className="flex max-w-md flex-col items-center gap-3">
          <p className="text-lg font-semibold">{t("app.error.title")}</p>
          <p className="text-sm text-muted-foreground">{state.message}</p>
          <p className="text-xs text-muted-foreground">
            {t("app.error.gatewayHint")}
          </p>
        </div>
      </div>
    );
  }

  const handleModelNameChange = (modelName: string | null) => {
    setState((current) =>
      current.status === "ready" ? { ...current, modelName } : current,
    );
  };

  const handleLogout = () => {
    if (state.status === "ready") {
      state.client.close();
    }
    clearSavedSecret();
    setState({ status: "auth" });
  };

  return (
    <ClientProvider
      client={state.client}
      token={state.token}
      modelName={state.modelName}
    >
      <Shell onModelNameChange={handleModelNameChange} onLogout={handleLogout} />
    </ClientProvider>
  );
}

function Shell({
  onModelNameChange,
  onLogout,
}: {
  onModelNameChange: (modelName: string | null) => void;
  onLogout: () => void;
}) {
  const { t, i18n } = useTranslation();
  const { client } = useClient();
  const { theme, toggle } = useTheme();
  const { sessions, loading, refresh, createChat, deleteChat } = useSessions();
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [view, setView] = useState<ShellView>("chat");
  const [desktopSidebarOpen, setDesktopSidebarOpen] =
    useState<boolean>(readSidebarOpen);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<{
    key: string;
    label: string;
  } | null>(null);
  const [notesSheetState, setNotesSheetState] = useState<{
    open: boolean;
    sessionKey: string | null;
    title: string;
  }>({ open: false, sessionKey: null, title: "" });
  const [benativeArticleSelectOpen, setBenativeArticleSelectOpen] = useState(false);
  const [benativeNotesSheetState, setBenativeNotesSheetState] = useState<{
    open: boolean;
    sessionKey: string | null;
    title: string;
  }>({ open: false, sessionKey: null, title: "" });
  const restartSawDisconnectRef = useRef(false);
  const [restartToast, setRestartToast] = useState<string | null>(null);
  const [isRestarting, setIsRestarting] = useState(false);
  const [subagentToasts, setSubagentToasts] = useState<
    Array<{ taskId: string; label: string; phase: string }>
  >([]);
  const subagentTimers = useRef<Map<string, number>>(new Map());

  useEffect(() => {
    try {
      window.localStorage.setItem(
        SIDEBAR_STORAGE_KEY,
        desktopSidebarOpen ? "1" : "0",
      );
    } catch {
      // ignore storage errors (private mode, etc.)
    }
  }, [desktopSidebarOpen]);

  // Close notes sheet when switching sessions
  useEffect(() => {
    if (notesSheetState.open && notesSheetState.sessionKey !== activeKey) {
      setNotesSheetState((s) => ({ ...s, open: false }));
    }
  }, [activeKey, notesSheetState.open, notesSheetState.sessionKey]);

  // Close benative sheets when switching sessions
  useEffect(() => {
    if (benativeNotesSheetState.open && benativeNotesSheetState.sessionKey !== activeKey) {
      setBenativeNotesSheetState((s) => ({ ...s, open: false }));
    }
  }, [activeKey, benativeNotesSheetState.open, benativeNotesSheetState.sessionKey]);

  useEffect(() => {
    if (benativeArticleSelectOpen && activeKey === null) {
      setBenativeArticleSelectOpen(false);
    }
  }, [activeKey, benativeArticleSelectOpen]);

  const activeSession = useMemo<ChatSummary | null>(() => {
    if (!activeKey) return null;
    return sessions.find((s) => s.key === activeKey) ?? null;
  }, [sessions, activeKey]);

  const handleBenativeArticleSelect = useCallback(
    (articleId: string) => {
      if (activeSession?.chatId) {
        client.sendMessage(activeSession.chatId, `/benative select ${articleId}`);
      }
      setBenativeArticleSelectOpen(false);
    },
    [activeSession, client],
  );

  const closeDesktopSidebar = useCallback(() => {
    setDesktopSidebarOpen(false);
  }, []);

  const closeMobileSidebar = useCallback(() => {
    setMobileSidebarOpen(false);
  }, []);

  const toggleSidebar = useCallback(() => {
    const isDesktop =
      typeof window !== "undefined" &&
      window.matchMedia("(min-width: 1024px)").matches;
    if (isDesktop) {
      setDesktopSidebarOpen((v) => !v);
    } else {
      setMobileSidebarOpen((v) => !v);
    }
  }, []);

  const onCreateChat = useCallback(async () => {
    try {
      const chatId = await createChat();
      setActiveKey(`websocket:${chatId}`);
      setView("chat");
      setMobileSidebarOpen(false);
      return chatId;
    } catch (e) {
      console.error("Failed to create chat", e);
      return null;
    }
  }, [createChat]);

  const onFreeChat = useCallback(async () => {
    try {
      const chatId = await createChat();
      const key = `websocket:${chatId}`;
      setActiveKey(key);
      setView("chat");
      setMobileSidebarOpen(false);
      // Send /freechat to the new session - the backend will pick a topic and ask the first question
      client.sendMessage(chatId, "/freechat");
    } catch (e) {
      console.error("Failed to create free chat", e);
    }
  }, [createChat, client]);

  const onNewChat = useCallback(() => {
    setActiveKey(null);
    setView("chat");
    setMobileSidebarOpen(false);
  }, []);

  const onSelectChat = useCallback(
    (key: string) => {
      setActiveKey(key);
      setView("chat");
      setMobileSidebarOpen(false);
    },
    [],
  );

  const onOpenSettings = useCallback(() => {
    setView("settings");
    setMobileSidebarOpen(false);
  }, []);

  const onBackToChat = useCallback(() => {
    setView("chat");
    setMobileSidebarOpen(false);
    setActiveKey((current) => {
      if (!current) return null;
      if (sessions.some((session) => session.key === current)) return current;
      return sessions[0]?.key ?? null;
    });
  }, [sessions]);

  const onRestart = useCallback(() => {
    const chatId = activeSession?.chatId ?? client.defaultChatId;
    if (!chatId) return;
    restartSawDisconnectRef.current = false;
    setIsRestarting(true);
    try {
      window.localStorage.setItem(RESTART_STARTED_KEY, String(Date.now()));
    } catch {
      // ignore storage errors
    }
    client.sendMessage(chatId, "/restart");
  }, [activeSession?.chatId, client]);

  useEffect(() => {
    return client.onRuntimeModelUpdate((modelName) => {
      onModelNameChange(modelName);
    });
  }, [client, onModelNameChange]);

  useEffect(() => {
    return client.onSubagentStatus((ev) => {
      setSubagentToasts((prev) => {
        const others = prev.filter((t) => t.taskId !== ev.task_id);
        if (ev.phase === "started") {
          return [...others, { taskId: ev.task_id, label: ev.label, phase: "started" }];
        }
        // done or error: update then schedule removal
        const updated = [...others, { taskId: ev.task_id, label: ev.label, phase: ev.phase }];
        const timer = window.setTimeout(() => {
          setSubagentToasts((p) => p.filter((t) => t.taskId !== ev.task_id));
        }, 3_000);
        const existing = subagentTimers.current.get(ev.task_id);
        if (existing) clearTimeout(existing);
        subagentTimers.current.set(ev.task_id, timer);
        return updated;
      });
    });
  }, [client]);

  useEffect(() => {
    return client.onStatus((status) => {
      let startedAt = 0;
      try {
        startedAt = Number(window.localStorage.getItem(RESTART_STARTED_KEY) ?? "0");
      } catch {
        startedAt = 0;
      }
      if (!startedAt) return;
      if (status !== "open") {
        restartSawDisconnectRef.current = true;
        return;
      }
      const elapsedMs = Date.now() - startedAt;
      if (!restartSawDisconnectRef.current && elapsedMs < 1500) return;
      try {
        window.localStorage.removeItem(RESTART_STARTED_KEY);
      } catch {
        // ignore storage errors
      }
      setIsRestarting(false);
      setRestartToast(t("app.restart.completed", { seconds: (elapsedMs / 1000).toFixed(1) }));
      window.setTimeout(() => setRestartToast(null), 3_500);
    });
  }, [client, t]);

  const onTurnEnd = useDeferredTitleRefresh(activeSession, refresh);

  const onConfirmDelete = useCallback(async () => {
    if (!pendingDelete) return;
    const key = pendingDelete.key;
    const deletingActive = activeKey === key;
    const currentIndex = sessions.findIndex((s) => s.key === key);
    const fallbackKey = deletingActive
      ? (sessions[currentIndex + 1]?.key ?? sessions[currentIndex - 1]?.key ?? null)
      : activeKey;
    setPendingDelete(null);
    if (deletingActive) setActiveKey(fallbackKey);
    try {
      await deleteChat(key);
    } catch (e) {
      if (deletingActive) setActiveKey(key);
      console.error("Failed to delete session", e);
    }
  }, [pendingDelete, deleteChat, activeKey, sessions]);

  const headerTitle = activeSession
    ? activeSession.title ||
      deriveTitle(activeSession.preview, t("chat.newChat"))
    : t("app.brand");

  const handleOpenNotes = useCallback(() => {
    if (activeSession) {
      setNotesSheetState({
        open: true,
        sessionKey: activeSession.key,
        title: activeSession.title || headerTitle,
      });
    }
  }, [activeSession, headerTitle]);

  useEffect(() => {
    if (view === "settings") {
      document.title = t("app.documentTitle.chat", {
        title: t("settings.sidebar.title"),
      });
      return;
    }
    document.title = activeSession
      ? t("app.documentTitle.chat", { title: headerTitle })
      : t("app.documentTitle.base");
  }, [activeSession, headerTitle, i18n.resolvedLanguage, t, view]);

  const sidebarProps = {
    sessions,
    activeKey,
    loading,
    onNewChat,
    onFreeChat,
    onSelect: onSelectChat,
    onRequestDelete: (key: string, label: string) =>
      setPendingDelete({ key, label }),
    onOpenSettings,
  };
  const showMainSidebar = view !== "settings";

  return (
    <ThemeProvider theme={theme}>
      <div className="relative flex h-full w-full overflow-hidden">
        {/* Desktop sidebar: in normal flow, so the thread area width stays honest. */}
        {showMainSidebar ? (
          <aside
            className={cn(
              "relative z-20 hidden shrink-0 overflow-hidden lg:block",
              "transition-[width] duration-300 ease-out",
            )}
            style={{ width: desktopSidebarOpen ? SIDEBAR_WIDTH : 0 }}
          >
            <div
              className={cn(
                "absolute inset-y-0 left-0 h-full overflow-hidden bg-sidebar shadow-inner-right",
                "transition-transform duration-300 ease-out",
                desktopSidebarOpen ? "translate-x-0" : "-translate-x-full",
              )}
              style={{ width: SIDEBAR_WIDTH }}
            >
              <Sidebar {...sidebarProps} onCollapse={closeDesktopSidebar} />
            </div>
          </aside>
        ) : null}

        {showMainSidebar ? (
          <Sheet
            open={mobileSidebarOpen}
            onOpenChange={(open) => setMobileSidebarOpen(open)}
          >
            <SheetContent
              side="left"
              showCloseButton={false}
              className="p-0 lg:hidden"
              style={{ width: SIDEBAR_WIDTH, maxWidth: SIDEBAR_WIDTH }}
            >
              <Sidebar {...sidebarProps} onCollapse={closeMobileSidebar} />
            </SheetContent>
          </Sheet>
        ) : null}

        <main className="relative flex h-full min-w-0 flex-1 flex-col">
          <div
            className={cn(
              "absolute inset-0 flex flex-col",
              view === "settings" && "invisible pointer-events-none",
            )}
          >
            <ThreadShell
              session={activeSession}
              title={headerTitle}
              onToggleSidebar={toggleSidebar}
              onNewChat={onNewChat}
              onCreateChat={onCreateChat}
              onTurnEnd={onTurnEnd}
              onOpenNotes={handleOpenNotes}
              theme={theme}
              onToggleTheme={toggle}
              hideSidebarToggleOnDesktop={desktopSidebarOpen}
              benativeIndicator={
                <BenativeProgressIndicator sessionKey={activeSession?.key ?? null} />
              }
            />
          </div>
          {view === "settings" && (
            <div className="absolute inset-0 flex flex-col">
              <SettingsView
                theme={theme}
                onToggleTheme={toggle}
                onBackToChat={onBackToChat}
                onModelNameChange={onModelNameChange}
                onLogout={onLogout}
                onRestart={onRestart}
                isRestarting={isRestarting}
              />
            </div>
          )}
        </main>

        <DeleteConfirm
          open={!!pendingDelete}
          title={pendingDelete?.label ?? ""}
          onCancel={() => setPendingDelete(null)}
          onConfirm={onConfirmDelete}
        />

        <SessionNotesSheet
          open={notesSheetState.open}
          onOpenChange={(open) =>
            setNotesSheetState((s) => ({ ...s, open }))
          }
          sessionKey={notesSheetState.sessionKey}
          sessionTitle={notesSheetState.title}
        />
        {restartToast ? (
          <div
            role="status"
            className="fixed left-1/2 top-4 z-50 -translate-x-1/2 rounded-full border border-border/70 bg-popover px-4 py-2 text-sm font-medium text-popover-foreground shadow-lg"
          >
            {restartToast}
          </div>
        ) : null}
        {subagentToasts.length > 0 ? (
          <div className="fixed right-4 top-4 z-50 flex flex-col gap-2">
            {subagentToasts.map((t) => (
              <div
                key={t.taskId}
                role="status"
                className={`rounded-lg border px-4 py-2 text-sm font-medium shadow-lg transition-all ${
                  t.phase === "started"
                    ? "border-blue-200 bg-blue-50 text-blue-800 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-200"
                    : t.phase === "error"
                      ? "border-red-200 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200"
                      : "border-green-200 bg-green-50 text-green-800 dark:border-green-800 dark:bg-green-950 dark:text-green-200"
                }`}
              >
                {t.phase === "started"
                  ? `${t.label} subagent running...`
                  : t.phase === "error"
                    ? `${t.label} subagent failed`
                    : `${t.label} subagent completed`}
              </div>
            ))}
          </div>
        ) : null}

        {/* Benative Article Selection Dialog */}
        <ArticleSelectDialog
          open={benativeArticleSelectOpen}
          onOpenChange={setBenativeArticleSelectOpen}
          onSelect={handleBenativeArticleSelect}
        />

        {/* Benative Notes Sheet */}
        <BenativeNotesSheet
          open={benativeNotesSheetState.open}
          onOpenChange={(open) =>
            setBenativeNotesSheetState((s) => ({ ...s, open }))
          }
          sessionKey={benativeNotesSheetState.sessionKey}
          sessionTitle={benativeNotesSheetState.title}
        />
      </div>
    </ThemeProvider>
  );
}
