"""Cadastros: times, papéis, IA, integrações, perfis e regras, repositórios, runners."""

import json

import httpx
import pytest
from conftest import (
    grant,
    make_integration,
    make_profile,
    make_repo,
    make_team,
    ok,
    register_runner,
    uid,
)

from sentinela_api.providers.gitlab import GitLabClient
from sentinela_api.services.secrets import DbSecretStore, KeyRing


async def test_config_me_and_seed(client, as_user):
    cfg = await ok(await as_user(None).get("/api/v1/config"))
    assert cfg["auth"]["mode"] == "dev"
    me = await ok(await client.get("/api/v1/me"))
    assert me["is_superadmin"] and any(t["name"] == "plataforma" for t in me["teams"])
    r = await as_user(None).get("/api/v1/me")
    assert r.status_code == 401
    engines = await ok(await client.get("/api/v1/ai/engines"))
    kinds = {e["kind"] for e in engines}
    assert kinds == {"claude_code", "copilot_cli", "fake"}
    models = await ok(await client.get("/api/v1/ai/models"))
    defaults = [x for x in models if x["is_default"]]
    assert len(defaults) == 1 and defaults[0]["engine_kind"] == "fake"


async def test_teams_and_roles(client, as_user):
    team = await make_team(client)
    r = await as_user("ze").post("/api/v1/teams", json={"name": uid("t")})
    assert r.status_code == 403
    await grant(client, team, "ze", "tech_lead")
    r = await client.post(
        f"/api/v1/teams/{team}/roles", json={"username": "ze", "role": "tech_lead"}
    )
    assert r.status_code == 409
    me = await ok(await as_user("ze").get("/api/v1/me"))
    assert [t["name"] for t in me["teams"]] == [team]
    assert me["roles"] == [{"team": team, "role": "tech_lead"}]
    r = await as_user("ze").get(f"/api/v1/teams/{team}/roles")
    assert r.status_code == 403  # papéis só o admin do time
    roles = await ok(await client.get(f"/api/v1/teams/{team}/roles"))
    await ok(await client.delete(f"/api/v1/teams/{team}/roles/{roles[0]['id']}"), 204)
    r = await as_user("ze").get(f"/api/v1/teams/{team}/profiles")
    assert r.status_code == 403


async def test_users_provider_logins_only_by_admin(client, as_user):
    created = await ok(
        await client.post(
            "/api/v1/users",
            json={"username": uid("u"), "github_login": "Gh-User", "gitlab_username": "gl"},
        ),
        201,
    )
    assert created["github_login"] == "Gh-User"
    r = await as_user("qualquer").patch(
        f"/api/v1/users/{created['id']}", json={"github_login": "outro"}
    )
    assert r.status_code == 403
    out = await ok(await client.patch(f"/api/v1/users/{created['id']}", json={"github_login": ""}))
    assert out["github_login"] is None


async def test_ai_engines_and_models_admin_only(client, as_user, state):
    r = await as_user("dev").post("/api/v1/ai/models", json={"engine_id": "x", "label": "x"})
    assert r.status_code == 403
    engine = await ok(
        await client.post(
            "/api/v1/ai/engines",
            json={"kind": "claude_code", "name": uid("Claude"), "max_turns": 12, "timeout_s": 600},
        ),
        201,
    )
    model = await ok(
        await client.post(
            "/api/v1/ai/models",
            json={"engine_id": engine["id"], "model": "claude-opus-5-5", "label": "Opus 5.5"},
        ),
        201,
    )
    r = await client.post(
        "/api/v1/ai/models",
        json={"engine_id": engine["id"], "model": "claude-opus-5-5", "label": "dup"},
    )
    assert r.status_code == 409
    out = await ok(
        await client.put(
            f"/api/v1/ai/engines/{engine['id']}/secrets",
            json={"values": {"ANTHROPIC_API_KEY": "sk-ant-1"}},
        )
    )
    assert out["secret_env_names"] == ["ANTHROPIC_API_KEY"]
    assert "sk-ant" not in json.dumps(out)
    r = await client.put(
        f"/api/v1/ai/engines/{engine['id']}/secrets", json={"values": {"nome ruim": "x"}}
    )
    assert r.status_code == 422
    default = await ok(await client.put("/api/v1/ai/default", json={"model_id": model["id"]}))
    assert default["is_default"]
    models = await ok(await client.get("/api/v1/ai/models"))
    assert [x["id"] for x in models if x["is_default"]] == [model["id"]]
    # volta o simulador como padrão para os outros testes
    fake = next(x for x in models if x["engine_kind"] == "fake")
    await ok(await client.put("/api/v1/ai/default", json={"model_id": fake["id"]}))
    await ok(await client.delete(f"/api/v1/ai/engines/{engine['id']}"), 204)
    assert await state.secrets.read(f"engines/{engine['id']}") is None


