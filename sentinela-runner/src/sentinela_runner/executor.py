"""Execução de uma revisão: checkout → diff → regras de padrão → IA → resultado."""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from sentinela_core.diff import parse_unified_diff
from sentinela_core.findings import AiOutput, coverage_finding, normalize_findings
from sentinela_core.prompt import PullRequestInfo, build_review_prompt
from sentinela_core.rules import ProfileSpec, run_pattern_rules
from sentinela_runner.api import ApiError, SentinelaApi
from sentinela_runner.engines import Engine, EngineError, EngineRequest
from sentinela_runner.gitops import (
    Git,
    GitError,
    checkout,
    line_reader,
    strip_agent_instructions,
)
from sentinela_runner.logs import LogShipper, Masker
from sentinela_runner.process import Canceled
from sentinela_runner.settings import RunnerSettings

log = logging.getLogger("sentinela.runner")


class ReviewExecutor:
    def __init__(
        self, settings: RunnerSettings, api: SentinelaApi, engines: dict[str, tuple[Engine, str]]
    ):
        self.settings = settings
        self.api = api
        self.engines = engines

    async def run(self, review: dict[str, Any], cancel: asyncio.Event) -> None:
        review_id = review["id"]
        masker = Masker(review.get("mask_values") or [])
        shipper = LogShipper(self.api, review_id, masker, self.settings.log_push_interval_s)
        shipper.start()
        work_root = self.settings.home / "work"
        work_root.mkdir(parents=True, exist_ok=True)
        scratch = Path(tempfile.mkdtemp(prefix=f"rev-{review_id[:8]}-", dir=work_root))
        started = time.monotonic()
        try:
            body = await self._execute(review, scratch, shipper, cancel)
            await shipper.flush()
            await self.api.result(review_id, body)
            log.info("revisão %s concluída: %d apontamento(s)", review_id, len(body["findings"]))
        except Canceled:
            shipper.info("revisão cancelada")
            log.info("revisão %s cancelada", review_id)
        except (GitError, EngineError) as exc:
            message = masker(str(exc))
            shipper.write(message, "stderr")
            log.warning("revisão %s falhou: %s", review_id, message)
            await self._fail(review_id, message, exc.retryable)
        except ApiError as exc:
            log.warning("revisão %s: API recusou o resultado: %s", review_id, exc)
        except Exception as exc:  # noqa: BLE001
            message = masker(f"{type(exc).__name__}: {exc}")
            log.exception("erro inesperado na revisão %s", review_id)
            shipper.write(message, "stderr")
            await self._fail(review_id, message, True)
        finally:
            shipper.info(f"tempo total: {time.monotonic() - started:.1f}s")
            await shipper.stop()
            if not self.settings.keep_workspaces:
                shutil.rmtree(scratch, ignore_errors=True)

    async def _fail(self, review_id: str, message: str, retryable: bool) -> None:
        try:
            await self.api.fail(review_id, message, retryable)
        except Exception as exc:  # noqa: BLE001
            log.warning("não foi possível registrar a falha de %s: %s", review_id, exc)

    async def _phase(self, review_id: str, phase: str, detail: str | None = None) -> None:
        try:
            await self.api.phase(review_id, phase, detail)
        except ApiError as exc:
            if exc.status == 409:
                raise Canceled() from exc
            log.debug("fase %s não registrada: %s", phase, exc)

    async def _execute(
        self, review: dict[str, Any], scratch: Path, shipper: LogShipper, cancel: asyncio.Event
    ) -> dict[str, Any]:
        rid = review["id"]
        pr = review["pull_request"]
        repo = review["repository"]
        engine_cfg = review["engine"]
        timings: dict[str, float] = {}
        shipper.info(
            f"revisão de {repo['full_name']}#{pr['number']} @ {pr['head_sha'][:10]} "
            f"(tentativa {review['attempt']})"
        )

        # ------------------------------------------------------------ código
        await self._phase(rid, "cloning")
        t0 = time.monotonic()
        git = Git(
            self.settings.git_path,
            scratch / "repo",
            username=review["git"].get("username"),
            token=review["git"].get("token"),
            auth_url=repo["clone_url"],
            timeout=self.settings.git_timeout_s,
            cancel=cancel,
            log=shipper.info,
        )
        co = await checkout(
            git,
            clone_url=repo["clone_url"],
            provider=repo["provider"],
            number=pr["number"],
            head_sha=pr["head_sha"],
            base_sha=pr.get("base_sha"),
            target_branch=pr["target_branch"],
            depth=self.settings.fetch_depth,
        )
        timings["checkout_s"] = round(time.monotonic() - t0, 2)

        # ------------------------------------------------------------ diff
        await self._phase(rid, "diff")
        files = parse_unified_diff(co.diff)
        diff_path = scratch / "pr.diff"
        diff_path.write_text(co.diff, encoding="utf-8")
        additions = sum(f.additions for f in files)
        deletions = sum(f.deletions for f in files)
        shipper.info(
            f"{len(files)} arquivo(s) alterado(s), +{additions} -{deletions} "
            f"(base {co.merge_base[:10]})"
        )

        profiles = [ProfileSpec.model_validate(p) for p in review["profiles"]]
        await self._phase(rid, "patterns")
        warnings: list[str] = []
        # em outra thread: o heartbeat e os logs seguem enquanto as regex rodam
        hits = await asyncio.to_thread(run_pattern_rules, files, profiles, warnings)
        for warning in warnings:
            shipper.write(warning, "stderr")
        shipper.info(f"regras de padrão: {len(hits)} ocorrência(s)")

        # ------------------------------------------------------------ IA
        bundle = build_review_prompt(
            PullRequestInfo(
                repository=repo["full_name"],
                number=pr["number"],
                title=pr["title"],
                author=pr.get("author"),
                source_branch=pr.get("source_branch"),
                target_branch=pr.get("target_branch"),
                description=pr.get("description"),
            ),
            profiles,
            files,
            co.diff,
            max_diff_chars=int(review.get("max_diff_chars") or 200_000),
            full_diff_path=str(diff_path),
            structured_output=engine_cfg["kind"] == "claude_code",
        )
        engine_stats: dict[str, Any] = {}
        if bundle.needs_ai:
            entry = self.engines.get(engine_cfg["kind"])
            if entry is None:
                raise EngineError(
                    f"motor {engine_cfg['kind']} não está instalado neste runner", retryable=True
                )
            engine = entry[0]
            removed = strip_agent_instructions(co.path)
            if removed:
                # O conteúdo segue no diff como dado; o que sai é o carregamento automático
                # como instrução da IA (CLAUDE.md, AGENTS.md, .claude/...).
                shipper.info(
                    f"{len(removed)} arquivo(s) de instrução de agente ignorados no checkout: "
                    + ", ".join(removed[:10])
                )
            await self._phase(rid, "ai", engine_cfg.get("model_label") or engine_cfg["kind"])
            shipper.info(
                f"{len(bundle.reviewed_files)} arquivo(s) vão para a IA "
                f"({bundle.diff_chars} caracteres de diff"
                + (", truncado" if bundle.truncated else "")
                + ")"
            )
            t1 = time.monotonic()
            response = await engine.review(
                EngineRequest(
                    workdir=co.path,
                    scratch=scratch,
                    system_prompt=bundle.system,
                    user_prompt=bundle.user,
                    model=engine_cfg.get("model") or "",
                    max_turns=int(engine_cfg.get("max_turns") or 30),
                    timeout_s=int(engine_cfg.get("timeout_s") or 900),
                    max_budget_usd=engine_cfg.get("max_budget_usd"),
                    extra_args=list(engine_cfg.get("extra_args") or []),
                    env=dict(engine_cfg.get("env") or {}),
                    log=shipper,
                    cancel=cancel,
                    files=files,
                    profiles=profiles,
                    reviewed_files=bundle.reviewed_files,
                )
            )
            timings["ai_s"] = round(time.monotonic() - t1, 2)
            ai_output = response.output
            engine_stats = response.stats
        else:
            shipper.info("nenhum arquivo alterado tem regra de IA; só as regras de padrão valem")
            ai_output = AiOutput(
                summary="Nenhum arquivo alterado é coberto por regras de IA dos perfis; "
                "aplicadas só as regras de padrão."
            )

        await self._phase(rid, "reporting")
        findings = normalize_findings(ai_output, hits, profiles, files, line_reader(co.path))
        uncovered = coverage_finding(files, profiles)
        if uncovered is not None:
            shipper.info("há arquivos alterados fora dos perfis: a decisão fica com uma pessoa")
            findings.append(uncovered)
        stats = {
            "files_changed": len(files),
            "additions": additions,
            "deletions": deletions,
            "files_reviewed_ai": len(bundle.reviewed_files),
            "pattern_hits": len(hits),
            "diff_truncated": bundle.truncated,
            "merge_base": co.merge_base,
            **timings,
            **{k: v for k, v in engine_stats.items() if v is not None},
        }
        return {
            "summary": ai_output.summary,
            "findings": [f.model_dump(mode="json") for f in findings],
            "stats": stats,
        }
