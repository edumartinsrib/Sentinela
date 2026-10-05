"""Ponta a ponta com processos reais: API (uvicorn), GitHub simulado, runner com o motor de
simulação e um repositório git de verdade. Cobre webhook assinado, revisão pelo runner,
status no commit, justificativa, aprovação, merge pela plataforma e webhook de merge.

    uv run pytest tests/e2e
"""

from __future__ import annotations

import base64
import os
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
DB_URL = os.environ.get(
    "SENTINELA_E2E_DATABASE_URL", "postgresql://sentinela:sentinela@localhost:56432/sentinela_e2e"
)
REG_TOKEN = "snt_reg_00000000-0000-4000-8000-0000000000e2.segredo-e2e"
USER = "X-Sentinela-User"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(check: Callable[[], object], timeout: float = 40, what: str = "condição"):
    deadline = time.monotonic() + timeout
    last: object = None
    while time.monotonic() < deadline:
        try:
            last = check()
            if last:
                return last
        except (httpx.HTTPError, KeyError, IndexError, AssertionError):
            pass
        time.sleep(0.3)
    raise AssertionError(f"tempo esgotado esperando {what} (último valor: {last!r})")


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("e2e")
    env_db = {**os.environ, "SENTINELA_DATABASE_URL": DB_URL}
    api_dir = ROOT / "sentinela-api"
    for step in ("downgrade base", "upgrade head"):
        subprocess.run(
            [sys.executable, "-m", "alembic", *step.split()],
            cwd=api_dir,
            env=env_db,
            check=True,
            capture_output=True,
        )

    gh_port, api_port = free_port(), free_port()
    procs: list[subprocess.Popen] = []
    logs = {name: open(tmp / f"{name}.log", "w") for name in ("github", "api", "runner")}  # noqa: SIM115

    def start(name: str, argv: list[str], env: dict[str, str], cwd: Path = ROOT):
        proc = subprocess.Popen(
            argv, cwd=cwd, env={**os.environ, **env}, stdout=logs[name], stderr=subprocess.STDOUT
        )
        procs.append(proc)
        return proc

    start(
        "github",
        [
            sys.executable,
            "-m",
            "uvicorn",
            "fake_github:app",
            "--app-dir",
            "scripts",
            "--port",
            str(gh_port),
            "--log-level",
            "warning",
        ],
        {},
    )
    api_env = {
        "SENTINELA_DATABASE_URL": DB_URL,
        "SENTINELA_AUTH_MODE": "dev",
        "SENTINELA_SECRET_STORE": "db",
        "SENTINELA_SECRET_KEY": "e2e:" + base64.b64encode(os.urandom(32)).decode(),
        "SENTINELA_ENABLE_FAKE_ENGINE": "true",
        "SENTINELA_BOOTSTRAP_RUNNER_TOKEN": REG_TOKEN,
        "SENTINELA_PUBLIC_API_URL": f"http://127.0.0.1:{api_port}",
        "SENTINELA_PUBLIC_URL": "http://console.e2e",
        "SENTINELA_RECONCILE_INTERVAL_S": "2",
        "SENTINELA_CLAIM_WAIT_S": "2",
        "SENTINELA_PORT": str(api_port),
    }
    start("api", [sys.executable, "-m", "sentinela_api.main"], api_env)
    base = f"http://127.0.0.1:{api_port}"
    wait_for(lambda: httpx.get(f"{base}/readyz").status_code == 200, what="API")
    wait_for(
        lambda: httpx.get(f"http://127.0.0.1:{gh_port}/user").status_code == 200,
        what="GitHub simulado",
    )
    start(
        "runner",
        [sys.executable, "-m", "sentinela_runner.main"],
        {
            "SENTINELA_API_URL": base,
            "SENTINELA_REGISTRATION_TOKEN": REG_TOKEN,
            "SENTINELA_ENGINES": "fake",
            "SENTINELA_ENABLE_FAKE_ENGINE": "true",
            "SENTINELA_RUNNER_HOME": str(tmp / "runner"),
            "SENTINELA_RUNNER_NAME": "E2E-RUNNER",
            "SENTINELA_SLOTS": "2",
        },
    )
    yield {"api": base, "github": f"http://127.0.0.1:{gh_port}", "tmp": tmp, "logs": logs}
    for proc in procs:
        proc.terminate()
    for proc in procs:
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
    for f in logs.values():
        f.close()


