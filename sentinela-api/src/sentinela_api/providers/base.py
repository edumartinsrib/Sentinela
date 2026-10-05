"""Interface comum para GitHub e GitLab: o resto da API não sabe qual é qual."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import httpx

if TYPE_CHECKING:
    from sentinela_api.models import Integration
    from sentinela_api.services.secrets import SecretStore

# Estado do status/commit check no vocabulário do Sentinela; cada provedor traduz.
StatusState = Literal["pending", "success", "failure", "error"]


class ProviderError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass
class PullRequestData:
    number: int
    title: str
    description: str | None
    author_login: str | None
    source_branch: str
    target_branch: str
    head_sha: str
    base_sha: str | None
    web_url: str | None
    state: Literal["open", "merged", "closed"]
    draft: bool = False
    merged_by: str | None = None


@dataclass
class RemoteRepository:
    full_name: str
    external_id: str
    default_branch: str
    web_url: str
    private: bool = True


@dataclass
class ProtectionReport:
    """Diagnóstico de como o provedor está configurado para respeitar o gate."""

    ok: bool
    checks: list[dict[str, Any]] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str, required: bool = True) -> None:
        self.checks.append({"name": name, "ok": ok, "detail": detail, "required": required})
        if required and not ok:
            self.ok = False


@dataclass
class MergeResult:
    merged: bool
    sha: str | None = None
    message: str | None = None


class ProviderClient:
    provider: str = ""
    clone_username: str = ""

    def __init__(
        self,
        api_url: str,
        web_url: str,
        token: str,
        *,
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.api_url = api_url.rstrip("/")
        self.web_url = web_url.rstrip("/")
        self.token = token
        self._timeout = timeout
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.api_url,
            headers=self._headers(),
            timeout=self._timeout,
            transport=self._transport,
        )

    def _headers(self) -> dict[str, str]:
        raise NotImplementedError

    async def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        try:
            async with self._client() as http:
                resp = await http.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.provider} indisponível: {exc}") from exc
        return resp

    async def _json(self, method: str, path: str, *, ok: tuple[int, ...] = (200, 201), **kw: Any):
        resp = await self._request(method, path, **kw)
        if resp.status_code not in ok:
            raise ProviderError(_describe(resp), resp.status_code)
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    # ------------------------------------------------------------------ operações
    async def current_user(self) -> str:
        raise NotImplementedError

    async def list_repositories(self, search: str | None = None) -> list[RemoteRepository]:
        raise NotImplementedError

    async def get_repository(self, full_name: str) -> RemoteRepository:
        raise NotImplementedError

    async def get_pull_request(self, repo: str, number: int) -> PullRequestData:
        raise NotImplementedError

    async def list_open_pull_requests(self, repo: str) -> list[PullRequestData]:
        raise NotImplementedError

    async def set_status(
        self,
        repo: str,
        sha: str,
        state: StatusState,
        description: str,
        context: str,
        target_url: str | None,
    ) -> None:
        raise NotImplementedError

    async def get_status(self, repo: str, sha: str, context: str) -> StatusState | None:
        raise NotImplementedError

    async def upsert_comment(
        self, repo: str, number: int, body: str, marker: str, comment_id: str | None
    ) -> str:
        raise NotImplementedError

    async def merge(
        self, repo: str, number: int, sha: str, method: str, title: str | None
    ) -> MergeResult:
        raise NotImplementedError

    async def check_protection(
        self, repo: str, branch: str, context: str, *, require_status: bool, platform_merge: bool
    ) -> ProtectionReport:
        raise NotImplementedError

    async def create_webhook(self, repo: str, url: str, secret: str) -> str:
        raise NotImplementedError

    def clone_url(self, full_name: str) -> str:
        return f"{self.web_url}/{full_name}.git"


def _describe(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        body = resp.text[:300]
    if isinstance(body, dict):
        msg = body.get("message") or body.get("error") or body.get("error_description") or body
        if isinstance(msg, (dict, list)):
            msg = str(msg)[:300]
    else:
        msg = body
    return f"HTTP {resp.status_code}: {msg}"


def truncate(text: str, size: int) -> str:
    return text if len(text) <= size else text[: size - 1] + "…"


class ProviderFactory:
    """Cria o cliente de uma integração com o token lido do cofre."""

    def __init__(
        self,
        secrets: SecretStore,
        *,
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._secrets = secrets
        self._timeout = timeout
        self.transport = transport

    async def token(self, integration: Integration) -> str:
        from sentinela_api.services.secrets import integration_path

        data = await self._secrets.read(integration_path(integration.id)) or {}
        token = data.get("token")
        if not token:
            raise ProviderError(f"integração {integration.name} sem token configurado")
        return token

    async def webhook_secret(self, integration: Integration) -> str | None:
        from sentinela_api.services.secrets import integration_path

        data = await self._secrets.read(integration_path(integration.id)) or {}
        return data.get("webhook_secret")

    def build(self, integration: Integration, token: str) -> ProviderClient:
        from sentinela_api.providers.github import GitHubClient
        from sentinela_api.providers.gitlab import GitLabClient

        cls = {"github": GitHubClient, "gitlab": GitLabClient}.get(integration.provider)
        if cls is None:
            raise ProviderError(f"provedor desconhecido: {integration.provider}")
        return cls(
            integration.api_url,
            integration.web_url,
            token,
            timeout=self._timeout,
            transport=self.transport,
        )

    async def client(self, integration: Integration) -> ProviderClient:
        return self.build(integration, await self.token(integration))
