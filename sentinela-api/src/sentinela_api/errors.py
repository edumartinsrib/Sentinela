"""Erros da API no formato {"detail": "...", "errors": [...]}."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status: int, detail: str, errors: list[str] | None = None):
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.errors = errors


def not_found(what: str) -> ApiError:
    return ApiError(404, f"{what} não encontrado")


def conflict(detail: str) -> ApiError:
    return ApiError(409, detail)


def forbidden(detail: str = "sem permissão") -> ApiError:
    return ApiError(403, detail)


def unprocessable(detail: str, errors: list[str] | None = None) -> ApiError:
    return ApiError(422, detail, errors)


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        body: dict = {"detail": exc.detail}
        if exc.errors:
            body["errors"] = exc.errors
        return JSONResponse(body, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"] if p not in ("body", "query", "path"))
            msg = str(err["msg"]).removeprefix("Value error, ")
            errors.append(f"{loc}: {msg}" if loc else msg)
        return JSONResponse({"detail": "requisição inválida", "errors": errors}, status_code=422)
