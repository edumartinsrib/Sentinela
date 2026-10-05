// Tipos da API do Sentinela (espelham sentinela_api/schemas.py).

export type Role = 'admin' | 'tech_lead' | 'reviewer' | 'developer' | 'reader';
export type Severity = 'blocker' | 'high' | 'medium' | 'low' | 'info';
export type Category =
  | 'security'
  | 'architecture'
  | 'structure'
  | 'standards'
  | 'tests'
  | 'performance'
  | 'docs'
  | 'other';
export type RuleKind = 'ai' | 'pattern';
export type FindingStatus = 'open' | 'disputed' | 'waived' | 'false_positive';
export type FindingSource = 'ai' | 'pattern';
export type Provider = 'github' | 'gitlab';
export type GateMode = 'status_check' | 'platform_merge' | 'both';
export type Enforcement = 'enforce' | 'observe';
export type ApprovalMode = 'ai_when_clean' | 'always_human';
export type MergeMethod = 'merge' | 'squash' | 'rebase';
export type PullRequestState = 'open' | 'merged' | 'closed';
export type ReviewStatus = 'queued' | 'running' | 'completed' | 'failed' | 'canceled';
export type GateStatus =
  | 'reviewing'
  | 'blocked'
  | 'awaiting_approval'
  | 'approved'
  | 'rejected'
  | 'error'
  | 'overridden'
  | 'stale'
  | 'merged';
export type EngineKind = 'claude_code' | 'copilot_cli' | 'fake';

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface Config {
  auth: { mode: 'dev' | 'oidc'; authority: string | null; client_id: string | null; scopes: string[] };
  version: string;
  public_api_url: string;
}

export interface Team {
  id: string;
  name: string;
  display_name: string;
  description: string | null;
  created_at: string;
}

export interface Me {
  id: string;
  username: string;
  display_name: string | null;
  email: string | null;
  is_superadmin: boolean;
  github_login: string | null;
  gitlab_username: string | null;
  roles: { team: string | null; role: Role }[];
  teams: Team[];
}

export interface User {
  id: string;
  username: string;
  display_name: string | null;
  email: string | null;
  is_superadmin: boolean;
  github_login: string | null;
  gitlab_username: string | null;
  created_at: string;
  last_login_at: string | null;
}

export interface RoleBinding {
  id: string;
  team: string | null;
  username: string | null;
  display_name: string | null;
  group: string | null;
  role: Role;
  created_by: string | null;
  created_at: string;
}

export interface AuditEntry {
  id: number;
  at: string;
  actor: string;
  actor_type: string;
  action: string;
  resource_type: string;
  resource_id: string | null;
  team: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  detail: string | null;
}

// ------------------------------------------------------------------------- IA
export interface AiModel {
  id: string;
  engine_id: string;
  engine_name: string;
  engine_kind: EngineKind;
  model: string;
  label: string;
  description: string | null;
  enabled: boolean;
  is_default: boolean;
}

export interface AiEngine {
  id: string;
  kind: EngineKind;
  name: string;
  description: string | null;
  enabled: boolean;
  extra_args: string[];
  max_turns: number;
  timeout_s: number;
  max_budget_usd: number | null;
  secret_env_names: string[];
  models: AiModel[];
  runners_online: number;
}

// ------------------------------------------------------------------------- integrações
export interface Integration {
  id: string;
  name: string;
  provider: Provider;
  api_url: string;
  web_url: string;
  enabled: boolean;
  bot_login: string | null;
  has_token: boolean;
  has_webhook_secret: boolean;
  webhook_url: string;
  last_check_at: string | null;
  last_check_ok: boolean | null;
  last_check_detail: string | null;
  repositories: number;
  created_at: string;
}

export interface RemoteRepository {
  full_name: string;
  external_id: string;
  default_branch: string;
  web_url: string;
  private: boolean;
  imported_in: string | null;
}

export interface WebhookDelivery {
  id: number;
  received_at: string;
  event: string | null;
  action: string | null;
  repository: string | null;
  number: number | null;
  outcome: string;
  detail: string | null;
}

