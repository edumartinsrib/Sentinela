"""Fluxo completo do gate: webhook → revisão → apontamentos → justificativa → aprovação →
status no provedor → merge pela plataforma."""

from datetime import UTC, datetime, timedelta

from conftest import (
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
from sqlalchemy import select, update

from sentinela_api import models as m
from sentinela_api.db import sessionmaker
from sentinela_api.services import reconciler, reviews


async def claim_for(runner, full_name: str, number: int) -> dict:
    for _ in range(50):
        review = await runner.claim(engines=("fake", "claude_code", "copilot_cli"))
        assert review is not None, "nenhuma revisão na fila"
        if (
            review["repository"]["full_name"] == full_name
            and review["pull_request"]["number"] == number
        ):
            return review
        await runner.result(review["id"], [])
    raise AssertionError("revisão não encontrada")


async def setup_repo(client, gh, **kw):
    team = await make_team(client)
    integration = await make_integration(client)
    profile = await make_profile(client, team)
    repo = await make_repo(client, gh, team, integration, [profile["id"]], **kw)
    return team, integration, profile, repo


def statuses(gh, full: str, head: str) -> list[dict]:
    return gh.statuses.get(f"{full}@{head}", [])


async def detail(client, team: str, pr_id: str) -> dict:
    return await ok(await client.get(f"/api/v1/teams/{team}/pull-requests/{pr_id}"))


async def test_full_gate_flow(client, as_user, gh, app):
    team, integration, profile, repo = await setup_repo(client, gh, gate_mode="both")
    full = repo["full_name"]
    for user, role in (("ana", "developer"), ("bia", "reviewer"), ("caio", "tech_lead")):
        await grant(client, team, user, role)

    head = sha(uid("commit"))
    resp = await send_webhook(client, integration, pr_payload(gh, full, 7, head, author="ana"))
    assert (await ok(resp))["outcome"] == "processed"

    page = await ok(await client.get(f"/api/v1/teams/{team}/pull-requests"))
    assert page["total"] == 1
    pr = page["items"][0]
    assert pr["gate"]["status"] == "reviewing"
    assert statuses(gh, full, head)[-1]["state"] == "pending"

    runner = await register_runner(app)
    review = await claim_for(runner, full, 7)
    assert review["git"]["username"] == "x-access-token"
    assert review["git"]["token"] == "ghp_token_de_teste"
    assert review["repository"]["clone_url"] == f"https://github.fake/{full}.git"
    assert review["engine"]["kind"] == "fake"
    assert review["profiles"][0]["name"] == profile["name"]
    assert "ghp_token_de_teste" in review["mask_values"]

    await runner.result(
        review["id"],
        [
            finding("SEC-001", "blocker", source="pattern", evidence='API_KEY = "x"'),
            finding("PY-001", "low", category="standards", line=9),
        ],
        summary="Rota nova lista pedidos.",
    )
    data = await detail(client, team, pr["id"])
    assert data["current_gate"]["status"] == "blocked"
    assert data["current_gate"]["human_required"] is True
    assert data["review"]["summary"] == "Rota nova lista pedidos."
    assert [f["rule_code"] for f in data["findings"]] == ["SEC-001", "PY-001"]
    assert data["findings"][0]["blocking"] is True
    assert data["findings"][0]["rule_title"] == "Segredo ou credencial no código"
    assert data["findings"][0]["file_url"].endswith("/src/app/routers/pedidos.py#L5")
    assert statuses(gh, full, head)[-1]["state"] == "failure"
    comments = gh.comments[f"{full}#7"]
    assert len(comments) == 1 and "Bloqueado" in comments[0]["body"]

    ana, bia, caio = as_user("ana"), as_user("bia"), as_user("caio")
    # autor não aprova; revisor não aprova com bloqueante; dev não justifica
    r = await ana.post(f"/api/v1/teams/{team}/pull-requests/{pr['id']}/approve", json={})
    assert r.status_code == 403
    r = await bia.post(f"/api/v1/teams/{team}/pull-requests/{pr['id']}/approve", json={})
    assert r.status_code == 409 and "bloqueantes" in r.json()["detail"]
    blocker, low = data["findings"]
    r = await ana.post(
        f"/api/v1/teams/{team}/findings/{blocker['id']}/waive", json={"reason": "sem permissão"}
    )
    assert r.status_code == 403
    # dev contesta, tech lead aceita como exceção
    await ok(
        await ana.post(
            f"/api/v1/teams/{team}/findings/{blocker['id']}/dispute",
            json={"reason": "é chave de teste"},
        )
    )
    out = await ok(
        await caio.post(
            f"/api/v1/teams/{team}/findings/{blocker['id']}/waive",
            json={"reason": "chave fake usada só no exemplo"},
        )
    )
    assert out["status"] == "waived" and [e["action"] for e in out["events"]] == [
        "dispute",
        "waive",
    ]

    data = await detail(client, team, pr["id"])
    assert data["current_gate"]["status"] == "awaiting_approval"
    assert statuses(gh, full, head)[-1]["state"] == "pending"
    assert data["permissions"]["merge"] is False

    # merge pela plataforma ainda recusado; aprovação de terceiro libera
    r = await ana.post(f"/api/v1/teams/{team}/pull-requests/{pr['id']}/merge", json={})
    assert r.status_code == 409
    data = await ok(
        await bia.post(
            f"/api/v1/teams/{team}/pull-requests/{pr['id']}/approve",
            json={"comment": "ok com a exceção"},
        )
    )
    assert data["current_gate"]["status"] == "approved"
    assert data["current_gate"]["approved_by"] == ["bia"]
    assert statuses(gh, full, head)[-1]["state"] == "success"
    assert "Aprovado" in gh.comments[f"{full}#7"][0]["body"]

    merged = await ok(
        await ana.post(
            f"/api/v1/teams/{team}/pull-requests/{pr['id']}/merge", json={"method": "squash"}
        )
    )
    assert merged["merged"] is True
    data = await detail(client, team, pr["id"])
    assert data["state"] == "merged" and data["merged_without_gate"] is False

    audit = await ok(await client.get(f"/api/v1/teams/{team}/audit"))
    actions = {a["action"] for a in audit["items"]}
    assert {"finding.dispute", "finding.waive", "gate.approve", "pull_request.merge"} <= actions


async def test_ai_approves_clean_review_and_new_push_resets(client, as_user, gh, app):
    team, integration, _, repo = await setup_repo(client, gh)
    full = repo["full_name"]
    head1 = sha(uid("c1"))
    await ok(await send_webhook(client, integration, pr_payload(gh, full, 3, head1)))
    runner = await register_runner(app)
    review = await claim_for(runner, full, 3)
    await runner.result(review["id"], [])
    page = await ok(await client.get(f"/api/v1/teams/{team}/pull-requests"))
    pr = page["items"][0]
    assert pr["gate"]["status"] == "approved" and pr["gate"]["human_required"] is False
    assert statuses(gh, full, head1)[-1]["description"].startswith("Aprovado pela IA")

    # novo commit: gate novo em revisão, o antigo fica substituído
    head2 = sha(uid("c2"))
    await ok(
        await send_webhook(
            client, integration, pr_payload(gh, full, 3, head2, action="synchronize")
        )
    )
    data = await detail(client, team, pr["id"])
    assert data["current_gate"]["head_sha"] == head2
    assert data["current_gate"]["status"] == "reviewing"
    assert [h["gate"]["status"] for h in data["history"]] == ["reviewing", "stale"]
    assert statuses(gh, full, head2)[-1]["state"] == "pending"


async def test_waivers_carry_over_to_next_commit(client, as_user, gh, app):
    team, integration, _, repo = await setup_repo(client, gh)
    full = repo["full_name"]
    await grant(client, team, "tl", "tech_lead")
    runner = await register_runner(app)
    head1 = sha(uid("c1"))
    await ok(await send_webhook(client, integration, pr_payload(gh, full, 4, head1)))
    review = await claim_for(runner, full, 4)
    item = finding("SEC-005", "high", evidence="db.execute(f'select {x}')")
    await runner.result(review["id"], [item])
    pr_id = (await ok(await client.get(f"/api/v1/teams/{team}/pull-requests")))["items"][0]["id"]
    data = await detail(client, team, pr_id)
    fid = data["findings"][0]["id"]
    await ok(
        await as_user("tl").post(
            f"/api/v1/teams/{team}/findings/{fid}/waive",
            json={"reason": "consulta interna validada"},
        )
    )

    head2 = sha(uid("c2"))
    await ok(
        await send_webhook(
            client, integration, pr_payload(gh, full, 4, head2, action="synchronize")
        )
    )
    review = await claim_for(runner, full, 4)
    await runner.result(review["id"], [{**item, "line": 40}])
    data = await detail(client, team, pr_id)
    f = data["findings"][0]
    assert f["status"] == "waived" and f["inherited"] is True
    assert f["status_reason"] == "consulta interna validada"
    # a justificativa herdada não dispensa o humano: houve apontamento
    assert data["current_gate"]["status"] == "awaiting_approval"


async def test_rejection_survives_rerun(client, as_user, gh, app):
    team, integration, _, repo = await setup_repo(client, gh)
    full = repo["full_name"]
    await grant(client, team, "rev", "reviewer")
    await grant(client, team, "dev", "developer")
    runner = await register_runner(app)
    await ok(await send_webhook(client, integration, pr_payload(gh, full, 5, sha(uid("h")))))
    review = await claim_for(runner, full, 5)
    await runner.result(review["id"], [finding("PY-003", "low", category="standards")])
    pr_id = (await ok(await client.get(f"/api/v1/teams/{team}/pull-requests")))["items"][0]["id"]

    r = await as_user("rev").post(
        f"/api/v1/teams/{team}/pull-requests/{pr_id}/reject", json={"comment": "faltou teste"}
    )
    data = await ok(r)
    assert data["current_gate"]["status"] == "rejected"
    # leitor/sem papel não reexecuta; dev reexecuta
    r = await as_user("estranho").post(
        f"/api/v1/teams/{team}/pull-requests/{pr_id}/reviews", json={}
    )
    assert r.status_code == 403
    rerun = await ok(
        await as_user("dev").post(f"/api/v1/teams/{team}/pull-requests/{pr_id}/reviews", json={}),
        201,
    )
    assert rerun["trigger"] == "manual" and rerun["status"] == "queued"
    review = await claim_for(runner, full, 5)
    assert review["id"] == rerun["id"]
    # a nova rodada não acha nada, mas o "não" do revisor e a exigência de humano continuam
    await runner.result(review["id"], [])
    data = await detail(client, team, pr_id)
    assert data["current_gate"]["status"] == "rejected"
    assert data["current_gate"]["human_required"] is True
    assert [d["current"] for d in data["decisions"]] == [True]
    # só quem reprovou muda o voto
    data = await ok(
        await as_user("rev").post(f"/api/v1/teams/{team}/pull-requests/{pr_id}/approve", json={})
    )
    assert data["current_gate"]["status"] == "approved"


async def test_merge_without_gate_is_flagged(client, gh, app):
    team, integration, _, repo = await setup_repo(client, gh)
    full = repo["full_name"]
    head = sha(uid("h"))
    await ok(await send_webhook(client, integration, pr_payload(gh, full, 9, head)))
    await ok(
        await send_webhook(
            client,
            integration,
            pr_payload(gh, full, 9, head, action="closed", state="closed", merged=True),
        )
    )
    pr = (await ok(await client.get(f"/api/v1/teams/{team}/pull-requests?state=all")))["items"][0]
    assert pr["state"] == "merged" and pr["merged_without_gate"] is True
    audit = await ok(
        await client.get(
            f"/api/v1/teams/{team}/audit", params={"action": "pull_request.merged_without_gate"}
        )
    )
    assert audit["total"] == 1


async def test_override_observe_mode_and_unknown_branch(client, as_user, gh, app):
    team, integration, _, repo = await setup_repo(client, gh)
    full = repo["full_name"]
    head = sha(uid("h"))
    await ok(await send_webhook(client, integration, pr_payload(gh, full, 11, head)))
    pr_id = (await ok(await client.get(f"/api/v1/teams/{team}/pull-requests")))["items"][0]["id"]

    # modo observação: status sempre sucesso, mas o gate continua calculado
    await ok(
        await client.patch(
            f"/api/v1/teams/{team}/repositories/{repo['id']}", json={"enforcement": "observe"}
        )
    )
    last = statuses(gh, full, head)[-1]
    assert last["state"] == "success" and last["description"].startswith("Modo observação")
    await ok(
        await client.patch(
            f"/api/v1/teams/{team}/repositories/{repo['id']}", json={"enforcement": "enforce"}
        )
    )
    assert statuses(gh, full, head)[-1]["state"] == "pending"

    await grant(client, team, "tl2", "tech_lead")
    r = await as_user("tl2").post(
        f"/api/v1/teams/{team}/pull-requests/{pr_id}/override",
        json={"reason": "incidente em produção, correção urgente"},
    )
    assert r.status_code == 403
    data = await ok(
        await client.post(
            f"/api/v1/teams/{team}/pull-requests/{pr_id}/override",
            json={"reason": "incidente em produção, correção urgente"},
        )
    )
    assert data["current_gate"]["status"] == "overridden"
    assert statuses(gh, full, head)[-1]["state"] == "success"

    # PR para branch fora do gate não cria revisão
    await ok(
        await send_webhook(
            client, integration, pr_payload(gh, full, 12, sha(uid("x")), base="experimento")
        )
    )
    page = await ok(await client.get(f"/api/v1/teams/{team}/pull-requests"))
    other = next(p for p in page["items"] if p["number"] == 12)
    assert other["gated"] is False and other["gate"] is None


async def test_webhook_rejections_and_ignored(client, gh):
    integration = await make_integration(client)
    payload = pr_payload(gh, "nao/existe", 1, sha("x"))
    r = await send_webhook(client, integration, payload, secret="errado")
    assert r.status_code == 401
    r = await send_webhook(client, integration, payload)
    assert r.status_code == 202 and r.json()["outcome"] == "ignored"
    r = await send_webhook(client, integration, {"zen": "hi"}, event="ping")
    assert r.json()["detail"] == "pong"
    async with sessionmaker()() as session:
        rows = (
            await session.scalars(
                select(m.WebhookDelivery).where(
                    m.WebhookDelivery.integration_id == integration["id"]
                )
            )
        ).all()
    assert sorted(r.outcome for r in rows) == ["ignored", "ignored", "rejected"]
    listed = await ok(await client.get(f"/api/v1/integrations/{integration['id']}/deliveries"))
    assert [d["outcome"] for d in listed][-1] == "rejected" and len(listed) == 3


async def test_heartbeat_cancel_and_lease_requeue(client, gh, app, state):
    team, integration, _, repo = await setup_repo(client, gh)
    full = repo["full_name"]
    runner = await register_runner(app)
    await ok(await send_webhook(client, integration, pr_payload(gh, full, 21, sha(uid("a")))))
    review = await claim_for(runner, full, 21)
    hb = await ok(
        await runner.http.post("/api/v1/runner/heartbeat", json={"running": [review["id"]]})
    )
    assert hb["cancel"] == []
    # commit novo cancela a revisão em andamento
    await ok(
        await send_webhook(
            client, integration, pr_payload(gh, full, 21, sha(uid("b")), action="synchronize")
        )
    )
    hb = await ok(
        await runner.http.post("/api/v1/runner/heartbeat", json={"running": [review["id"]]})
    )
    assert hb["cancel"] == [review["id"]]
    # resultado atrasado da revisão cancelada é descartado
    await runner.result(review["id"], [finding("SEC-001", "blocker")])

    second = await claim_for(runner, full, 21)
    async with sessionmaker()() as session:
        await session.execute(
            update(m.Review)
            .where(m.Review.id == second["id"])
            .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=5))
        )
        await session.commit()
    assert await reviews.requeue_expired(state) == 1
    again = await claim_for(runner, full, 21)
    assert again["id"] == second["id"] and again["attempt"] == 2


