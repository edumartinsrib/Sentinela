"""Perfis de padrão e regras: formato de troca (API ↔ runner, YAML de import/export)
e a avaliação determinística das regras por expressão regular."""

from __future__ import annotations

import re
import time
from typing import Any

import regex
import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from sentinela_core.diff import DiffFile
from sentinela_core.enums import Category, FindingSource, RuleKind, Severity
from sentinela_core.paths import is_valid_glob, matches_any

RULE_CODE_RE = r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*$"
GENERAL_RULE = "GERAL"
MAX_MATCHES_PER_RULE_FILE = 20


class RuleSpec(BaseModel):
    code: str = Field(min_length=2, max_length=40, pattern=RULE_CODE_RE)
    title: str = Field(min_length=3, max_length=200)
    category: Category = Category.STANDARDS
    severity: Severity = Severity.MEDIUM
    kind: RuleKind = RuleKind.AI
    # IA: o que verificar, em linguagem natural. Padrão: explicação mostrada no achado.
    instruction: str = ""
    # Só para kind=pattern: regex aplicada a cada linha adicionada.
    pattern: str | None = None
    ignore_case: bool = False
    # Restringe a regra a alguns arquivos (além dos globs do perfil).
    paths: list[str] = Field(default_factory=list)
    exclude_paths: list[str] = Field(default_factory=list)
    suggestion: str | None = None
    reference_url: str | None = None
    enabled: bool = True

    @field_validator("code", mode="before")
    @classmethod
    def _upper(cls, v: Any) -> Any:
        return v.strip().upper() if isinstance(v, str) else v

    @field_validator("paths", "exclude_paths")
    @classmethod
    def _globs(cls, v: list[str]) -> list[str]:
        clean = [p.strip() for p in v if p and p.strip()]
        bad = [p for p in clean if not is_valid_glob(p)]
        if bad:
            raise ValueError(f"glob inválido: {', '.join(bad)}")
        return clean

    @model_validator(mode="after")
    def _check_kind(self) -> RuleSpec:
        if self.kind == RuleKind.PATTERN:
            if not self.pattern:
                raise ValueError("regra de padrão precisa de uma expressão regular")
            try:
                regex.compile(self.pattern)
            except (regex.error, re.error) as exc:
                raise ValueError(f"expressão regular inválida: {exc}") from exc
        elif not self.instruction.strip():
            raise ValueError("regra de IA precisa de uma instrução")
        if self.code == GENERAL_RULE:
            raise ValueError(f"o código {GENERAL_RULE} é reservado")
        return self

    def compiled(self) -> regex.Pattern[str]:
        assert self.pattern
        return regex.compile(self.pattern, regex.IGNORECASE if self.ignore_case else 0)


class ProfileSpec(BaseModel):
    """Perfil = padrão de um tipo de implementação (ex.: API Python, front React)."""

    name: str = Field(min_length=2, max_length=120)
    description: str | None = None
    # Contexto de arquitetura e convenções do time, entregue à IA como referência.
    instructions: str = ""
    # Arquivos a que o perfil se aplica. Vazio = todos.
    path_globs: list[str] = Field(default_factory=list)
    rules: list[RuleSpec] = Field(default_factory=list)

    @field_validator("path_globs")
    @classmethod
    def _globs(cls, v: list[str]) -> list[str]:
        clean = [p.strip() for p in v if p and p.strip()]
        bad = [p for p in clean if not is_valid_glob(p)]
        if bad:
            raise ValueError(f"glob inválido: {', '.join(bad)}")
        return clean

    @model_validator(mode="after")
    def _unique_codes(self) -> ProfileSpec:
        seen: set[str] = set()
        for rule in self.rules:
            if rule.code in seen:
                raise ValueError(f"código de regra repetido: {rule.code}")
            seen.add(rule.code)
        return self

    def applies_to(self, path: str) -> bool:
        return matches_any(path, self.path_globs)

    def rule_applies(self, rule: RuleSpec, path: str) -> bool:
        return (
            rule.enabled
            and self.applies_to(path)
            and matches_any(path, rule.paths)
            and not (rule.exclude_paths and matches_any(path, rule.exclude_paths))
        )

    def ai_rules(self) -> list[RuleSpec]:
        return [r for r in self.rules if r.enabled and r.kind == RuleKind.AI]

    def pattern_rules(self) -> list[RuleSpec]:
        return [r for r in self.rules if r.enabled and r.kind == RuleKind.PATTERN]


