"""Fixtures dos testes da API: Postgres real (migrado com Alembic) e GitHub simulado
(scripts/fake_github.py) atendendo as chamadas da API pelo transporte ASGI."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import fake_github  # noqa: E402

from sentinela_api.main import build_state, create_app  # noqa: E402
from sentinela_api.services.secrets import MemorySecretStore  # noqa: E402
from sentinela_api.settings import Settings  # noqa: E402

DB_URL = os.environ.get(
    "SENTINELA_TEST_DATABASE_URL",
    "postgresql://sentinela:sentinela@localhost:56432/sentinela_test",
)
WEBHOOK_SECRET = "segredo-do-webhook"
REG_TOKEN = "snt_reg_00000000-0000-4000-8000-0000000000aa.segredo-de-registro"
USER_HEADER = "X-Sentinela-User"


@pytest.fixture(scope="session")
def migrated_db() -> str:
    env = {**os.environ, "SENTINELA_DATABASE_URL": DB_URL}
    cwd = ROOT / "sentinela-api"
    alembic = [sys.executable, "-m", "alembic"]
    subprocess.run(
        [*alembic, "downgrade", "base"], cwd=cwd, env=env, check=True, capture_output=True
    )
    subprocess.run([*alembic, "upgrade", "head"], cwd=cwd, env=env, check=True, capture_output=True)
    return DB_URL


@pytest.fixture(scope="session")
def settings(migrated_db) -> Settings:
    return Settings(
        database_url=migrated_db,
        auth_mode="dev",
        secret_store="memory",
        reconciler_enabled=False,
        bootstrap_admins="admin",
        enable_fake_engine=True,
        default_team="plataforma",
        public_url="http://console.test",
        public_api_url="http://api.test",
        claim_wait_s=0.2,
        bootstrap_runner_token=REG_TOKEN,
    )


@pytest.fixture(scope="session")
def gh() -> fake_github.FakeGitHub:
    return fake_github.fake


@pytest.fixture(scope="session")
async def app(settings):
    transport = httpx.ASGITransport(app=fake_github.app)
    state = await build_state(
        settings, secrets_store=MemorySecretStore(), provider_transport=transport
    )
    application = create_app(settings, state=state)
    async with LifespanManager(application):
        yield application


def _client(app, user: str | None) -> httpx.AsyncClient:
    headers = {USER_HEADER: user} if user else {}
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api.test", headers=headers
    )


@pytest.fixture(scope="session")
async def client(app):
    async with _client(app, "admin") as c:
        yield c


@pytest.fixture
def as_user(app):
    clients: list[httpx.AsyncClient] = []

    def make(username: str | None) -> httpx.AsyncClient:
        c = _client(app, username)
        clients.append(c)
        return c

    yield make


@pytest.fixture
def state(app):
    return app.state.sentinela


# ----------------------------------------------------------------------------- ajudantes
def uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def sha(seed: str) -> str:
    return hashlib.sha1(seed.encode()).hexdigest()


async def ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, f"{resp.status_code}: {resp.text}"
    return resp.json() if resp.content else None


async def make_team(client) -> str:
    name = uid("time")
    await ok(await client.post("/api/v1/teams", json={"name": name}), 201)
    return name


async def grant(client, team: str, username: str, role: str) -> None:
    await ok(
        await client.post(f"/api/v1/teams/{team}/roles", json={"username": username, "role": role}),
        201,
    )
    await link_logins(client, username)


async def link_logins(client, username: str) -> None:
    """Vincula o login do GitHub/GitLab igual ao usuário (requisito para decidir gates)."""
    users = await ok(await client.get("/api/v1/users"))
    user = next(u for u in users if u["username"] == username)
    if user["github_login"] != username:
        await ok(
            await client.patch(
                f"/api/v1/users/{user['id']}",
                json={"github_login": username, "gitlab_username": username},
            )
        )


async def make_integration(client) -> dict:
    return await ok(
        await client.post(
            "/api/v1/integrations",
            json={
                "name": uid("github"),
                "provider": "github",
                "api_url": "http://github.fake",
                "web_url": "https://github.fake",
                "token": "ghp_token_de_teste",
                "webhook_secret": WEBHOOK_SECRET,
            },
        ),
        201,
    )


async def make_profile(client, team: str, template: str = "python-api", **kw) -> dict:
    body = {"name": kw.pop("name", uid("perfil")), "template": template, **kw}
    return await ok(await client.post(f"/api/v1/teams/{team}/profiles", json=body), 201)


async def make_repo(client, gh, team: str, integration: dict, profiles: list[str], **kw) -> dict:
    full = kw.pop("full_name", f"loja/{uid('api')}")
    gh.create_repo(full, "main", kw.pop("required_contexts", ["sentinela/gate"]))
    body = {"integration_id": integration["id"], "full_name": full, "profile_ids": profiles, **kw}
    return await ok(await client.post(f"/api/v1/teams/{team}/repositories", json=body), 201)


def pr_payload(
    gh,
    full: str,
    number: int,
    head: str,
    *,
    action: str = "opened",
    author: str = "ana",
    base: str = "main",
    title: str = "Lista pedidos",
    state: str = "open",
    merged: bool = False,
    draft: bool = False,
) -> dict:
    pr = {
        "number": number,
        "title": title,
        "body": "Adiciona rota de pedidos",
        "author": author,
        "head_ref": f"feat/{number}",
        "head_sha": head,
        "base_ref": base,
        "base_sha": sha("base"),
        "state": state,
        "merged": merged,
        "draft": draft,
        "merged_by": "alguem" if merged else None,
    }
    if full in gh.pulls:
        gh.pulls[full][number] = pr
    return {
        "action": action,
        "number": number,
        "pull_request": gh.pr_json(full, pr),
        "repository": {"full_name": full},
        "sender": {"login": author},
    }


async def send_webhook(
    client,
    integration: dict,
    payload: dict,
    *,
    secret: str = WEBHOOK_SECRET,
    event: str = "pull_request",
) -> httpx.Response:
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return await client.post(
        f"/webhooks/github/{integration['id']}",
        content=body,
        headers={
            "X-GitHub-Event": event,
            "X-Hub-Signature-256": sig,
            "X-GitHub-Delivery": str(uuid.uuid4()),
            "Content-Type": "application/json",
        },
    )


class RunnerClient:
    def __init__(self, app, token: str):
        self.http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://api.test",
            headers={"Authorization": f"Bearer {token}"},
        )

    async def claim(self, engines=("fake",), wait_s: float = 0) -> dict | None:
        resp = await self.http.post(
            "/api/v1/runner/claim", json={"engines": list(engines), "wait_s": wait_s}
        )
        if resp.status_code == 204:
            return None
        assert resp.status_code == 200, resp.text
        return resp.json()["review"]

    async def result(
        self, review_id: str, findings: list[dict], summary: str = "ok", stats: dict | None = None
    ) -> None:
        resp = await self.http.post(
            f"/api/v1/runner/reviews/{review_id}/result",
            json={"summary": summary, "findings": findings, "stats": stats or {"cost_usd": 0.0123}},
        )
        assert resp.status_code == 204, resp.text

    async def drain(self) -> None:
        """Esvazia a fila (revisões de outros testes no mesmo banco)."""
        while review := await self.claim(engines=("fake", "claude_code", "copilot_cli")):
            await self.result(review["id"], [])


async def register_runner(app, name: str | None = None) -> RunnerClient:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api.test"
    ) as c:
        data = await ok(
            await c.post(
                "/api/v1/runner/register",
                json={
                    "registration_token": REG_TOKEN,
                    "name": name or uid("runner"),
                    "engines": {"fake": "1.0"},
                    "slots": 2,
                    "labels": ["linux"],
                },
            )
        )
    return RunnerClient(app, data["runner_token"])


def finding(
    rule: str,
    severity: str,
    file: str = "src/app/routers/pedidos.py",
    line: int = 5,
    category: str = "security",
    evidence: str | None = None,
    **kw,
) -> dict:
    return {
        "rule_code": rule,
        "profile": "API Python (FastAPI)",
        "source": kw.pop("source", "ai"),
        "category": category,
        "severity": severity,
        "file": file,
        "line": line,
        "title": kw.pop("title", f"Divergência {rule}"),
        "description": "explicação",
        "suggestion": "faça assim",
        "evidence": evidence or f"linha {rule} {line}",
        "in_diff": True,
        "fingerprint": hashlib.sha1(f"{rule}{file}{evidence}".encode()).hexdigest()[:20],
        **kw,
    }
