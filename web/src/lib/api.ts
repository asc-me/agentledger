/**
 * Typed fetch client. Access token is kept in memory; the refresh token lives in
 * localStorage so a reload can silently re-auth. On a 401 the client attempts one
 * refresh, then retries the original request.
 */
import type {
  ApiKey,
  ApiKeyCreated,
  ChatResponse,
  CodeAnswer,
  CodeForRefRow,
  CodeHit,
  CodeMap,
  CodeNeighbors,
  CodeRef,
  DashboardData,
  GraphLink,
  Item,
  McpToolInfo,
  Member,
  PlatformConfig,
  Prd,
  PrdCoverage,
  PrdStatus,
  PrdSummary,
  PrdVersion,
  Project,
  RequestItem,
  RoadmapPhase,
  Shard,
  ShardHit,
  Status,
  User,
} from "./types";

const REFRESH_KEY = "al_refresh";

let accessToken: string | null = null;

// The project the app is currently scoped to. Writes (create item / shard / PRD,
// platform settings) target this project. ProjectProvider keeps it in sync with the
// active project so no create silently falls back to a non-existent default.
let activeProjectId: string | undefined;
export function setActiveProjectId(id: string | undefined) {
  activeProjectId = id;
}
function projectQuery(): string {
  return activeProjectId ? `?project_id=${encodeURIComponent(activeProjectId)}` : "";
}

export function setRefreshToken(t: string | null) {
  if (t) localStorage.setItem(REFRESH_KEY, t);
  else localStorage.removeItem(REFRESH_KEY);
}
export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}
export function setAccessToken(t: string | null) {
  accessToken = t;
}
export function hasSession(): boolean {
  return !!accessToken || !!getRefreshToken();
}

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function refresh(): Promise<boolean> {
  const rt = getRefreshToken();
  if (!rt) return false;
  const res = await fetch("/api/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: rt }),
  });
  if (!res.ok) {
    setRefreshToken(null);
    accessToken = null;
    return false;
  }
  const data = await res.json();
  accessToken = data.access_token;
  setRefreshToken(data.refresh_token);
  return true;
}

