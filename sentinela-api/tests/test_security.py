"""Regressões de segurança: tomada de repositório, endereço de clone, autoaprovação,
falso positivo em bloqueante, política relaxada e identidade de runner."""

import hashlib
import hmac
import json

from conftest import (
    WEBHOOK_SECRET,
    finding,
    grant,
    make_integration,
    make_profile,
    make_repo,
    make_team,
    ok,
    pr_payload,
    register_runner,
    send_webhook,
    sha,
    uid,
)
from test_flow import claim_for, detail


async def test_repository_names_are_unique_ignoring_case(client, as_user, gh):
    team_a, team_b = await make_team(client), await make_team(client)
    integration = await make_integration(client)
    profile_b = await make_profile(client, team_b)
    repo = await make_repo(client, gh, team_b, integration, [profile_b["id"]])
    await grant(client, team_a, "lead-a", "tech_lead")
    # outro time não consegue registrar o mesmo repositório com outra grafia
    r = await as_user("lead-a").post(
        f"/api/v1/teams/{team_a}/repositories",
        json={"integration_id": integration["id"], "full_name": repo["full_name"].upper()},
    )
    assert r.status_code in (409, 422), r.text  # o simulador não normaliza a grafia
    # mesmo sem consultar o provedor, a grafia diferente não cria um segundo cadastro
    r = await client.post(
        f"/api/v1/teams/{team_a}/repositories",
        json={
            "integration_id": integration["id"],
            "full_name": repo["full_name"].upper(),
            "lookup": False,
        },
    )
    assert r.status_code == 409, r.text
    # nem pular a consulta ao provedor, nem escolher o endereço de clone
    r = await as_user("lead-a").post(
        f"/api/v1/teams/{team_a}/repositories",
        json={"integration_id": integration["id"], "full_name": "x/y", "lookup": False},
    )
    assert r.status_code == 403
    base = f"/api/v1/teams/{team_b}/repositories/{repo['id']}"
    await grant(client, team_b, "lead-b", "tech_lead")
    r = await as_user("lead-b").patch(base, json={"clone_url": "https://atacante.example/x.git"})
    assert r.status_code == 403
    r = await client.patch(base, json={"clone_url": "https://atacante.example/x.git"})
    assert r.status_code == 422 and "mesmo host" in r.text
    ok_url = f"https://github.fake/{repo['full_name']}.git"
    assert (await ok(await client.patch(base, json={"clone_url": ok_url})))["clone_url"] == ok_url
    # observação publica sucesso: só o administrador global liga
    r = await as_user("lead-b").patch(base, json={"enforcement": "observe"})
    assert r.status_code == 403


async def test_decisions_need_known_author_and_linked_login(client, as_user, gh, app):
    team = await make_team(client)
    integration = await make_integration(client)
    profile = await make_profile(client, team)
    repo = await make_repo(client, gh, team, integration, [profile["id"]])
    full = repo["full_name"]
    await grant(client, team, "rev", "reviewer")
    await grant(client, team, "lead", "tech_lead")
    # revisora sem login vinculado: papel sem identidade comprovada
    await ok(
        await client.post(
            f"/api/v1/teams/{team}/roles", json={"username": "solta", "role": "reviewer"}
        ),
        201,
    )
    head = sha(uid("h"))
    await ok(await send_webhook(client, integration, pr_payload(gh, full, 3, head, author="ana")))
    runner = await register_runner(app)
    review = await claim_for(runner, full, 3)
    await runner.result(
        review["id"],
        [finding("SEC-001", "blocker", source="pattern"), finding("PY-001", "low", line=9)],
    )
    pr_id = (await ok(await client.get(f"/api/v1/teams/{team}/pull-requests")))["items"][0]["id"]
    data = await detail(client, team, pr_id)
    blocker = next(f for f in data["findings"] if f["rule_code"] == "SEC-001")

    # falso positivo num bloqueante é decisão do tech lead, não do revisor
    r = await as_user("rev").post(
        f"/api/v1/teams/{team}/findings/{blocker['id']}/dismiss", json={"reason": "não procede"}
    )
    assert r.status_code == 403 and "tech lead" in r.text
    await ok(
        await as_user("lead").post(
            f"/api/v1/teams/{team}/findings/{blocker['id']}/waive", json={"reason": "sandbox"}
        )
    )
    r = await as_user("solta").post(f"/api/v1/teams/{team}/pull-requests/{pr_id}/approve", json={})
    assert r.status_code == 403 and "Vincule" in r.text
    perms = (await detail(as_user("solta"), team, pr_id))["permissions"]
    assert perms["approve"] is False and perms["dismiss"] is False

    # webhook sem autor (fallback do GitLab, por exemplo) não apaga o autor conhecido
    payload = pr_payload(gh, full, 3, head, author="ana", action="edited")
    payload["pull_request"]["user"] = None
    await ok(await send_webhook(client, integration, payload))
    data = await detail(client, team, pr_id)
    assert data["author_login"] == "ana"
    await ok(
        await as_user("rev").post(f"/api/v1/teams/{team}/pull-requests/{pr_id}/approve", json={})
    )