async def test_integrations(client, as_user, gh):
    integration = await make_integration(client)
    assert integration["last_check_ok"] and integration["bot_login"] == "sentinela-bot"
    assert integration["has_token"] and integration["has_webhook_secret"]
    assert integration["webhook_url"] == f"http://api.test/webhooks/github/{integration['id']}"
    assert "token" not in json.dumps(
        {k: v for k, v in integration.items() if k not in ("has_token",)}
    )
    secret = await ok(await client.get(f"/api/v1/integrations/{integration['id']}/webhook-secret"))
    assert secret["webhook_secret"] == "segredo-do-webhook"
    gh.create_repo(f"org/{uid('remoto')}")
    team = await make_team(client)
    await grant(client, team, "lead", "tech_lead")
    remotes = await ok(
        await as_user("lead").get(
            f"/api/v1/integrations/{integration['id']}/remote-repositories",
            params={"search": "org/"},
        )
    )
    assert remotes and all(r["full_name"].startswith("org/") for r in remotes)
    r = await as_user("dev-solto").get(
        f"/api/v1/integrations/{integration['id']}/remote-repositories"
    )
    assert r.status_code == 403
    gl = await ok(
        await client.post(
            "/api/v1/integrations",
            json={
                "name": uid("gitlab"),
                "provider": "gitlab",
                "web_url": "https://gitlab.empresa.local",
                "token": "glpat-x",
            },
        ),
        201,
    )
    assert gl["api_url"] == "https://gitlab.empresa.local/api/v4"


async def test_profiles_rules_import_export(client, as_user):
    team = await make_team(client)
    await grant(client, team, "dev1", "developer")
    r = await as_user("dev1").post(f"/api/v1/teams/{team}/profiles", json={"name": "x"})
    assert r.status_code == 403
    profile = await make_profile(client, team, name="API Python")
    assert profile["rules_total"] == 15 and profile["rules_by_kind"]["pattern"] == 4
    assert profile["path_globs"][0] == "**/*.py"
    base = f"/api/v1/teams/{team}/profiles/{profile['id']}"

    r = await client.post(
        f"{base}/rules",
        json={"code": "X-1", "title": "regex ruim", "kind": "pattern", "pattern": "("},
    )
    assert r.status_code == 422 and "expressão regular" in r.text
    rule = await ok(
        await client.post(
            f"{base}/rules",
            json={
                "code": "arq-9",
                "title": "Sem import circular",
                "category": "architecture",
                "severity": "medium",
                "instruction": "Módulos não se importam em ciclo.",
                "paths": ["src/**"],
            },
        ),
        201,
    )
    assert rule["code"] == "ARQ-9"
    r = await client.patch(f"{base}/rules/{rule['id']}", json={"kind": "pattern"})
    assert r.status_code == 422  # padrão sem regex
    rule = await ok(
        await client.patch(
            f"{base}/rules/{rule['id']}", json={"severity": "blocker", "enabled": False}
        )
    )
    assert rule["severity"] == "blocker" and not rule["enabled"]

    test = await ok(
        await client.post(
            f"/api/v1/teams/{team}/pattern-test",
            json={"pattern": r"print\(", "sample": "x = 1\nprint(x)"},
        )
    )
    assert test["matches"][0]["line"] == 2
    bad = await ok(
        await client.post(
            f"/api/v1/teams/{team}/pattern-test", json={"pattern": "(", "sample": "x"}
        )
    )
    assert bad["valid"] is False

    exported = await client.get(f"{base}/export")
    assert exported.status_code == 200 and "ARQ-9" in exported.text
    assert exported.headers["content-disposition"].endswith('api-python.yaml"')
    r = await client.post(f"/api/v1/teams/{team}/profiles/import", json={"yaml": exported.text})
    assert r.status_code == 409
    changed = exported.text.replace("Sem import circular", "Sem ciclos de import")
    imported = await ok(
        await client.post(
            f"/api/v1/teams/{team}/profiles/import", json={"yaml": changed, "replace": True}
        )
    )
    assert imported["id"] == profile["id"]
    assert any(r["title"] == "Sem ciclos de import" for r in imported["rules"])
    r = await client.post(
        f"/api/v1/teams/{team}/profiles/import",
        json={"yaml": "name: x\nrules:\n  - code: A-1\n    title: abc\n"},
    )
    assert r.status_code == 422

    other = await ok(
        await client.post(
            f"/api/v1/teams/{team}/profiles", json={"name": "Terraform", "path_globs": ["**/*.tf"]}
        ),
        201,
    )
    out = await ok(
        await client.post(
            f"/api/v1/teams/{team}/profiles/{other['id']}/library",
            json={"keys": ["IAC-001", "IAC-002", "IAC-001"]},
        )
    )
    assert [r["code"] for r in out["rules"]] == ["IAC-001", "IAC-002"]
    lib = await ok(await client.get("/api/v1/library"))
    assert {t["key"] for t in lib["templates"]} >= {"python-api", "react-frontend"}

    r = await as_user("dev1").patch(base, json={"model_id": None})
    assert r.status_code == 403
    await ok(await client.delete(f"{base}/rules/{rule['id']}"), 204)
    await ok(await client.delete(base), 204)


