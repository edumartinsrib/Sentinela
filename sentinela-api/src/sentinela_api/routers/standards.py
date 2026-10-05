"""Perfis de padrão (por tipo de implementação) e suas regras. O tech lead define aqui
o que o Sentinela verifica."""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Response
from pydantic import ValidationError
from sqlalchemy import func, select

from sentinela_api import models as m
from sentinela_api import schemas as s
from sentinela_api.deps import Session, StandardsWrite, User, View
from sentinela_api.errors import ApiError, conflict, not_found, unprocessable
from sentinela_api.services import audit, library, standards
from sentinela_api.services.serializers import profile_out, profile_summary, rule_out
from sentinela_core.rules import RuleSpec, profile_from_yaml, profile_to_yaml, try_pattern

router = APIRouter(prefix="/api/v1", tags=["padrões"])


def _validation_errors(exc: ValidationError) -> list[str]:
    out = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"])
        msg = str(err["msg"]).removeprefix("Value error, ")
        out.append(f"{loc}: {msg}" if loc else msg)
    return out


async def _profile(session, team: m.Team, profile_id: uuid.UUID) -> m.Profile:
    profile = await session.get(m.Profile, profile_id)
    if profile is None or profile.team_id != team.id:
        raise not_found("perfil")
    return profile


async def _repos_by_profile(session, team_id: uuid.UUID) -> dict[uuid.UUID, list[s.RefOut]]:
    rows = await session.execute(
        select(m.RepositoryProfile.profile_id, m.Repository.id, m.Repository.full_name)
        .join(m.Repository, m.Repository.id == m.RepositoryProfile.repository_id)
        .where(m.Repository.team_id == team_id)
        .order_by(m.Repository.full_name)
    )
    out: dict[uuid.UUID, list[s.RefOut]] = {}
    for profile_id, repo_id, name in rows.all():
        out.setdefault(profile_id, []).append(s.RefOut(id=str(repo_id), name=name))
    return out


async def _violations(session, team_id: uuid.UUID, profile_name: str) -> dict[str, int]:
    since = datetime.now(UTC) - timedelta(days=30)
    rows = await session.execute(
        select(m.Finding.rule_code, func.count())
        .where(
            m.Finding.team_id == team_id,
            m.Finding.profile_name == profile_name,
            m.Finding.created_at >= since,
            m.Finding.inherited.is_(False),
        )
        .group_by(m.Finding.rule_code)
    )
    return dict(rows.all())


async def _full(session, team: m.Team, profile: m.Profile) -> s.ProfileOut:
    await session.refresh(profile, ["rules"])
    repos = (await _repos_by_profile(session, team.id)).get(profile.id, [])
    return profile_out(profile, repos, await _violations(session, team.id, profile.name))


def _touch(profile: m.Profile, actor: str) -> None:
    profile.updated_at = datetime.now(UTC)
    profile.updated_by = actor


# --------------------------------------------------------------------------- biblioteca
@router.get("/library", response_model=s.LibraryOut)
async def get_library(principal: User) -> s.LibraryOut:
    return s.LibraryOut(
        templates=[
            s.LibraryTemplate(
                key=t.key,
                name=t.name,
                description=t.description,
                path_globs=list(t.path_globs),
                rules=len(t.rules),
                categories=library.template_categories(t.key),
            )
            for t in library.TEMPLATES.values()
        ],
        rules=[
            s.LibraryRule(key=code, rule=e.rule, tags=list(e.tags))
            for code, e in sorted(library.RULES.items())
        ],
    )


@router.post("/teams/{team}/pattern-test", response_model=s.PatternTestOut)
async def pattern_test(body: s.PatternTestIn, ctx: StandardsWrite) -> s.PatternTestOut:
    try:
        # fora do event loop: mesmo com tempo limite por linha, não segura outras requisições
        matches = await asyncio.to_thread(
            try_pattern, body.pattern, body.sample[:100_000], body.ignore_case
        )
    except ValueError as exc:
        return s.PatternTestOut(valid=False, error=str(exc))
    return s.PatternTestOut(valid=True, matches=[s.PatternMatch(**x) for x in matches[:200]])