// ------------------------------------------------------------------------- padrões
export interface RuleSpec {
  code: string;
  title: string;
  category: Category;
  severity: Severity;
  kind: RuleKind;
  instruction: string;
  pattern?: string | null;
  ignore_case?: boolean;
  paths?: string[];
  exclude_paths?: string[];
  suggestion?: string | null;
  reference_url?: string | null;
  enabled?: boolean;
}

export interface Rule extends Required<Omit<RuleSpec, 'pattern' | 'suggestion' | 'reference_url'>> {
  id: string;
  pattern: string | null;
  suggestion: string | null;
  reference_url: string | null;
  position: number;
  created_at: string;
  updated_at: string | null;
  violations_30d: number;
}

export interface Ref {
  id: string;
  name: string;
}

export interface ProfileSummary {
  id: string;
  name: string;
  description: string | null;
  path_globs: string[];
  enabled: boolean;
  model_id: string | null;
  model_label: string | null;
  rules_total: number;
  rules_enabled: number;
  rules_by_category: Partial<Record<Category, number>>;
  rules_by_kind: Partial<Record<RuleKind, number>>;
  blocking_rules: number;
  repositories: Ref[];
  updated_at: string | null;
  updated_by: string | null;
  created_at: string;
}

export interface Profile extends ProfileSummary {
  instructions: string;
  rules: Rule[];
}

export interface LibraryTemplate {
  key: string;
  name: string;
  description: string;
  path_globs: string[];
  rules: number;
  categories: Partial<Record<Category, number>>;
}

export interface Library {
  templates: LibraryTemplate[];
  rules: { key: string; rule: RuleSpec; tags: string[] }[];
}

// ------------------------------------------------------------------------- repositórios
export interface Repository {
  id: string;
  team: string;
  integration: { id: string; name: string; provider: Provider };
  full_name: string;
  external_id: string | null;
  web_url: string | null;
  clone_url: string | null;
  default_branch: string;
  gated_branches: string[];
  gate_mode: GateMode;
  enforcement: Enforcement;
  merge_method: MergeMethod;
  status_context: string;
  approval_mode: ApprovalMode;
  human_min_severity: Severity;
  block_severity: Severity;
  min_approvals: number;
  carry_waivers: boolean;
  post_comments: boolean;
  review_drafts: boolean;
  model_id: string | null;
  model_label: string | null;
  enabled: boolean;
  webhook_url: string;
  webhook_configured: boolean;
  last_webhook_at: string | null;
  last_sync_at: string | null;
  profiles: Ref[];
  open_pull_requests: number;
  created_at: string;
}

export interface ProtectionReport {
  ok: boolean;
  branch: string;
  checks: { name: string; ok: boolean; detail: string; required: boolean }[];
}

// ------------------------------------------------------------------------- PRs e gates
export interface GateSummary {
  id: string;
  status: GateStatus;
  description: string;
  head_sha: string;
  human_required: boolean;
  approvals: number;
  approvals_required: number;
  findings_total: number;
  findings_open: number;
  findings_blocking: number;
  by_severity: Partial<Record<Severity, number>>;
  review_status: ReviewStatus | null;
  created_at: string;
  updated_at: string;
}

export interface PullRequest {
  id: string;
  repository: { id: string; full_name: string; provider: Provider; web_url: string | null };
  number: number;
  title: string;
  author_login: string | null;
  source_branch: string;
  target_branch: string;
  head_sha: string;
  web_url: string | null;
  state: PullRequestState;
  draft: boolean;
  gated: boolean;
  merged_at: string | null;
  merged_by: string | null;
  merged_without_gate: boolean;
  created_at: string;
  updated_at: string;
  gate: GateSummary | null;
}

export interface FindingEvent {
  at: string;
  actor: string;
  action: 'waive' | 'dismiss' | 'dispute' | 'reopen' | 'comment';
  comment: string | null;
}