async def test_repository_settings(client, as_user, gh):
    team = await make_team(client)
    integration = await make_integration(client)
    profile = await make_profile(client, team)
    repo = await make_repo(
        client,
        gh,
        team,
        integration,
        [profile["id"]],
        gated_branches=["main", "release/*"],
        gate_mode="both",
        approval_mode="always_human",
        min_approvals=2,
    )
    assert repo["default_branch"] == "main" and repo["external_id"]
    assert repo["profiles"][0]["name"] == profile["name"]
    r = await client.post(
        f"/api/v1/teams/{team}/repositories",
        json={"integration_id": integration["id"], "full_name": repo["full_name"]},
    )
    assert r.status_code == 409
    r = await client.post(
        f"/api/v1/teams/{team}/repositories",
        json={"integration_id": integration["id"], "full_name": "nao/existe"},
    )
    assert r.status_code == 422
    base = f"/api/v1/teams/{team}/repositories/{repo['id']}"
    await grant(client, team, "lead2", "tech_lead")
    updated = await ok(
        await as_user("lead2").patch(
            base, json={"block_severity": "blocker", "post_comments": False, "gated_branches": []}
        )
    )
    assert updated["block_severity"] == "blocker" and updated["gated_branches"] == ["main"]
    r = await as_user("lead2").patch(base, json={"model_id": None})
    assert r.status_code == 403

    prot = await ok(await client.get(f"{base}/protection"))
    names = {c["name"]: c for c in prot["checks"]}
    assert names["Status sentinela/gate obrigatório"]["ok"] is True
    assert names["Merge restrito ao robô"]["ok"] is False
    assert prot["ok"] is False

    hooked = await ok(await client.post(f"{base}/webhook"))
    assert hooked["webhook_configured"]
    assert gh.hooks[repo["full_name"]][0]["url"].endswith(integration["id"])

    synced = await ok(await client.post(f"{base}/sync"))
    assert synced == {"pull_requests": 0, "reviews_queued": 0}
    await ok(await client.delete(base), 204)


async def test_runner_registration_and_tokens(client, app):
    r = await httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api.test"
    ).post("/api/v1/runner/register", json={"registration_token": "snt_reg_invalido", "name": "x"})
    assert r.status_code == 401
    created = await ok(
        await client.post("/api/v1/runner-tokens", json={"description": "runners linux"}), 201
    )
    assert created["token"].startswith("snt_reg_")
    runner = await register_runner(app, name=uid("RUNNER"))
    cfg = await ok(await runner.http.get("/api/v1/runner/config"))
    assert cfg["enabled"] and not cfg["draining"]
    runners = await ok(await client.get("/api/v1/runners"))
    mine = next(x for x in runners if x["name"] == cfg["runner_name"])
    assert mine["status"] == "online" and mine["engines"] == {"fake": "1.0"}
    await ok(await client.patch(f"/api/v1/runners/{mine['id']}", json={"draining": True}))
    assert await runner.claim() is None  # drenando não pega revisão
    await ok(await client.delete(f"/api/v1/runner-tokens/{created['id']}"), 204)
    bad = await runner.http.get(
        "/api/v1/runner/config", headers={"Authorization": "Bearer snt_rn_x.y"}
    )
    assert bad.status_code == 401


