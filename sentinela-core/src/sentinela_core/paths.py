"""Globs de caminho no estilo do .gitignore, usados para ligar perfis e regras a arquivos.

- `*` casa qualquer coisa dentro de um segmento; `**` atravessa diretórios;
  `**/` casa zero ou mais diretórios; `?` um caractere; `[abc]` classes.
- `{a,b}` expande alternativas: `src/**/*.{ts,tsx}`.
- Padrão sem `/` casa o nome do arquivo em qualquer profundidade (`*.py`).
- Padrão iniciado por `!` exclui (avaliado depois dos positivos).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache


def expand_braces(pattern: str) -> list[str]:
    start = pattern.find("{")
    if start == -1:
        return [pattern]
    end = pattern.find("}", start)
    if end == -1:
        return [pattern]
    head, body, tail = pattern[:start], pattern[start + 1 : end], pattern[end + 1 :]
    out: list[str] = []
    for option in body.split(","):
        out.extend(expand_braces(head + option + tail))
    return out


def _translate(pattern: str) -> str:
    i, out = 0, []
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if pattern.startswith("**/", i):
                out.append("(?:.*/)?")
                i += 3
                continue
            if pattern.startswith("**", i):
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            close = pattern.find("]", i + 1)
            if close == -1:
                out.append(re.escape(c))
            else:
                body = pattern[i + 1 : close]
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append(f"[{body}]")
                i = close + 1
                continue
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


@lru_cache(maxsize=2048)
def _compile(pattern: str) -> re.Pattern[str]:
    pat = pattern.strip().lstrip("/")
    if pat.endswith("/"):
        pat += "**"
    alternatives = []
    for p in expand_braces(pat):
        body = _translate(p)
        if "/" not in p:
            body = "(?:.*/)?" + body
        alternatives.append(body)
    return re.compile("^(?:" + "|".join(alternatives) + ")$")


def glob_match(path: str, pattern: str) -> bool:
    return bool(_compile(pattern).match(path.lstrip("/")))


def matches_any(path: str, patterns: Iterable[str] | None, *, empty_matches: bool = True) -> bool:
    """`patterns` vazio casa tudo (ou nada, com empty_matches=False). Padrões com `!` excluem."""
    pats = [p.strip() for p in (patterns or []) if p and p.strip()]
    positives = [p for p in pats if not p.startswith("!")]
    negatives = [p[1:] for p in pats if p.startswith("!")]
    if positives:
        hit = any(glob_match(path, p) for p in positives)
    else:
        hit = empty_matches
    if hit and negatives:
        hit = not any(glob_match(path, p) for p in negatives)
    return hit


def is_valid_glob(pattern: str) -> bool:
    try:
        _compile(pattern.lstrip("!"))
        return True
    except re.error:
        return False


TEST_PATH_HINTS = (
    "**/tests/**",
    "**/test/**",
    "**/__tests__/**",
    "**/*_test.*",
    "**/test_*.*",
    "**/*.test.*",
    "**/*.spec.*",
    "**/*Test.java",
    "**/*Tests.java",
    "**/*Test.kt",
)


def looks_like_test(path: str) -> bool:
    return matches_any(path, TEST_PATH_HINTS, empty_matches=False)
