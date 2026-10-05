"""Simulador do GitHub para desenvolvimento, demonstração e testes.

Implementa o pedaço da API REST que o Sentinela usa (repositórios, PRs, status de commit,
comentários, merge, proteção de branch, webhooks) e dispara os webhooks `pull_request`
assinados, como o GitHub faria. Estado só em memória.

    uv run uvicorn fake_github:app --app-dir scripts --port 9000

Rotas de controle (não existem no GitHub):
    POST /_fake/repos                         cria repositório
    POST /_fake/repos/{owner}/{repo}/pulls    abre PR (dispara "opened")
    POST /_fake/repos/{o}/{r}/pulls/{n}/push  novo commit no PR (dispara "synchronize")
    POST /_fake/repos/{o}/{r}/pulls/{n}/force-merge  merge ignorando a proteção (bypass)
    POST /_fake/repos/{o}/{r}/git             recebe um `git bundle` e hospeda o repositório
    GET  /_fake/state                         estado completo

Os repositórios recebidos ficam clonáveis por HTTP (protocolo smart, com fetch raso) em
/git/{owner}/{repo}.git — é de lá que o runner baixa o código na demonstração.
FAKE_GITHUB_GIT_ROOT escolhe a pasta (padrão: diretório temporário).
"""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import hmac
import itertools
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

WEB = "https://github.fake"
_ids = itertools.count(1000)
GIT_ROOT = Path(os.environ.get("FAKE_GITHUB_GIT_ROOT") or tempfile.mkdtemp(prefix="fake-github-"))
_SAFE = re.compile(r"^[A-Za-z0-9._-]+$")


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class FakeGitHub:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.login = "sentinela-bot"
        self.repos: dict[str, dict[str, Any]] = {}
        self.pulls: dict[str, dict[int, dict[str, Any]]] = {}
        self.statuses: dict[str, list[dict[str, Any]]] = {}  # "<repo>@<sha>"
        self.comments: dict[str, list[dict[str, Any]]] = {}  # "<repo>#<n>"
        self.hooks: dict[str, list[dict[str, Any]]] = {}
        self.protection: dict[str, dict[str, Any]] = {}  # "<repo>:<branch>"
        self.deliveries: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ helpers
    def repo(self, full: str) -> dict[str, Any]:
        if full not in self.repos:
            raise HTTPException(404, detail={"message": "Not Found"})
        return self.repos[full]

    def pull(self, full: str, number: int) -> dict[str, Any]:
        self.repo(full)
        pr = self.pulls[full].get(number)
        if pr is None:
            raise HTTPException(404, detail={"message": "Not Found"})
        return pr

    def latest_status(self, full: str, sha: str, context: str) -> str | None:
        for st in reversed(self.statuses.get(f"{full}@{sha}", [])):
            if st["context"] == context:
                return st["state"]
        return None

    def create_repo(
        self, full: str, default_branch: str = "main", required_contexts: list[str] | None = None
    ) -> dict[str, Any]:
        repo = {
            "id": next(_ids),
            "full_name": full,
            "default_branch": default_branch,
            "html_url": f"{WEB}/{full}",
            "private": True,
        }
        self.repos[full] = repo
        self.pulls.setdefault(full, {})
        if required_contexts:
            self.protection[f"{full}:{default_branch}"] = {
                "required_status_checks": {
                    "strict": False,
                    "contexts": required_contexts,
                    "checks": [{"context": c, "app_id": None} for c in required_contexts],
                },
                "enforce_admins": {"enabled": True},
                "restrictions": None,
            }
        return repo

    def pr_json(self, full: str, pr: dict[str, Any]) -> dict[str, Any]:
        return {
            "number": pr["number"],
            "title": pr["title"],
            "body": pr["body"],
            "user": {"login": pr["author"]},
            "head": {"ref": pr["head_ref"], "sha": pr["head_sha"]},
            "base": {"ref": pr["base_ref"], "sha": pr["base_sha"]},
            "html_url": f"{WEB}/{full}/pull/{pr['number']}",
            "state": pr["state"],
            "merged": pr["merged"],
            "merged_at": pr.get("merged_at"),
            "merged_by": {"login": pr["merged_by"]} if pr.get("merged_by") else None,
            "draft": pr["draft"],
        }

    async def fire(self, full: str, action: str, pr: dict[str, Any], sender: str) -> None:
        payload = {
            "action": action,
            "number": pr["number"],
            "pull_request": self.pr_json(full, pr),
            "repository": {"full_name": full, "id": self.repos[full]["id"]},
            "sender": {"login": sender},
        }
        body = json.dumps(payload).encode()
        for hook in self.hooks.get(full, []):
            sig = "sha256=" + hmac.new(hook["secret"].encode(), body, hashlib.sha256).hexdigest()
            headers = {
                "Content-Type": "application/json",
                "X-GitHub-Event": "pull_request",
                "X-GitHub-Delivery": str(uuid.uuid4()),
                "X-Hub-Signature-256": sig,
            }
            try:
                async with httpx.AsyncClient(timeout=30) as http:
                    resp = await http.post(hook["url"], content=body, headers=headers)
                self.deliveries.append(
                    {
                        "url": hook["url"],
                        "action": action,
                        "status": resp.status_code,
                        "body": resp.text[:300],
                    }
                )
            except httpx.HTTPError as exc:
                self.deliveries.append({"url": hook["url"], "action": action, "error": str(exc)})


