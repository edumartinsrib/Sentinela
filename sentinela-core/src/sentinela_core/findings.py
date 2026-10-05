"""Achados: o formato que a IA devolve, a leitura tolerante dessa resposta e a
normalização (severidade e categoria sempre vêm da regra cadastrada, não da IA)."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sentinela_core.diff import DiffFile
from sentinela_core.enums import (
    SEVERITY_RANK,
    Category,
    FindingSource,
    Severity,
    max_severity,
    min_severity,
)
from sentinela_core.redact import mask_secrets
from sentinela_core.rules import GENERAL_RULE, PatternHit, ProfileSpec, RuleSpec

# Achados fora das regras cadastradas nunca passam desta severidade: a IA não cria
# bloqueios por conta própria, só o padrão do time bloqueia.
GENERAL_MAX_SEVERITY = Severity.MEDIUM

AI_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "Resumo do PR e da avaliação em até 4 frases, em português.",
        },
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rule": {"type": "string", "description": "Código da regra violada ou GERAL"},
                    "file": {"type": "string", "description": "Caminho relativo à raiz do repo"},
                    "line": {"type": ["integer", "null"]},
                    "end_line": {"type": ["integer", "null"]},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "suggestion": {"type": "string"},
                    "evidence": {"type": "string", "description": "Trecho exato da linha"},
                    "severity": {"type": "string", "enum": [s.value for s in Severity]},
                    "category": {"type": "string", "enum": [c.value for c in Category]},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["rule", "file", "title", "description"],
            },
        },
    },
    "required": ["summary", "findings"],
}


class AiFinding(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rule: str = GENERAL_RULE
    file: str = ""
    line: int | None = None
    end_line: int | None = None
    title: str = ""
    description: str = ""
    suggestion: str | None = None
    evidence: str | None = None
    severity: Severity | None = None
    category: Category | None = None
    confidence: Literal["high", "medium", "low"] | None = None

    @field_validator("line", "end_line", mode="before")
    @classmethod
    def _int(cls, v: Any) -> Any:
        if v in (None, "", "null"):
            return None
        if isinstance(v, str):
            m = re.match(r"\s*(\d+)", v)
            return int(m.group(1)) if m else None
        return v

    @field_validator("severity", mode="before")
    @classmethod
    def _sev(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip().lower()
            aliases = {
                "critical": "blocker",
                "bloqueante": "blocker",
                "alta": "high",
                "media": "medium",
                "média": "medium",
                "baixa": "low",
                "informativa": "info",
                "warning": "medium",
                "error": "high",
            }
            v = aliases.get(v, v)
            return v if v in Severity._value2member_map_ else None
        return None

    @field_validator("category", mode="before")
    @classmethod
    def _cat(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip().lower()
            return v if v in Category._value2member_map_ else None
        return None

    @field_validator("confidence", mode="before")
    @classmethod
    def _conf(cls, v: Any) -> Any:
        if isinstance(v, str) and v.strip().lower() in ("high", "medium", "low"):
            return v.strip().lower()
        return None

    @field_validator("rule", "file", "title", "description", mode="before")
    @classmethod
    def _str(cls, v: Any) -> Any:
        return "" if v is None else str(v)


class AiOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str = ""
    findings: list[AiFinding] = Field(default_factory=list)


class ReviewFinding(BaseModel):
    """Achado já normalizado, como o runner envia à API."""

    rule_code: str
    profile: str | None = None
    source: FindingSource
    category: Category
    severity: Severity
    file: str | None = None
    line: int | None = None
    end_line: int | None = None
    title: str
    description: str = ""
    suggestion: str | None = None
    evidence: str | None = None
    confidence: str | None = None
    in_diff: bool = True
    fingerprint: str


class ReviewResult(BaseModel):
    summary: str = ""
    findings: list[ReviewFinding] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)


# ----------------------------------------------------------------------------- leitura
def _closing_brace(text: str, start: int) -> int:
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _json_objects(text: str) -> list[dict[str, Any]]:
    """Todos os objetos JSON de primeiro nível no texto, na ordem em que aparecem."""
    out: list[dict[str, Any]] = []
    start = text.find("{")
    while start != -1:
        end = _closing_brace(text, start)
        if end != -1:
            try:
                data = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict):
                out.append(data)
                start = text.find("{", end + 1)
                continue
        start = text.find("{", start + 1)
    return out


def _unwrap(data: dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(data.get("findings"), list):
        return data
    inner = data.get("result")
    if isinstance(inner, dict) and isinstance(inner.get("findings"), list):
        return inner
    return None


def extract_json(text: str) -> dict[str, Any]:
    """Acha a resposta da IA no texto: o ÚLTIMO objeto JSON que traz a lista "findings".
    Um JSON citado do PR antes da resposta (ou um objeto qualquer) nunca vale como
    "nenhum apontamento": sem "findings", é erro e a revisão falha em vez de aprovar."""
    stripped = text.strip()
    try:
        whole = json.loads(stripped)
        candidates = [whole] if isinstance(whole, dict) else []
    except json.JSONDecodeError:
        candidates = _json_objects(text)
    for data in reversed(candidates):
        found = _unwrap(data)
        if found is not None:
            return found
    raise ValueError("a resposta da IA não traz um objeto JSON com a lista 'findings'")


def parse_ai_output(raw: str | dict[str, Any]) -> AiOutput:
    if isinstance(raw, dict):
        data = _unwrap(raw)
        if data is None:
            raise ValueError("a saída estruturada da IA não traz a lista 'findings'")
    else:
        data = extract_json(raw)
    return AiOutput.model_validate(data)


# ----------------------------------------------------------------------------- normalização
def normalize_path(path: str | None) -> str | None:
    if not path:
        return None
    p = path.strip().replace("\\", "/")
    for prefix in ("./", "a/", "b/"):
        if p.startswith(prefix):
            p = p[len(prefix) :]
    return p.lstrip("/") or None


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def fingerprint(rule_code: str, file: str | None, anchor: str) -> str:
    """Identifica o mesmo achado entre revisões (independente do número da linha)."""
    raw = f"{rule_code}|{file or ''}|{_norm_text(anchor)}"
    return hashlib.sha1(raw.encode()).hexdigest()[:20]


def _clip(text: str | None, size: int) -> str | None:
    if text is None:
        return None
    text = text.strip()
    return text if len(text) <= size else text[: size - 1] + "…"


class RuleIndex:
    """Regras dos perfis aplicados, por código. O mesmo código em dois perfis vale
    como uma regra só (fica a maior severidade)."""

    def __init__(self, profiles: list[ProfileSpec]):
        self.rules: dict[str, tuple[ProfileSpec, RuleSpec]] = {}
        self.severity: dict[str, Severity] = {}
        for profile in profiles:
            for rule in profile.rules:
                if not rule.enabled:
                    continue
                if rule.code not in self.rules:
                    self.rules[rule.code] = (profile, rule)
                    self.severity[rule.code] = rule.severity
                else:
                    self.severity[rule.code] = max_severity(self.severity[rule.code], rule.severity)

    def get(self, code: str) -> tuple[ProfileSpec, RuleSpec] | None:
        return self.rules.get(code)


def _clean_code(code: str) -> str:
    return code.strip().strip("[]()").strip().upper()


def _line_in_diff(files: dict[str, DiffFile], path: str | None, line: int | None) -> bool:
    if not path or path not in files:
        return False
    if line is None:
        return True
    for hunk in files[path].hunks:
        if hunk.new_start <= line < hunk.new_start + max(hunk.new_count, 1):
            return True
    return False


def normalize_findings(
    ai: AiOutput | None,
    hits: list[PatternHit],
    profiles: list[ProfileSpec],
    files: list[DiffFile],
    line_reader: Callable[[str, int], str | None] | None = None,
) -> list[ReviewFinding]:
    index = RuleIndex(profiles)
    by_path = {f.path: f for f in files}
    out: dict[str, ReviewFinding] = {}

    def add(finding: ReviewFinding) -> None:
        existing = out.get(finding.fingerprint)
        if existing is None or SEVERITY_RANK[finding.severity] > SEVERITY_RANK[existing.severity]:
            out[finding.fingerprint] = finding

    for hit in hits:
        entry = index.get(hit.rule_code)
        if entry is None:
            continue
        profile, rule = entry
        add(
            ReviewFinding(
                rule_code=rule.code,
                profile=hit.profile,
                source=FindingSource.PATTERN,
                category=rule.category,
                severity=index.severity[rule.code],
                file=hit.file,
                line=hit.line,
                title=rule.title,
                description=rule.instruction
                or f"A linha casa com o padrão proibido `{rule.pattern}`.",
                suggestion=rule.suggestion,
                evidence=mask_secrets(hit.evidence),
                confidence="high",
                in_diff=True,
                fingerprint=fingerprint(rule.code, hit.file, mask_secrets(hit.evidence) or ""),
            )
        )

    for item in ai.findings if ai else []:
        if not (item.title.strip() or item.description.strip()):
            continue
        code = _clean_code(item.rule or GENERAL_RULE)
        path = normalize_path(item.file)
        evidence = item.evidence
        if not evidence and path and item.line and line_reader:
            evidence = line_reader(path, item.line)
        evidence = mask_secrets(evidence)
        entry = index.get(code)
        if entry is not None:
            profile, rule = entry
            category = rule.category
            severity = index.severity[code]
            profile_name: str | None = profile.name
            title = item.title.strip() or rule.title
        else:
            code = GENERAL_RULE
            category = item.category or Category.OTHER
            severity = min_severity(item.severity or Severity.MEDIUM, GENERAL_MAX_SEVERITY)
            profile_name = None
            title = item.title.strip() or "Apontamento geral"
        anchor = evidence or f"{title}|{item.line or ''}"
        end_line = (
            item.end_line if item.end_line and item.line and item.end_line >= item.line else None
        )
        add(
            ReviewFinding(
                rule_code=code,
                profile=profile_name,
                source=FindingSource.AI,
                category=category,
                severity=severity,
                file=path,
                line=item.line,
                end_line=end_line,
                title=_clip(mask_secrets(title), 300) or title,
                description=_clip(mask_secrets(item.description), 4000) or "",
                suggestion=_clip(mask_secrets(item.suggestion), 4000) or None,
                evidence=_clip(evidence, 1000),
                confidence=item.confidence,
                in_diff=_line_in_diff(by_path, path, item.line),
                fingerprint=fingerprint(code, path, anchor),
            )
        )

    return sorted(
        out.values(),
        key=lambda f: (-SEVERITY_RANK[f.severity], f.file or "", f.line or 0, f.rule_code),
    )


def coverage_finding(
    files: list[DiffFile], profiles: list[ProfileSpec], limit: int = 30
) -> ReviewFinding | None:
    """Arquivos alterados que nenhum perfil cobre não passam por regra nem por IA. Em vez de
    a IA aprovar sem ter olhado, vira um apontamento informativo e uma pessoa decide."""
    uncovered = sorted(
        f.path
        for f in files
        if f.status != "deleted" and not any(p.applies_to(f.path) for p in profiles)
    )
    if not uncovered:
        return None
    listed = "\n".join(f"- {path}" for path in uncovered[:limit])
    if len(uncovered) > limit:
        listed += f"\n- … e mais {len(uncovered) - limit}"
    return ReviewFinding(
        rule_code=GENERAL_RULE,
        profile=None,
        source=FindingSource.PATTERN,
        category=Category.OTHER,
        severity=Severity.INFO,
        title="Arquivos fora dos perfis de padrão",
        description=(
            f"Nenhum perfil aplicado ao repositório cobre {len(uncovered)} arquivo(s) "
            "alterado(s); eles não passaram pelas regras nem pela IA e precisam de um olhar "
            f"humano:\n{listed}"
        ),
        suggestion="Inclua esses caminhos num perfil (ou crie um perfil para esse tipo de "
        "arquivo) para que entrem na revisão automática.",
        confidence="high",
        in_diff=True,
        fingerprint=fingerprint(GENERAL_RULE, None, "fora-dos-perfis|" + "|".join(uncovered)),
    )
