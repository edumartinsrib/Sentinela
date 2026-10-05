"""Configuração da API, lida só de variáveis de ambiente (prefixo SENTINELA_).

Os nomes alternativos (DATABASE_URL, PGHOST, REDIS_URL, VAULT_ADDR…) permitem usar as
variáveis que a plataforma de implantação já injeta.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import quote

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _env(*names: str) -> AliasChoices:
    return AliasChoices(*names)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore", populate_by_name=True)

    # --- Postgres ---
    database_url: str | None = Field(
        default=None, validation_alias=_env("SENTINELA_DATABASE_URL", "DATABASE_URL")
    )
    db_host: str = Field(
        default="localhost", validation_alias=_env("SENTINELA_DB_HOST", "PGHOST", "DB_HOST")
    )
    db_port: int = Field(
        default=5432, validation_alias=_env("SENTINELA_DB_PORT", "PGPORT", "DB_PORT")
    )
    db_user: str = Field(
        default="sentinela", validation_alias=_env("SENTINELA_DB_USER", "PGUSER", "DB_USER")
    )
    db_password: str = Field(
        default="sentinela",
        validation_alias=_env("SENTINELA_DB_PASSWORD", "PGPASSWORD", "DB_PASSWORD"),
    )
    db_name: str = Field(
        default="sentinela", validation_alias=_env("SENTINELA_DB_NAME", "PGDATABASE", "DB_NAME")
    )
    db_pool_size: int = Field(default=10, validation_alias=_env("SENTINELA_DB_POOL_SIZE"))

    # --- Redis (opcional: distribui os eventos SSE entre réplicas) ---
    redis_url: str | None = Field(
        default=None, validation_alias=_env("SENTINELA_REDIS_URL", "REDIS_URL")
    )

    # --- Segredos (tokens do GitHub/GitLab, segredos de webhook, chaves de IA) ---
    # db: cifrados com AES-GCM no próprio Postgres (chave em SENTINELA_SECRET_KEY)
    # vault: KV v2 do HashiCorp Vault; memory: só para testes
    secret_store: Literal["db", "vault", "memory"] = Field(
        default="db", validation_alias=_env("SENTINELA_SECRET_STORE")
    )
    secret_key: str | None = Field(default=None, validation_alias=_env("SENTINELA_SECRET_KEY"))
    vault_addr: str | None = Field(
        default=None, validation_alias=_env("VAULT_ADDR", "SENTINELA_VAULT_ADDR")
    )
    vault_token: str | None = Field(
        default=None, validation_alias=_env("VAULT_TOKEN", "SENTINELA_VAULT_TOKEN")
    )
    vault_role_id: str | None = Field(default=None, validation_alias=_env("VAULT_ROLE_ID"))
    vault_secret_id: str | None = Field(default=None, validation_alias=_env("VAULT_SECRET_ID"))
    vault_namespace: str | None = Field(default=None, validation_alias=_env("VAULT_NAMESPACE"))
    vault_mount: str = Field(
        default="secret", validation_alias=_env("SENTINELA_VAULT_MOUNT", "VAULT_KV_MOUNT")
    )
    vault_prefix: str = Field(default="sentinela", validation_alias=_env("SENTINELA_VAULT_PREFIX"))

    # --- Autenticação ---
    # oidc por padrão: o modo dev (usuário no cabeçalho, sem senha) precisa ser pedido
    # explicitamente com SENTINELA_AUTH_MODE=dev e nunca deve ir para produção.
    auth_mode: Literal["dev", "oidc"] = Field(
        default="oidc", validation_alias=_env("SENTINELA_AUTH_MODE")
    )
    oidc_authority: str | None = Field(
        default=None, validation_alias=_env("SENTINELA_OIDC_AUTHORITY", "OIDC_AUTHORITY")
    )
    oidc_audience: str | None = Field(
        default=None, validation_alias=_env("SENTINELA_OIDC_AUDIENCE", "OIDC_AUDIENCE")
    )
    oidc_client_id: str | None = Field(
        default=None, validation_alias=_env("SENTINELA_OIDC_CLIENT_ID", "OIDC_CLIENT_ID")
    )
    oidc_scopes: str = Field(
        default="openid profile email", validation_alias=_env("SENTINELA_OIDC_SCOPES")
    )
    admin_groups: str = Field(default="", validation_alias=_env("SENTINELA_ADMIN_GROUPS"))
    bootstrap_admins: str = Field(
        default="admin", validation_alias=_env("SENTINELA_BOOTSTRAP_ADMINS")
    )
    cors_origins: str = Field(default="", validation_alias=_env("SENTINELA_CORS_ORIGINS"))

    # --- URLs públicas ---
    # Endereço do console (links nos status e comentários dos PRs).
    public_url: str = Field(
        default="http://localhost:8090", validation_alias=_env("SENTINELA_PUBLIC_URL")
    )
    # Endereço pelo qual o GitHub/GitLab alcança a API (webhooks).
    public_api_url: str = Field(
        default="http://localhost:8000", validation_alias=_env("SENTINELA_PUBLIC_API_URL")
    )

    # --- Revisões e runners ---
    bootstrap_runner_token: str | None = Field(
        default=None, validation_alias=_env("SENTINELA_BOOTSTRAP_RUNNER_TOKEN")
    )
    enable_fake_engine: bool = Field(
        default=False, validation_alias=_env("SENTINELA_ENABLE_FAKE_ENGINE")
    )
    default_team: str | None = Field(
        default="plataforma", validation_alias=_env("SENTINELA_DEFAULT_TEAM")
    )
    review_lease_s: int = Field(default=120, validation_alias=_env("SENTINELA_REVIEW_LEASE_S"))
    review_max_attempts: int = Field(
        default=2, validation_alias=_env("SENTINELA_REVIEW_MAX_ATTEMPTS")
    )
    claim_wait_s: float = Field(default=20.0, validation_alias=_env("SENTINELA_CLAIM_WAIT_S"))
    max_diff_chars: int = Field(default=200_000, validation_alias=_env("SENTINELA_MAX_DIFF_CHARS"))
    log_buffer_lines: int = Field(default=3000, validation_alias=_env("SENTINELA_LOG_BUFFER_LINES"))
    log_buffer_ttl_s: int = Field(
        default=14 * 86400, validation_alias=_env("SENTINELA_LOG_BUFFER_TTL_S")
    )
    reconciler_enabled: bool = Field(
        default=True, validation_alias=_env("SENTINELA_RECONCILER_ENABLED")
    )
    reconcile_interval_s: int = Field(
        default=30, validation_alias=_env("SENTINELA_RECONCILE_INTERVAL_S")
    )
    runner_offline_after_s: int = Field(
        default=90, validation_alias=_env("SENTINELA_RUNNER_OFFLINE_AFTER_S")
    )
    # Confere periodicamente se alguém publicou o status do gate por fora (adulteração).
    tamper_check_enabled: bool = Field(
        default=True, validation_alias=_env("SENTINELA_TAMPER_CHECK")
    )
    tamper_check_interval_s: int = Field(
        default=300, validation_alias=_env("SENTINELA_TAMPER_CHECK_INTERVAL_S")
    )
    provider_timeout_s: float = Field(
        default=20.0, validation_alias=_env("SENTINELA_PROVIDER_TIMEOUT_S")
    )

    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            url = self.database_url
            for prefix in ("postgres://", "postgresql://"):
                if url.startswith(prefix):
                    return "postgresql+asyncpg://" + url[len(prefix) :]
            return url
        return (
            f"postgresql+asyncpg://{quote(self.db_user)}:{quote(self.db_password)}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def admin_group_list(self) -> list[str]:
        return [g.strip() for g in self.admin_groups.split(",") if g.strip()]

    @property
    def bootstrap_admin_list(self) -> list[str]:
        return [u.strip().lower() for u in self.bootstrap_admins.split(",") if u.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def check_security(self) -> None:
        """Recusa subir com uma configuração de autenticação aberta por engano."""
        if self.auth_mode == "oidc":
            if not self.oidc_authority:
                raise RuntimeError(
                    "SENTINELA_OIDC_AUTHORITY não configurado. Configure o provedor OIDC ou, "
                    "só em desenvolvimento, use SENTINELA_AUTH_MODE=dev."
                )
            if not (self.oidc_audience or self.oidc_client_id):
                raise RuntimeError(
                    "Defina SENTINELA_OIDC_AUDIENCE (ou SENTINELA_OIDC_CLIENT_ID): sem audiência, "
                    "tokens emitidos para outros aplicativos seriam aceitos."
                )

    @property
    def effective_oidc_audience(self) -> str | None:
        return self.oidc_audience or self.oidc_client_id


@lru_cache
def get_settings() -> Settings:
    return Settings()