def make_repo(tmp: Path) -> dict:
    src = tmp / "src"
    src.mkdir()
    git("init", "-q", "-b", "main", cwd=src)
    git("config", "user.email", "dev@empresa", cwd=src)
    git("config", "user.name", "Dev", cwd=src)
    (src / "app" / "routers").mkdir(parents=True)
    (src / "app" / "routers" / "pedidos.py").write_text(
        "from fastapi import APIRouter\n\nrouter = APIRouter()\n"
    )
    git("add", ".", cwd=src)
    git("commit", "-q", "-m", "base", cwd=src)
    base = git("rev-parse", "HEAD", cwd=src)
    git("checkout", "-q", "-b", "feat/pedidos", cwd=src)
    (src / "app" / "routers" / "pedidos.py").write_text(
        "from fastapi import APIRouter\nfrom app.db import session\n\nrouter = APIRouter()\n"
        'API_KEY = "sk-live-0123456789"\n\n\n'
        "@router.get('/pedidos')\n"
        "def listar(cliente: str):\n"
        "    return session.execute(f\"SELECT * FROM pedidos WHERE c = '{cliente}'\")\n"
    )
    git("commit", "-q", "-am", "lista pedidos", cwd=src)
    head = git("rev-parse", "HEAD", cwd=src)
    bare = tmp / "loja-api.git"
    git("clone", "-q", "--bare", str(src), str(bare), cwd=tmp)
    git("update-ref", "refs/pull/1/head", head, cwd=bare)
    return {"bare": bare, "base": base, "head": head}


