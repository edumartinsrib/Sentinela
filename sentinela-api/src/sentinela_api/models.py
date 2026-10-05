"""Modelo de dados do Sentinela (Postgres)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB, list[str]: JSONB}


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _ts(**kw: Any) -> Any:
    return mapped_column(DateTime(timezone=True), **kw)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ============================================================================ pessoas
class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(200), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(300))
    external_id: Mapped[str | None] = mapped_column(String(200))
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False)
    # Logins nos provedores: impedem o autor do PR de aprovar o próprio gate.
    github_login: Mapped[str | None] = mapped_column(String(200))
    gitlab_username: Mapped[str | None] = mapped_column(String(200))
    last_login_at: Mapped[datetime | None] = _ts()


class Team(TimestampMixin, Base):
    __tablename__ = "teams"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)


class RoleBinding(TimestampMixin, Base):
    __tablename__ = "role_bindings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    # Nulo = vale para todos os times.
    team_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    group: Mapped[str | None] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(20))
    created_by: Mapped[str | None] = mapped_column(String(200))

    user: Mapped[User | None] = relationship(lazy="joined")
    team: Mapped[Team | None] = relationship(lazy="joined")


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_team_at", "team_id", "at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    actor: Mapped[str] = mapped_column(String(200))
    actor_type: Mapped[str] = mapped_column(String(20), default="user")
    action: Mapped[str] = mapped_column(String(80), index=True)
    resource_type: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[str | None] = mapped_column(String(80))
    team_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    detail: Mapped[str | None] = mapped_column(Text)


class SecretEntry(Base):
    """Segredos cifrados (AES-GCM) quando SENTINELA_SECRET_STORE=db."""

    __tablename__ = "secrets"

    path: Mapped[str] = mapped_column(String(300), primary_key=True)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    key_id: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_by: Mapped[str | None] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ============================================================================ IA
class AiEngine(TimestampMixin, Base):
    """Ferramenta que executa a revisão no runner (Claude Code, Copilot CLI)."""

    __tablename__ = "ai_engines"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    extra_args: Mapped[list[str]] = mapped_column(default=list)
    max_turns: Mapped[int] = mapped_column(Integer, default=30)
    timeout_s: Mapped[int] = mapped_column(Integer, default=900)
    max_budget_usd: Mapped[float | None] = mapped_column(Float)
    # Nomes das variáveis de ambiente guardadas no cofre (os valores não saem da API).
    secret_env_names: Mapped[list[str]] = mapped_column(default=list)
    updated_at: Mapped[datetime | None] = _ts(onupdate=func.now())

    models: Mapped[list[AiModel]] = relationship(
        back_populates="engine",
        lazy="selectin",
        order_by="AiModel.label",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AiModel(TimestampMixin, Base):
    __tablename__ = "ai_models"
    __table_args__ = (UniqueConstraint("engine_id", "model"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    engine_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ai_engines.id", ondelete="CASCADE"))
    # Valor passado em --model. Vazio = padrão da ferramenta.
    model: Mapped[str] = mapped_column(String(200))
    label: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    engine: Mapped[AiEngine] = relationship(back_populates="models", lazy="joined")


# ============================================================================ integrações
class Integration(TimestampMixin, Base):
    """Conexão com uma instância do GitHub ou GitLab. Token e segredo do webhook ficam no cofre."""

    __tablename__ = "integrations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    provider: Mapped[str] = mapped_column(String(20))
    api_url: Mapped[str] = mapped_column(String(500))
    web_url: Mapped[str] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    bot_login: Mapped[str | None] = mapped_column(String(200))
    last_check_at: Mapped[datetime | None] = _ts()
    last_check_ok: Mapped[bool | None] = mapped_column(Boolean)
    last_check_detail: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime | None] = _ts(onupdate=func.now())


# ============================================================================ padrões
class Profile(TimestampMixin, Base):
    """Perfil de padrão de um tipo de implementação (API Python, front React, Terraform…)."""

    __tablename__ = "profiles"
    __table_args__ = (UniqueConstraint("team_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    instructions: Mapped[str] = mapped_column(Text, default="")
    path_globs: Mapped[list[str]] = mapped_column(default=list)
    # Modelo específico para este perfil (só o administrador altera).
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_models.id", ondelete="SET NULL")
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(String(200))
    updated_at: Mapped[datetime | None] = _ts(onupdate=func.now())
    updated_by: Mapped[str | None] = mapped_column(String(200))

    team: Mapped[Team] = relationship(lazy="joined")
    model: Mapped[AiModel | None] = relationship(lazy="joined")
    rules: Mapped[list[Rule]] = relationship(
        back_populates="profile",
        lazy="selectin",
        order_by="(Rule.position, Rule.code)",
        cascade="all, delete-orphan",
    )


class Rule(TimestampMixin, Base):
    __tablename__ = "rules"
    __table_args__ = (UniqueConstraint("profile_id", "code"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(20))
    severity: Mapped[str] = mapped_column(String(10))
    kind: Mapped[str] = mapped_column(String(10))
    instruction: Mapped[str] = mapped_column(Text, default="")
    pattern: Mapped[str | None] = mapped_column(Text)
    ignore_case: Mapped[bool] = mapped_column(Boolean, default=False)
    paths: Mapped[list[str]] = mapped_column(default=list)
    exclude_paths: Mapped[list[str]] = mapped_column(default=list)
    suggestion: Mapped[str | None] = mapped_column(Text)
    reference_url: Mapped[str | None] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime | None] = _ts(onupdate=func.now())

    profile: Mapped[Profile] = relationship(back_populates="rules")


# ============================================================================ repositórios
class Repository(TimestampMixin, Base):
    __tablename__ = "repositories"
    # GitHub e GitLab tratam owner/nome sem diferenciar maiúsculas: "Org/Repo" e "org/repo"
    # são o mesmo repositório e não podem ser cadastrados duas vezes (nem por times diferentes).
    __table_args__ = (
        Index(
            "uq_repositories_integration_lower_name",
            "integration_id",
            func.lower(text("full_name")),
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    integration_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("integrations.id", ondelete="RESTRICT")
    )
    full_name: Mapped[str] = mapped_column(String(400))
    external_id: Mapped[str | None] = mapped_column(String(100))
    web_url: Mapped[str | None] = mapped_column(String(500))
    # Sobrescreve a URL de clone derivada da integração (espelhos, testes locais).
    clone_url: Mapped[str | None] = mapped_column(String(500))
    default_branch: Mapped[str] = mapped_column(String(200), default="main")
    # PRs para estas branches passam pelo gate.
    gated_branches: Mapped[list[str]] = mapped_column(default=list)
    gate_mode: Mapped[str] = mapped_column(String(20), default="status_check")
    enforcement: Mapped[str] = mapped_column(String(10), default="enforce")
    merge_method: Mapped[str] = mapped_column(String(10), default="merge")
    status_context: Mapped[str] = mapped_column(String(100), default="sentinela/gate")
    # política do gate
    approval_mode: Mapped[str] = mapped_column(String(20), default="ai_when_clean")
    human_min_severity: Mapped[str] = mapped_column(String(10), default="info")
    block_severity: Mapped[str] = mapped_column(String(10), default="high")
    min_approvals: Mapped[int] = mapped_column(Integer, default=1)
    carry_waivers: Mapped[bool] = mapped_column(Boolean, default=True)
    post_comments: Mapped[bool] = mapped_column(Boolean, default=True)
    review_drafts: Mapped[bool] = mapped_column(Boolean, default=True)
    # Modelo específico para o repositório (só o administrador altera).
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_models.id", ondelete="SET NULL")
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    webhook_id: Mapped[str | None] = mapped_column(String(100))
    last_sync_at: Mapped[datetime | None] = _ts()
    last_webhook_at: Mapped[datetime | None] = _ts()
    created_by: Mapped[str | None] = mapped_column(String(200))
    updated_at: Mapped[datetime | None] = _ts(onupdate=func.now())

    team: Mapped[Team] = relationship(lazy="joined")
    integration: Mapped[Integration] = relationship(lazy="joined")
    model: Mapped[AiModel | None] = relationship(lazy="joined")
    profiles: Mapped[list[Profile]] = relationship(
        secondary="repository_profiles", lazy="selectin", order_by="Profile.name"
    )


class RepositoryProfile(Base):
    __tablename__ = "repository_profiles"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), primary_key=True
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True
    )


# ============================================================================ PRs, gates, revisões
class PullRequest(TimestampMixin, Base):
    __tablename__ = "pull_requests"
    __table_args__ = (
        UniqueConstraint("repository_id", "number"),
        Index("ix_pull_requests_team_state", "team_id", "state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE")
    )
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    author_login: Mapped[str | None] = mapped_column(String(200))
    source_branch: Mapped[str] = mapped_column(String(300))
    target_branch: Mapped[str] = mapped_column(String(300))
    head_sha: Mapped[str] = mapped_column(String(64))
    base_sha: Mapped[str | None] = mapped_column(String(64))
    web_url: Mapped[str | None] = mapped_column(String(500))
    state: Mapped[str] = mapped_column(String(10), default="open")
    draft: Mapped[bool] = mapped_column(Boolean, default=False)
    gated: Mapped[bool] = mapped_column(Boolean, default=True)
    merged_at: Mapped[datetime | None] = _ts()
    merged_by: Mapped[str | None] = mapped_column(String(200))
    # Merge feito sem o gate liberado (bypass de administrador no provedor).
    merged_without_gate: Mapped[bool] = mapped_column(Boolean, default=False)
    current_gate_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gates.id", ondelete="SET NULL", use_alter=True)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    repository: Mapped[Repository] = relationship(lazy="joined")
    current_gate: Mapped[Gate | None] = relationship(
        foreign_keys=[current_gate_id], lazy="joined", post_update=True
    )


class Gate(TimestampMixin, Base):
    """Situação do gate para um commit (head) do PR. Commit novo = gate novo."""

    __tablename__ = "gates"
    __table_args__ = (UniqueConstraint("pull_request_id", "head_sha"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    pull_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pull_requests.id", ondelete="CASCADE")
    )
    head_sha: Mapped[str] = mapped_column(String(64))
    base_sha: Mapped[str | None] = mapped_column(String(64))
    target_branch: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="reviewing")
    status_description: Mapped[str] = mapped_column(String(300), default="")
    human_required: Mapped[bool] = mapped_column(Boolean, default=True)
    approvals_required: Mapped[int] = mapped_column(Integer, default=0)
    # Fotografia da política usada (muda no repositório não afeta gates antigos).
    policy: Mapped[dict[str, Any]] = mapped_column(default=dict)
    current_review_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reviews.id", ondelete="SET NULL", use_alter=True)
    )
    decided_at: Mapped[datetime | None] = _ts()
    override_by: Mapped[str | None] = mapped_column(String(200))
    override_reason: Mapped[str | None] = mapped_column(Text)
    published_state: Mapped[str | None] = mapped_column(String(20))
    published_description: Mapped[str | None] = mapped_column(String(300))
    published_at: Mapped[datetime | None] = _ts()
    publish_error: Mapped[str | None] = mapped_column(Text)
    comment_id: Mapped[str | None] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    pull_request: Mapped[PullRequest] = relationship(foreign_keys=[pull_request_id])
    current_review: Mapped[Review | None] = relationship(
        foreign_keys=[current_review_id], lazy="joined", post_update=True
    )


class Review(TimestampMixin, Base):
    """Uma execução da revisão automática (fila no Postgres, executada por um runner)."""

    __tablename__ = "reviews"
    __table_args__ = (Index("ix_reviews_status_created", "status", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    gate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gates.id", ondelete="CASCADE"))
    pull_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pull_requests.id", ondelete="CASCADE")
    )
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    head_sha: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    trigger: Mapped[str] = mapped_column(String(20), default="webhook")
    requested_by: Mapped[str | None] = mapped_column(String(200))
    engine_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_engines.id", ondelete="SET NULL")
    )
    engine_kind: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(200), default="")
    model_label: Mapped[str | None] = mapped_column(String(200))
    # Perfis e regras como estavam quando a revisão foi criada.
    profiles_snapshot: Mapped[list[Any]] = mapped_column(default=list)
    runner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("runners.id", ondelete="SET NULL")
    )
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    phase: Mapped[str | None] = mapped_column(String(40))
    lease_expires_at: Mapped[datetime | None] = _ts()
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime | None] = _ts()
    finished_at: Mapped[datetime | None] = _ts()
    error: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    stats: Mapped[dict[str, Any]] = mapped_column(default=dict)

    pull_request: Mapped[PullRequest] = relationship(lazy="joined")
    runner: Mapped[Runner | None] = relationship(lazy="joined")


class Finding(TimestampMixin, Base):
    __tablename__ = "findings"
    __table_args__ = (
        Index("ix_findings_pr_fingerprint", "pull_request_id", "fingerprint"),
        Index("ix_findings_team_created", "team_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    review_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"))
    gate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gates.id", ondelete="CASCADE"))
    pull_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pull_requests.id", ondelete="CASCADE")
    )
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    rule_code: Mapped[str] = mapped_column(String(40))
    rule_title: Mapped[str | None] = mapped_column(String(200))
    profile_name: Mapped[str | None] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(10))
    category: Mapped[str] = mapped_column(String(20))
    severity: Mapped[str] = mapped_column(String(10))
    file: Mapped[str | None] = mapped_column(String(1000))
    line: Mapped[int | None] = mapped_column(Integer)
    end_line: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    suggestion: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str | None] = mapped_column(String(10))
    in_diff: Mapped[bool] = mapped_column(Boolean, default=True)
    fingerprint: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="open")
    status_reason: Mapped[str | None] = mapped_column(Text)
    status_by: Mapped[str | None] = mapped_column(String(200))
    status_at: Mapped[datetime | None] = _ts()
    # Decisão herdada de um commit anterior do mesmo PR.
    inherited: Mapped[bool] = mapped_column(Boolean, default=False)


class FindingEvent(Base):
    """Histórico de um achado: contestação, justificativa, falso positivo, reabertura e
    comentários."""

    __tablename__ = "finding_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    finding_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("findings.id", ondelete="CASCADE"), index=True
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(20))
    comment: Mapped[str | None] = mapped_column(Text)


class GateDecision(TimestampMixin, Base):
    __tablename__ = "gate_decisions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    gate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gates.id", ondelete="CASCADE"), index=True
    )
    username: Mapped[str] = mapped_column(String(200))
    display_name: Mapped[str | None] = mapped_column(String(200))
    decision: Mapped[str] = mapped_column(String(10))
    comment: Mapped[str | None] = mapped_column(Text)
    # Decisões anteriores a uma nova revisão do mesmo commit deixam de valer.
    review_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reviews.id", ondelete="SET NULL")
    )


# ============================================================================ runners
class Runner(TimestampMixin, Base):
    __tablename__ = "runners"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    hostname: Mapped[str | None] = mapped_column(String(300))
    os: Mapped[str | None] = mapped_column(String(30))
    labels: Mapped[list[str]] = mapped_column(default=list)
    # Ferramentas instaladas: {"claude_code": "2.1.0", "copilot_cli": "1.0.3"}
    engines: Mapped[dict[str, Any]] = mapped_column(default=dict)
    slots: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="offline")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    draining: Mapped[bool] = mapped_column(Boolean, default=False)
    last_heartbeat_at: Mapped[datetime | None] = _ts()
    agent_version: Mapped[str | None] = mapped_column(String(50))
    running_reviews: Mapped[list[str]] = mapped_column(default=list)
    secret_hash: Mapped[str] = mapped_column(String(128))


class RunnerRegistrationToken(TimestampMixin, Base):
    __tablename__ = "runner_registration_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    description: Mapped[str] = mapped_column(String(300))
    token_hash: Mapped[str] = mapped_column(String(128))
    created_by: Mapped[str | None] = mapped_column(String(200))
    expires_at: Mapped[datetime | None] = _ts()
    revoked_at: Mapped[datetime | None] = _ts()
    last_used_at: Mapped[datetime | None] = _ts()


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    integration_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("integrations.id", ondelete="CASCADE")
    )
    provider: Mapped[str] = mapped_column(String(20))
    event: Mapped[str | None] = mapped_column(String(80))
    action: Mapped[str | None] = mapped_column(String(80))
    delivery_id: Mapped[str | None] = mapped_column(String(100))
    repository: Mapped[str | None] = mapped_column(String(400))
    number: Mapped[int | None] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(20))
    detail: Mapped[str | None] = mapped_column(Text)