fake = FakeGitHub()
app = FastAPI(title="GitHub simulado (Sentinela)")


@app.exception_handler(HTTPException)
async def _http_error(_: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, dict) else {"message": exc.detail}
    return JSONResponse(detail, status_code=exc.status_code)


# ============================================================================ API "real"
@app.get("/user")
async def user() -> dict:
    return {"login": fake.login}


@app.get("/user/repos")
async def user_repos() -> list:
    return list(fake.repos.values())


@app.get("/repos/{owner}/{name}")
async def get_repo(owner: str, name: str) -> dict:
    return fake.repo(f"{owner}/{name}")


@app.get("/repos/{owner}/{name}/pulls")
async def list_pulls(owner: str, name: str, state: str = "open") -> list:
    full = f"{owner}/{name}"
    fake.repo(full)
    return [
        fake.pr_json(full, p)
        for p in fake.pulls[full].values()
        if state == "all" or p["state"] == state
    ]


@app.get("/repos/{owner}/{name}/pulls/{number}")
async def get_pull(owner: str, name: str, number: int) -> dict:
    full = f"{owner}/{name}"
    return fake.pr_json(full, fake.pull(full, number))


@app.post("/repos/{owner}/{name}/statuses/{sha}", status_code=201)
async def create_status(owner: str, name: str, sha: str, request: Request) -> dict:
    full = f"{owner}/{name}"
    fake.repo(full)
    body = await request.json()
    if body.get("state") not in ("error", "failure", "pending", "success"):
        raise HTTPException(422, detail={"message": "Validation Failed"})
    item = {
        "id": next(_ids),
        "state": body["state"],
        "context": body.get("context", "default"),
        "description": body.get("description"),
        "target_url": body.get("target_url"),
        "created_at": _now(),
    }
    fake.statuses.setdefault(f"{full}@{sha}", []).append(item)
    return item


@app.get("/repos/{owner}/{name}/commits/{sha}/statuses")
async def list_statuses(owner: str, name: str, sha: str) -> list:
    return list(reversed(fake.statuses.get(f"{owner}/{name}@{sha}", [])))


@app.get("/repos/{owner}/{name}/issues/{number}/comments")
async def list_comments(owner: str, name: str, number: int) -> list:
    return fake.comments.get(f"{owner}/{name}#{number}", [])


@app.post("/repos/{owner}/{name}/issues/{number}/comments", status_code=201)
async def create_comment(owner: str, name: str, number: int, request: Request) -> dict:
    full = f"{owner}/{name}"
    fake.pull(full, number)
    body = await request.json()
    item = {"id": next(_ids), "body": body["body"], "user": {"login": fake.login}}
    fake.comments.setdefault(f"{full}#{number}", []).append(item)
    return item


