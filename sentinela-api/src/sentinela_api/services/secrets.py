"""Cofre de segredos (tokens do GitHub/GitLab, segredos de webhook, chaves das IAs).

- `db` (padrão): cifrado com AES-GCM no próprio Postgres. Chave em SENTINELA_SECRET_KEY
  (`id:base64` de 32 bytes; várias separadas por vírgula para rotação, a primeira cifra).
- `vault`: KV v2 do HashiCorp Vault em `<prefixo>/<caminho>`.
- `memory`: só para testes.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from typing import Any, Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import delete, select

from sentinela_api.settings import Settings

log = logging.getLogger(__name__)

# Chave fixa usada só no modo dev sem SENTINELA_SECRET_KEY (nunca em produção).
_DEV_KEY = "dev:" + base64.b64encode(b"sentinela-dev-key-nao-use-em-prd").decode()


class SecretStore(Protocol):
    async def read(self, path: str) -> dict[str, Any] | None: ...
    async def write(self, path: str, data: dict[str, Any]) -> None: ...
    async def delete(self, path: str) -> None: ...


class MemorySecretStore:
    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}

    async def read(self, path: str) -> dict[str, Any] | None:
        value = self._data.get(path)
        return dict(value) if value is not None else None

    async def write(self, path: str, data: dict[str, Any]) -> None:
        self._data[path] = dict(data)

    async def delete(self, path: str) -> None:
        self._data.pop(path, None)


class KeyRing:
    def __init__(self, spec: str):
        self.keys: list[tuple[str, bytes]] = []
        for part in spec.split(","):
            part = part.strip()
            if not part:
                continue
            kid, sep, b64 = part.partition(":")
            if not sep:
                kid, b64 = "k1", part
            raw = base64.b64decode(b64)
            if len(raw) != 32:
                raise ValueError("SENTINELA_SECRET_KEY: cada chave precisa ter 32 bytes em base64")
            self.keys.append((kid, raw))
        if not self.keys:
            raise ValueError("SENTINELA_SECRET_KEY vazia")

    @staticmethod
    def generate() -> str:
        return base64.b64encode(os.urandom(32)).decode()

    def encrypt(self, data: dict[str, Any], aad: str) -> tuple[str, bytes, bytes]:
        kid, key = self.keys[0]
        nonce = os.urandom(12)
        ct = AESGCM(key).encrypt(nonce, json.dumps(data).encode(), aad.encode())
        return kid, nonce, ct

    def decrypt(self, kid: str, nonce: bytes, ct: bytes, aad: str) -> dict[str, Any]:
        for k, key in self.keys:
            if k == kid:
                return json.loads(AESGCM(key).decrypt(nonce, ct, aad.encode()))
        raise ValueError(f"chave {kid} não configurada em SENTINELA_SECRET_KEY")


class DbSecretStore:
    def __init__(self, ring: KeyRing):
        self._ring = ring

    async def read(self, path: str) -> dict[str, Any] | None:
        from sentinela_api.db import sessionmaker
        from sentinela_api.models import SecretEntry

        async with sessionmaker()() as session:
            row = await session.get(SecretEntry, path)
            if row is None:
                return None
            return self._ring.decrypt(row.key_id, row.nonce, row.ciphertext, path)

    async def write(self, path: str, data: dict[str, Any]) -> None:
        from sqlalchemy.dialects.postgresql import insert

        from sentinela_api.db import sessionmaker
        from sentinela_api.models import SecretEntry

        kid, nonce, ct = self._ring.encrypt(data, path)
        stmt = insert(SecretEntry).values(path=path, nonce=nonce, ciphertext=ct, key_id=kid)
        stmt = stmt.on_conflict_do_update(
            index_elements=[SecretEntry.path],
            set_={"nonce": nonce, "ciphertext": ct, "key_id": kid},
        )
        async with sessionmaker()() as session:
            await session.execute(stmt)
            await session.commit()

    async def delete(self, path: str) -> None:
        from sentinela_api.db import sessionmaker
        from sentinela_api.models import SecretEntry

        async with sessionmaker()() as session:
            await session.execute(delete(SecretEntry).where(SecretEntry.path == path))
            await session.commit()

    async def paths(self) -> list[str]:
        from sentinela_api.db import sessionmaker
        from sentinela_api.models import SecretEntry

        async with sessionmaker()() as session:
            return list((await session.scalars(select(SecretEntry.path))).all())


class VaultSecretStore:
    def __init__(self, settings: Settings):
        import hvac

        self._mount = settings.vault_mount
        self._prefix = settings.vault_prefix.strip("/")
        self._client = hvac.Client(
            url=settings.vault_addr,
            token=settings.vault_token,
            namespace=settings.vault_namespace,
        )
        self._role_id = None if settings.vault_token else settings.vault_role_id
        self._secret_id = settings.vault_secret_id
        self._login()

    def _login(self) -> None:
        if self._role_id:
            self._client.auth.approle.login(role_id=self._role_id, secret_id=self._secret_id)

    def _call(self, fn, **kwargs):
        """Chama o Vault; com AppRole, um token vencido (403) leva a um novo login."""
        from hvac.exceptions import Forbidden

        try:
            return fn(**kwargs)
        except Forbidden:
            if not self._role_id:
                raise
            self._login()
            return fn(**kwargs)

    def _path(self, path: str) -> str:
        return f"{self._prefix}/{path}"

    def _read(self, path: str) -> dict[str, Any] | None:
        from hvac.exceptions import InvalidPath

        try:
            resp = self._call(
                self._client.secrets.kv.v2.read_secret_version,
                path=self._path(path),
                mount_point=self._mount,
                raise_on_deleted_version=True,
            )
        except InvalidPath:
            return None
        return resp["data"]["data"]

    async def read(self, path: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._read, path)

    async def write(self, path: str, data: dict[str, Any]) -> None:
        await asyncio.to_thread(
            self._call,
            self._client.secrets.kv.v2.create_or_update_secret,
            path=self._path(path),
            secret=data,
            mount_point=self._mount,
        )

    async def delete(self, path: str) -> None:
        await asyncio.to_thread(
            self._call,
            self._client.secrets.kv.v2.delete_metadata_and_all_versions,
            path=self._path(path),
            mount_point=self._mount,
        )


def build_secret_store(settings: Settings) -> SecretStore:
    if settings.secret_store == "memory":
        log.warning("Cofre em memória: segredos não sobrevivem a reinício")
        return MemorySecretStore()
    if settings.secret_store == "vault":
        if not settings.vault_addr:
            raise RuntimeError("SENTINELA_SECRET_STORE=vault exige VAULT_ADDR")
        return VaultSecretStore(settings)
    spec = settings.secret_key
    if not spec:
        if settings.auth_mode != "dev":
            raise RuntimeError(
                "Defina SENTINELA_SECRET_KEY (32 bytes em base64) para cifrar os segredos"
            )
        log.warning("SENTINELA_SECRET_KEY ausente: usando a chave fixa de desenvolvimento")
        spec = _DEV_KEY
    return DbSecretStore(KeyRing(spec))


def integration_path(integration_id: Any) -> str:
    return f"integrations/{integration_id}"


def engine_path(engine_id: Any) -> str:
    return f"engines/{engine_id}"
