export type Status = "backlog" | "next" | "in_progress" | "review" | "done" | "blocked";
export type RequestType = "bug" | "feature" | "enhancement" | "feedback";

export interface User {
  id: string;
  name: string;
  handle: string;
  email: string;
  avatar: string;
  initials: string;
}

export interface Project {
  id: string;
  name: string;
  accent: string;
  visibility: string;
  description: string;
  share_global_memory: boolean;
  auto_extract: boolean;
  mcp_enabled: boolean;
  embed_model: string;
}

export interface Reporter {
  name?: string;
  handle?: string;
  avatar?: string;
}

export interface PR {
  number: number;
  title: string;
  branch: string;
  state: string;
  additions: number;
  deletions: number;
  checks: string;
  ago: string;
}

export interface Item {
  id: string;
  project_id: string;
  title: string;
  description: string;
  status: Status;
  tags: string[];
  effort: number;
  sort_order: number;
  blocker: string;
  date: string;
  reporter: Reporter;
  pr: PR | null;
  created_at: string;
  updated_at: string;
}

export interface Shard {
  id: string;
  text: string;
  scope: string;
  source: string;
  item_id: string | null;
  project_id: string | null;
  fresh: boolean;
  created_at: string;
}

export interface ShardHit {
  shard: Shard;
  score: number;
}

export interface RequestItem {
  id: string;
  project_id: string;
  type: RequestType;
  title: string;
  detail: string;
  by: string;
  votes: number;
  status: string;
  linked_to: string | null;
  ago: string;
  source_url: string;
  meta: Record<string, unknown>;
  created_at: string;
}

export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  project_id: string | null;
  last_used: string | null;
  created_at: string;
}

export interface ApiKeyCreated extends ApiKey {
  plaintext: string;
}

export interface ChatResponse {
  reply: string;
  shards: ShardHit[];
}

export type LlmMode = "stub" | "local" | "cloud";

export interface PlatformConfig {
  project_id: string;
  llm_mode: LlmMode;
  local_base_url: string;
  local_model: string;
  cloud_provider: string;
  cloud_model: string;
  github_connected: boolean;
  github_account: string;
  github_repo: string;
  github_scope: string;
  gdrive_connected: boolean;
  gdrive_account: string;
  gdrive_folder: string;
}

export interface Member {
  user: User;
  role: string;
  access: string;
}

export type PrdStatus = "draft" | "review" | "approved";

export interface PrdSummary {
  id: string;
  title: string;
  status: PrdStatus;
  version: string;
  linked: string[];
  updated: string;
}

export interface Prd extends PrdSummary {
  project_id: string;
  body: string;
  created_at: string;
  updated_at: string;
}

export interface PrdVersion {
  id: number;
  version: string;
  date: string;
  note: string;
  body: string;
  created_at: string;
}

export interface RoadmapPhase {
  key: string;
  name: string;
  window: string;
  color: string;
  done: number;
  total: number;
  milestones: { title: string; tag: string; done: boolean }[];
}

export type LinkType = "dependency" | "code" | "semantic" | "tag";

export interface GraphLink {
  id: number;
  a: string;
  b: string;
  type: LinkType;
  confidence: number;
  reason: string;
}

export interface McpToolInfo {
  name: string;
  description: string;
  params: string[];
  calls: number;
  status: string;
}

export interface DashboardData {
  items_total: number;
  items_by_status: Record<Status, number>;
  effort_total: number;
  done_count: number;
  in_progress_count: number;
  blocked_count: number;
  requests_total: number;
  requests_by_type: Record<string, number>;
  requests_by_status: Record<string, number>;
  shard_count: number;
  prd_count: number;
  mcp_calls: number;
  recent_items: { id: string; title: string; status: Status; date: string }[];
}

export interface DuplicateHit {
  kind: "item" | "request";
  id: string;
  title: string;
  score: number;
  type?: string | null;
  status?: string | null;
}

export interface PublicSubmitResponse {
  request: RequestItem;
  duplicates: DuplicateHit[];
}
