"""esquema inicial

Revision ID: 0001
Revises:
Create Date: 2026-10-05 10:59:26.074527
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_engines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("extra_args", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("max_turns", sa.Integer(), nullable=False),
        sa.Column("timeout_s", sa.Integer(), nullable=False),
        sa.Column("max_budget_usd", sa.Float(), nullable=True),
        sa.Column("secret_env_names", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_engines")),
        sa.UniqueConstraint("name", name=op.f("uq_ai_engines_name")),
    )
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_app_settings")),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("actor_type", sa.String(length=20), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("resource_type", sa.String(length=40), nullable=False),
        sa.Column("resource_id", sa.String(length=80), nullable=True),
        sa.Column("team_id", sa.Uuid(), nullable=True),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index(op.f("ix_audit_log_action"), "audit_log", ["action"], unique=False)
    op.create_index(op.f("ix_audit_log_at"), "audit_log", ["at"], unique=False)
    op.create_index("ix_audit_log_team_at", "audit_log", ["team_id", "at"], unique=False)
    op.create_table(
        "integrations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("api_url", sa.String(length=500), nullable=False),
        sa.Column("web_url", sa.String(length=500), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("bot_login", sa.String(length=200), nullable=True),
        sa.Column("last_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_check_ok", sa.Boolean(), nullable=True),
        sa.Column("last_check_detail", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integrations")),
        sa.UniqueConstraint("name", name=op.f("uq_integrations_name")),
    )
    op.create_table(
        "runner_registration_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runner_registration_tokens")),
    )
    op.create_table(
        "runners",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("hostname", sa.String(length=300), nullable=True),
        sa.Column("os", sa.String(length=30), nullable=True),
        sa.Column("labels", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("engines", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("slots", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("draining", sa.Boolean(), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("agent_version", sa.String(length=50), nullable=True),
        sa.Column("running_reviews", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("secret_hash", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runners")),
        sa.UniqueConstraint("name", name=op.f("uq_runners_name")),
    )
    op.create_table(
        "secrets",
        sa.Column("path", sa.String(length=300), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("key_id", sa.String(length=40), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("path", name=op.f("pk_secrets")),
    )
    op.create_table(
        "teams",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_teams")),
        sa.UniqueConstraint("name", name=op.f("uq_teams_name")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=200), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("email", sa.String(length=300), nullable=True),
        sa.Column("external_id", sa.String(length=200), nullable=True),
        sa.Column("is_superadmin", sa.Boolean(), nullable=False),
        sa.Column("github_login", sa.String(length=200), nullable=True),
        sa.Column("gitlab_username", sa.String(length=200), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
    )
    op.create_table(
        "ai_models",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("engine_id", sa.Uuid(), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["engine_id"],
            ["ai_engines.id"],
            name=op.f("fk_ai_models_engine_id_ai_engines"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_models")),
        sa.UniqueConstraint("engine_id", "model", name=op.f("uq_ai_models_engine_id")),
    )
    op.create_table(
        "role_bindings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("group", sa.String(length=300), nullable=True),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name=op.f("fk_role_bindings_team_id_teams"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_role_bindings_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_role_bindings")),
    )
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("integration_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("event", sa.String(length=80), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=True),
        sa.Column("delivery_id", sa.String(length=100), nullable=True),
        sa.Column("repository", sa.String(length=400), nullable=True),
        sa.Column("number", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["integration_id"],
            ["integrations.id"],
            name=op.f("fk_webhook_deliveries_integration_id_integrations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_deliveries")),
    )
    op.create_index(
        op.f("ix_webhook_deliveries_received_at"),
        "webhook_deliveries",
        ["received_at"],
        unique=False,
    )
    op.create_table(
        "profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("path_globs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model_id", sa.Uuid(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["ai_models.id"],
            name=op.f("fk_profiles_model_id_ai_models"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], name=op.f("fk_profiles_team_id_teams"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_profiles")),
        sa.UniqueConstraint("team_id", "name", name=op.f("uq_profiles_team_id")),
    )
    op.create_table(
        "repositories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("integration_id", sa.Uuid(), nullable=False),
        sa.Column("full_name", sa.String(length=400), nullable=False),
        sa.Column("external_id", sa.String(length=100), nullable=True),
        sa.Column("web_url", sa.String(length=500), nullable=True),
        sa.Column("clone_url", sa.String(length=500), nullable=True),
        sa.Column("default_branch", sa.String(length=200), nullable=False),
        sa.Column("gated_branches", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("gate_mode", sa.String(length=20), nullable=False),
        sa.Column("enforcement", sa.String(length=10), nullable=False),
        sa.Column("merge_method", sa.String(length=10), nullable=False),
        sa.Column("status_context", sa.String(length=100), nullable=False),
        sa.Column("approval_mode", sa.String(length=20), nullable=False),
        sa.Column("human_min_severity", sa.String(length=10), nullable=False),
        sa.Column("block_severity", sa.String(length=10), nullable=False),
        sa.Column("min_approvals", sa.Integer(), nullable=False),
        sa.Column("carry_waivers", sa.Boolean(), nullable=False),
        sa.Column("post_comments", sa.Boolean(), nullable=False),
        sa.Column("review_drafts", sa.Boolean(), nullable=False),
        sa.Column("model_id", sa.Uuid(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("webhook_id", sa.String(length=100), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_webhook_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["integration_id"],
            ["integrations.id"],
            name=op.f("fk_repositories_integration_id_integrations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["ai_models.id"],
            name=op.f("fk_repositories_model_id_ai_models"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name=op.f("fk_repositories_team_id_teams"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_repositories")),
    )
    op.create_index(
        "uq_repositories_integration_lower_name",
        "repositories",
        ["integration_id", sa.text("lower(full_name)")],
        unique=True,
    )
    op.create_table(
        "pull_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("author_login", sa.String(length=200), nullable=True),
        sa.Column("source_branch", sa.String(length=300), nullable=False),
        sa.Column("target_branch", sa.String(length=300), nullable=False),
        sa.Column("head_sha", sa.String(length=64), nullable=False),
        sa.Column("base_sha", sa.String(length=64), nullable=True),
        sa.Column("web_url", sa.String(length=500), nullable=True),
        sa.Column("state", sa.String(length=10), nullable=False),
        sa.Column("draft", sa.Boolean(), nullable=False),
        sa.Column("gated", sa.Boolean(), nullable=False),
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("merged_by", sa.String(length=200), nullable=True),
        sa.Column("merged_without_gate", sa.Boolean(), nullable=False),
        sa.Column("current_gate_id", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_pull_requests_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name=op.f("fk_pull_requests_team_id_teams"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pull_requests")),
        sa.UniqueConstraint("repository_id", "number", name=op.f("uq_pull_requests_repository_id")),
    )
    op.create_index(
        "ix_pull_requests_team_state", "pull_requests", ["team_id", "state"], unique=False
    )
    op.create_table(
        "repository_profiles",
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["profiles.id"],
            name=op.f("fk_repository_profiles_profile_id_profiles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_repository_profiles_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("repository_id", "profile_id", name=op.f("pk_repository_profiles")),
    )
    op.create_table(
        "rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("pattern", sa.Text(), nullable=True),
        sa.Column("ignore_case", sa.Boolean(), nullable=False),
        sa.Column("paths", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("exclude_paths", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("suggestion", sa.Text(), nullable=True),
        sa.Column("reference_url", sa.String(length=500), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["profiles.id"],
            name=op.f("fk_rules_profile_id_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rules")),
        sa.UniqueConstraint("profile_id", "code", name=op.f("uq_rules_profile_id")),
    )
    op.create_table(
        "gates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pull_request_id", sa.Uuid(), nullable=False),
        sa.Column("head_sha", sa.String(length=64), nullable=False),
        sa.Column("base_sha", sa.String(length=64), nullable=True),
        sa.Column("target_branch", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("status_description", sa.String(length=300), nullable=False),
        sa.Column("human_required", sa.Boolean(), nullable=False),
        sa.Column("approvals_required", sa.Integer(), nullable=False),
        sa.Column("policy", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("current_review_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("override_by", sa.String(length=200), nullable=True),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("published_state", sa.String(length=20), nullable=True),
        sa.Column("published_description", sa.String(length=300), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("publish_error", sa.Text(), nullable=True),
        sa.Column("comment_id", sa.String(length=100), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["pull_request_id"],
            ["pull_requests.id"],
            name=op.f("fk_gates_pull_request_id_pull_requests"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_gates")),
        sa.UniqueConstraint("pull_request_id", "head_sha", name=op.f("uq_gates_pull_request_id")),
    )
    op.create_table(
        "reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("gate_id", sa.Uuid(), nullable=False),
        sa.Column("pull_request_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("head_sha", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("requested_by", sa.String(length=200), nullable=True),
        sa.Column("engine_id", sa.Uuid(), nullable=True),
        sa.Column("engine_kind", sa.String(length=30), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("model_label", sa.String(length=200), nullable=True),
        sa.Column("profiles_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("runner_id", sa.Uuid(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(length=40), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["engine_id"],
            ["ai_engines.id"],
            name=op.f("fk_reviews_engine_id_ai_engines"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["gate_id"], ["gates.id"], name=op.f("fk_reviews_gate_id_gates"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["pull_request_id"],
            ["pull_requests.id"],
            name=op.f("fk_reviews_pull_request_id_pull_requests"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["runner_id"],
            ["runners.id"],
            name=op.f("fk_reviews_runner_id_runners"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], name=op.f("fk_reviews_team_id_teams"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reviews")),
    )
    op.create_index("ix_reviews_status_created", "reviews", ["status", "created_at"], unique=False)
    op.create_table(
        "findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("review_id", sa.Uuid(), nullable=False),
        sa.Column("gate_id", sa.Uuid(), nullable=False),
        sa.Column("pull_request_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("rule_code", sa.String(length=40), nullable=False),
        sa.Column("rule_title", sa.String(length=200), nullable=True),
        sa.Column("profile_name", sa.String(length=120), nullable=True),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("file", sa.String(length=1000), nullable=True),
        sa.Column("line", sa.Integer(), nullable=True),
        sa.Column("end_line", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("suggestion", sa.Text(), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("confidence", sa.String(length=10), nullable=True),
        sa.Column("in_diff", sa.Boolean(), nullable=False),
        sa.Column("fingerprint", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("status_by", sa.String(length=200), nullable=True),
        sa.Column("status_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inherited", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["gate_id"], ["gates.id"], name=op.f("fk_findings_gate_id_gates"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["pull_request_id"],
            ["pull_requests.id"],
            name=op.f("fk_findings_pull_request_id_pull_requests"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["review_id"],
            ["reviews.id"],
            name=op.f("fk_findings_review_id_reviews"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], name=op.f("fk_findings_team_id_teams"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_findings")),
    )
    op.create_index(
        "ix_findings_pr_fingerprint", "findings", ["pull_request_id", "fingerprint"], unique=False
    )
    op.create_index("ix_findings_team_created", "findings", ["team_id", "created_at"], unique=False)
    op.create_table(
        "gate_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("gate_id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=200), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("decision", sa.String(length=10), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("review_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["gate_id"],
            ["gates.id"],
            name=op.f("fk_gate_decisions_gate_id_gates"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["review_id"],
            ["reviews.id"],
            name=op.f("fk_gate_decisions_review_id_reviews"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_gate_decisions")),
    )
    op.create_index(op.f("ix_gate_decisions_gate_id"), "gate_decisions", ["gate_id"], unique=False)
    op.create_table(
        "finding_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["findings.id"],
            name=op.f("fk_finding_events_finding_id_findings"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_finding_events")),
    )
    op.create_index(
        op.f("ix_finding_events_finding_id"), "finding_events", ["finding_id"], unique=False
    )

    # chaves circulares (PR → gate atual → revisão atual) criadas depois das tabelas
    op.create_foreign_key(
        op.f("fk_pull_requests_current_gate_id_gates"),
        "pull_requests",
        "gates",
        ["current_gate_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_gates_current_review_id_reviews"),
        "gates",
        "reviews",
        ["current_review_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_gates_current_review_id_reviews"), "gates", type_="foreignkey")
    op.drop_constraint(
        op.f("fk_pull_requests_current_gate_id_gates"), "pull_requests", type_="foreignkey"
    )
    op.drop_index(op.f("ix_finding_events_finding_id"), table_name="finding_events")
    op.drop_table("finding_events")
    op.drop_index(op.f("ix_gate_decisions_gate_id"), table_name="gate_decisions")
    op.drop_table("gate_decisions")
    op.drop_index("ix_findings_team_created", table_name="findings")
    op.drop_index("ix_findings_pr_fingerprint", table_name="findings")
    op.drop_table("findings")
    op.drop_index("ix_reviews_status_created", table_name="reviews")
    op.drop_table("reviews")
    op.drop_table("gates")
    op.drop_table("rules")
    op.drop_table("repository_profiles")
    op.drop_index("ix_pull_requests_team_state", table_name="pull_requests")
    op.drop_table("pull_requests")
    op.drop_table("repositories")
    op.drop_table("profiles")
    op.drop_index(op.f("ix_webhook_deliveries_received_at"), table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")
    op.drop_table("role_bindings")
    op.drop_table("ai_models")
    op.drop_table("users")
    op.drop_table("teams")
    op.drop_table("secrets")
    op.drop_table("runners")
    op.drop_table("runner_registration_tokens")
    op.drop_table("integrations")
    op.drop_index("ix_audit_log_team_at", table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_at"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_action"), table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("app_settings")
    op.drop_table("ai_engines")
