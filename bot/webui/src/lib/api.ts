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