async def test_tamper_check_republishes(client, gh, app, state):
    team, integration, _, repo = await setup_repo(client, gh)
    full = repo["full_name"]
    head = sha(uid("t"))
    await ok(await send_webhook(client, integration, pr_payload(gh, full, 31, head)))
    gh.statuses[f"{full}@{head}"].append(
        {"id": 1, "state": "success", "context": "sentinela/gate", "description": "forjado"}
    )
    found = await reconciler.tamper_check(state)
    assert found >= 1
    assert statuses(gh, full, head)[-1]["state"] == "pending"
    audit = await ok(
        await client.get(f"/api/v1/teams/{team}/audit", params={"action": "gate.status_tampered"})
    )
    assert audit["total"] == 1


async def test_dashboard(client, gh, app):
    team, integration, _, repo = await setup_repo(client, gh)
    runner = await register_runner(app)
    await ok(
        await send_webhook(
            client, integration, pr_payload(gh, repo["full_name"], 41, sha(uid("d")))
        )
    )
    review = await claim_for(runner, repo["full_name"], 41)
    await runner.result(review["id"], [finding("SEC-001", "blocker")])
    data = await ok(await client.get(f"/api/v1/teams/{team}/dashboard"))
    assert data["kpis"]["blocked"] == 1
    assert data["top_rules"][0]["rule_code"] == "SEC-001"
    assert len(data["daily"]) == 14
    assert data["recent"][0]["number"] == 41
    assert data["kpis"]["ai_cost_usd_7d"] > 0
