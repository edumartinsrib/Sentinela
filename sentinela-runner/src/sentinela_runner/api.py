"""Cliente da API do Sentinela usado pelo runner."""

from __future__ import annotations

from typing import Any

import httpx

from sentinela_runner import __version__


class ApiError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


class SentinelaApi:
    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._transport = transport
        self._http: httpx.AsyncClient | None = None

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(30.0, read=90.0),
                transport=self._transport,
                headers={"User-Agent": f"sentinela-runner/{__version__}"},
            )
        return self._http

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def _call(self, method: str, path: str, **kw: Any) -> Any:
        headers = kw.pop("headers", {})
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        resp = await self._client().request(method, f"/api/v1/runner{path}", headers=headers, **kw)
        if resp.status_code == 204:
            return None
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except ValueError:
                detail = resp.text
            raise ApiError(resp.status_code, str(detail)[:500])
        return resp.json() if resp.content else None

    async def register(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._call("POST", "/register", json=body)

    async def config(self) -> dict[str, Any]:
        return await self._call("GET", "/config")

    async def heartbeat(self, running: list[str], engines: dict[str, str], slots: int):
        return await self._call(
            "POST", "/heartbeat", json={"running": running, "engines": engines, "slots": slots}
        )

    async def claim(self, engines: list[str], wait_s: float) -> dict[str, Any] | None:
        data = await self._call(
            "POST",
            "/claim",
            json={"engines": engines, "wait_s": wait_s},
            timeout=httpx.Timeout(30.0, read=wait_s + 30.0),
        )
        return data["review"] if data else None

    async def phase(self, review_id: str, phase: str, detail: str | None = None) -> None:
        await self._call(
            "POST", f"/reviews/{review_id}/phase", json={"phase": phase, "detail": detail}
        )

    async def logs(self, review_id: str, lines: list[dict[str, Any]]) -> None:
        await self._call("POST", f"/reviews/{review_id}/logs", json={"lines": lines})

    async def result(self, review_id: str, body: dict[str, Any]) -> None:
        await self._call("POST", f"/reviews/{review_id}/result", json=body)

    async def fail(self, review_id: str, error: str, retryable: bool) -> None:
        await self._call(
            "POST",
            f"/reviews/{review_id}/fail",
            json={"error": error[:20_000], "retryable": retryable},
        )
