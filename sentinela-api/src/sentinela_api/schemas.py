"""Esquemas de entrada e saída da API (ver docs/api.md)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sentinela_core.enums import (
    ApprovalMode,
    Category,
    Decision,
    Enforcement,
    EngineKind,
    FindingSource,
    FindingStatus,
    GateMode,
    GateStatus,
    MergeMethod,
    Provider,
    PullRequestState,
    ReviewStatus,
    ReviewTrigger,
    Role,
    RuleKind,
    Severity,
)
from sentinela_core.findings import ReviewResult
from sentinela_core.paths import is_valid_glob
from sentinela_core.rules import RuleSpec

T = TypeVar("T")
SLUG = r"^[a-z0-9][a-z0-9-]*$"


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


def _check_globs(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    clean = [v.strip() for v in values if v and v.strip()]
    bad = [v for v in clean if not is_valid_glob(v)]
    if bad:
        raise ValueError(f"glob inválido: {', '.join(bad)}")
    return clean


# ============================================================================ config / me
class AuthConfig(BaseModel):
    mode: Literal["dev", "oidc"]
    authority: str | None = None
    client_id: str | None = None
    scopes: list[str] = Field(default_factory=list)


class ConfigOut(BaseModel):
    auth: AuthConfig
    version: str
    public_api_url: str


class TeamOut(Out):
    id: str
    name: str
    display_name: str
    description: str | None
    created_at: datetime


class TeamCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120, pattern=SLUG)
    display_name: str | None = None
    description: str | None = None


class TeamUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None


class RoleAssignment(BaseModel):
    team: str | None
    role: Role


class MeOut(BaseModel):
    id: str
    username: str
    display_name: str | None
    email: str | None
    is_superadmin: bool
    github_login: str | None
    gitlab_username: str | None
    roles: list[RoleAssignment]
    teams: list[TeamOut]


class UserOut(BaseModel):
    id: str
    username: str
    display_name: str | None
    email: str | None
    is_superadmin: bool
    github_login: str | None
    gitlab_username: str | None
    created_at: datetime
    last_login_at: datetime | None


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=200)
    display_name: str | None = None
    email: str | None = None
    is_superadmin: bool = False
    github_login: str | None = None
    gitlab_username: str | None = None


class UserUpdate(BaseModel):
    display_name: str | None = None
    email: str | None = None
    is_superadmin: bool | None = None
    github_login: str | None = None
    gitlab_username: str | None = None


class RoleBindingOut(BaseModel):
    id: str
    team: str | None
    username: str | None
    display_name: str | None
    group: str | None
    role: Role
    created_by: str | None
    created_at: datetime


class RoleBindingCreate(BaseModel):
    username: str | None = None
    group: str | None = None
    role: Role


class AuditOut(BaseModel):
    id: int
    at: datetime
    actor: str
    actor_type: str
    action: str
    resource_type: str
    resource_id: str | None
    team: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    detail: str | None


# ============================================================================ IA
class AiModelOut(BaseModel):
    id: str
    engine_id: str
    engine_name: str
    engine_kind: EngineKind
    model: str
    label: str
    description: str | None
    enabled: bool
    is_default: bool


class AiModelCreate(BaseModel):
    engine_id: str
    model: str = Field(default="", max_length=200)
    label: str = Field(min_length=1, max_length=200)
    description: str | None = None
    enabled: bool = True
    is_default: bool = False


class AiModelUpdate(BaseModel):
    model: str | None = Field(default=None, max_length=200)
    label: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    enabled: bool | None = None
    is_default: bool | None = None


class AiEngineOut(BaseModel):
    id: str
    kind: EngineKind
    name: str
    description: str | None
    enabled: bool
    extra_args: list[str]
    max_turns: int
    timeout_s: int
    max_budget_usd: float | None
    secret_env_names: list[str]
    models: list[AiModelOut]
    runners_online: int


class AiEngineCreate(BaseModel):
    kind: EngineKind
    name: str = Field(min_length=2, max_length=120)
    description: str | None = None
    enabled: bool = True
    extra_args: list[str] = Field(default_factory=list)
    max_turns: int = Field(default=30, ge=1, le=500)
    timeout_s: int = Field(default=900, ge=30, le=7200)
    max_budget_usd: float | None = Field(default=None, gt=0)


class AiEngineUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = None
    enabled: bool | None = None
    extra_args: list[str] | None = None
    max_turns: int | None = Field(default=None, ge=1, le=500)
    timeout_s: int | None = Field(default=None, ge=30, le=7200)
    max_budget_usd: float | None = Field(default=None, ge=0)


class EngineSecretsIn(BaseModel):
    """Variáveis de ambiente secretas entregues ao runner (ex.: ANTHROPIC_API_KEY).
    Valor nulo ou vazio remove a variável."""

    values: dict[str, str | None]

    @field_validator("values")
    @classmethod
    def _names(cls, v: dict[str, str | None]) -> dict[str, str | None]:
        import re

        for name in v:
            if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", name):
                raise ValueError(f"nome de variável inválido: {name}")
        return v


# ============================================================================ integrações
class IntegrationOut(BaseModel):
    id: str
    name: str
    provider: Provider
    api_url: str
    web_url: str
    enabled: bool
    bot_login: str | None
    has_token: bool
    has_webhook_secret: bool
    webhook_url: str
    last_check_at: datetime | None
    last_check_ok: bool | None
    last_check_detail: str | None
    repositories: int
    created_at: datetime


class IntegrationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    provider: Provider
    api_url: str | None = None
    web_url: str | None = None
    token: str = Field(min_length=4)
    webhook_secret: str | None = None


class IntegrationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    api_url: str | None = None
    web_url: str | None = None
    enabled: bool | None = None
    token: str | None = None
    webhook_secret: str | None = None
    rotate_webhook_secret: bool = False


class IntegrationCheckOut(BaseModel):
    ok: bool
    login: str | None
    detail: str


class IntegrationSecretOut(BaseModel):
    webhook_url: str
    webhook_secret: str


class WebhookDeliveryOut(BaseModel):
    id: int
    received_at: datetime
    event: str | None
    action: str | None
    repository: str | None
    number: int | None
    outcome: str
    detail: str | None


class RemoteRepositoryOut(BaseModel):
    full_name: str
    external_id: str
    default_branch: str
    web_url: str
    private: bool
    imported_in: str | None


# ============================================================================ padrões
class RuleOut(BaseModel):
    id: str
    code: str
    title: str
    category: Category
    severity: Severity
    kind: RuleKind
    instruction: str
    pattern: str | None
    ignore_case: bool
    paths: list[str]
    exclude_paths: list[str]
    suggestion: str | None
    reference_url: str | None
    enabled: bool
    position: int
    created_at: datetime
    updated_at: datetime | None
    violations_30d: int = 0


class RuleIn(RuleSpec):
    position: int | None = None


class RuleUpdate(BaseModel):
    code: str | None = None
    title: str | None = None
    category: Category | None = None
    severity: Severity | None = None
    kind: RuleKind | None = None
    instruction: str | None = None
    pattern: str | None = None
    ignore_case: bool | None = None
    paths: list[str] | None = None
    exclude_paths: list[str] | None = None
    suggestion: str | None = None
    reference_url: str | None = None
    enabled: bool | None = None
    position: int | None = None


class RefOut(BaseModel):
    id: str
    name: str


class ProfileSummary(BaseModel):
    id: str
    name: str
    description: str | None
    path_globs: list[str]
    enabled: bool
    model_id: str | None
    model_label: str | None
    rules_total: int
    rules_enabled: int
    rules_by_category: dict[str, int]
    rules_by_kind: dict[str, int]
    blocking_rules: int
    repositories: list[RefOut]
    updated_at: datetime | None
    updated_by: str | None
    created_at: datetime


class ProfileOut(ProfileSummary):
    instructions: str
    rules: list[RuleOut]


class ProfileCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = None
    instructions: str = ""
    path_globs: list[str] = Field(default_factory=list)
    enabled: bool = True
    rules: list[RuleSpec] = Field(default_factory=list)
    # Cria a partir de um modelo da biblioteca (perfil completo).
    template: str | None = None

    @field_validator("path_globs")
    @classmethod
    def _globs(cls, v: list[str] | None) -> list[str] | None:
        return _check_globs(v)


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = None
    instructions: str | None = None
    path_globs: list[str] | None = None
    enabled: bool | None = None
    # Só administradores globais.
    model_id: str | None = None

    @field_validator("path_globs")
    @classmethod
    def _globs(cls, v: list[str] | None) -> list[str] | None:
        return _check_globs(v)


class ProfileImport(BaseModel):
    yaml: str = Field(min_length=10)
    # Se já existir um perfil com o mesmo nome: substitui as regras.
    replace: bool = False


class PatternTestIn(BaseModel):
    pattern: str
    sample: str
    ignore_case: bool = False


class PatternMatch(BaseModel):
    line: int
    text: str
    match: str


class PatternTestOut(BaseModel):
    valid: bool
    error: str | None = None
    matches: list[PatternMatch] = Field(default_factory=list)


class LibraryRule(BaseModel):
    key: str
    rule: RuleSpec
    tags: list[str]


class LibraryTemplate(BaseModel):
    key: str
    name: str
    description: str
    path_globs: list[str]
    rules: int
    categories: dict[str, int]


class LibraryOut(BaseModel):
    templates: list[LibraryTemplate]
    rules: list[LibraryRule]


class AddLibraryRulesIn(BaseModel):
    keys: list[str] = Field(min_length=1)


# ============================================================================ repositórios
class IntegrationRef(BaseModel):
    id: str
    name: str
    provider: Provider


class PolicyFields(BaseModel):
    approval_mode: ApprovalMode = ApprovalMode.AI_WHEN_CLEAN
    human_min_severity: Severity = Severity.INFO
    block_severity: Severity = Severity.HIGH
    min_approvals: int = Field(default=1, ge=1, le=5)
    carry_waivers: bool = True


class RepositoryOut(BaseModel):
    id: str
    team: str
    integration: IntegrationRef
    full_name: str
    external_id: str | None
    web_url: str | None
    clone_url: str | None
    default_branch: str
    gated_branches: list[str]
    gate_mode: GateMode
    enforcement: Enforcement
    merge_method: MergeMethod
    status_context: str
    approval_mode: ApprovalMode
    human_min_severity: Severity
    block_severity: Severity
    min_approvals: int
    carry_waivers: bool
    post_comments: bool
    review_drafts: bool
    model_id: str | None
    model_label: str | None
    enabled: bool
    webhook_url: str
    webhook_configured: bool
    last_webhook_at: datetime | None
    last_sync_at: datetime | None
    profiles: list[RefOut]
    open_pull_requests: int
    created_at: datetime


class RepositoryCreate(PolicyFields):
    integration_id: str
    full_name: str = Field(min_length=3, max_length=400)
    profile_ids: list[str] = Field(default_factory=list)
    gated_branches: list[str] | None = None
    gate_mode: GateMode = GateMode.STATUS_CHECK
    enforcement: Enforcement = Enforcement.ENFORCE
    merge_method: MergeMethod = MergeMethod.MERGE
    status_context: str = Field(default="sentinela/gate", min_length=3, max_length=100)
    post_comments: bool = True
    review_drafts: bool = True
    clone_url: str | None = None
    # Busca o repositório no provedor (id, branch padrão). Desligado só em testes locais.
    lookup: bool = True


class RepositoryUpdate(BaseModel):
    profile_ids: list[str] | None = None
    gated_branches: list[str] | None = None
    gate_mode: GateMode | None = None
    enforcement: Enforcement | None = None
    merge_method: MergeMethod | None = None
    status_context: str | None = Field(default=None, min_length=3, max_length=100)
    approval_mode: ApprovalMode | None = None
    human_min_severity: Severity | None = None
    block_severity: Severity | None = None
    min_approvals: int | None = Field(default=None, ge=1, le=5)
    carry_waivers: bool | None = None
    post_comments: bool | None = None
    review_drafts: bool | None = None
    clone_url: str | None = None
    enabled: bool | None = None
    # Só administradores globais.
    model_id: str | None = None


class ProtectionCheck(BaseModel):
    name: str
    ok: bool
    detail: str
    required: bool


class ProtectionOut(BaseModel):
    ok: bool
    branch: str
    checks: list[ProtectionCheck]


class SyncOut(BaseModel):
    pull_requests: int
    reviews_queued: int


# ============================================================================ PRs, gates, revisões
class RepoRef(BaseModel):
    id: str
    full_name: str
    provider: Provider
    web_url: str | None


class GateSummary(BaseModel):
    id: str
    status: GateStatus
    description: str
    head_sha: str
    human_required: bool
    approvals: int
    approvals_required: int
    findings_total: int
    findings_open: int
    findings_blocking: int
    by_severity: dict[str, int]
    review_status: ReviewStatus | None
    created_at: datetime
    updated_at: datetime


class PullRequestOut(BaseModel):
    id: str
    repository: RepoRef
    number: int
    title: str
    author_login: str | None
    source_branch: str
    target_branch: str
    head_sha: str
    web_url: str | None
    state: PullRequestState
    draft: bool
    gated: bool
    merged_at: datetime | None
    merged_by: str | None
    merged_without_gate: bool
    created_at: datetime
    updated_at: datetime
    gate: GateSummary | None


class FindingEventOut(BaseModel):
    at: datetime
    actor: str
    action: str
    comment: str | None


class FindingOut(BaseModel):
    id: str
    review_id: str
    rule_code: str
    rule_title: str | None
    profile_name: str | None
    source: FindingSource
    category: Category
    severity: Severity
    file: str | None
    line: int | None
    end_line: int | None
    title: str
    description: str
    suggestion: str | None
    evidence: str | None
    confidence: str | None
    in_diff: bool
    fingerprint: str
    status: FindingStatus
    status_reason: str | None
    status_by: str | None
    status_at: datetime | None
    inherited: bool
    blocking: bool
    file_url: str | None
    created_at: datetime
    events: list[FindingEventOut] = Field(default_factory=list)


class DecisionOut(BaseModel):
    id: str
    username: str
    display_name: str | None
    decision: Decision
    comment: str | None
    created_at: datetime
    current: bool


class GateOut(BaseModel):
    id: str
    head_sha: str
    base_sha: str | None
    target_branch: str
    status: GateStatus
    description: str
    human_required: bool
    approvals: int
    approvals_required: int
    approved_by: list[str]
    rejected_by: list[str]
    blocking: int
    unresolved: int
    policy: dict[str, Any]
    decided_at: datetime | None
    override_by: str | None
    override_reason: str | None
    published_state: str | None
    published_description: str | None
    published_at: datetime | None
    publish_error: str | None
    created_at: datetime
    updated_at: datetime


class ReviewOut(BaseModel):
    id: str
    gate_id: str
    pull_request_id: str
    status: ReviewStatus
    trigger: ReviewTrigger
    requested_by: str | None
    # claude_code | copilot_cli | fake | none (sem modelo configurado)
    engine_kind: str
    model: str
    model_label: str | None
    runner_name: str | None
    attempt: int
    phase: str | None
    profiles: list[str]
    rules: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_s: float | None
    error: str | None
    summary: str | None
    stats: dict[str, Any]
    cancel_requested: bool


class Permissions(BaseModel):
    approve: bool
    approve_reason: str | None
    reject: bool
    waive: bool
    dismiss: bool
    dispute: bool
    rerun: bool
    merge: bool
    merge_reason: str | None
    override: bool
    is_author: bool


class GateHistoryItem(BaseModel):
    gate: GateSummary
    review: ReviewOut | None


class PullRequestDetail(PullRequestOut):
    description: str | None
    current_gate: GateOut | None
    review: ReviewOut | None
    findings: list[FindingOut]
    decisions: list[DecisionOut]
    history: list[GateHistoryItem]
    permissions: Permissions
    merge_via_platform: bool
    status_check: bool
    enforcement: Enforcement


class FindingActionIn(BaseModel):
    """Justificativa (aceitar, descartar, contestar, reabrir) ou texto do comentário."""

    reason: str = Field(min_length=1, max_length=4000)


class DecisionIn(BaseModel):
    comment: str | None = Field(default=None, max_length=4000)


class RejectIn(BaseModel):
    comment: str = Field(min_length=3, max_length=4000)


class OverrideIn(BaseModel):
    reason: str = Field(min_length=10, max_length=4000)


class MergeIn(BaseModel):
    method: MergeMethod | None = None


class MergeOut(BaseModel):
    merged: bool
    sha: str | None
    message: str | None


class RerunIn(BaseModel):
    # Só administradores globais escolhem outro modelo para uma reexecução.
    model_id: str | None = None


# ============================================================================ painel
class DashboardKpis(BaseModel):
    awaiting_approval: int
    blocked: int
    reviewing: int
    errors: int
    approved_7d: int
    approved_by_ai_7d: int
    merged_without_gate_30d: int
    overrides_30d: int
    median_approval_minutes_7d: float | None
    ai_cost_usd_7d: float


class DailyPoint(BaseModel):
    day: str
    approved_ai: int
    approved_human: int
    blocked: int
    other: int


class RuleCount(BaseModel):
    rule_code: str
    rule_title: str | None
    category: Category
    severity: Severity
    count: int
    waived: int
    dismissed: int


class DashboardOut(BaseModel):
    kpis: DashboardKpis
    daily: list[DailyPoint]
    top_rules: list[RuleCount]
    by_category: dict[str, int]
    my_queue: list[PullRequestOut]
    recent: list[PullRequestOut]
    runners_online: int
    runners_total: int


# ============================================================================ runners (console)
class RunnerOut(BaseModel):
    id: str
    name: str
    hostname: str | None
    os: str | None
    labels: list[str]
    engines: dict[str, Any]
    slots: int
    status: str
    enabled: bool
    draining: bool
    last_heartbeat_at: datetime | None
    agent_version: str | None
    running_reviews: list[str]
    created_at: datetime


class RunnerUpdate(BaseModel):
    enabled: bool | None = None
    draining: bool | None = None
    labels: list[str] | None = None


class RegistrationTokenOut(BaseModel):
    id: str
    description: str
    created_by: str | None
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None


class RegistrationTokenCreate(BaseModel):
    description: str = Field(min_length=2, max_length=300)
    expires_in_days: int | None = Field(default=30, ge=1, le=3650)


class RegistrationTokenCreated(RegistrationTokenOut):
    token: str


# ============================================================================ API do runner
class RunnerRegister(BaseModel):
    registration_token: str
    name: str = Field(min_length=1, max_length=200)
    hostname: str | None = None
    os: str | None = None
    labels: list[str] = Field(default_factory=list)
    engines: dict[str, str] = Field(default_factory=dict)
    slots: int = Field(default=1, ge=1, le=64)
    agent_version: str | None = None


class RunnerConfig(BaseModel):
    runner_id: str
    runner_name: str
    heartbeat_interval_s: int
    claim_wait_s: float
    enabled: bool
    draining: bool


class RunnerRegistered(BaseModel):
    runner_id: str
    runner_token: str
    config: RunnerConfig


class RunnerHeartbeat(BaseModel):
    running: list[str] = Field(default_factory=list)
    engines: dict[str, str] | None = None
    slots: int | None = Field(default=None, ge=1, le=64)


class RunnerHeartbeatResponse(BaseModel):
    config: RunnerConfig
    cancel: list[str]


class ClaimRequest(BaseModel):
    engines: list[EngineKind]
    wait_s: float | None = Field(default=None, ge=0, le=60)


class ClaimedPullRequest(BaseModel):
    number: int
    title: str
    description: str | None
    author: str | None
    source_branch: str
    target_branch: str
    head_sha: str
    base_sha: str | None
    web_url: str | None


class ClaimedRepository(BaseModel):
    full_name: str
    provider: Provider
    clone_url: str
    web_url: str | None


class GitCredentials(BaseModel):
    username: str | None
    token: str | None


class ClaimedEngine(BaseModel):
    kind: EngineKind
    name: str
    model: str
    model_label: str | None
    max_turns: int
    timeout_s: int
    max_budget_usd: float | None
    extra_args: list[str]
    env: dict[str, str]


class ClaimedReview(BaseModel):
    id: str
    attempt: int
    team: str
    pull_request: ClaimedPullRequest
    repository: ClaimedRepository
    git: GitCredentials
    profiles: list[dict[str, Any]]
    engine: ClaimedEngine
    max_diff_chars: int
    mask_values: list[str]


class PhaseIn(BaseModel):
    phase: str = Field(max_length=40)
    detail: str | None = None


class LogLineIn(BaseModel):
    ts: datetime | None = None
    stream: Literal["stdout", "stderr", "system"] = "system"
    text: str = Field(max_length=20_000)


class LogsIn(BaseModel):
    lines: list[LogLineIn] = Field(max_length=2000)


class ResultIn(ReviewResult):
    pass


class FailIn(BaseModel):
    error: str = Field(max_length=20_000)
    retryable: bool = False