async def test_webhook_signature_with_unicode_is_rejected_not_crashed(client, gh):
    integration = await make_integration(client)
    body = json.dumps({"action": "opened"}).encode()
    r = await client.post(
        f"/webhooks/github/{integration['id']}",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": "sha256=ção".encode(),
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 401
    good = "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    assert good.startswith("sha256=")


async def test_runner_name_cannot_be_taken_while_active(app):
    name = uid("RUNNER")
    await register_runner(app, name=name)
    import httpx
    from conftest import REG_TOKEN

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api.test"
    ) as c:
        r = await c.post(
            "/api/v1/runner/register",
            json={"registration_token": REG_TOKEN, "name": name, "engines": {"fake": "1.0"}},
        )
    assert r.status_code == 409


async def _repo_with_people(client, gh):
    team = await make_team(client)
    integration = await make_integration(client)
    profile = await make_profile(client, team)
    repo = await make_repo(client, gh, team, integration, [profile["id"]])
    await grant(client, team, "lead", "tech_lead")
    return team, integration, repo["full_name"]


async def _pr_id(client, team: str) -> str:
    page = await ok(await client.get(f"/api/v1/teams/{team}/pull-requests?state=all"))
    return page["items"][0]["id"]


async def test_reopened_finding_is_not_inherited_again(client, as_user, gh, app):
    team, integration, full = await _repo_with_people(client, gh)
    runner = await register_runner(app)
    same = finding("PY-002", "medium", category="standards", evidence="except Exception:")

    async def push(head: str, action: str) -> dict:
        await ok(
            await send_webhook(client, integration, pr_payload(gh, full, 4, head, action=action))
        )
        review = await claim_for(runner, full, 4)
        await runner.result(review["id"], [same])
        return (await detail(client, team, await _pr_id(client, team)))["findings"][0]

    first = await push(sha(uid("c1")), "opened")
    await ok(
        await as_user("lead").post(
            f"/api/v1/teams/{team}/findings/{first['id']}/waive", json={"reason": "legado"}
        )
    )
    second = await push(sha(uid("c2")), "synchronize")
    assert second["status"] == "waived" and second["inherited"] is True
    await ok(
        await as_user("lead").post(
            f"/api/v1/teams/{team}/findings/{second['id']}/reopen", json={"reason": "voltou"}
        )
    )
    third = await push(sha(uid("c3")), "synchronize")
    assert third["status"] == "open" and third["inherited"] is False


async def test_reopening_a_pr_queues_a_new_review(client, gh, app):
    team, integration, full = await _repo_with_people(client, gh)
    head = sha(uid("h"))
    await ok(await send_webhook(client, integration, pr_payload(gh, full, 6, head)))
    closed = pr_payload(gh, full, 6, head, action="closed", state="closed")
    await ok(await send_webhook(client, integration, closed))
    await ok(
        await send_webhook(client, integration, pr_payload(gh, full, 6, head, action="reopened"))
    )
    data = await detail(client, team, await _pr_id(client, team))
    assert data["state"] == "open"
    assert data["review"]["status"] == "queued" and data["current_gate"]["status"] == "reviewing"


async def test_late_webhook_for_an_older_commit_is_ignored(client, gh, app):
    team, integration, full = await _repo_with_people(client, gh)
    old, new = sha(uid("old")), sha(uid("new"))
    late = pr_payload(gh, full, 8, old)  # entregue fora de ordem, depois do commit novo
    await ok(await send_webhook(client, integration, late))
    await ok(
        await send_webhook(client, integration, pr_payload(gh, full, 8, new, action="synchronize"))
    )
    replay = dict(late, action="synchronize")
    await ok(await send_webhook(client, integration, replay))
    data = await detail(client, team, await _pr_id(client, team))
    assert data["head_sha"] == new and data["current_gate"]["head_sha"] == new
