"""Gera as capturas de tela de docs/screenshots a partir da demonstração no ar.

    uv run python scripts/demo.py ...            # popula
    uv run --group ui python scripts/screenshots.py --ui http://localhost:8090

SENTINELA_CHROMIUM aponta um Chromium já instalado, se preferir não usar o do Playwright.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import httpx
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
TEAM = "loja-online"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ui", default="http://localhost:8090")
    parser.add_argument("--out", default=str(ROOT / "docs" / "screenshots"))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    items = httpx.get(
        f"{args.ui}/api/v1/teams/{TEAM}/pull-requests",
        params={"state": "all", "limit": 100},
        headers={"X-Sentinela-User": "admin"},
    ).json()["items"]
    prs = {(p["repository"]["full_name"], p["number"]): p["id"] for p in items}
    profiles = httpx.get(
        f"{args.ui}/api/v1/teams/{TEAM}/profiles", headers={"X-Sentinela-User": "admin"}
    ).json()
    python_profile = next(p["id"] for p in profiles if p["name"].startswith("API Python"))

    def pr(full: str, number: int) -> str:
        return f"/t/{TEAM}/pull-requests/{prs[(full, number)]}"

    with sync_playwright() as p:
        exe = os.environ.get("SENTINELA_CHROMIUM")
        browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()

        def page_for(user: str | None) -> Page:
            ctx = browser.new_context(
                viewport={"width": 1440, "height": 900}, device_scale_factor=1, locale="pt-BR"
            )
            if user:
                ctx.add_init_script(
                    f"localStorage.setItem('sentinela.devUser', {json.dumps(user)})"
                )
            return ctx.new_page()

        def shot(page: Page, name: str, height: int | None = None) -> None:
            page.wait_for_timeout(900)
            if height:
                page.set_viewport_size({"width": 1440, "height": height})
                page.wait_for_timeout(300)
            page.screenshot(path=str(out / f"{name}.png"))
            print(f"docs/screenshots/{name}.png")

        def visit(page: Page, path: str) -> None:
            page.goto(args.ui + path)
            page.wait_for_timeout(1800)

        admin, caio, bia = page_for("admin"), page_for("caio"), page_for("bia")

        visit(admin, f"/t/{TEAM}")
        shot(admin, "01-painel", 1500)
        visit(admin, f"/t/{TEAM}/pull-requests")
        shot(admin, "02-pull-requests", 900)
        visit(caio, pr("loja/api-pedidos", 12))
        shot(caio, "03-pr-bloqueado", 1400)
        visit(bia, pr("loja/api-pedidos", 14))
        shot(bia, "04-pr-aguardando-aprovacao", 1000)
        visit(admin, pr("loja/api-pedidos", 16))
        shot(admin, "05-merge-sem-gate", 900)
        visit(caio, pr("loja/api-pedidos", 12))
        caio.get_by_role("tab", name="Revisão automática").click()
        shot(caio, "06-revisao-automatica", 1500)
        visit(admin, f"/t/{TEAM}/padroes/{python_profile}")
        shot(admin, "07-perfil-de-padrao", 1400)
        visit(admin, f"/t/{TEAM}/repositorios")
        admin.get_by_text("loja/api-pedidos").first.click()
        shot(admin, "08-repositorio-gate", 1000)
        admin.set_viewport_size({"width": 1440, "height": 900})
        visit(admin, f"/t/{TEAM}/admin/ia")
        shot(admin, "09-ia-e-modelos", 1150)
        visit(admin, f"/t/{TEAM}/admin/runners")
        shot(admin, "10-runners", 700)
        login = page_for(None)
        visit(login, "/login")
        shot(login, "11-login", 900)
        browser.close()


if __name__ == "__main__":
    main()