@app.patch("/repos/{owner}/{name}/issues/comments/{comment_id}")
async def update_comment(owner: str, name: str, comment_id: int, request: Request) -> dict:
    body = await request.json()
    for items in fake.comments.values():
        for item in items:
            if item["id"] == comment_id:
                item["body"] = body["body"]
                return item
    raise HTTPException(404, detail={"message": "Not Found"})


@app.put("/repos/{owner}/{name}/pulls/{number}/merge")
async def merge_pull(owner: str, name: str, number: int, request: Request):
    full = f"{owner}/{name}"
    pr = fake.pull(full, number)
    body = await request.json()
    if pr["state"] != "open":
        raise HTTPException(405, detail={"message": "Pull Request is not mergeable"})
    if body.get("sha") and body["sha"] != pr["head_sha"]:
        raise HTTPException(
            409, detail={"message": "Head branch was modified. Review and try the merge again."}
        )
    rule = fake.protection.get(f"{full}:{pr['base_ref']}")
    if rule:
        for ctx in rule["required_status_checks"]["contexts"]:
            if fake.latest_status(full, pr["head_sha"], ctx) != "success":
                raise HTTPException(
                    405, detail={"message": f'Required status check "{ctx}" is expected.'}
                )
    merge_sha = hashlib.sha1(f"merge-{full}-{number}".encode()).hexdigest()
    pr.update(state="closed", merged=True, merged_at=_now(), merged_by=fake.login)
    await fake.fire(full, "closed", pr, fake.login)
    return {"sha": merge_sha, "merged": True, "message": "Pull Request successfully merged"}


@app.get("/repos/{owner}/{name}/branches/{branch}/protection")
async def protection(owner: str, name: str, branch: str) -> dict:
    rule = fake.protection.get(f"{owner}/{name}:{branch}")
    if rule is None:
        raise HTTPException(404, detail={"message": "Branch not protected"})
    return rule


@app.get("/repos/{owner}/{name}/rules/branches/{branch}")
async def branch_rules(owner: str, name: str, branch: str) -> list:
    return []


@app.post("/repos/{owner}/{name}/hooks", status_code=201)
async def create_hook(owner: str, name: str, request: Request) -> dict:
    full = f"{owner}/{name}"
    fake.repo(full)
    body = await request.json()
    hook = {
        "id": next(_ids),
        "url": body["config"]["url"],
        "secret": body["config"].get("secret", ""),
        "events": body.get("events", []),
    }
    fake.hooks.setdefault(full, []).append(hook)
    return {"id": hook["id"], "active": True}


# ============================================================================ controle
class RepoIn(BaseModel):
    full_name: str
    default_branch: str = "main"
    required_contexts: list[str] = []


class PullIn(BaseModel):
    number: int | None = None
    title: str
    body: str | None = None
    author: str
    head_ref: str
    head_sha: str
    base_ref: str = "main"
    base_sha: str | None = None
    draft: bool = False


class PushIn(BaseModel):
    head_sha: str


@app.post("/_fake/repos", status_code=201)
async def fake_repo(body: RepoIn) -> dict:
    return fake.create_repo(body.full_name, body.default_branch, body.required_contexts)


@app.post("/_fake/repos/{owner}/{name}/pulls", status_code=201)
async def fake_open_pull(owner: str, name: str, body: PullIn) -> dict:
    full = f"{owner}/{name}"
    fake.repo(full)
    number = body.number or (max(fake.pulls[full], default=0) + 1)
    pr = {
        **body.model_dump(),
        "number": number,
        "state": "open",
        "merged": False,
        "base_sha": body.base_sha or "0" * 40,
    }
    fake.pulls[full][number] = pr
    await fake.fire(full, "opened", pr, body.author)
    return fake.pr_json(full, pr)


@app.post("/_fake/repos/{owner}/{name}/pulls/{number}/push")
async def fake_push(owner: str, name: str, number: int, body: PushIn) -> dict:
    full = f"{owner}/{name}"
    pr = fake.pull(full, number)
    pr["head_sha"] = body.head_sha
    await fake.fire(full, "synchronize", pr, pr["author"])
    return fake.pr_json(full, pr)