def test_end_to_end(stack):
    api, gh, tmp = stack["api"], stack["github"], stack["tmp"]
    admin = httpx.Client(base_url=api, headers={USER: "admin"}, timeout=30)
    repo_git = make_repo(tmp)
    full = "loja/api-pedidos"
    httpx.post(
        f"{gh}/_fake/repos", json={"full_name": full, "required_contexts": ["sentinela/gate"]}
    ).raise_for_status()

    team = admin.post("/api/v1/teams", json={"name": "loja"}).json()["name"]
    for user, role in (("ana", "developer"), ("bia", "reviewer"), ("caio", "tech_lead")):
        admin.post(f"/api/v1/teams/{team}/roles", json={"username": user, "role": role})
    # o login no GitHub de cada pessoa é o que comprova quem não é o autor do PR
    for u in admin.get("/api/v1/users").json():
        if u["username"] in ("ana", "bia", "caio"):
            admin.patch(f"/api/v1/users/{u['id']}", json={"github_login": u["username"]})
    integ = admin.post(
        "/api/v1/integrations",
        json={
            "name": "GitHub simulado",
            "provider": "github",
            "api_url": gh,
            "web_url": "https://github.fake",
            "token": "ghp_e2e",
        },
    ).json()
    assert integ["last_check_ok"], integ
    profile = admin.post(
        f"/api/v1/teams/{team}/profiles", json={"name": "API Python", "template": "python-api"}
    ).json()
    repo = admin.post(
        f"/api/v1/teams/{team}/repositories",
        json={
            "integration_id": integ["id"],
            "full_name": full,
            "profile_ids": [profile["id"]],
            "gate_mode": "both",
            "clone_url": repo_git["bare"].as_uri(),
        },
    ).json()
    assert admin.post(f"/api/v1/teams/{team}/repositories/{repo['id']}/webhook").status_code == 200
    wait_for(
        lambda: any(r["status"] == "online" for r in admin.get("/api/v1/runners").json()),
        what="runner online",
    )

    # ------------------------------------------------------------ PR aberto → revisão
    httpx.post(
        f"{gh}/_fake/repos/{full}/pulls",
        json={
            "number": 1,
            "title": "Lista pedidos por cliente",
            "author": "ana",
            "head_ref": "feat/pedidos",
            "head_sha": repo_git["head"],
            "base_sha": repo_git["base"],
        },
    ).raise_for_status()

    def gate():
        items = admin.get(f"/api/v1/teams/{team}/pull-requests").json()["items"]
        return items[0] if items and items[0]["gate"] else None

    pr = wait_for(
        lambda: (g := gate()) and g["gate"]["status"] == "blocked" and g,
        timeout=60,
        what="gate bloqueado",
    )
    detail = admin.get(f"/api/v1/teams/{team}/pull-requests/{pr['id']}").json()
    codes = {f["rule_code"]: f for f in detail["findings"]}
    assert codes["SEC-001"]["source"] == "pattern" and codes["SEC-001"]["blocking"]
    assert {"SEC-005", "ARQ-001"} <= set(codes)
    assert detail["review"]["runner_name"] == "E2E-RUNNER"
    assert detail["review"]["stats"]["files_changed"] == 1

    state = httpx.get(f"{gh}/_fake/state").json()
    statuses = state["statuses"][f"{full}@{repo_git['head']}"]
    assert statuses[0]["state"] == "pending" and statuses[-1]["state"] == "failure"
    assert "Bloqueado" in state["comments"][f"{full}#1"][0]["body"]

    logs = admin.get(f"/api/v1/teams/{team}/reviews/{detail['review']['id']}/logs").json()
    text = "\n".join(line["text"] for line in logs["lines"])
    assert "arquivo(s) alterado(s)" in text and "ghp_e2e" not in text

    # ------------------------------------------------------------ tratamento e aprovação
    caio = httpx.Client(base_url=api, headers={USER: "caio"})
    bia = httpx.Client(base_url=api, headers={USER: "bia"})
    ana = httpx.Client(base_url=api, headers={USER: "ana"})
    for f in detail["findings"]:
        if f["blocking"]:
            r = caio.post(
                f"/api/v1/teams/{team}/findings/{f['id']}/waive",
                json={"reason": "chave de sandbox; remoção no próximo PR"},
            )
            assert r.status_code == 200, r.text
    r = ana.post(f"/api/v1/teams/{team}/pull-requests/{pr['id']}/approve", json={})
    assert r.status_code == 403
    r = bia.post(
        f"/api/v1/teams/{team}/pull-requests/{pr['id']}/approve",
        json={"comment": "exceções registradas"},
    )
    assert r.status_code == 200 and r.json()["current_gate"]["status"] == "approved", r.text
    state = httpx.get(f"{gh}/_fake/state").json()
    assert state["statuses"][f"{full}@{repo_git['head']}"][-1]["state"] == "success"

    # ------------------------------------------------------------ merge pela plataforma
    r = ana.post(f"/api/v1/teams/{team}/pull-requests/{pr['id']}/merge", json={})
    assert r.status_code == 200 and r.json()["merged"], r.text
    final = wait_for(
        lambda: (
            (d := admin.get(f"/api/v1/teams/{team}/pull-requests/{pr['id']}").json())
            and d["state"] == "merged"
            and d
        ),
        what="PR com merge",
    )
    assert final["merged_without_gate"] is False
    deliveries = admin.get(f"/api/v1/integrations/{integ['id']}/deliveries").json()
    assert {d["action"] for d in deliveries} >= {"opened", "closed"}
    dash = admin.get(f"/api/v1/teams/{team}/dashboard").json()
    assert dash["kpis"]["approved_7d"] >= 1 and dash["runners_online"] >= 1