# ----------------------------------------------------------------------------- YAML
def profile_to_yaml(profile: ProfileSpec) -> str:
    data = profile.model_dump(mode="json", exclude_defaults=False)
    for rule in data["rules"]:
        for key in ("pattern", "suggestion", "reference_url"):
            if rule.get(key) is None:
                rule.pop(key, None)
        for key in ("paths", "exclude_paths"):
            if not rule.get(key):
                rule.pop(key, None)
        if not rule.get("ignore_case"):
            rule.pop("ignore_case", None)
        if rule.get("enabled", True):
            rule.pop("enabled", None)
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100)


def profile_from_yaml(text: str) -> ProfileSpec:
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("o YAML do perfil deve ser um objeto")
    return ProfileSpec.model_validate(data)


# ----------------------------------------------------------------------------- padrões
class PatternHit(BaseModel):
    rule_code: str
    profile: str
    file: str
    line: int
    evidence: str


# A regex vem do tech lead e o texto vem do PR: com tempo limite, uma expressão com
# retrocesso catastrófico (ex.: ^(a+)+$) não trava a revisão nem a API.
SEARCH_TIMEOUT_S = 0.05
RULE_FILE_BUDGET_S = 2.0
MAX_LINE_CHARS = 4000


def _search(pattern: regex.Pattern[str], text: str) -> regex.Match[str] | None:
    return pattern.search(text[:MAX_LINE_CHARS], timeout=SEARCH_TIMEOUT_S)


def run_pattern_rules(
    files: list[DiffFile], profiles: list[ProfileSpec], warnings: list[str] | None = None
) -> list[PatternHit]:
    """Aplica as regras de expressão regular às linhas adicionadas de cada arquivo.
    Regras que estouram o tempo limite são interrompidas e anotadas em `warnings`."""
    hits: list[PatternHit] = []
    for f in files:
        if f.binary or f.status == "deleted":
            continue
        added = f.added_lines()
        if not added:
            continue
        for profile in profiles:
            for rule in profile.pattern_rules():
                if not profile.rule_applies(rule, f.path):
                    continue
                pattern = rule.compiled()
                count = 0
                spent = 0.0
                for lineno, text in added:
                    started = time.monotonic()
                    try:
                        found = _search(pattern, text)
                    except TimeoutError:
                        found = None
                        spent = RULE_FILE_BUDGET_S
                    spent += time.monotonic() - started
                    if spent >= RULE_FILE_BUDGET_S:
                        if warnings is not None:
                            warnings.append(
                                f"regra {rule.code} interrompida em {f.path}: a expressão "
                                "regular demorou demais (revise o padrão)"
                            )
                        break
                    if found:
                        hits.append(
                            PatternHit(
                                rule_code=rule.code,
                                profile=profile.name,
                                file=f.path,
                                line=lineno,
                                evidence=text.strip()[:300],
                            )
                        )
                        count += 1
                        if count >= MAX_MATCHES_PER_RULE_FILE:
                            break
    return hits


def try_pattern(pattern: str, sample: str, ignore_case: bool = False) -> list[dict[str, Any]]:
    """Usado pela tela de regras para testar a regex contra um trecho de código.
    Levanta ValueError para expressão inválida ou lenta demais."""
    try:
        compiled = regex.compile(pattern, regex.IGNORECASE if ignore_case else 0)
    except (regex.error, re.error) as exc:
        raise ValueError(f"expressão regular inválida: {exc}") from exc
    out = []
    for i, line in enumerate(sample.split("\n")[:500], start=1):
        try:
            m = _search(compiled, line.rstrip("\r"))
        except TimeoutError as exc:
            raise ValueError(
                f"a expressão demorou demais na linha {i} (retrocesso excessivo)"
            ) from exc
        if m:
            out.append({"line": i, "text": line, "match": m.group(0)})
    return out


SOURCE_FOR_KIND = {RuleKind.AI: FindingSource.AI, RuleKind.PATTERN: FindingSource.PATTERN}
