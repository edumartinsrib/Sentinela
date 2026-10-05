"""Cliente da API v4 do GitLab (gitlab.com ou self-managed).

Token: personal/project/group access token de um usuário-robô com escopo `api` (status de
commit, notas, merge e webhooks) e acesso de leitura ao código (`read_repository`).
"""

from __future__ import annotations

import fnmatch
import re
from typing import Any
from urllib.parse import quote

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

# Sentinela → GitLab
_TO_GITLAB = {"pending": "pending", "success": "success", "failure": "failed", "error": "failed"}
# GitLab → Sentinela
_FROM_GITLAB = {
    "success": "success",
    "failed": "failure",
    "canceled": "error",
    "pending": "pending",
    "running": "pending",
    "created": "pending",
}
_ACCESS_DEVELOPER = 30


def pid(full_name: str) -> str:
    return quote(full_name, safe="")


class GitLabClient(ProviderClient):
    provider = "gitlab"
    clone_username = "oauth2"

    def _headers(self) -> dict[str, str]:
        return {"PRIVATE-TOKEN": self.token, "User-Agent": "sentinela"}

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
            out.extend(resp.json())
            m = _NEXT.search(resp.headers.get("link", ""))
            url = m.group(1) if m else None
            query = {}
        return out

    async def current_user(self) -> str:
        return (await self._json("GET", "/user"))["username"]

    @staticmethod
    def _repo(data: dict[str, Any]) -> RemoteRepository:
        return RemoteRepository(
            full_name=data["path_with_namespace"],
            external_id=str(data["id"]),
            default_branch=data.get("default_branch") or "main",
            web_url=data.get("web_url") or "",
            private=data.get("visibility", "private") != "public",
        )

    async def list_repositories(self, search: str | None = None) -> list[RemoteRepository]:
        params: dict[str, Any] = {
            "membership": "true",
            "simple": "true",
            "order_by": "last_activity_at",
        }
        if search:
            params["search"] = search
        return [self._repo(p) for p in await self._paged("/projects", params)]

    async def get_repository(self, full_name: str) -> RemoteRepository:
        return self._repo(await self._json("GET", f"/projects/{pid(full_name)}"))

    @staticmethod
    def _pr(data: dict[str, Any]) -> PullRequestData:
        state = {"opened": "open", "merged": "merged"}.get(data.get("state", ""), "closed")
        diff_refs = data.get("diff_refs") or {}
        merged_by = data.get("merged_by") or data.get("merge_user") or {}
        return PullRequestData(
            number=int(data["iid"]),
            title=data.get("title") or "",
            description=data.get("description"),
            author_login=(data.get("author") or {}).get("username"),
            source_branch=data["source_branch"],
            target_branch=data["target_branch"],
            head_sha=data.get("sha") or diff_refs.get("head_sha") or "",
            base_sha=diff_refs.get("base_sha"),
            web_url=data.get("web_url"),
            state=state,
            draft=bool(data.get("draft") or data.get("work_in_progress")),
            merged_by=merged_by.get("username"),
        )

    async def get_pull_request(self, repo: str, number: int) -> PullRequestData:
        return self._pr(await self._json("GET", f"/projects/{pid(repo)}/merge_requests/{number}"))

    async def list_open_pull_requests(self, repo: str) -> list[PullRequestData]:
        items = await self._paged(f"/projects/{pid(repo)}/merge_requests", {"state": "opened"})
        return [self._pr(i) for i in items]

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
            "state": _TO_GITLAB[state],
            "name": context,
            "description": truncate(description, 255),
        }
        if target_url:
            body["target_url"] = target_url
        resp = await self._request("POST", f"/projects/{pid(repo)}/statuses/{sha}", json=body)
        if resp.status_code in (200, 201):
            return
        # Repetir o mesmo estado devolve 400 "Cannot transition status": já está como queremos.
        if resp.status_code == 400 and "transition" in resp.text.lower():
            return
        raise ProviderError(_describe(resp), resp.status_code)

    async def get_status(self, repo: str, sha: str, context: str) -> StatusState | None:
        items = await self._json(
            "GET",
            f"/projects/{pid(repo)}/repository/commits/{sha}/statuses",
            params={"name": context, "all": "true", "per_page": 100},
        )
        mine = [i for i in items or [] if i.get("name") == context]
        if not mine:
            return None
        latest = max(mine, key=lambda i: i.get("id", 0))
        return _FROM_GITLAB.get(latest.get("status", ""), "pending")

    async def upsert_comment(
        self, repo: str, number: int, body: str, marker: str, comment_id: str | None
    ) -> str:
        base = f"/projects/{pid(repo)}/merge_requests/{number}/notes"
        if comment_id:
            resp = await self._request("PUT", f"{base}/{comment_id}", json={"body": body})
            if resp.status_code == 200:
                return comment_id
        for note in await self._paged(base, {"sort": "desc"}):
            if marker in (note.get("body") or ""):
                await self._json("PUT", f"{base}/{note['id']}", json={"body": body})
                return str(note["id"])
        created = await self._json("POST", base, json={"body": body})
        return str(created["id"])

    async def merge(
        self, repo: str, number: int, sha: str, method: str, title: str | None
    ) -> MergeResult:
        body: dict[str, Any] = {"sha": sha, "squash": method == "squash"}
        if title and method != "squash":
            body["merge_commit_message"] = title
        resp = await self._request(
            "PUT", f"/projects/{pid(repo)}/merge_requests/{number}/merge", json=body
        )
        data: dict[str, Any] = {}
        try:
            data = resp.json()
        except ValueError:
            pass
        if resp.status_code == 200 and data.get("state") == "merged":
            return MergeResult(True, data.get("merge_commit_sha") or data.get("sha"))
        message = data.get("message") if isinstance(data, dict) else None
        message = str(message or f"HTTP {resp.status_code}")
        if resp.status_code in (405, 406, 409, 422):
            return MergeResult(False, None, message)
        raise ProviderError(message, resp.status_code)

    async def check_protection(
        self, repo: str, branch: str, context: str, *, require_status: bool, platform_merge: bool
    ) -> ProtectionReport:
        report = ProtectionReport(ok=True)
        project = await self._json("GET", f"/projects/{pid(repo)}")
        rule = None
        resp = await self._request(
            "GET", f"/projects/{pid(repo)}/protected_branches/{quote(branch, safe='')}"
        )
        if resp.status_code == 200:
            rule = resp.json()
        else:
            for item in await self._paged(f"/projects/{pid(repo)}/protected_branches"):
                if fnmatch.fnmatch(branch, item.get("name", "")):
                    rule = item
                    break
        report.add(
            "Branch protegida",
            rule is not None,
            f"{branch} é protegida" if rule else f"proteja {branch} em Settings → Repository",
        )
        pipeline = bool(project.get("only_allow_merge_if_pipeline_succeeds"))
        report.add(
            "Pipelines precisam passar",
            pipeline,
            f"o status {context} entra no pipeline e trava o merge enquanto não for sucesso"
            if pipeline
            else "ative 'Pipelines must succeed' em Settings → Merge requests",
            required=require_status,
        )
        skipped = bool(project.get("allow_merge_on_skipped_pipeline"))
        report.add(
            "Pipeline ignorada não libera merge",
            not skipped,
            "ok" if not skipped else "desative 'Skipped pipelines are considered successful'",
            required=False,
        )
        if platform_merge:
            levels = (rule or {}).get("merge_access_levels") or []
            developer_can = any(
                (lv.get("access_level") or 0) <= _ACCESS_DEVELOPER
                and lv.get("access_level")
                and not lv.get("user_id")
                for lv in levels
            )
            restricted = rule is not None and not developer_can
            report.add(
                "Merge restrito ao robô",
                restricted,
                "merge limitado a mantenedores ou usuários específicos"
                if restricted
                else "em 'Allowed to merge' deixe só o usuário-robô do Sentinela (ou mantenedores)",
            )
        report.add(
            "Status externo do Sentinela",
            True,
            f"o Sentinela publica o status '{context}' no commit de cada MR",
            required=False,
        )
        return report

    async def create_webhook(self, repo: str, url: str, secret: str) -> str:
        data = await self._json(
            "POST",
            f"/projects/{pid(repo)}/hooks",
            json={
                "url": url,
                "merge_requests_events": True,
                "push_events": False,
                "token": secret,
                "enable_ssl_verification": url.startswith("https://"),
            },
        )
        return str(data["id"])