# --------------------------------------------------------------------------- perfis
@router.get("/teams/{team}/profiles", response_model=list[s.ProfileSummary])
async def list_profiles(ctx: View, session: Session) -> list[s.ProfileSummary]:
    rows = (
        (
            await session.scalars(
                select(m.Profile).where(m.Profile.team_id == ctx.team.id).order_by(m.Profile.name)
            )
        )
        .unique()
        .all()
    )
    repos = await _repos_by_profile(session, ctx.team.id)
    return [profile_summary(p, repos.get(p.id, [])) for p in rows]


@router.post("/teams/{team}/profiles", response_model=s.ProfileOut, status_code=201)
async def create_profile(body: s.ProfileCreate, ctx: StandardsWrite, session: Session):
    spec_rules = list(body.rules)
    instructions, globs, description = body.instructions, body.path_globs, body.description
    if body.template:
        if body.template not in library.TEMPLATES:
            raise unprocessable(f"modelo {body.template} não existe")
        tpl = library.template_profile(body.template)
        spec_rules = spec_rules or tpl.rules
        instructions = instructions or tpl.instructions
        globs = globs or tpl.path_globs
        description = description or tpl.description
    if await session.scalar(
        select(m.Profile.id).where(m.Profile.team_id == ctx.team.id, m.Profile.name == body.name)
    ):
        raise conflict(f"já existe um perfil {body.name} neste time")
    codes = [r.code for r in spec_rules]
    if len(codes) != len(set(codes)):
        raise unprocessable("códigos de regra repetidos")
    profile = m.Profile(
        team=ctx.team,
        name=body.name,
        description=description,
        instructions=instructions,
        path_globs=globs,
        enabled=body.enabled,
        created_by=ctx.actor,
        updated_by=ctx.actor,
        model=None,
        rules=[],
    )
    session.add(profile)
    await session.flush()
    for pos, spec in enumerate(spec_rules):
        profile.rules.append(standards.new_rule(profile, spec, pos))
    await session.flush()
    audit.record(
        session,
        actor=ctx.actor,
        action="profile.create",
        resource_type="profile",
        resource_id=profile.id,
        team_id=ctx.team.id,
        after={**(audit.snapshot(profile) or {}), "rules": codes},
        detail=f"modelo {body.template}" if body.template else None,
    )
    await session.commit()
    return await _full(session, ctx.team, profile)


@router.get("/teams/{team}/profiles/{profile_id}", response_model=s.ProfileOut)
async def get_profile(profile_id: uuid.UUID, ctx: View, session: Session) -> s.ProfileOut:
    return await _full(session, ctx.team, await _profile(session, ctx.team, profile_id))


@router.patch("/teams/{team}/profiles/{profile_id}", response_model=s.ProfileOut)
async def update_profile(
    profile_id: uuid.UUID, body: s.ProfileUpdate, ctx: StandardsWrite, session: Session
) -> s.ProfileOut:
    profile = await _profile(session, ctx.team, profile_id)
    before = audit.snapshot(profile)
    data = body.model_dump(exclude_unset=True)
    if "model_id" in data:
        if not ctx.principal.is_superadmin:
            raise ApiError(403, "só administradores globais escolhem o modelo de IA")
        model_id = data.pop("model_id")
        if model_id:
            model = await session.get(m.AiModel, uuid.UUID(model_id))
            if model is None:
                raise not_found("modelo")
            profile.model = model
        else:
            profile.model = None
    if "name" in data and data["name"] and data["name"] != profile.name:
        if await session.scalar(
            select(m.Profile.id).where(
                m.Profile.team_id == ctx.team.id, m.Profile.name == data["name"]
            )
        ):
            raise conflict(f"já existe um perfil {data['name']} neste time")
    for key, value in data.items():
        if value is None and key not in ("description",):
            continue
        setattr(profile, key, value)
    _touch(profile, ctx.actor)
    audit.record(
        session,
        actor=ctx.actor,
        action="profile.update",
        resource_type="profile",
        resource_id=profile.id,
        team_id=ctx.team.id,
        before=before,
        after=audit.snapshot(profile),
    )
    await session.commit()
    return await _full(session, ctx.team, profile)


