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
  touchpoints: string[];
  effort: number;
  sort_order: number;
  blocker: string;
  date: string;
  reporter: Reporter;
  pr: PR | null;
  github_url: string;
  assignee: string;
  claimed_by: string | null;
  prd_id: string | null;
  prd_section: string;
  created_at: string;
  updated_at: string;
}

export type ShardStatus = "candidate" | "published" | "rejected";

export interface Shard {
  id: string;
  text: string;
  scope: string;
  source: string;
  status: ShardStatus;
  origin: string;
  item_id: string | null;
  project_id: string | null;
  fresh: boolean;
  created_at: string;
}

export interface ShardCluster {
  size: number;
  representative: Shard;
  members: Shard[];
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
  attachment_ids: string[];
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
  rate_limit_per_min: number;
  turnstile_sitekey: string;
  turnstile_secret_set: boolean;
  active_chat_provider: string;
  provider_config: Record<string, ProviderConfigView>;
}

export type ProviderKind = "stub" | "anthropic" | "openai" | "ollama";

export interface AiProvider {
  id: string;
  label: string;
  kind: ProviderKind;
  embeds: boolean;
  base_url: string;
  chat_model: string;
  embed_model: string;
  auth: boolean;
}

export interface ProviderConfigView {
  base_url: string;
  chat_model: string;
  embed_model: string;
  key_set: boolean;
}

export interface ProviderConfigUpdate {
  api_key?: string;
  base_url?: string;
  chat_model?: string;
  embed_model?: string;
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

export interface PrdCoverageSection {
  section: string;
  item_count: number;
  done: number;
  by_status: Record<string, number>;
  gap: boolean;
  item_ids: string[];
}

export interface PrdCoverage {
  prd_id: string;
  title: string;
  status: PrdStatus;
  sections: PrdCoverageSection[];
  section_count: number;
  sections_with_tasks: number;
  gaps: string[];
  total_items: number;
  done_items: number;
  percent_done: number;
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

// ── Code structure graph ──────────────────────────────────────────────────
export type CodeKind = "module" | "file" | "symbol";
export type CodeEdgeType = "imports" | "calls" | "owns" | "tested_by" | "references";

export interface CodeNode {
  id: string;
  path: string;
  kind: string;
  name: string;
  lang: string;
  summary: string;
  fresh: boolean;
}

export interface CodeEdge {
  src: string;
  dst: string;
  type: CodeEdgeType;
}

export interface CodeHit {
  node: CodeNode;
  score: number;
}

export interface CodeAnswer {
  reply: string;
  nodes: CodeHit[];
}

export interface CodeMap {
  nodes: CodeNode[];
  edges: CodeEdge[];
  node_count: number;
  edge_count: number;
}

export interface CodeLinkedItem {
  id: string;
  title: string;
  status: string;
  relation: string;
}

export interface CodeLinkedRequest {
  id: string;
  title: string;
  type: string;
  status: string;
  relation: string;
}

export interface CodeNeighbors {
  path: string;
  node: CodeNode | null;
  outgoing: { dst: string; type: CodeEdgeType }[];
  incoming: { src: string; type: CodeEdgeType }[];
  items_touching: { id: string; title: string; status: string }[];
  linked_items: CodeLinkedItem[];
  linked_requests: CodeLinkedRequest[];
}

export type CodeRelation = "affects" | "implements" | "fixes" | "tests" | "references";

export interface CodeRef {
  id: number;
  ref_type: string;
  ref_id: string;
  path: string;
  relation: string;
}

export interface CodeForRefRow {
  path: string;
  relation: string;
  node: CodeNode | null;
}

export interface McpToolInfo {
  name: string;
  description: string;
  params: string[];
  calls: number;
  status: string;
}

export interface Event {
  id: number;
  ts: string | null;
  actor_type: "user" | "apikey" | "system";
  actor_id: string;
  actor_label: string;
  surface: "mcp" | "rest" | "public";
  action: string;
  target_type: string;
  target_id: string;
  project_id: string | null;
  meta: Record<string, unknown> | null;
}

export interface EventPage {
  results: Event[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
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
