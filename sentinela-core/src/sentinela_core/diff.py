"""Leitura do diff unificado do git (`git diff --no-color -M base head`)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_DIFF_GIT = re.compile(r'^diff --git (?P<a>"(?:[^"\\]|\\.)*"|\S+) (?P<b>"(?:[^"\\]|\\.)*"|\S+)$')


@dataclass
class DiffLine:
    kind: str  # "+", "-" ou " "
    text: str
    old_lineno: int | None
    new_lineno: int | None


@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[DiffLine] = field(default_factory=list)


@dataclass
class DiffFile:
    path: str
    old_path: str | None = None
    status: str = "modified"  # added | modified | deleted | renamed
    binary: bool = False
    hunks: list[Hunk] = field(default_factory=list)
    # trecho bruto do diff deste arquivo (cabeçalho + hunks)
    raw: str = field(default="", repr=False)
    # trecho bruto do diff deste arquivo (cabeçalho + hunks)
    raw: str = field(default="", repr=False)

    @property
    def additions(self) -> int:
        return sum(1 for h in self.hunks for ln in h.lines if ln.kind == "+")

    @property
    def deletions(self) -> int:
        return sum(1 for h in self.hunks for ln in h.lines if ln.kind == "-")

    def added_lines(self) -> list[tuple[int, str]]:
        return [
            (ln.new_lineno, ln.text)
            for h in self.hunks
            for ln in h.lines
            if ln.kind == "+" and ln.new_lineno is not None
        ]

    def changed_new_lines(self) -> set[int]:
        return {n for n, _ in self.added_lines()}

    def status_letter(self) -> str:
        return {"added": "A", "deleted": "D", "renamed": "R"}.get(self.status, "M")


def _unquote(path: str) -> str:
    """Caminhos com caracteres especiais vêm entre aspas e com escapes em octal."""
    if not (path.startswith('"') and path.endswith('"')):
        return path
    raw = path[1:-1]
    out = bytearray()
    i = 0
    simple = {"n": b"\n", "t": b"\t", '"': b'"', "\\": b"\\", "a": b"\a", "b": b"\b"}
    while i < len(raw):
        c = raw[i]
        if c == "\\" and i + 1 < len(raw):
            nxt = raw[i + 1]
            if nxt in "01234567" and i + 3 < len(raw) + 1:
                out.append(int(raw[i + 1 : i + 4], 8))
                i += 4
                continue
            out.extend(simple.get(nxt, nxt.encode()))
            i += 2
            continue
        out.extend(c.encode())
        i += 1
    return out.decode("utf-8", errors="replace")


def _strip_prefix(path: str) -> str:
    path = _unquote(path)
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path


def parse_unified_diff(text: str) -> list[DiffFile]:
    """Lê o diff linha a linha só por "\n" (um "\r" no meio de uma linha do PR não pode
    inventar cabeçalhos) e respeita as contagens de cada hunk."""
    files: list[DiffFile] = []
    current: DiffFile | None = None
    hunk: Hunk | None = None
    old_no = new_no = old_left = new_left = 0
    buf: list[str] = []

    def close() -> None:
        if current is not None:
            current.raw = "\n".join(buf) + "\n"

    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    for raw in lines:
        line = raw[:-1] if raw.endswith("\r") else raw  # CRLF do arquivo original
        in_hunk = hunk is not None and (old_left > 0 or new_left > 0)
        if not in_hunk and line.startswith("diff --git "):
            close()
            buf = [raw]
            m = _DIFF_GIT.match(line)
            a = _strip_prefix(m.group("a")) if m else ""
            b = _strip_prefix(m.group("b")) if m else ""
            current = DiffFile(path=b or a, old_path=a if a != b else None)
            files.append(current)
            hunk = None
            continue
        if current is None:
            continue
        buf.append(raw)
        if in_hunk:
            assert hunk is not None
            kind, body = (line[0], line[1:]) if line else (" ", "")
            if kind == "\\":  # "\ No newline at end of file"
                continue
            if kind == "+":
                hunk.lines.append(DiffLine("+", body, None, new_no))
                new_no += 1
                new_left -= 1
            elif kind == "-":
                hunk.lines.append(DiffLine("-", body, old_no, None))
                old_no += 1
                old_left -= 1
            else:
                # contexto (inclusive linha vazia cujo espaço inicial alguma ferramenta tirou)
                hunk.lines.append(DiffLine(" ", body, old_no, new_no))
                old_no += 1
                new_no += 1
                old_left -= 1
                new_left -= 1
            continue
        # cabeçalho do arquivo
        if line.startswith("new file mode"):
            current.status = "added"
        elif line.startswith("deleted file mode"):
            current.status = "deleted"
        elif line.startswith("rename from "):
            current.status = "renamed"
            current.old_path = _unquote(line[len("rename from ") :])
        elif line.startswith("rename to "):
            current.path = _unquote(line[len("rename to ") :])
        elif line.startswith("Binary files ") or line.startswith("GIT binary patch"):
            current.binary = True
        elif line.startswith("+++ "):
            dst = line[4:].strip()
            if dst != "/dev/null":
                current.path = _strip_prefix(dst)
        m = _HUNK.match(line)
        if m:
            hunk = Hunk(
                old_start=int(m.group(1)),
                old_count=int(m.group(2) if m.group(2) is not None else 1),
                new_start=int(m.group(3)),
                new_count=int(m.group(4) if m.group(4) is not None else 1),
            )
            current.hunks.append(hunk)
            old_no, new_no = hunk.old_start, hunk.new_start
            old_left, new_left = hunk.old_count, hunk.new_count
    close()
    for f in files:
        if f.status == "deleted" and f.old_path:
            f.path = f.old_path
        if f.status != "renamed" and f.old_path == f.path:
            f.old_path = None
    return files


def split_diff_by_file(text: str) -> dict[str, str]:
    """Trechos do diff por arquivo, vindos da mesma leitura que define os arquivos (para
    montar um diff só com os arquivos revisados)."""
    return {f.path: f.raw for f in parse_unified_diff(text)}
