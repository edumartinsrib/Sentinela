"""Perfis e regras: conversão entre o banco e o formato de troca (sentinela_core.rules)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sentinela_api import models as m
from sentinela_core.rules import ProfileSpec, RuleSpec

RULE_FIELDS = (
    "code",
    "title",
    "category",
    "severity",
    "kind",
    "instruction",
    "pattern",
    "ignore_case",
    "paths",
    "exclude_paths",
    "suggestion",
    "reference_url",
    "enabled",
)


def rule_spec(rule: m.Rule) -> RuleSpec:
    return RuleSpec.model_validate({f: getattr(rule, f) for f in RULE_FIELDS})


def profile_spec(profile: m.Profile) -> ProfileSpec:
    return ProfileSpec(
        name=profile.name,
        description=profile.description,
        instructions=profile.instructions or "",
        path_globs=list(profile.path_globs or []),
        rules=[rule_spec(r) for r in profile.rules],
    )


def snapshot(profiles: list[m.Profile]) -> list[dict[str, Any]]:
    """Fotografia dos perfis habilitados (com as regras) gravada na revisão."""
    return [profile_spec(p).model_dump(mode="json") for p in profiles if p.enabled]


def apply_rule(rule: m.Rule, spec: RuleSpec, position: int | None = None) -> None:
    data = spec.model_dump(mode="json")
    for f in RULE_FIELDS:
        setattr(rule, f, data[f])
    if position is not None:
        rule.position = position


def new_rule(profile: m.Profile, spec: RuleSpec, position: int) -> m.Rule:
    rule = m.Rule(profile_id=profile.id, position=position)
    apply_rule(rule, spec)
    return rule


async def replace_rules(session: AsyncSession, profile: m.Profile, specs: list[RuleSpec]) -> None:
    existing = {r.code: r for r in profile.rules}
    keep: set[str] = set()
    for pos, spec in enumerate(specs):
        keep.add(spec.code)
        if spec.code in existing:
            apply_rule(existing[spec.code], spec, pos)
        else:
            profile.rules.append(new_rule(profile, spec, pos))
    for code, rule in existing.items():
        if code not in keep:
            profile.rules.remove(rule)
    await session.flush()