async def test_db_secret_store_roundtrip(app):
    store = DbSecretStore(KeyRing(f"k2:{KeyRing.generate()},k1:{KeyRing.generate()}"))
    await store.write("teste/x", {"token": "abc"})
    assert await store.read("teste/x") == {"token": "abc"}
    await store.write("teste/x", {"token": "def"})
    assert await store.read("teste/x") == {"token": "def"}
    other = DbSecretStore(KeyRing(KeyRing.generate()))
    with pytest.raises(ValueError):
        await other.read("teste/x")
    await store.delete("teste/x")
    assert await store.read("teste/x") is None


# ----------------------------------------------------------------------------- GitLab
def gitlab_transport(calls: list):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.raw_path.decode(), request.content))
        path = request.url.raw_path.decode()
        if path.endswith("/merge_requests/4"):
            return httpx.Response(
                200,
                json={
                    "iid": 4,
                    "title": "MR",
                    "description": "d",
                    "author": {"username": "ana"},
                    "source_branch": "feat",
                    "target_branch": "main",
                    "sha": "h" * 40,
                    "diff_refs": {"base_sha": "b" * 40},
                    "web_url": "https://gl/x/-/merge_requests/4",
                    "state": "opened",
                    "draft": False,
                },
            )
        if "/statuses/" in path and request.method == "POST":
            body = json.loads(request.content)
            if body["state"] == "pending" and len([c for c in calls if "/statuses/" in c[1]]) > 1:
                return httpx.Response(
                    400, json={"message": "Cannot transition status via :enqueue"}
                )
            return httpx.Response(201, json={"id": 1})
        if path.startswith("/api/v4/projects/grupo%2Fapi/protected_branches/main"):
            return httpx.Response(
                200,
                json={
                    "name": "main",
                    "merge_access_levels": [
                        {"access_level": 30, "access_level_description": "Developers + Maintainers"}
                    ],
                },
            )
        if path == "/api/v4/projects/grupo%2Fapi":
            return httpx.Response(
                200,
                json={
                    "only_allow_merge_if_pipeline_succeeds": True,
                    "allow_merge_on_skipped_pipeline": True,
                    "path_with_namespace": "grupo/api",
                    "id": 9,
                },
            )
        if path.endswith("/merge"):
            return httpx.Response(405, json={"message": "Method Not Allowed"})
        return httpx.Response(404, json={"message": "404 Not Found"})

    return httpx.MockTransport(handler)


async def test_gitlab_client():
    calls: list = []
    client = GitLabClient(
        "https://gl/api/v4", "https://gl", "glpat", transport=gitlab_transport(calls)
    )
    mr = await client.get_pull_request("grupo/api", 4)
    assert mr.author_login == "ana" and mr.base_sha == "b" * 40 and mr.state == "open"
    await client.set_status("grupo/api", "h" * 40, "failure", "bloqueado", "sentinela/gate", None)
    sent = json.loads(calls[-1][2])
    assert sent["state"] == "failed" and sent["name"] == "sentinela/gate"
    await client.set_status("grupo/api", "h" * 40, "pending", "x", "sentinela/gate", None)
    await client.set_status("grupo/api", "h" * 40, "pending", "x", "sentinela/gate", None)
    report = await client.check_protection(
        "grupo/api", "main", "sentinela/gate", require_status=True, platform_merge=True
    )
    checks = {c["name"]: c["ok"] for c in report.checks}
    assert checks["Pipelines precisam passar"] and not checks["Merge restrito ao robô"]
    assert not checks["Pipeline ignorada não libera merge"]
    result = await client.merge("grupo/api", 4, "h" * 40, "squash", None)
    assert result.merged is False
    assert client.clone_url("grupo/api") == "https://gl/grupo/api.git"