async function request<T>(path: string, opts: RequestInit = {}, retry = true): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(opts.headers as Record<string, string>),
  };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;

  const res = await fetch(`/api${path}`, { ...opts, headers });

  if (res.status === 401 && retry && (await refresh())) {
    return request<T>(path, opts, false);
  }
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  async login(email: string, password: string): Promise<User> {
    const data = await request<{ access_token: string; refresh_token: string }>(
      "/auth/login",
      { method: "POST", body: JSON.stringify({ email, password }) },
      false,
    );
    accessToken = data.access_token;
    setRefreshToken(data.refresh_token);
    return this.me();
  },
  async register(name: string, email: string, handle: string, password: string): Promise<User> {
    const data = await request<{ access_token: string; refresh_token: string }>(
      "/auth/register",
      { method: "POST", body: JSON.stringify({ name, email, handle, password }) },
      false,
    );
    accessToken = data.access_token;
    setRefreshToken(data.refresh_token);
    return this.me();
  },
  logout() {
    accessToken = null;
    setRefreshToken(null);
  },
  me: () => request<User>("/auth/me"),
  myMemberships: () =>
    request<{ project_id: string; project_name: string; accent: string; role: string; access: string }[]>(
      "/auth/me/memberships",
    ),

  projects: () => request<Project[]>("/projects"),
  createProject: (body: { name: string; accent?: string; description?: string }) =>
    request<Project>("/projects", { method: "POST", body: JSON.stringify(body) }),

  items: (projectId?: string) =>
    request<Item[]>(`/items${projectId ? `?project_id=${projectId}` : ""}`),
  createItem: (body: Partial<Item>) =>
    request<Item>("/items", {
      method: "POST",
      body: JSON.stringify({ project_id: activeProjectId, ...body }),
    }),
  updateItem: (id: string, body: Partial<Item>) =>
    request<Item>(`/items/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  reorderItems: (orderedIds: string[]) =>
    request<Item[]>("/items/reorder", {
      method: "PATCH",
      body: JSON.stringify({ ordered_ids: orderedIds }),
    }),

  shards: (projectId?: string) =>
    request<Shard[]>(`/memory/shards${projectId ? `?project_id=${projectId}` : ""}`),
  addShard: (body: { text: string; scope?: string; item_id?: string | null }) =>
    request<Shard>("/memory/shards", {
      method: "POST",
      body: JSON.stringify({ project_id: activeProjectId, ...body }),
    }),
  searchMemory: (query: string, top_k = 5) =>
    request<ShardHit[]>("/memory/search", {
      method: "POST",
      body: JSON.stringify({ query, top_k }),
    }),

  requests: (projectId?: string) =>
    request<RequestItem[]>(`/requests${projectId ? `?project_id=${projectId}` : ""}`),
  voteRequest: (id: string, delta = 1) =>
    request<RequestItem>(`/requests/${id}/vote`, {
      method: "POST",
      body: JSON.stringify({ delta }),
    }),
  linkRequest: (id: string, itemId: string | null) =>
    request<RequestItem>(`/requests/${id}/link`, {
      method: "POST",
      body: JSON.stringify({ item_id: itemId }),
    }),

  apiKeys: () => request<ApiKey[]>("/api-keys"),
  createApiKey: (name: string, projectId: string | null) =>
    request<ApiKeyCreated>("/api-keys", {
      method: "POST",
      body: JSON.stringify({ name, project_id: projectId }),
    }),
  revokeApiKey: (id: string) => request<void>(`/api-keys/${id}`, { method: "DELETE" }),

  prds: (projectId?: string) =>
    request<PrdSummary[]>(`/prds${projectId ? `?project_id=${projectId}` : ""}`),
  prd: (id: string) => request<Prd>(`/prds/${id}`),
  prdCoverage: (id: string) => request<PrdCoverage>(`/prds/${id}/coverage`),
  decomposePrd: (id: string, create: boolean) =>
    request<{ prd_id: string; proposals: { section: string; title: string }[]; created: string[] }>(
      `/prds/${id}/decompose?create=${create}`,
      { method: "POST" },
    ),
  createPrd: (title: string, template = "standard", body?: string) =>
    request<Prd>("/prds", {
      method: "POST",
      body: JSON.stringify({ title, template, project_id: activeProjectId, body }),
    }),
  updatePrd: (id: string, body: { title?: string; status?: PrdStatus; body?: string }) =>
    request<Prd>(`/prds/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  prdVersions: (id: string) => request<PrdVersion[]>(`/prds/${id}/versions`),
  snapshotPrd: (id: string, note: string) =>
    request<Prd>(`/prds/${id}/versions`, { method: "POST", body: JSON.stringify({ note }) }),
  linkPrd: (id: string, itemId: string, add: boolean) =>
    request<Prd>(`/prds/${id}/link`, { method: "POST", body: JSON.stringify({ item_id: itemId, add }) }),
  prdAi: (id: string, command: string) =>
    request<{ text: string }>(`/prds/${id}/ai`, {
      method: "POST",
      body: JSON.stringify({ command }),
    }),

  dashboard: (projectId?: string) =>
    request<DashboardData>(`/dashboard${projectId ? `?project_id=${projectId}` : ""}`),
  roadmap: (projectId?: string) =>
    request<RoadmapPhase[]>(`/roadmap${projectId ? `?project_id=${projectId}` : ""}`),
  links: (projectId?: string) =>
    request<GraphLink[]>(`/links${projectId ? `?project_id=${projectId}` : ""}`),
  mcpTools: () => request<{ live: number; tools: McpToolInfo[] }>("/mcp/tools"),

  platform: () => request<PlatformConfig>(`/platform${projectQuery()}`),
  updatePlatform: (body: Partial<PlatformConfig>) =>
    request<PlatformConfig>(`/platform${projectQuery()}`, { method: "PATCH", body: JSON.stringify(body) }),
  githubConnect: (account: string, repo: string) =>
    request<PlatformConfig>(`/platform/github/connect${projectQuery()}`, { method: "POST", body: JSON.stringify({ account, repo }) }),
  githubDisconnect: () => request<PlatformConfig>(`/platform/github/disconnect${projectQuery()}`, { method: "POST" }),
  gdriveConnect: (account: string, folder: string) =>
    request<PlatformConfig>(`/platform/gdrive/connect${projectQuery()}`, { method: "POST", body: JSON.stringify({ account, folder }) }),
  gdriveDisconnect: () => request<PlatformConfig>(`/platform/gdrive/disconnect${projectQuery()}`, { method: "POST" }),
  gdriveSync: () =>
    request<{
      folder: string;
      prds_dir: string;
      exported: string[];
      imported: string[];
      updated_db: string[];
      updated_file: string[];
      conflicts: string[];
      in_sync: number;
    }>(`/platform/gdrive/sync${projectQuery()}`, { method: "POST" }),
  updateProject: (id: string, body: Partial<Project>) =>
    request<Project>(`/projects/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  members: (id: string) => request<Member[]>(`/projects/${id}/members`),

  chat: (message: string, projectId?: string) =>
    request<ChatResponse>("/agent/chat", {
      method: "POST",
      body: JSON.stringify({ message, project_id: projectId }),
    }),

  /** Stream a chat reply over SSE, invoking onDelta as tokens arrive. */
  async chatStream(
    message: string,
    handlers: { onDelta: (text: string) => void; onShards?: (shards: ShardHit[]) => void },
    projectId?: string,
    retry = true,
  ): Promise<void> {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
    const res = await fetch("/api/agent/chat/stream", {
      method: "POST",
      headers,
      body: JSON.stringify({ message, project_id: projectId }),
    });
    if (res.status === 401 && retry && (await refresh())) {
      return this.chatStream(message, handlers, projectId, false);
    }
    if (!res.ok || !res.body) throw new Error(`stream failed: ${res.status}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx: number;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const frame = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const event = frame.match(/^event: (.*)$/m)?.[1];
        const data = frame.match(/^data: ([\s\S]*)$/m)?.[1];
        if (!event || data === undefined) continue;
        if (event === "delta") handlers.onDelta(JSON.parse(data).text);
        else if (event === "shards") handlers.onShards?.(JSON.parse(data));
      }
    }
  },

  // ── Code structure graph ──────────────────────────────────────────────
  codeMap: (projectId?: string) =>
    request<CodeMap>(`/agent/code/map${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ""}`),
  codeNeighbors: (path: string, projectId?: string) =>
    request<CodeNeighbors>(
      `/agent/code/neighbors?path=${encodeURIComponent(path)}${projectId ? `&project_id=${encodeURIComponent(projectId)}` : ""}`,
    ),
  codeChat: (message: string, projectId?: string) =>
    request<CodeAnswer>("/agent/code", {
      method: "POST",
      body: JSON.stringify({ message, project_id: projectId }),
    }),

  // ── item/request ↔ code bridge ────────────────────────────────────────
  codeForRef: (refId: string, projectId?: string) =>
    request<CodeForRefRow[]>(
      `/agent/code/for?ref_id=${encodeURIComponent(refId)}${projectId ? `&project_id=${encodeURIComponent(projectId)}` : ""}`,
    ),
  codeLink: (body: { ref_id: string; path: string; relation?: string }, projectId?: string) =>
    request<CodeRef>(`/agent/code/link${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ""}`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  codeUnlink: (body: { ref_id: string; path: string; relation?: string }, projectId?: string) =>
    request<{ removed: number }>(`/agent/code/unlink${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ""}`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  /** Stream a code-graph answer over SSE. Emits a `nodes` event, then `delta`s, then `done`. */
  async codeChatStream(
    message: string,
    handlers: { onDelta: (text: string) => void; onNodes?: (nodes: CodeHit[]) => void },
    projectId?: string,
    retry = true,
  ): Promise<void> {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
    const res = await fetch("/api/agent/code/stream", {
      method: "POST",
      headers,
      body: JSON.stringify({ message, project_id: projectId }),
    });
    if (res.status === 401 && retry && (await refresh())) {
      return this.codeChatStream(message, handlers, projectId, false);
    }
    if (!res.ok || !res.body) throw new Error(`stream failed: ${res.status}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx: number;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const frame = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const event = frame.match(/^event: (.*)$/m)?.[1];
        const data = frame.match(/^data: ([\s\S]*)$/m)?.[1];
        if (!event || data === undefined) continue;
        if (event === "delta") handlers.onDelta(JSON.parse(data).text);
        else if (event === "nodes") handlers.onNodes?.(JSON.parse(data));
      }
    }
  },
};

export type { Status };