export interface Finding {
  id: string;
  review_id: string;
  rule_code: string;
  rule_title: string | null;
  profile_name: string | null;
  source: FindingSource;
  category: Category;
  severity: Severity;
  file: string | null;
  line: number | null;
  end_line: number | null;
  title: string;
  description: string;
  suggestion: string | null;
  evidence: string | null;
  confidence: string | null;
  in_diff: boolean;
  fingerprint: string;
  status: FindingStatus;
  status_reason: string | null;
  status_by: string | null;
  status_at: string | null;
  inherited: boolean;
  blocking: boolean;
  file_url: string | null;
  created_at: string;
  events: FindingEvent[];
}

export interface Decision {
  id: string;
  username: string;
  display_name: string | null;
  decision: 'approve' | 'reject';
  comment: string | null;
  created_at: string;
  current: boolean;
}

export interface Gate {
  id: string;
  head_sha: string;
  base_sha: string | null;
  target_branch: string;
  status: GateStatus;
  description: string;
  human_required: boolean;
  approvals: number;
  approvals_required: number;
  approved_by: string[];
  rejected_by: string[];
  blocking: number;
  unresolved: number;
  policy: Record<string, unknown>;
  decided_at: string | null;
  override_by: string | null;
  override_reason: string | null;
  published_state: string | null;
  published_description: string | null;
  published_at: string | null;
  publish_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface Review {
  id: string;
  gate_id: string;
  pull_request_id: string;
  status: ReviewStatus;
  trigger: 'webhook' | 'manual' | 'sync';
  requested_by: string | null;
  engine_kind: string;
  model: string;
  model_label: string | null;
  runner_name: string | null;
  attempt: number;
  phase: string | null;
  profiles: string[];
  rules: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_s: number | null;
  error: string | null;
  summary: string | null;
  stats: Record<string, unknown>;
  cancel_requested: boolean;
}

export interface Permissions {
  approve: boolean;
  approve_reason: string | null;
  reject: boolean;
  waive: boolean;
  dismiss: boolean;
  dispute: boolean;
  rerun: boolean;
  merge: boolean;
  merge_reason: string | null;
  override: boolean;
  is_author: boolean;
}

export interface PullRequestDetail extends PullRequest {
  description: string | null;
  current_gate: Gate | null;
  review: Review | null;
  findings: Finding[];
  decisions: Decision[];
  history: { gate: GateSummary; review: Review | null }[];
  permissions: Permissions;
  merge_via_platform: boolean;
  status_check: boolean;
  enforcement: Enforcement;
}

// ------------------------------------------------------------------------- painel
export interface Dashboard {
  kpis: {
    awaiting_approval: number;
    blocked: number;
    reviewing: number;
    errors: number;
    approved_7d: number;
    approved_by_ai_7d: number;
    merged_without_gate_30d: number;
    overrides_30d: number;
    median_approval_minutes_7d: number | null;
    ai_cost_usd_7d: number;
  };
  daily: { day: string; approved_ai: number; approved_human: number; blocked: number; other: number }[];
  top_rules: {
    rule_code: string;
    rule_title: string | null;
    category: Category;
    severity: Severity;
    count: number;
    waived: number;
    dismissed: number;
  }[];
  by_category: Partial<Record<Category, number>>;
  my_queue: PullRequest[];
  recent: PullRequest[];
  runners_online: number;
  runners_total: number;
}

// ------------------------------------------------------------------------- runners
export interface Runner {
  id: string;
  name: string;
  hostname: string | null;
  os: string | null;
  labels: string[];
  engines: Record<string, string>;
  slots: number;
  status: 'online' | 'offline';
  enabled: boolean;
  draining: boolean;
  last_heartbeat_at: string | null;
  agent_version: string | null;
  running_reviews: string[];
  created_at: string;
}

export interface RegistrationToken {
  id: string;
  description: string;
  created_by: string | null;
  created_at: string;
  expires_at: string | null;
  revoked_at: string | null;
  last_used_at: string | null;
  token?: string;
}
