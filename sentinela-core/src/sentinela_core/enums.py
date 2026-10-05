"""Enumerações do domínio. Os valores são estáveis (gravados no banco e na API);
os rótulos em pt-BR ficam em LABELS."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    TECH_LEAD = "tech_lead"
    REVIEWER = "reviewer"
    DEVELOPER = "developer"
    READER = "reader"


class Severity(StrEnum):
    BLOCKER = "blocker"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


SEVERITY_RANK: dict[Severity, int] = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.BLOCKER: 4,
}


def severity_at_least(value: Severity | str, threshold: Severity | str) -> bool:
    return SEVERITY_RANK[Severity(value)] >= SEVERITY_RANK[Severity(threshold)]


def max_severity(a: Severity | str, b: Severity | str) -> Severity:
    a, b = Severity(a), Severity(b)
    return a if SEVERITY_RANK[a] >= SEVERITY_RANK[b] else b


def min_severity(a: Severity | str, b: Severity | str) -> Severity:
    a, b = Severity(a), Severity(b)
    return a if SEVERITY_RANK[a] <= SEVERITY_RANK[b] else b


class Category(StrEnum):
    SECURITY = "security"
    ARCHITECTURE = "architecture"
    STRUCTURE = "structure"
    STANDARDS = "standards"
    TESTS = "tests"
    PERFORMANCE = "performance"
    DOCS = "docs"
    OTHER = "other"


class RuleKind(StrEnum):
    # Avaliada pela IA a partir de uma instrução em linguagem natural.
    AI = "ai"
    # Expressão regular aplicada às linhas adicionadas (determinística, sem custo de IA).
    PATTERN = "pattern"


class FindingSource(StrEnum):
    AI = "ai"
    PATTERN = "pattern"


class FindingStatus(StrEnum):
    OPEN = "open"
    # Desenvolvedor contestou; continua contando como aberto até alguém decidir.
    DISPUTED = "disputed"
    # Exceção aceita com justificativa (tech lead).
    WAIVED = "waived"
    # Descartado como falso positivo.
    FALSE_POSITIVE = "false_positive"


UNRESOLVED_FINDING = {FindingStatus.OPEN, FindingStatus.DISPUTED}


class Provider(StrEnum):
    GITHUB = "github"
    GITLAB = "gitlab"


class GateMode(StrEnum):
    # Status obrigatório no PR/MR; o merge continua no GitHub/GitLab.
    STATUS_CHECK = "status_check"
    # O merge é feito pelo botão do Sentinela (a branch só aceita merge do robô).
    PLATFORM_MERGE = "platform_merge"
    BOTH = "both"


class Enforcement(StrEnum):
    # Bloqueia de verdade: o status reflete o gate.
    ENFORCE = "enforce"
    # Período de adoção: revisa e mostra tudo, mas publica sucesso para não travar merges.
    OBSERVE = "observe"


class ApprovalMode(StrEnum):
    # Sem apontamentos, a IA aprova; com apontamentos, exige aprovação humana.
    AI_WHEN_CLEAN = "ai_when_clean"
    # Sempre exige aprovação humana.
    ALWAYS_HUMAN = "always_human"


class MergeMethod(StrEnum):
    MERGE = "merge"
    SQUASH = "squash"
    REBASE = "rebase"


class PullRequestState(StrEnum):
    OPEN = "open"
    MERGED = "merged"
    CLOSED = "closed"


class ReviewStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


ACTIVE_REVIEW = {ReviewStatus.QUEUED, ReviewStatus.RUNNING}


class ReviewTrigger(StrEnum):
    WEBHOOK = "webhook"
    MANUAL = "manual"
    SYNC = "sync"


class GateStatus(StrEnum):
    REVIEWING = "reviewing"
    BLOCKED = "blocked"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    ERROR = "error"
    OVERRIDDEN = "overridden"
    STALE = "stale"
    MERGED = "merged"


# Gates que liberam o merge.
PASSING_GATE = {GateStatus.APPROVED, GateStatus.OVERRIDDEN}
# Gates que não mudam mais.
FINAL_GATE = {GateStatus.STALE, GateStatus.MERGED}


class Decision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class EngineKind(StrEnum):
    CLAUDE_CODE = "claude_code"
    COPILOT_CLI = "copilot_cli"
    # Motor de simulação (heurísticas locais) para desenvolvimento, demonstração e testes.
    FAKE = "fake"


class RunnerStatus(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"


LABELS: dict[str, str] = {
    # papéis
    "admin": "Administrador",
    "tech_lead": "Tech lead",
    "reviewer": "Revisor",
    "developer": "Desenvolvedor",
    "reader": "Leitor",
    # severidades
    "blocker": "Bloqueante",
    "high": "Alta",
    "medium": "Média",
    "low": "Baixa",
    "info": "Informativa",
    # categorias
    "security": "Segurança",
    "architecture": "Arquitetura",
    "structure": "Estrutura",
    "standards": "Padrão de código",
    "tests": "Testes",
    "performance": "Desempenho",
    "docs": "Documentação",
    "other": "Outros",
}


def label(value: str) -> str:
    return LABELS.get(str(value), str(value))
