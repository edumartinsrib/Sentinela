"""Checkout do PR e cálculo do diff (merge-base → head).

A credencial vai por `http.extraHeader` em variáveis GIT_CONFIG_* (não aparece na linha de
comando nem na URL do remoto)."""

from __future__ import annotations

import asyncio
import base64
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from sentinela_runner import process


class GitError(Exception):
    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class Checkout:
    path: Path
    head_sha: str
    merge_base: str
    diff: str


def _origin(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}/"


def pr_ref(provider: str, number: int) -> str:
    if provider == "gitlab":
        return f"refs/merge-requests/{number}/head"
    return f"refs/pull/{number}/head"


class Git:
    def __init__(
        self,
        git: str,
        workdir: Path,
        *,
        username: str | None,
        token: str | None,
        auth_url: str | None = None,
        timeout: float,
        cancel: asyncio.Event | None,
        log,
    ):
        self.git = git
        self.workdir = workdir
        self.timeout = timeout
        self.cancel = cancel
        self.log = log
        env = {
            k: v
            for k, v in os.environ.items()
            if k
            in (
                "PATH",
                "HOME",
                "LANG",
                "LC_ALL",
                "SSL_CERT_FILE",
                "SSL_CERT_DIR",
                "HTTPS_PROXY",
                "HTTP_PROXY",
                "NO_PROXY",
                "https_proxy",
                "http_proxy",
                "no_proxy",
                "GIT_SSL_CAINFO",
                "SYSTEMROOT",
                "TEMP",
                "TMP",
            )
        }
        env.update(GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="echo", GCM_INTERACTIVE="never")
        configs = [("safe.directory", "*"), ("advice.detachedHead", "false")]
        origin = _origin(auth_url)
        if token and origin:
            # Só para o host do repositório: o token da integração nunca vai para outro lugar
            # (redirecionamentos, submódulos ou um endereço de clone trocado).
            basic = base64.b64encode(f"{username or 'x-access-token'}:{token}".encode()).decode()
            configs.append((f"http.{origin}.extraHeader", f"Authorization: Basic {basic}"))
        env["GIT_CONFIG_COUNT"] = str(len(configs))
        for i, (key, value) in enumerate(configs):
            env[f"GIT_CONFIG_KEY_{i}"] = key
            env[f"GIT_CONFIG_VALUE_{i}"] = value
        self.env = env

    async def __call__(self, *args: str, check: bool = True, quiet: bool = False) -> str:
        try:
            result = await process.run(
                [self.git, *args],
                cwd=str(self.workdir),
                env=self.env,
                timeout=self.timeout,
                cancel=self.cancel,
            )
        except process.ProcessTimeout as exc:
            raise GitError(f"git {args[0]}: {exc}") from exc
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout).strip().splitlines()[-3:]
            raise GitError(f"git {args[0]} falhou: {' / '.join(detail)}")
        if not quiet and result.stderr.strip():
            for line in result.stderr.strip().splitlines()[-5:]:
                self.log(f"git: {line}")
        return result.stdout


async def checkout(
    git: Git,
    *,
    clone_url: str,
    provider: str,
    number: int,
    head_sha: str,
    base_sha: str | None,
    target_branch: str,
    depth: int,
) -> Checkout:
    git.workdir.mkdir(parents=True, exist_ok=True)
    await git("init", "-q")
    await git("remote", "add", "origin", clone_url)
    pr = pr_ref(provider, number)
    git.log(f"buscando {target_branch} e {pr} (profundidade {depth})")
    await git(
        "fetch",
        "--no-tags",
        "--quiet",
        f"--depth={depth}",
        "origin",
        f"+refs/heads/{target_branch}:refs/remotes/origin/base",
        f"+{pr}:refs/remotes/origin/pr",
    )
    if (await git("cat-file", "-t", head_sha, check=False, quiet=True)).strip() != "commit":
        git.log(f"commit {head_sha[:10]} fora da ref do PR; buscando pelo SHA")
        try:
            await git("fetch", "--no-tags", "--quiet", f"--depth={depth}", "origin", head_sha)
        except GitError as exc:
            raise GitError(
                f"o commit {head_sha[:10]} não existe mais no repositório (push forçado?)",
                retryable=False,
            ) from exc
    base_ref = "refs/remotes/origin/base"
    merge_base = ""
    for attempt in range(4):
        merge_base = (await git("merge-base", base_ref, head_sha, check=False, quiet=True)).strip()
        if merge_base:
            break
        if attempt < 3:
            git.log("histórico raso demais para achar o ponto de partida; aprofundando")
            await git(
                "fetch",
                "--no-tags",
                "--quiet",
                "--deepen=1000",
                "origin",
                f"+refs/heads/{target_branch}:refs/remotes/origin/base",
                f"+{pr}:refs/remotes/origin/pr",
            )
    if not merge_base:
        if (
            base_sha
            and (await git("cat-file", "-t", base_sha, check=False, quiet=True)).strip() == "commit"
        ):
            merge_base = base_sha
        else:
            raise GitError(
                "não foi possível achar o ponto comum entre o PR e a branch de destino",
                retryable=False,
            )
    await git("checkout", "-q", "--detach", head_sha)
    diff = await git(
        "diff",
        "--no-color",
        "--no-ext-diff",
        "-M",
        "--unified=3",
        merge_base,
        head_sha,
        quiet=True,
    )
    return Checkout(git.workdir, head_sha, merge_base, diff)


def line_reader(root: Path):
    cache: dict[str, list[str] | None] = {}

    def read(path: str, line: int) -> str | None:
        if path not in cache:
            target = (root / path).resolve()
            if not str(target).startswith(str(root.resolve())) or not target.is_file():
                cache[path] = None
            else:
                try:
                    # read_bytes: sem conversão de fim de linha; só "\n" separa linhas (como no git)
                    text = target.read_bytes().decode("utf-8", errors="replace")
                    cache[path] = [ln.removesuffix("\r") for ln in text.split("\n")]
                except OSError:
                    cache[path] = None
        lines = cache[path]
        if not lines or line < 1 or line > len(lines):
            return None
        return lines[line - 1]

    return read


# Arquivos que as CLIs de IA carregam sozinhas como instrução (memória do projeto, regras
# do agente, servidores MCP). Num PR eles são conteúdo a revisar, não ordens para o revisor.
AGENT_FILES = {"claude.md", "claude.local.md", "agents.md", ".mcp.json", "copilot-instructions.md"}
AGENT_DIRS = {".claude"}
AGENT_SUBDIRS = {(".github", "instructions"), (".github", "prompts"), (".github", "chatmodes")}


def strip_agent_instructions(root: Path) -> list[str]:
    """Remove do checkout os arquivos de instrução de agentes. Devolve os caminhos removidos."""
    removed: list[str] = []
    for current, dirs, names in os.walk(root, topdown=True):
        here = Path(current)
        rel_parent = here.relative_to(root).parts
        for name in list(dirs):
            if name == ".git" and not rel_parent:
                dirs.remove(name)
            elif name in AGENT_DIRS or (rel_parent[-1:] + (name,)) in AGENT_SUBDIRS:
                shutil.rmtree(here / name, ignore_errors=True)
                removed.append(str((here / name).relative_to(root)) + "/")
                dirs.remove(name)
        for name in names:
            if name.lower() in AGENT_FILES:
                (here / name).unlink(missing_ok=True)
                removed.append(str((here / name).relative_to(root)))
    return sorted(removed)
