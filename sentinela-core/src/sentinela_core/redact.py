"""Mascara credenciais em trechos de código antes de guardar ou publicar.

Um apontamento de "segredo no código" não pode virar mais um lugar onde o segredo aparece:
o trecho vai para o banco, para o console e para o comentário no PR. Aqui fica só o
começo do valor, o suficiente para a pessoa reconhecer qual credencial revogar.
"""

from __future__ import annotations

import re

MASK = "••••••"

_PEM = re.compile(
    r"-----BEGIN (?P<kind>[A-Z ]*PRIVATE KEY)-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)"
)
_ASSIGN = re.compile(
    r"(?i)(?P<key>[\w.-]*(?:password|passwd|pwd|senha|secret|token|api[_-]?key|access[_-]?key"
    r"|private[_-]?key|client[_-]?secret|credential)[\w.-]*['\"]?\s*(?::=|=>|[:=])\s*"
    r"[bru]?['\"`])(?P<val>[^'\"`\s]{4,})(?P<end>['\"`])"
)
_URL_CREDENTIAL = re.compile(r"(?P<pre>\b[a-z][a-z0-9+.-]*://[^/\s:@]+:)(?P<val>[^@\s/]{3,})(?=@)")
_TOKENS = re.compile(
    r"\b(?:"
    r"gh[pousr]_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|glpat-[A-Za-z0-9_-]{20,}"
    r"|sk-(?:ant-|live-|test-|proj-)?[A-Za-z0-9_-]{16,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|xox[abposr]-[A-Za-z0-9-]{10,}"
    r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    r")"
)
_BEARER = re.compile(r"(?i)(?P<pre>\b(?:bearer|basic)\s+)(?P<val>[A-Za-z0-9._~+/=-]{12,})")


def _hide(value: str) -> str:
    keep = 4 if len(value) >= 12 else 0
    return value[:keep] + MASK


def mask_secrets(text: str | None) -> str | None:
    """Troca valores de credenciais por um prefixo curto seguido de ••••••."""
    if not text:
        return text
    out = _PEM.sub(lambda m: f"-----BEGIN {m['kind']}----- {MASK}", text)
    out = _ASSIGN.sub(lambda m: f"{m['key']}{_hide(m['val'])}{m['end']}", out)
    out = _URL_CREDENTIAL.sub(lambda m: f"{m['pre']}{MASK}", out)
    out = _BEARER.sub(lambda m: f"{m['pre']}{_hide(m['val'])}", out)
    return _TOKENS.sub(lambda m: _hide(m.group(0)), out)
