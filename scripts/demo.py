"""Popula um ambiente de demonstração: time, pessoas, integração com o GitHub simulado,
perfis de padrão, três repositórios git de verdade e oito PRs em situações diferentes
(bloqueado, aprovado pela IA, aguardando aprovação, liberado em emergência, merge sem gate…).

Os repositórios são montados numa pasta temporária e enviados ao GitHub simulado como
`git bundle`; o runner clona de lá por HTTP, como faria com o GitHub de verdade.

Com o compose (perfil demo):

    docker compose --profile demo up -d --build
    uv run python scripts/demo.py

Sem Docker (API, runner e GitHub simulado rodando na máquina):

    uv run python scripts/demo.py --github-api http://localhost:9000 \\
        --github-control http://localhost:9000 --webhook-base http://localhost:8000
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

TEAM = "loja-online"
CONTEXT = "sentinela/gate"


# ============================================================================ git
def git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def write(base: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


class DemoRepo:
    def __init__(self, root: Path, name: str, base_files: dict[str, str]):
        self.name = name
        self.work = root / name
        self.work.mkdir(parents=True)
        git("init", "-q", "-b", "main", cwd=self.work)
        git("config", "user.email", "dev@loja.exemplo", cwd=self.work)
        git("config", "user.name", "Dev da Loja", cwd=self.work)
        write(self.work, base_files)
        git("add", ".", cwd=self.work)
        git("commit", "-q", "-m", "versão inicial", cwd=self.work)
        self.base = git("rev-parse", "HEAD", cwd=self.work)

    def pr(self, number: int, branch: str, files: dict[str, str], message: str) -> str:
        git("checkout", "-q", "-b", branch, "main", cwd=self.work)
        write(self.work, files)
        git("add", ".", cwd=self.work)
        git("commit", "-q", "-m", message, cwd=self.work)
        head = git("rev-parse", "HEAD", cwd=self.work)
        git("checkout", "-q", "main", cwd=self.work)
        # Como no GitHub: cada PR também fica em refs/pull/<n>/head.
        git("update-ref", f"refs/pull/{number}/head", head, cwd=self.work)
        return head

    def bundle(self) -> bytes:
        path = self.work.parent / f"{self.name}.bundle"
        git("bundle", "create", "-q", str(path), "--all", cwd=self.work)
        return path.read_bytes()


# ============================================================================ conteúdo
API_BASE = {
    "pyproject.toml": '[project]\nname = "api-pedidos"\nversion = "1.4.0"\n',
    "app/__init__.py": "",
    "app/main.py": "from fastapi import FastAPI\n\nfrom app.routers import catalogo\n\napp = FastAPI()\n"
    "app.include_router(catalogo.router)\n",
    "app/db.py": "from sqlalchemy import create_engine\nfrom sqlalchemy.orm import Session\n\n"
    "engine = create_engine('postgresql://app@db/loja')\nsession = Session(engine)\n",
    "app/routers/__init__.py": "",
    "app/routers/catalogo.py": "from fastapi import APIRouter\n\nfrom app.services import catalogo\n\n"
    "router = APIRouter()\n\n\n@router.get('/produtos')\ndef listar(pagina: int = 1):\n"
    "    return catalogo.listar(pagina)\n",
    "app/services/__init__.py": "",
    "app/services/catalogo.py": "def listar(pagina: int) -> list[dict]:\n    return []\n",
    "tests/test_catalogo.py": "from app.services import catalogo\n\n\ndef test_lista_vazia():\n"
    "    assert catalogo.listar(1) == []\n",
}

API_PRS = {
    12: (
        "feat/pedidos-por-cliente",
        "ana-dev",
        "Lista pedidos por cliente",
        {
            "app/routers/pedidos.py": "from fastapi import APIRouter\nfrom sqlalchemy import text\n\n"
            "from app.db import session\n\nrouter = APIRouter()\n"
            'PAGAMENTOS_API_KEY = "sk-live-9f8e7d6c5b4a3f2e"\n\n\n'
            "@router.get('/clientes/{cliente_id}/pedidos')\n"
            "def pedidos_do_cliente(cliente_id: str):\n"
            "    return session.execute(text(f\"SELECT * FROM pedidos WHERE cliente_id = '{cliente_id}'\")).all()\n",
        },
        "Adiciona a rota que lista os pedidos de um cliente para a tela de atendimento.",
    ),
    13: (
        "feat/paginacao-catalogo",
        "dani-dev",
        "Ajusta paginação do catálogo",
        {
            "app/services/catalogo.py": "TAMANHO_PAGINA = 20\n\n\ndef listar(pagina: int) -> list[dict]:\n"
            "    inicio = (max(pagina, 1) - 1) * TAMANHO_PAGINA\n    return [][inicio : inicio + TAMANHO_PAGINA]\n",
            "tests/test_catalogo.py": "from app.services import catalogo\n\n\ndef test_lista_vazia():\n"
            "    assert catalogo.listar(1) == []\n\n\ndef test_pagina_invalida_vira_primeira():\n"
            "    assert catalogo.listar(0) == []\n",
        },
        "Limita o catálogo a 20 itens por página.",
    ),
    14: (
        "feat/email-confirmacao",
        "ana-dev",
        "Envia e-mail de confirmação do pedido",
        {
            "app/services/notificacao.py": "import logging\nimport smtplib\n\nlogger = logging.getLogger(__name__)\n\n\n"
            "def enviar_confirmacao(pedido: dict, email: str) -> None:\n"
            "    print('enviando confirmação para', email)\n"
            "    try:\n        with smtplib.SMTP('smtp.interno') as smtp:\n"
            "            smtp.sendmail('loja@exemplo', email, f\"Pedido {pedido['id']} confirmado\")\n"
            "    except Exception:\n        pass\n",
        },
        "Dispara o e-mail de confirmação depois do pagamento.",
    ),
    15: (
        "hotfix/timeout-pagamento",
        "dani-dev",
        "Hotfix: timeout no gateway de pagamento",
        {
            "app/routers/pagamentos.py": "import requests\nfrom fastapi import APIRouter\n\nrouter = APIRouter()\n\n\n"
            "@router.post('/pagamentos/{pedido_id}/captura')\ndef capturar(pedido_id: str) -> dict:\n"
            "    resposta = requests.post(\n        f'https://gateway.interno/capturas/{pedido_id}',\n"
            "        timeout=5,\n        verify=False,\n    )\n    return resposta.json()\n",
        },
        "Gateway com certificado expirado em produção; correção definitiva no chamado INC-4821.",
    ),
    16: (
        "fix/preco-promocional",
        "dani-dev",
        "Corrige preço promocional",
        {
            "app/routers/precos.py": "from fastapi import APIRouter\n\nfrom app.db import session\n\nrouter = APIRouter()\n\n\n"
            "@router.get('/precos/{sku}')\ndef preco(sku: str) -> dict:\n"
            "    linha = session.query(Preco).filter_by(sku=sku).first()\n    return {'sku': sku, 'preco': linha.valor}\n",
        },
        "Ajuste rápido pedido pelo comercial.",
    ),
}

WEB_BASE = {
    "package.json": '{\n  "name": "web-vitrine",\n  "dependencies": {\n    "react": "^18.3.1",\n'
    '    "vite": "^5.4.0"\n  }\n}\n',
    "src/App.tsx": "import { Carrinho } from './components/Carrinho';\n\n"
    "export function App() {\n  return <Carrinho />;\n}\n",
    "src/api/client.ts": "export async function get<T>(path: string): Promise<T> {\n"
    "  const res = await fetch(`/api${path}`);\n  return res.json() as Promise<T>;\n}\n",
    "src/components/Carrinho.tsx": "export function Carrinho() {\n  return <section>Carrinho</section>;\n}\n",
}

WEB_PRS = {
    7: (
        "feat/cupom",
        "dani-dev",
        "Carrinho com cupom de desconto",
        {
            "src/components/Carrinho.tsx": "import { useState } from 'react';\n\n"
            "export function Carrinho() {\n  const [cupom, setCupom] = useState('');\n"
            "  const [desconto, setDesconto] = useState(0);\n\n  async function aplicar() {\n"
            "    console.log('aplicando cupom', cupom);\n"
            "    const resposta: any = await fetch('/api/cupons/' + cupom).then((r) => r.json());\n"
            "    setDesconto(resposta.percentual);\n  }\n\n  return (\n    <section>\n"
            "      <input value={cupom} onChange={(e) => setCupom(e.target.value)} />\n"
            "      <button onClick={aplicar}>Aplicar</button>\n      <span>{desconto}%</span>\n"
            "    </section>\n  );\n}\n",
        },
        "Campo de cupom no carrinho.",
    ),
    8: (
        "chore/deps",
        "ana-dev",
        "Atualiza React e Vite",
        {
            "package.json": '{\n  "name": "web-vitrine",\n  "dependencies": {\n    "react": "^19.1.0",\n'
            '    "vite": "^7.1.0"\n  }\n}\n',
        },
        "Atualização de dependências sem mudança de código.",
    ),
}

WORKER_BASE = {
    "worker/main.py": "def processar(evento: dict) -> None:\n    return None\n",
    "tests/test_worker.py": "from worker.main import processar\n\n\ndef test_ok():\n"
    "    assert processar({}) is None\n",
}

WORKER_PRS = {
    3: (
        "feat/imagem-docker",
        "caio-tl",
        "Imagem Docker e pipeline do worker",
        {
            "Dockerfile": "FROM python:latest\nWORKDIR /app\nCOPY . .\nRUN pip install -r requirements.txt\n"
            'CMD ["python", "-m", "worker.main"]\n',
            ".github/workflows/build.yml": "name: build\non: [push]\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
            "    steps:\n      - uses: actions/checkout@main\n      - run: docker build -t worker .\n",
        },
        "Empacota o worker de estoque.",
    ),
}


# ============================================================================ API
class Api:
    def __init__(self, base: str, user: str = "admin"):
        self.http = httpx.Client(base_url=base, headers={"X-Sentinela-User": user}, timeout=60)

    def as_user(self, user: str) -> Api:
        return Api(str(self.http.base_url), user)

    def __call__(self, method: str, path: str, **kw: Any) -> Any:
        resp = self.http.request(method, f"/api/v1{path}", **kw)
        if resp.status_code >= 400:
            raise SystemExit(f"{method} {path} → {resp.status_code}: {resp.text}")
        return resp.json() if resp.content else None


def wait_ready(url: str, what: str, timeout: float = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=3).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise SystemExit(f"{what} não respondeu em {url}")


def wait_reviews(api: Api, expected: int, timeout: float = 180) -> list[dict]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        items = api("GET", f"/teams/{TEAM}/pull-requests", params={"state": "all", "limit": 100})[
            "items"
        ]
        gated = [p for p in items if p["gate"]]
        if len(gated) >= expected and all(
            p["gate"]["review_status"] in ("completed", "failed") for p in gated
        ):
            return items
        time.sleep(1.5)
    raise SystemExit("as revisões não terminaram a tempo; o runner está de pé?")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument(
        "--github-api",
        default="http://fake-github:9000",
        help="endereço do GitHub simulado visto pela API",
    )
    parser.add_argument(
        "--github-control",
        default="http://localhost:9000",
        help="endereço do GitHub simulado visto por este script",
    )
    parser.add_argument(
        "--webhook-base",
        default="http://api:8000",
        help="endereço da API visto pelo GitHub simulado",
    )
    args = parser.parse_args()

    wait_ready(f"{args.api}/readyz", "API")
    wait_ready(f"{args.github_control}/user", "GitHub simulado")
    admin = Api(args.api)
    gh = httpx.Client(base_url=args.github_control, timeout=60)
    gh.post("/_fake/reset")

    teams = {t["name"] for t in admin("GET", "/teams")}
    if TEAM in teams:
        raise SystemExit(
            f"o time {TEAM} já existe: a demonstração espera um banco limpo "
            "(docker compose down -v)"
        )
    admin(
        "POST",
        "/teams",
        json={"name": TEAM, "display_name": "Loja online", "description": "Squad de e-commerce"},
    )
    people = [
        ("ana", "Ana Ribeiro", "ana-dev", "developer"),
        ("dani", "Daniel Costa", "dani-dev", "developer"),
        ("bia", "Beatriz Lima", "bia-rev", "reviewer"),
        ("caio", "Caio Martins", "caio-tl", "tech_lead"),
    ]
    for username, name, login, role in people:
        user = admin(
            "POST",
            "/users",
            json={"username": username, "display_name": name, "github_login": login},
        )
        admin("POST", f"/teams/{TEAM}/roles", json={"username": user["username"], "role": role})
    print("time e pessoas criados")

    integration = admin(
        "POST",
        "/integrations",
        json={
            "name": "GitHub (simulado)",
            "provider": "github",
            "api_url": args.github_api,
            "web_url": "https://github.fake",
            "token": "ghp_demo_token_0000000000",
        },
    )
    secret = admin("GET", f"/integrations/{integration['id']}/webhook-secret")["webhook_secret"]
    hook_url = f"{args.webhook_base.rstrip('/')}/webhooks/github/{integration['id']}"

    profiles = {
        key: admin("POST", f"/teams/{TEAM}/profiles", json={"name": name, "template": key})
        for key, name in (
            ("python-api", "API Python (FastAPI)"),
            ("react-frontend", "Front-end React"),
            ("containers-pipelines", "Containers e pipelines"),
        )
    }
    print("perfis criados a partir da biblioteca")

    plan = [
        ("loja/api-pedidos", "api-pedidos", API_BASE, API_PRS, ["python-api"], "both"),
        ("loja/web-vitrine", "web-vitrine", WEB_BASE, WEB_PRS, ["react-frontend"], "status_check"),
        (
            "loja/worker-estoque",
            "worker-estoque",
            WORKER_BASE,
            WORKER_PRS,
            ["python-api", "containers-pipelines"],
            "status_check",
        ),
    ]
    repos: dict[str, dict] = {}
    pending: list[tuple[str, int, dict]] = []
    workdir = tempfile.TemporaryDirectory(prefix="sentinela-demo-")
    root = Path(workdir.name)
    for full, name, base_files, prs, profile_keys, mode in plan:
        demo = DemoRepo(root, name, base_files)
        for number, (branch, author, title, files, body) in prs.items():
            head = demo.pr(number, branch, files, title)
            pending.append(
                (
                    full,
                    number,
                    {
                        "number": number,
                        "title": title,
                        "body": body,
                        "author": author,
                        "head_ref": branch,
                        "head_sha": head,
                        "base_sha": demo.base,
                    },
                )
            )
        gh.post(
            "/_fake/repos", json={"full_name": full, "required_contexts": [CONTEXT]}
        ).raise_for_status()
        gh.post(f"/_fake/repos/{full}/git", content=demo.bundle()).raise_for_status()
        gh.post(
            f"/repos/{full}/hooks",
            json={"config": {"url": hook_url, "secret": secret}, "events": ["pull_request"]},
        ).raise_for_status()
        repos[full] = admin(
            "POST",
            f"/teams/{TEAM}/repositories",
            json={
                "integration_id": integration["id"],
                "full_name": full,
                "profile_ids": [profiles[k]["id"] for k in profile_keys],
                "gate_mode": mode,
                # O runner clona do GitHub simulado, no mesmo endereço que a API usa.
                "clone_url": f"{args.github_api.rstrip('/')}/git/{full}.git",
            },
        )
    workdir.cleanup()
    print("repositórios git e cadastro prontos")

    for full, _number, pr in pending:
        gh.post(f"/_fake/repos/{full}/pulls", json=pr).raise_for_status()
        time.sleep(0.3)
    print(f"{len(pending)} PRs abertos; aguardando o runner revisar…")
    items = wait_reviews(admin, len(pending))
    by_key = {(p["repository"]["full_name"], p["number"]): p for p in items}

    def pr_id(full: str, number: int) -> str:
        return by_key[(full, number)]["id"]

    def detail(full: str, number: int) -> dict:
        return admin("GET", f"/teams/{TEAM}/pull-requests/{pr_id(full, number)}")

    ana, bia, caio = admin.as_user("ana"), admin.as_user("bia"), admin.as_user("caio")
    # #12: a dev contesta o SQL e o tech lead comenta (continua bloqueado)
    for f in detail("loja/api-pedidos", 12)["findings"]:
        if f["rule_code"] == "SEC-005":
            ana(
                "POST",
                f"/teams/{TEAM}/findings/{f['id']}/dispute",
                json={"reason": "A rota é só para o painel interno de atendimento."},
            )
            caio(
                "POST",
                f"/teams/{TEAM}/findings/{f['id']}/comment",
                json={
                    "reason": "Interno também precisa de parâmetro; ajusta com text() e :cliente."
                },
            )
    # #13: aprovado pela IA → merge pela plataforma
    dani = admin.as_user("dani")
    dani("POST", f"/teams/{TEAM}/pull-requests/{pr_id('loja/api-pedidos', 13)}/merge", json={})
    # #15: hotfix liberado em caráter emergencial pelo admin
    admin(
        "POST",
        f"/teams/{TEAM}/pull-requests/{pr_id('loja/api-pedidos', 15)}/override",
        json={"reason": "INC-4821: gateway fora do ar em produção; correção do TLS no próximo PR."},
    )
    # #16: alguém fez merge direto no GitHub, ignorando o gate
    gh.post("/_fake/repos/loja/api-pedidos/pulls/16/force-merge").raise_for_status()
    # #7: tech lead aceita o any como exceção, revisora aprova
    for f in detail("loja/web-vitrine", 7)["findings"]:
        if f["rule_code"] == "TS-002":
            caio(
                "POST",
                f"/teams/{TEAM}/findings/{f['id']}/waive",
                json={"reason": "Tipagem do endpoint de cupons chega no PR do contrato OpenAPI."},
            )
    bia(
        "POST",
        f"/teams/{TEAM}/pull-requests/{pr_id('loja/web-vitrine', 7)}/approve",
        json={"comment": "Ok para seguir; console.log sai no próximo commit."},
    )
    time.sleep(1)

    final = admin("GET", f"/teams/{TEAM}/pull-requests", params={"state": "all", "limit": 100})[
        "items"
    ]
    print("\nSituação final:")
    for p in sorted(final, key=lambda x: (x["repository"]["full_name"], x["number"])):
        gate = p["gate"]["status"] if p["gate"] else "-"
        flag = " (merge sem gate)" if p["merged_without_gate"] else ""
        print(
            f"  {p['repository']['full_name']}#{p['number']:<3} {gate:<18} {p['state']}{flag}  {p['title']}"
        )
    print(f"\nConsole: entre como admin, ana, bia ou caio e abra o time {TEAM}.")


if __name__ == "__main__":
    sys.exit(main())
