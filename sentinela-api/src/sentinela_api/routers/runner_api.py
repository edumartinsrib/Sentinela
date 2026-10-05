"""API usada pelos runners: registro, heartbeat, reivindicação (long-poll), fases, logs e
resultado."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response

from sentinela_api import models as m
from sentinela_api import schemas as s
from sentinela_api.db import sessionmaker
from sentinela_api.deps import Session, State
from sentinela_api.errors import ApiError
from sentinela_api.providers.base import ProviderError
from sentinela_api.services import reviews
from sentinela_api.services import runners as svc
from sentinela_api.services.events import review_channel

router = APIRouter(prefix="/api/v1/runner", tags=["runner"])


async def current_runner(authorization: str | None = Header(default=None)) -> m.Runner:
    """Autentica com uma sessão curta (o claim faz long-poll e não deve segurar conexão)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ApiError(401, "token de runner ausente")
    async with sessionmaker()() as session:
        return await svc.authenticate(session, authorization[7:].strip())


RunnerDep = Annotated[m.Runner, Depends(current_runner)]


@router.post("/register", response_model=s.RunnerRegistered)
async def register(body: s.RunnerRegister, session: Session, state: State) -> s.RunnerRegistered:
    runner, token = await svc.register(session, body, state.settings)
    return s.RunnerRegistered(
        runner_id=str(runner.id),
        runner_token=token,
        config=svc.runner_config(state.settings, runner),
    )


@router.get("/config", response_model=s.RunnerConfig)
async def config(runner: RunnerDep, state: State) -> s.RunnerConfig:
    return svc.runner_config(state.settings, runner)


@router.post("/heartbeat", response_model=s.RunnerHeartbeatResponse)
async def heartbeat(
    body: s.RunnerHeartbeat, runner: RunnerDep, session: Session, state: State
) -> s.RunnerHeartbeatResponse:
    runner = await session.get(m.Runner, runner.id)
    assert runner is not None
    await svc.touch(session, runner, body.running, body.engines, body.slots)
    cancel = await reviews.heartbeat(session, state, runner, body.running)
    await session.commit()
    return s.RunnerHeartbeatResponse(
        config=svc.runner_config(state.settings, runner), cancel=cancel
    )


@router.post("/claim", response_model=None)
async def claim(body: s.ClaimRequest, runner: RunnerDep, state: State):
    if not runner.enabled:
        raise ApiError(403, "runner desabilitado")
    wait = body.wait_s if body.wait_s is not None else state.settings.claim_wait_s
    engines = [e.value for e in body.engines]
    review_id = await reviews.claim(state, runner, engines, wait)
    if review_id is None:
        return Response(status_code=204)
    async with sessionmaker()() as session:
        review = await session.get(m.Review, review_id)
        assert review is not None
        try:
            payload = await reviews.claim_payload(session, state, review)
        except ProviderError as exc:
            await reviews.fail(
                session,
                state,
                review,
                f"não foi possível preparar a revisão: {exc}",
                retryable=False,
            )
            return Response(status_code=204)
    await state.bus.publish(
        review_channel(str(review_id)),
        "phase",
        {
            "review_id": str(review_id),
            "phase": "claimed",
            "label": reviews.PHASES["claimed"],
            "detail": runner.name,
        },
    )
    return {"review": payload.model_dump(mode="json")}


@router.post("/reviews/{review_id}/phase", status_code=204)
async def phase(
    review_id: str, body: s.PhaseIn, runner: RunnerDep, session: Session, state: State
) -> Response:
    review = await reviews.runner_review(session, runner, review_id)
    await reviews.set_phase(session, state, review, body.phase, body.detail)
    return Response(status_code=204)


@router.post("/reviews/{review_id}/logs", status_code=204)
async def logs(
    review_id: str, body: s.LogsIn, runner: RunnerDep, session: Session, state: State
) -> Response:
    review = await reviews.runner_review(session, runner, review_id)
    lines = [line.model_dump(mode="json") for line in body.lines]
    await state.bus.append_logs(str(review.id), lines)
    await state.bus.publish(review_channel(str(review.id)), "log", {"lines": lines})
    return Response(status_code=204)


@router.post("/reviews/{review_id}/result", status_code=204)
async def result(
    review_id: str, body: s.ResultIn, runner: RunnerDep, session: Session, state: State
) -> Response:
    if not runner.enabled:
        raise ApiError(403, "runner desabilitado")
    review = await reviews.runner_review(session, runner, review_id)
    await reviews.complete(session, state, review, body, runner_id=runner.id)
    return Response(status_code=204)


@router.post("/reviews/{review_id}/fail", status_code=204)
async def fail(
    review_id: str, body: s.FailIn, runner: RunnerDep, session: Session, state: State
) -> Response:
    review = await reviews.runner_review(session, runner, review_id)
    await reviews.fail(session, state, review, body.error, body.retryable, runner_id=runner.id)
    return Response(status_code=204)