@router.delete("/teams/{team}/profiles/{profile_id}", status_code=204)
async def delete_profile(profile_id: uuid.UUID, ctx: StandardsWrite, session: Session) -> Response:
    profile = await _profile(session, ctx.team, profile_id)
    audit.record(
        session,
        actor=ctx.actor,
        action="profile.delete",
        resource_type="profile",
        resource_id=profile.id,
        team_id=ctx.team.id,
        before={**(audit.snapshot(profile) or {}), "rules": [r.code for r in profile.rules]},
    )
    await session.delete(profile)
    await session.commit()
    return Response(status_code=204)


@router.get("/teams/{team}/profiles/{profile_id}/export")
async def export_profile(profile_id: uuid.UUID, ctx: View, session: Session) -> Response:
    profile = await _profile(session, ctx.team, profile_id)
    text = profile_to_yaml(standards.profile_spec(profile))
    slug = re.sub(r"[^a-z0-9]+", "-", profile.name.lower()).strip("-") or "perfil"
    return Response(
        text,
        media_type="application/yaml; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{slug}.yaml"'},
    )


@router.post("/teams/{team}/profiles/import", response_model=s.ProfileOut)
async def import_profile(body: s.ProfileImport, ctx: StandardsWrite, session: Session):
    try:
        spec = profile_from_yaml(body.yaml)
    except ValidationError as exc:
        raise unprocessable("YAML inválido", _validation_errors(exc)) from exc
    except ValueError as exc:
        raise unprocessable(f"YAML inválido: {exc}") from exc
    existing = await session.scalar(
        select(m.Profile).where(m.Profile.team_id == ctx.team.id, m.Profile.name == spec.name)
    )
    if existing is not None and not body.replace:
        raise conflict(f"já existe um perfil {spec.name}; marque substituir para atualizar")
    if existing is None:
        profile = m.Profile(
            team=ctx.team, name=spec.name, created_by=ctx.actor, model=None, rules=[]
        )
        session.add(profile)
        await session.flush()
        action = "profile.import"
    else:
        profile = existing
        action = "profile.replace"
    profile.description = spec.description
    profile.instructions = spec.instructions
    profile.path_globs = spec.path_globs
    await standards.replace_rules(session, profile, spec.rules)
    _touch(profile, ctx.actor)
    audit.record(
        session,
        actor=ctx.actor,
        action=action,
        resource_type="profile",
        resource_id=profile.id,
        team_id=ctx.team.id,
        after={"name": spec.name, "rules": [r.code for r in spec.rules]},
    )
    await session.commit()
    return await _full(session, ctx.team, profile)


@router.post("/teams/{team}/profiles/{profile_id}/library", response_model=s.ProfileOut)
async def add_library_rules(
    profile_id: uuid.UUID, body: s.AddLibraryRulesIn, ctx: StandardsWrite, session: Session
) -> s.ProfileOut:
    profile = await _profile(session, ctx.team, profile_id)
    unknown = [k for k in body.keys if k not in library.RULES]
    if unknown:
        raise unprocessable(f"regras inexistentes na biblioteca: {', '.join(unknown)}")
    existing = {r.code for r in profile.rules}
    pos = max((r.position for r in profile.rules), default=-1) + 1
    added = []
    for key in body.keys:
        spec = library.RULES[key].rule
        if spec.code in existing:
            continue
        profile.rules.append(standards.new_rule(profile, spec, pos))
        existing.add(spec.code)
        added.append(spec.code)
        pos += 1
    _touch(profile, ctx.actor)
    audit.record(
        session,
        actor=ctx.actor,
        action="rule.import",
        resource_type="profile",
        resource_id=profile.id,
        team_id=ctx.team.id,
        after={"rules": added},
    )
    await session.commit()
    return await _full(session, ctx.team, profile)


