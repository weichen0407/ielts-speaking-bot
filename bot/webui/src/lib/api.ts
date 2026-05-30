import type {
  ChatSummary,
  ProviderSettingsUpdate,
  SettingsPayload,
  SettingsUpdate,
  SlashCommand,
  WebSearchSettingsUpdate,
  WebuiThreadPersistedPayload,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

async function request<T>(
  url: string,
  token: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(url, {
    ...(init ?? {}),
    headers: {
      ...(init?.headers ?? {}),
      Authorization: `Bearer ${token}`,
    },
    credentials: "same-origin",
  });
  if (!res.ok) {
    throw new ApiError(res.status, `HTTP ${res.status}`);
  }
  const contentType = typeof res.headers?.get === "function"
    ? (res.headers.get("content-type") ?? "")
    : "application/json";
  if (!contentType.toLowerCase().includes("application/json")) {
    const text = await res.text();
    const looksLikeHtml = /^\s*<!doctype|\s*<html/i.test(text);
    throw new ApiError(
      res.status,
      looksLikeHtml
        ? "API returned the WebUI HTML shell instead of JSON. Restart the nanobot gateway so the latest backend routes are loaded."
        : `API returned ${contentType || "a non-JSON response"}`,
    );
  }
  return (await res.json()) as T;
}

function splitKey(key: string): { channel: string; chatId: string } {
  const idx = key.indexOf(":");
  if (idx === -1) return { channel: "", chatId: key };
  return { channel: key.slice(0, idx), chatId: key.slice(idx + 1) };
}

export async function listSessions(
  token: string,
  base: string = "",
): Promise<ChatSummary[]> {
  type Row = {
    key: string;
    created_at: string | null;
    updated_at: string | null;
    title?: string;
    preview?: string;
  };
  const body = await request<{ sessions: Row[] }>(
    `${base}/api/sessions`,
    token,
  );
  return body.sessions.map((s) => ({
    key: s.key,
    ...splitKey(s.key),
    createdAt: s.created_at,
    updatedAt: s.updated_at,
    title: s.title ?? "",
    preview: s.preview ?? "",
  }));
}

/** Disk-backed WebUI display thread snapshot (separate from agent session). */
export async function fetchWebuiThread(
  token: string,
  key: string,
  base: string = "",
): Promise<WebuiThreadPersistedPayload | null> {
  const url = `${base}/api/sessions/${encodeURIComponent(key)}/webui-thread`;
  const res = await fetch(url, {
    headers: { Authorization: `Bearer ${token}` },
    credentials: "same-origin",
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`);
  return (await res.json()) as WebuiThreadPersistedPayload;
}

export async function deleteSession(
  token: string,
  key: string,
  base: string = "",
): Promise<boolean> {
  const body = await request<{ deleted: boolean }>(
    `${base}/api/sessions/${encodeURIComponent(key)}/delete`,
    token,
  );
  return body.deleted;
}

export interface SessionNotes {
  vocab: string;
  polisher: string;
}

export async function fetchSessionNotes(
  token: string,
  key: string,
  base: string = "",
): Promise<SessionNotes> {
  return request<SessionNotes>(
    `${base}/api/sessions/${encodeURIComponent(key)}/notes`,
    token,
  );
}

export interface AdminTrigger {
  id: string;
  name?: string;
  mode: string;
  source: string;
  enabled: boolean;
  condition?: Record<string, unknown>;
  subagent?: string | null;
  model?: string | null;
  prompt_file?: string | null;
  prompt_id?: string;
  task_template?: string | null;
  cursor?: Record<string, unknown> | null;
  error?: string | null;
}

export interface AdminPrompt {
  id: string;
  path: string;
  title: string;
  content: string;
  truncated: boolean;
  error?: string;
}

export interface AdminSubagentStatus {
  timestamp: string;
  chat_id: string;
  task_id: string;
  label: string;
  phase: string;
  error?: string | null;
}

export interface AdminSubagentRun {
  timestamp: string;
  task_id: string;
  label: string;
  phase: string;
  model?: string | null;
  stop_reason?: string | null;
  error?: string | null;
  origin?: Record<string, unknown>;
  task?: string;
  result?: string | null;
  usage?: Record<string, unknown>;
  tool_events?: unknown[];
  artifacts?: Array<{
    path: string;
    status: string;
    content?: string;
    delta?: string;
    truncated?: boolean;
    error?: string;
  }>;
  announce_result?: boolean;
}

export interface AdminActivity {
  kind: "subagent_result" | "tool" | string;
  session_id: string;
  timestamp?: string | null;
  label: string;
  detail: string;
  status?: string;
}

export interface AdminMonitorPayload {
  generated_at: string;
  workspace: string;
  triggers: AdminTrigger[];
  prompts: AdminPrompt[];
  subagent_statuses: AdminSubagentStatus[];
  subagent_runs: AdminSubagentRun[];
  recent_activity: AdminActivity[];
}

export async function fetchAdminMonitor(
  token: string,
  base: string = "",
): Promise<AdminMonitorPayload> {
  return request<AdminMonitorPayload>(`${base}/api/admin/monitor`, token);
}

export async function updateAdminTrigger(
  token: string,
  update: { source: string; id: string; count?: number; enabled?: boolean },
  base: string = "",
): Promise<{ ok: boolean; trigger: AdminTrigger }> {
  const params = new URLSearchParams({
    source: update.source,
    id: update.id,
  });
  if (typeof update.count === "number") params.set("count", String(update.count));
  if (typeof update.enabled === "boolean") params.set("enabled", update.enabled ? "true" : "false");
  return request<{ ok: boolean; trigger: AdminTrigger }>(
    `${base}/api/admin/triggers?${params.toString()}`,
    token,
  );
}

// Global notes API (cross-session user notebook)
export interface GlobalNotesResponse {
  date: string;
  content: string;
}

export interface AllGlobalNotesResponse {
  dates: Array<{
    date: string;
    content: string;
  }>;
}

export async function fetchAllGlobalNotes(
  token: string,
  base: string = "",
): Promise<AllGlobalNotesResponse> {
  return request<AllGlobalNotesResponse>(
    `${base}/api/notes?all_dates=true`,
    token,
  );
}

export async function fetchGlobalNotes(
  token: string,
  date: string,
  base: string = "",
): Promise<GlobalNotesResponse> {
  return request<GlobalNotesResponse>(
    `${base}/api/notes?date=${encodeURIComponent(date)}`,
    token,
  );
}

export async function saveGlobalNotes(
  token: string,
  date: string,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  entries: any[],
  base: string = "",
): Promise<{ date: string; saved: boolean }> {
  // Use GET with query params since WsRequest doesn't expose body directly
  const dataParam = encodeURIComponent(JSON.stringify(entries));
  return request<{ date: string; saved: boolean }>(
    `${base}/api/notes?date=${encodeURIComponent(date)}&data=${dataParam}`,
    token,
  );
}

// Notes AI Assistant API types
export interface AiReplyEntry {
  id: string;
  noteId: string;
  timestamp: number;
  replyContent: string;
  replyType: "encouragement" | "suggestion" | "question" | "correction";
  originalNoteContent?: string;
  quotedContent?: string;
  date?: string;
}

export interface AiReplyResponse {
  task_id: string;
  status: string;
  message?: string;
}

export interface AiReplyStatus {
  task_id: string;
  status: "done" | "running" | "error";
  reply: AiReplyEntry | null;
  error: string | null;
}

export async function triggerNotesAiReply(
  token: string,
  noteId: string,
  date: string,
  noteContent: string,
  quotedContent: string | null,
  replyType: string = "encouragement",
  base: string = "",
): Promise<AiReplyResponse> {
  // Use GET with query params - websockets' HTTP parser only accepts GET
  const params = new URLSearchParams({
    note_id: noteId,
    date: date,
    reply_type: replyType,
    note_content: noteContent,
  });
  if (quotedContent) {
    params.set("quoted_content", quotedContent);
  }
  return request<AiReplyResponse>(
    `${base}/api/notes/ai-reply?${params}`,
    token,
  );
}

export async function fetchNotesAiReplyStatus(
  token: string,
  taskId: string,
  base: string = "",
): Promise<AiReplyStatus> {
  const params = new URLSearchParams({ task_id: taskId });
  return request<AiReplyStatus>(
    `${base}/api/notes/ai-reply/status?${params}`,
    token,
  );
}

export async function fetchNotesAiReplies(
  token: string,
  date: string,
  base: string = "",
): Promise<{ date: string; replies: AiReplyEntry[] }> {
  const params = new URLSearchParams({ date: date });
  return request<{ date: string; replies: AiReplyEntry[] }>(
    `${base}/api/notes/ai-replies?${params}`,
    token,
  );
}

// Benative API types
export interface BenativeArticle {
  id: string;
  title: string;
  source: string;
  topic: string;
  sentence_count: number;
}

export interface BenativeProgress {
  article_id?: string;
  current_sentence?: number;
  total_sentences?: number;
}

export interface BenativeArticleWithPairs {
  article: {
    id: string;
    title: string;
    source: string;
    topic: string;
    content: string;
  };
  pairs: Array<{
    en: string;
    zh: string;
    sentence_index: number;
  }>;
  current_sentence: number;
  total_sentences: number;
}

export interface BenativeResponse {
  session_uuid: string;
  round: number;
  article_id: string;
  zh: string;
  user_en: string;
  timestamp: string;
}

export async function fetchBenativeArticles(
  token: string,
  base: string = "",
): Promise<{ articles: BenativeArticle[] }> {
  return request<{ articles: BenativeArticle[] }>(
    `${base}/api/benative/articles`,
    token,
  );
}

export async function fetchBenativeProgress(
  token: string,
  sessionKey: string,
  base: string = "",
): Promise<BenativeProgress> {
  return request<BenativeProgress>(
    `${base}/api/sessions/${encodeURIComponent(sessionKey)}/benative`,
    token,
  );
}

export async function fetchBenativeArticle(
  token: string,
  sessionKey: string,
  base: string = "",
): Promise<BenativeArticleWithPairs> {
  return request<BenativeArticleWithPairs>(
    `${base}/api/sessions/${encodeURIComponent(sessionKey)}/benative/article`,
    token,
  );
}

export async function fetchBenativeResponses(
  token: string,
  sessionKey: string,
  base: string = "",
): Promise<{ responses: BenativeResponse[] }> {
  return request<{ responses: BenativeResponse[] }>(
    `${base}/api/sessions/${encodeURIComponent(sessionKey)}/benative/responses`,
    token,
  );
}

// IELTS Exam API

export interface IeltsExamQuestion {
  number: number;
  question: string;
  depth: number;
  asked: boolean;
  answer?: string;
  timeSpent?: number;
}

export interface IeltsExamCueCard {
  topic: string;
  bulletPoints: string[];
  asked: boolean;
  answer?: string;
  prepTime?: number;
  speakTime?: number;
}

export interface IeltsExam {
  examId: string;
  topic: string;
  topicTitle?: string;
  state: string;
  currentPart: string;
  currentQuestionIndex: number;
  parts: {
    part1: { questions: IeltsExamQuestion[] };
    part2: { cueCard: IeltsExamCueCard };
    part3: { questions: IeltsExamQuestion[] };
  };
}

export async function startIeltsExam(
  token: string,
  topic?: string,
  random: boolean = false,
  base: string = "",
): Promise<{ exam: IeltsExam; currentQuestion: { number: number; question: string } | null }> {
  let url = `${base}/api/ielts/exam/start`;
  const params: string[] = [];
  if (topic) params.push(`topic=${encodeURIComponent(topic)}`);
  if (random) params.push("random=true");
  if (params.length > 0) url += `?${params.join("&")}`;

  return request<{ exam: IeltsExam; currentQuestion: { number: number; question: string } | null }>(
    url,
    token,
  );
}

export async function submitIeltsExamAnswer(
  token: string,
  examId: string,
  answer: string,
  timeSpent: number = 0,
  base: string = "",
): Promise<{ success: boolean }> {
  return request<{ success: boolean }>(
    `${base}/api/ielts/exam/answer`,
    token,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ examId, answer, timeSpent }),
    },
  );
}

export async function advanceIeltsExam(
  token: string,
  examId: string,
  base: string = "",
): Promise<{
  exam?: { examId: string; state: string; currentPart: string; currentQuestionIndex: number };
  currentQuestion?: { number: number; question: string } | null;
  cueCard?: { topic: string; bulletPoints: string[] } | null;
  completed?: boolean;
}> {
  return request<{
    exam?: { examId: string; state: string; currentPart: string; currentQuestionIndex: number };
    currentQuestion?: { number: number; question: string } | null;
    cueCard?: { topic: string; bulletPoints: string[] } | null;
    completed?: boolean;
  }>(
    `${base}/api/ielts/exam/next`,
    token,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ examId }),
    },
  );
}

export async function endIeltsExam(
  token: string,
  examId: string,
  base: string = "",
): Promise<{ success: boolean }> {
  return request<{ success: boolean }>(
    `${base}/api/ielts/exam/end`,
    token,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ examId }),
    },
  );
}

export async function listIeltsExams(
  token: string,
  base: string = "",
): Promise<{ exams: { examId: string; topic: string; startedAt: string; endedAt: string; finalScore: object }[] }> {
  return request<{ exams: { examId: string; topic: string; startedAt: string; endedAt: string; finalScore: object }[] }>(
    `${base}/api/ielts/exam/list`,
    token,
  );
}

// Wiki Memory API types

export interface WikiSearchResult {
  slug: string;
  title: string;
  type: string;
  mode: string;
  section: string;
  snippet: string;
  score: number;
  tags: string[];
  topics: string[];
}

export interface WikiPageMeta {
  slug: string;
  title: string;
  type: string;
  mode: string;
  tags: string[];
  topics: string[];
  links: string[];
  updated_at: string;
  confidence: "low" | "medium" | "high";
}

export interface WikiPageResponse {
  meta: WikiPageMeta;
  content: string;
}

export interface WikiGraphNode {
  id: string;
  label: string;
  kind: "page" | "tag" | "topic" | "mode";
  type?: string;
  mode?: string;
  tags?: string[];
  topics?: string[];
  updated_at?: string;
  summary?: string;
  size: number;
}

export interface WikiGraphEdge {
  source: string;
  target: string;
  kind: "link" | "has_tag" | "has_topic" | "has_mode";
}

export interface WikiGraphResponse {
  nodes: WikiGraphNode[];
  edges: WikiGraphEdge[];
}

export interface WikiPatchResponse {
  ok: boolean;
  slug: string;
}

export interface WikiRebuildResponse {
  ok: boolean;
  chunks_indexed: number;
}

export async function fetchWikiSearch(
  token: string,
  params: {
    q?: string;
    mode?: string;
    topic?: string;
    type?: string;
    tags?: string;
    limit?: number;
  } = {},
  base: string = "",
): Promise<{ results: WikiSearchResult[]; error?: string }> {
  const searchParams = new URLSearchParams();
  if (params.q) searchParams.set("q", params.q);
  if (params.mode) searchParams.set("mode", params.mode);
  if (params.topic) searchParams.set("topic", params.topic);
  if (params.type) searchParams.set("type", params.type);
  if (params.tags) searchParams.set("tags", params.tags);
  if (params.limit !== undefined) searchParams.set("limit", String(params.limit));
  return request<{ results: WikiSearchResult[]; error?: string }>(
    `${base}/api/wiki/search?${searchParams}`,
    token,
  );
}

export async function fetchWikiPage(
  token: string,
  slug: string,
  base: string = "",
): Promise<WikiPageResponse> {
  const params = new URLSearchParams({ slug });
  return request<WikiPageResponse>(
    `${base}/api/wiki/page?${params}`,
    token,
  );
}

export async function fetchWikiGraph(
  token: string,
  params: {
    mode?: string;
    topic?: string;
    type?: string;
    tags?: string;
  } = {},
  base: string = "",
): Promise<WikiGraphResponse> {
  const searchParams = new URLSearchParams();
  if (params.mode) searchParams.set("mode", params.mode);
  if (params.topic) searchParams.set("topic", params.topic);
  if (params.type) searchParams.set("type", params.type);
  if (params.tags) searchParams.set("tags", params.tags);
  return request<WikiGraphResponse>(
    `${base}/api/wiki/graph?${searchParams}`,
    token,
  );
}

export async function applyWikiPatch(
  token: string,
  patch: Record<string, unknown>,
  base: string = "",
): Promise<WikiPatchResponse> {
  const dataParam = encodeURIComponent(JSON.stringify(patch));
  return request<WikiPatchResponse>(
    `${base}/api/wiki/patch?data=${dataParam}`,
    token,
  );
}

export async function rebuildWikiIndex(
  token: string,
  base: string = "",
): Promise<WikiRebuildResponse> {
  return request<WikiRebuildResponse>(
    `${base}/api/wiki/rebuild-index`,
    token,
  );
}

export async function fetchSettings(
  token: string,
  base: string = "",
): Promise<SettingsPayload> {
  return request<SettingsPayload>(`${base}/api/settings`, token);
}

export async function listSlashCommands(
  token: string,
  base: string = "",
): Promise<SlashCommand[]> {
  type Row = {
    command: string;
    title: string;
    description: string;
    icon: string;
    arg_hint?: string;
  };
  const body = await request<{ commands: Row[] }>(`${base}/api/commands`, token);
  return body.commands
    .filter((command) => !["/stop", "/restart"].includes(command.command))
    .map((command) => ({
      command: command.command,
      title: command.title,
      description: command.description,
      icon: command.icon,
      argHint: command.arg_hint ?? "",
    }));
}

export async function updateSettings(
  token: string,
  update: SettingsUpdate,
  base: string = "",
): Promise<SettingsPayload> {
  const query = new URLSearchParams();
  if (update.model !== undefined) query.set("model", update.model);
  if (update.provider !== undefined) query.set("provider", update.provider);
  return request<SettingsPayload>(`${base}/api/settings/update?${query}`, token);
}

export async function updateProviderSettings(
  token: string,
  update: ProviderSettingsUpdate,
  base: string = "",
): Promise<SettingsPayload> {
  const query = new URLSearchParams();
  query.set("provider", update.provider);
  if (update.apiKey !== undefined) query.set("api_key", update.apiKey);
  if (update.apiBase !== undefined) query.set("api_base", update.apiBase);
  return request<SettingsPayload>(
    `${base}/api/settings/provider/update?${query}`,
    token,
  );
}

export async function updateWebSearchSettings(
  token: string,
  update: WebSearchSettingsUpdate,
  base: string = "",
): Promise<SettingsPayload> {
  const query = new URLSearchParams();
  query.set("provider", update.provider);
  if (update.apiKey !== undefined) query.set("api_key", update.apiKey);
  if (update.baseUrl !== undefined) query.set("base_url", update.baseUrl);
  return request<SettingsPayload>(
    `${base}/api/settings/web-search/update?${query}`,
    token,
  );
}

export interface VoiceSettingsUpdate {
  voice_provider?: "deepgram" | "whisperlivekit";
  whisperlivekit_autostart?: boolean;
  whisperlivekit_url?: string;
  whisperlivekit_language?: string;
  whisperlivekit_model?: string;
}

export async function updateVoiceSettings(
  token: string,
  update: VoiceSettingsUpdate,
  base: string = "",
): Promise<SettingsPayload> {
  const query = new URLSearchParams();
  if (update.voice_provider !== undefined) query.set("voice_provider", update.voice_provider);
  if (update.whisperlivekit_autostart !== undefined) query.set("whisperlivekit_autostart", String(update.whisperlivekit_autostart));
  if (update.whisperlivekit_url !== undefined) query.set("whisperlivekit_url", update.whisperlivekit_url);
  if (update.whisperlivekit_language !== undefined) query.set("whisperlivekit_language", update.whisperlivekit_language);
  if (update.whisperlivekit_model !== undefined) query.set("whisperlivekit_model", update.whisperlivekit_model);
  return request<SettingsPayload>(
    `${base}/api/settings/voice/update?${query}`,
    token,
  );
}
