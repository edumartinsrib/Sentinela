"""Cliente da API REST do GitHub (github.com ou GitHub Enterprise Server).

Token: PAT fine-grained, token de usuário-robô ou token de instalação de GitHub App, com
permissão de leitura de código e de escrita em commit statuses, pull requests e (para criar o
webhook) administração de webhooks.
"""

from __future__ import annotations

import re
from typing import Any

from sentinela_api.providers.base import (
    MergeResult,
    ProtectionReport,
    ProviderClient,
    ProviderError,
    PullRequestData,
    RemoteRepository,
    StatusState,
    _describe,
    truncate,
)

_NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')
MAX_PAGES = 10


class GitHubClient(ProviderClient):
    provider = "github"
    clone_username = "x-access-token"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "sentinela",
        }

    async def _paged(self, path: str, params: dict[str, Any] | None = None) -> list[Any]:
        out: list[Any] = []
        url: str | None = path
        query = {"per_page": 100, **(params or {})}
        for _ in range(MAX_PAGES):
            if url is None:
                break
            resp = await self._request("GET", url, params=query)
            if resp.status_code != 200:
                raise ProviderError(_describe(resp), resp.status_code)
            data = resp.json()
            out.extend(data["repositories"] if isinstance(data, dict) else data)
            m = _NEXT.search(resp.headers.get("link", ""))
            url = m.group(1) if m else None
            query = {}
        return out

    # ------------------------------------------------------------------ identidade e repos
    async def current_user(self) -> str:
        resp = await self._request("GET", "/user")
        if resp.status_code == 200:
            return resp.json()["login"]
        if resp.status_code == 403:
            # token de instalação de GitHub App não lê /user
            check = await self._request("GET", "/installation/repositories", params={"per_page": 1})
            if check.status_code == 200:
                return "github-app"
        raise ProviderError(_describe(resp), resp.status_code)

    @staticmethod
    def _repo(data: dict[str, Any]) -> RemoteRepository:
        return RemoteRepository(
            full_name=data["full_name"],
            external_id=str(data["id"]),
            default_branch=data.get("default_branch") or "main",
            web_url=data.get("html_url") or "",
            private=bool(data.get("private", True)),
        )

    async def list_repositories(self, search: str | None = None) -> list[RemoteRepository]:
        try:
            items = await self._paged("/user/repos", {"sort": "updated"})
        except ProviderError as exc:
            if exc.status != 403:
                raise
            items = await self._paged("/installation/repositories")
        repos = [self._repo(r) for r in items]
        if search:
            needle = search.lower()
            repos = [r for r in repos if needle in r.full_name.lower()]
        return repos

    async def get_repository(self, full_name: str) -> RemoteRepository:
        return self._repo(await self._json("GET", f"/repos/{full_name}"))

    # ------------------------------------------------------------------ pull requests
    @staticmethod
    def _pr(data: dict[str, Any]) -> PullRequestData:
        if data.get("merged") or data.get("merged_at"):
            state = "merged"
        elif data.get("state") == "closed":
            state = "closed"
        else:
            state = "open"
        return PullRequestData(
            number=int(data["number"]),
            title=data.get("title") or "",
            description=data.get("body"),
            author_login=(data.get("user") or {}).get("login"),
            source_branch=data["head"]["ref"],
            target_branch=data["base"]["ref"],
            head_sha=data["head"]["sha"],
            base_sha=data["base"].get("sha"),
            web_url=data.get("html_url"),
            state=state,
            draft=bool(data.get("draft")),
            merged_by=(data.get("merged_by") or {}).get("login"),
        )

    async def get_pull_request(self, repo: str, number: int) -> PullRequestData:
        return self._pr(await self._json("GET", f"/repos/{repo}/pulls/{number}"))

    async def list_open_pull_requests(self, repo: str) -> list[PullRequestData]:
        return [self._pr(p) for p in await self._paged(f"/repos/{repo}/pulls", {"state": "open"})]

    # ------------------------------------------------------------------ status e comentários
    async def set_status(
        self,
        repo: str,
        sha: str,
        state: StatusState,
        description: str,
        context: str,
        target_url: str | None,
    ) -> None:
        body: dict[str, Any] = {
            "state": state,
            "description": truncate(description, 140),
            "context": context,
        }
        if target_url:
            body["target_url"] = target_url
        await self._json("POST", f"/repos/{repo}/statuses/{sha}", json=body)

    async def get_status(self, repo: str, sha: str, context: str) -> StatusState | None:
        items = await self._json(
            "GET", f"/repos/{repo}/commits/{sha}/statuses", params={"per_page": 100}
        )
        for item in items or []:  # mais recente primeiro
            if item.get("context") == context:
                return item.get("state")
        return None

    async def upsert_comment(
        self, repo: str, number: int, body: str, marker: str, comment_id: str | None
    ) -> str:
        if comment_id:
            resp = await self._request(
                "PATCH", f"/repos/{repo}/issues/comments/{comment_id}", json={"body": body}
            )
            if resp.status_code == 200:
                return comment_id
        comments = await self._paged(f"/repos/{repo}/issues/{number}/comments")
        for c in comments:
            if marker in (c.get("body") or ""):
                await self._json(
                    "PATCH", f"/repos/{repo}/issues/comments/{c['id']}", json={"body": body}
                )
                return str(c["id"])
        created = await self._json(
            "POST", f"/repos/{repo}/issues/{number}/comments", json={"body": body}
        )
        return str(created["id"])

    # ------------------------------------------------------------------ merge
    async def merge(
        self, repo: str, number: int, sha: str, method: str, title: str | None
    ) -> MergeResult:
        body: dict[str, Any] = {"sha": sha, "merge_method": method}
        if title:
            body["commit_title"] = title
        resp = await self._request("PUT", f"/repos/{repo}/pulls/{number}/merge", json=body)
        data: dict[str, Any] = {}
        try:
            data = resp.json()
        except ValueError:
            pass
        if resp.status_code == 200 and data.get("merged"):
            return MergeResult(True, data.get("sha"), data.get("message"))
        message = data.get("message") or f"HTTP {resp.status_code}"
        if resp.status_code in (405, 409, 422):
            return MergeResult(False, None, message)
        raise ProviderError(message, resp.status_code)

    # ------------------------------------------------------------------ proteção da branch
    async def check_protection(
        self, repo: str, branch: str, context: str, *, require_status: bool, platform_merge: bool
    ) -> ProtectionReport:
        report = ProtectionReport(ok=True)
        protected = False
        required_contexts: set[str] = set()
        app_bound = False
        enforce_admins = None
        restricted_to: list[str] | None = None
        notes: list[str] = []

        resp = await self._request("GET", f"/repos/{repo}/branches/{branch}/protection")
        if resp.status_code == 200:
            data = resp.json()
            protected = True
            rsc = data.get("required_status_checks") or {}
            required_contexts.update(rsc.get("contexts") or [])
            for check in rsc.get("checks") or []:
                if check.get("context") == context:
                    required_contexts.add(context)
                    app_bound = app_bound or check.get("app_id") not in (None, -1)
            enforce_admins = (data.get("enforce_admins") or {}).get("enabled")
            restr = data.get("restrictions")
            if restr:
                restricted_to = [u.get("login") for u in restr.get("users") or []] + [
                    a.get("slug") for a in restr.get("apps") or []
                ]
        elif resp.status_code == 403:
            notes.append("o token não pode ler a proteção clássica (exige permissão de admin)")

        rules = await self._request("GET", f"/repos/{repo}/rules/branches/{branch}")
        if rules.status_code == 200:
            for rule in rules.json():
                protected = True
                if rule.get("type") == "required_status_checks":
                    for item in (rule.get("parameters") or {}).get("required_status_checks", []):
                        if item.get("context") == context:
                            required_contexts.add(context)
                            app_bound = app_bound or bool(item.get("integration_id"))

        report.add(
            "Branch protegida",
            protected,
            f"{branch} tem proteção ou ruleset"
            if protected
            else f"{branch} não tem proteção nem ruleset" + (f" ({notes[0]})" if notes else ""),
        )
        report.add(
            f"Status {context} obrigatório",
            context in required_contexts,
            "exigido antes do merge"
            if context in required_contexts
            else f"adicione {context} aos status checks obrigatórios da branch",
            required=require_status,
        )
        report.add(
            "Status preso ao app do Sentinela",
            app_bound,
            "só o app configurado pode publicar o status"
            if app_bound
            else "recomendado: exigir o status vindo do GitHub App do Sentinela "
            "(evita status forjado)",
            required=False,
        )
        if enforce_admins is not None:
            report.add(
                "Administradores também respeitam a regra",
                bool(enforce_admins),
                "ativo" if enforce_admins else "ative 'Do not allow bypassing the above settings'",
                required=False,
            )
        if platform_merge:
            ok = restricted_to is not None
            report.add(
                "Merge restrito ao robô",
                ok,
                f"push/merge permitido só para: {', '.join(filter(None, restricted_to or []))}"
                if ok
                else "restrinja quem pode fazer push na branch ao usuário/app do Sentinela",
            )
        return report

    async def create_webhook(self, repo: str, url: str, secret: str) -> str:
        data = await self._json(
            "POST",
            f"/repos/{repo}/hooks",
            json={
                "name": "web",
                "active": True,
                "events": ["pull_request"],
                "config": {
                    "url": url,
                    "content_type": "json",
                    "secret": secret,
                    "insecure_ssl": "0",
                },
            },
        )
        return str(data["id"])
