"""Motor de simulação: heurísticas locais no lugar da IA, para desenvolvimento,
demonstração e testes de ponta a ponta. Cada heurística tem uma categoria e palavras-chave;
o achado vai para a regra de IA da categoria cujo título/instrução cita uma das palavras
(ou para a primeira da categoria)."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass

from sentinela_core.diff import DiffFile
from sentinela_core.enums import Category
from sentinela_core.findings import AiFinding, AiOutput
from sentinela_core.paths import looks_like_test
from sentinela_core.rules import GENERAL_RULE, ProfileSpec
from sentinela_runner.engines.base import Engine, EngineRequest, EngineResponse


@dataclass
class Heuristic:
    category: Category
    title: str
    description: str
    suggestion: str
    match: Callable[[str, str], bool]  # (caminho, linha) -> bool
    keywords: tuple[str, ...] = ()


SQL = re.compile(
    r"(execute|query|text|raw)\s*\(\s*f[\"']|(select|insert|update|delete)\b.*[\"']\s*\+",
    re.IGNORECASE,
)
HEURISTICS = [
    Heuristic(
        Category.SECURITY,
        "Consulta SQL montada com interpolação",
        "A consulta é montada com f-string/concatenação a partir de dado externo, o que abre "
        "espaço para SQL injection.",
        "Use parâmetros: session.execute(text('... where cliente = :c'), {'c': cliente}).",
        lambda path, line: bool(SQL.search(line)),
        ("sql", "consulta"),
    ),
    Heuristic(
        Category.ARCHITECTURE,
        "Rota acessando o banco diretamente",
        "A camada de entrada (rota/controller) fala com o banco sem passar pela camada de "
        "serviço definida no padrão do time.",
        "Mova a consulta para um serviço/repositório e chame-o a partir da rota.",
        lambda path, line: (
            bool(re.search(r"/(routers|controllers|api|handlers)/", "/" + path))
            and bool(re.search(r"\bsession\.(execute|query|add)|\bselect\(|\bdb\.", line))
        ),
        ("camada", "rota", "controller"),
    ),
    Heuristic(
        Category.STANDARDS,
        "Exceção genérica engolida",
        "O bloco captura qualquer exceção e segue em silêncio, escondendo falhas.",
        "Capture a exceção específica e registre com contexto (logger.exception).",
        lambda path, line: (
            bool(re.search(r"except(\s+Exception)?\s*:\s*(pass)?\s*$", line.strip()))
            or line.strip() == "catch (Exception e) {}"
        ),
        ("exceç", "exception"),
    ),
    Heuristic(
        Category.SECURITY,
        "Dado sensível em log",
        "A linha de log inclui senha, token ou documento.",
        "Remova o dado do log ou mascare-o.",
        lambda path, line: bool(
            re.search(
                r"(log|logger|print|console)\S*\(.*(senha|password|token|cpf)", line, re.IGNORECASE
            )
        ),
        ("log",),
    ),
]


def _rule_for(
    category: Category, path: str, profiles: list[ProfileSpec], keywords: tuple[str, ...] = ()
) -> str:
    candidates = [
        rule
        for profile in profiles
        if profile.applies_to(path)
        for rule in profile.ai_rules()
        if rule.category == category and profile.rule_applies(rule, path)
    ]
    for rule in candidates:
        text = f"{rule.title} {rule.instruction}".lower()
        if any(k in text for k in keywords):
            return rule.code
    return candidates[0].code if candidates else GENERAL_RULE


def simulate(files: list[DiffFile], profiles: list[ProfileSpec], reviewed: list[str]) -> AiOutput:
    findings: list[AiFinding] = []
    reviewed_set = set(reviewed)
    by_path = {f.path: f for f in files}
    for path in reviewed:
        f = by_path[path]
        seen: set[str] = set()
        for lineno, text in f.added_lines():
            for h in HEURISTICS:
                if h.title in seen or not h.match(path, text):
                    continue
                seen.add(h.title)
                findings.append(
                    AiFinding(
                        rule=_rule_for(h.category, path, profiles, h.keywords),
                        file=path,
                        line=lineno,
                        title=h.title,
                        description=h.description,
                        suggestion=h.suggestion,
                        evidence=text.strip(),
                        category=h.category,
                        confidence="medium",
                    )
                )
    code_changed = [p for p in reviewed_set if not looks_like_test(p) and by_path[p].additions >= 5]
    tests_changed = any(looks_like_test(f.path) for f in files)
    if code_changed and not tests_changed:
        target = sorted(code_changed)[0]
        rule = _rule_for(Category.TESTS, target, profiles)
        if rule != GENERAL_RULE:
            findings.append(
                AiFinding(
                    rule=rule,
                    file=target,
                    line=None,
                    title="Comportamento novo sem teste",
                    description=(
                        f"O PR altera {len(code_changed)} arquivo(s) de código e nenhum teste."
                    ),
                    suggestion="Adicione testes cobrindo o caminho feliz e os erros esperados.",
                    category=Category.TESTS,
                    confidence="medium",
                )
            )
    total_add = sum(by_path[p].additions for p in reviewed)
    summary = (
        f"Simulação local (sem IA): {len(reviewed)} arquivo(s) revisado(s), "
        f"+{total_add} linhas; {len(findings)} apontamento(s) pelas heurísticas."
    )
    return AiOutput(summary=summary, findings=findings)


class FakeEngine(Engine):
    kind = "fake"

    async def detect(self) -> str | None:
        return "simulador"

    async def review(self, req: EngineRequest) -> EngineResponse:
        req.log.info("motor de simulação: heurísticas locais, sem chamar IA")
        await asyncio.sleep(0.2)
        output = simulate(req.files, req.profiles, req.reviewed_files)
        req.log.info(f"simulação concluída: {len(output.findings)} apontamento(s)")
        return EngineResponse(output, {"engine": self.kind, "cost_usd": 0.0})