@app.post("/_fake/repos/{owner}/{name}/pulls/{number}/force-merge")
async def fake_force_merge(owner: str, name: str, number: int) -> dict:
    full = f"{owner}/{name}"
    pr = fake.pull(full, number)
    pr.update(state="closed", merged=True, merged_at=_now(), merged_by="admin-apressado")
    await fake.fire(full, "closed", pr, "admin-apressado")
    return fake.pr_json(full, pr)


# ----------------------------------------------------------------------------- git por HTTP
def _git_dir(owner: str, name: str) -> Path:
    name = name.removesuffix(".git")
    if not (_SAFE.match(owner) and _SAFE.match(name)) or ".." in (owner + name):
        raise HTTPException(404, detail={"message": "Not Found"})
    return GIT_ROOT / owner / f"{name}.git"


def _git(*args: str, cwd: Path | None = None, data: bytes | None = None) -> bytes:
    proc = subprocess.run(["git", *args], cwd=cwd, input=data, capture_output=True, check=False)
    if proc.returncode != 0:
        raise HTTPException(500, detail={"message": proc.stderr.decode(errors="replace")})
    return proc.stdout


def _import_bundle(target: Path, bundle: bytes) -> None:
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    path = target.parent / f"{target.name}.bundle"
    path.write_bytes(bundle)
    try:
        _git("init", "--bare", "-q", "-b", "main", str(target))
        _git("fetch", "-q", str(path), "+refs/*:refs/*", cwd=target)
    finally:
        path.unlink(missing_ok=True)


@app.post("/_fake/repos/{owner}/{name}/git", status_code=201)
async def fake_upload_git(owner: str, name: str, request: Request) -> dict:
    """Corpo: `git bundle create - --all` (inclusive refs/pull/N/head)."""
    target = _git_dir(owner, name)
    await asyncio.to_thread(_import_bundle, target, await request.body())
    return {"clone_url": f"{str(request.base_url).rstrip('/')}/git/{owner}/{name}.git"}


def _pkt(line: str) -> bytes:
    return f"{len(line) + 4:04x}{line}".encode()


@app.get("/git/{owner}/{name}/info/refs")
async def git_info_refs(owner: str, name: str, service: str = "") -> Response:
    if service != "git-upload-pack":
        raise HTTPException(403, detail={"message": "só leitura (git-upload-pack)"})
    target = _git_dir(owner, name)
    if not target.exists():
        raise HTTPException(404, detail={"message": "Not Found"})
    refs = await asyncio.to_thread(
        _git, "upload-pack", "--stateless-rpc", "--advertise-refs", str(target)
    )
    body = _pkt("# service=git-upload-pack\n") + b"0000" + refs
    return Response(
        body,
        media_type="application/x-git-upload-pack-advertisement",
        headers={"Cache-Control": "no-cache"},
    )


@app.post("/git/{owner}/{name}/git-upload-pack")
async def git_upload_pack(owner: str, name: str, request: Request) -> Response:
    target = _git_dir(owner, name)
    if not target.exists():
        raise HTTPException(404, detail={"message": "Not Found"})
    data = await request.body()
    if request.headers.get("content-encoding") == "gzip":
        data = gzip.decompress(data)
    out = await asyncio.to_thread(_git, "upload-pack", "--stateless-rpc", str(target), data=data)
    return Response(
        out,
        media_type="application/x-git-upload-pack-result",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/_fake/state")
async def fake_state() -> dict:
    return {
        "repos": fake.repos,
        "pulls": {k: list(v.values()) for k, v in fake.pulls.items()},
        "statuses": fake.statuses,
        "comments": fake.comments,
        "hooks": {k: [{**h, "secret": "***"} for h in v] for k, v in fake.hooks.items()},
        "deliveries": fake.deliveries[-50:],
    }


@app.post("/_fake/reset", status_code=204)
async def fake_reset() -> None:
    fake.reset()
