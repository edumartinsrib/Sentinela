"""Teste de interface do console contra o ambiente de demonstração.

Precisa da demonstração no ar (scripts/demo.py) e do console servido:

    SENTINELA_UI_URL=http://localhost:8090 uv run --group ui pytest tests/ui

Sem SENTINELA_UI_URL o módulo é pulado. SENTINELA_CHROMIUM aponta um Chromium já
instalado, se não quiser usar o do `playwright install`.
O teste altera a demonstração: a revisora aprova o PR #3 do worker-estoque.
"""

from __future__ import annotations

import json
import os
import re

import httpx
import pytest

UI = os.environ.get("SENTINELA_UI_URL")
pytestmark = pytest.mark.skipif(not UI, reason="defina SENTINELA_UI_URL para rodar")
TEAM = "loja-online"

if UI:
    from playwright.sync_api import Page, expect, sync_playwright


def pr_path(full_name: str, number: int) -> str:
    resp = httpx.get(
        f"{UI}/api/v1/teams/{TEAM}/pull-requests",
        params={"state": "all", "limit": 100},
        headers={"X-Sentinela-User": "admin"},
    )
    resp.raise_for_status()
    for item in resp.json()["items"]:
        if item["repository"]["full_name"] == full_name and item["number"] == number:
            return f"/t/{TEAM}/pull-requests/{item['id']}"
    raise AssertionError(f"{full_name}#{number} não está na demonstração")


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        exe = os.environ.get("SENTINELA_CHROMIUM")
        b = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def errors():
    return []


def open_as(browser, user: str | None, errors: list[str]) -> Page:
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="pt-BR")
    if user:
        ctx.add_init_script(f"localStorage.setItem('sentinela.devUser', {json.dumps(user)})")
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    return page


def test_login_e_painel(browser, errors):
    page = open_as(browser, None, errors)
    page.goto(f"{UI}/login")
    page.get_by_label("Usuário").fill("bia")
    page.get_by_role("button", name="Entrar").click()
    expect(page.get_by_text("Visão geral")).to_be_visible()
    expect(page.get_by_text("Precisam da sua aprovação")).to_be_visible()
    expect(page.get_by_text("Envia e-mail de confirmação do pedido").first).to_be_visible()
    assert not errors


@pytest.mark.parametrize(
    "path, text",
    [
        ("pull-requests", "Pull requests"),
        ("padroes", "Padrões"),
        ("repositorios", "Repositórios"),
        ("auditoria", "Auditoria"),
        ("admin/ia", "IA e modelos"),
        ("admin/integracoes", "Integrações"),
        ("admin/runners", "Runners"),
        ("admin/acesso", "Acesso"),
    ],
)
def test_paginas_abrem_sem_erro(browser, errors, path, text):
    page = open_as(browser, "admin", errors)
    page.goto(f"{UI}/t/{TEAM}/{path}")
    expect(page.get_by_role("heading", name=text, level=1)).to_be_visible()
    assert not errors


def test_bloqueado_mostra_motivo_e_segredo_mascarado(browser, errors):
    page = open_as(browser, "caio", errors)
    page.goto(UI + pr_path("loja/api-pedidos", 12))
    expect(page.get_by_text("Bloqueado").first).to_be_visible()
    expect(page.get_by_text("SEC-001").first).to_be_visible()
    expect(page.get_by_text(re.compile(r"sk-l•+"))).to_be_visible()
    assert "9f8e7d6c" not in page.content()
    expect(page.get_by_role("button", name="Aprovar")).to_be_disabled()


def test_autor_nao_aprova_o_proprio_pr(browser, errors):
    page = open_as(browser, "ana", errors)
    page.goto(UI + pr_path("loja/api-pedidos", 14))
    expect(page.get_by_text("Você é o autor deste PR")).to_be_visible()
    expect(page.get_by_role("button", name="Aprovar")).to_be_disabled()


def test_revisora_aprova_pela_interface(browser, errors):
    page = open_as(browser, "bia", errors)
    page.goto(UI + pr_path("loja/worker-estoque", 3))
    expect(page.get_by_text("Aguardando aprovação").first).to_be_visible()
    page.get_by_role("button", name="Aprovar").first.click()
    dialog = page.get_by_role("alertdialog")
    dialog.get_by_label("Comentário (opcional)").fill("Imagem fixada no próximo PR.")
    dialog.get_by_role("button", name="Aprovar").click()
    expect(page.get_by_text("Aprovado por bia").first).to_be_visible()
    assert not errors