# --------------------------------------------------------------------------- regras
async def _rule(session, profile: m.Profile, rule_id: uuid.UUID) -> m.Rule:
    rule = await session.get(m.Rule, rule_id)
    if rule is None or rule.profile_id != profile.id:
        raise not_found("regra")
    return rule


@router.post("/teams/{team}/profiles/{profile_id}/rules", response_model=s.RuleOut, status_code=201)
async def create_rule(
    profile_id: uuid.UUID, body: s.RuleIn, ctx: StandardsWrite, session: Session
) -> s.RuleOut:
    profile = await _profile(session, ctx.team, profile_id)
    if any(r.code == body.code for r in profile.rules):
        raise conflict(f"já existe a regra {body.code} neste perfil")
    pos = (
        body.position
        if body.position is not None
        else (max((r.position for r in profile.rules), default=-1) + 1)
    )
    spec = RuleSpec.model_validate(body.model_dump(exclude={"position"}))
    rule = standards.new_rule(profile, spec, pos)
    profile.rules.append(rule)
    _touch(profile, ctx.actor)
    await session.flush()
    audit.record(
        session,
        actor=ctx.actor,
        action="rule.create",
        resource_type="rule",
        resource_id=rule.id,
        team_id=ctx.team.id,
        after={**(audit.snapshot(rule) or {}), "profile": profile.name},
    )
    await session.commit()
    await session.refresh(rule)
    return rule_out(rule)


@router.patch("/teams/{team}/profiles/{profile_id}/rules/{rule_id}", response_model=s.RuleOut)
async def update_rule(
    profile_id: uuid.UUID,
    rule_id: uuid.UUID,
    body: s.RuleUpdate,
    ctx: StandardsWrite,
    session: Session,
) -> s.RuleOut:
    profile = await _profile(session, ctx.team, profile_id)
    rule = await _rule(session, profile, rule_id)
    before = audit.snapshot(rule)
    current = standards.rule_spec(rule).model_dump(mode="json")
    patch = body.model_dump(exclude_unset=True, mode="json")
    position = patch.pop("position", None)
    merged = {
        **current,
        **{
            k: v
            for k, v in patch.items()
            if v is not None or k in ("pattern", "suggestion", "reference_url")
        },
    }
    try:
        spec = RuleSpec.model_validate(merged)
    except ValidationError as exc:
        raise unprocessable("regra inválida", _validation_errors(exc)) from exc
    if spec.code != rule.code and any(r.code == spec.code for r in profile.rules):
        raise conflict(f"já existe a regra {spec.code} neste perfil")
    standards.apply_rule(rule, spec, position)
    _touch(profile, ctx.actor)
    audit.record(
        session,
        actor=ctx.actor,
        action="rule.update",
        resource_type="rule",
        resource_id=rule.id,
        team_id=ctx.team.id,
        before=before,
        after={**(audit.snapshot(rule) or {}), "profile": profile.name},
    )
    await session.commit()
    await session.refresh(rule)
    return rule_out(rule)


@router.delete("/teams/{team}/profiles/{profile_id}/rules/{rule_id}", status_code=204)
async def delete_rule(
    profile_id: uuid.UUID, rule_id: uuid.UUID, ctx: StandardsWrite, session: Session
) -> Response:
    profile = await _profile(session, ctx.team, profile_id)
    rule = await _rule(session, profile, rule_id)
    audit.record(
        session,
        actor=ctx.actor,
        action="rule.delete",
        resource_type="rule",
        resource_id=rule.id,
        team_id=ctx.team.id,
        before={**(audit.snapshot(rule) or {}), "profile": profile.name},
    )
    profile.rules.remove(rule)
    _touch(profile, ctx.actor)
    await session.commit()
    return Response(status_code=204)
