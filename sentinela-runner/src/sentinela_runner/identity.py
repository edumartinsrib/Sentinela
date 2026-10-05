"""Token próprio do runner, salvo depois do primeiro registro (`runner.json`, só o dono lê)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Identity:
    runner_id: str
    runner_token: str
    api_url: str


def _path(home: Path) -> Path:
    return home / "runner.json"


def load(home: Path) -> Identity | None:
    path = _path(home)
    if not path.exists():
        return None
    try:
        return Identity(**json.loads(path.read_text()))
    except (ValueError, TypeError):
        return None


def save(home: Path, ident: Identity) -> None:
    home.mkdir(parents=True, exist_ok=True)
    path = _path(home)
    tmp = path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    # Criado já com 0600: o token nunca fica legível por outros usuários, nem por um instante.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps(asdict(ident)))
    tmp.replace(path)
