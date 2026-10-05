"""Biblioteca de regras e modelos de perfil prontos. O tech lead parte daqui e ajusta."""

from __future__ import annotations

from dataclasses import dataclass

from sentinela_core.enums import Category, RuleKind, Severity
from sentinela_core.rules import ProfileSpec, RuleSpec

S, A, ST, PD, T, P, D = (
    Category.SECURITY,
    Category.ARCHITECTURE,
    Category.STRUCTURE,
    Category.STANDARDS,
    Category.TESTS,
    Category.PERFORMANCE,
    Category.DOCS,
)
PAT, AI = RuleKind.PATTERN, RuleKind.AI
TEST_PATHS = [
    "**/tests/**",
    "**/test/**",
    "**/__tests__/**",
    "**/*.test.*",
    "**/*.spec.*",
    "**/test_*.py",
    "**/*_test.py",
    "**/*Test.java",
]


@dataclass(frozen=True)
class LibraryEntry:
    rule: RuleSpec
    tags: tuple[str, ...]


def _r(tags: tuple[str, ...], **kw) -> LibraryEntry:
    return LibraryEntry(RuleSpec(**kw), tags)


RULES: dict[str, LibraryEntry] = {
    e.rule.code: e
    for e in [
        # ------------------------------------------------------------------ geral
        _r(
            ("geral", "segurança"),
            code="SEC-001",
            title="Segredo ou credencial no código",
            category=S,
            severity=Severity.BLOCKER,
            kind=PAT,
            pattern=r"(?i)(password|passwd|senha|secret|api[_-]?key|access[_-]?key|private[_-]?key|token|client[_-]?secret)[a-z0-9_]*['\"]?\s*[:=]\s*['\"][^'\"\s]{8,}['\"]",
            instruction="Credenciais nunca ficam no código: use o cofre de segredos ou variáveis de ambiente injetadas na implantação.",
            suggestion="Remova o valor, revogue a credencial exposta e leia-a de uma variável de ambiente ou do cofre.",
            exclude_paths=TEST_PATHS,
        ),
        _r(
            ("geral", "segurança"),
            code="SEC-002",
            title="Chave privada no repositório",
            category=S,
            severity=Severity.BLOCKER,
            kind=PAT,
            pattern=r"-----BEGIN (RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY",
            instruction="Chaves privadas não podem ser versionadas.",
            suggestion="Remova o arquivo, gere uma nova chave e guarde-a no cofre.",
        ),
        _r(
            ("geral", "segurança"),
            code="SEC-003",
            title="Dado pessoal ou sensível em log",
            category=S,
            severity=Severity.HIGH,
            kind=AI,
            instruction="Logs, mensagens de erro e respostas não podem expor senhas, tokens, documentos (CPF/CNPJ), cartões, dados bancários ou dados pessoais completos. Verifique chamadas de log e exceções adicionadas.",
        ),
        _r(
            ("geral", "segurança"),
            code="SEC-004",
            title="Validação da entrada externa",
            category=S,
            severity=Severity.HIGH,
            kind=AI,
            instruction="Todo dado vindo de fora (requisição HTTP, fila, arquivo, parâmetro de linha de comando) deve ser validado por tipo, tamanho e formato antes de ser usado, com um schema explícito.",
        ),
        _r(
            ("geral", "segurança"),
            code="SEC-005",
            title="Consulta SQL montada com concatenação",
            category=S,
            severity=Severity.HIGH,
            kind=AI,
            instruction="Consultas SQL/NoSQL nunca concatenam ou interpolam valores (f-string, +, format, template string). Use parâmetros (bind) ou o query builder do ORM.",
        ),
        _r(
            ("geral", "segurança"),
            code="SEC-006",
            title="Verificação de TLS desligada",
            category=S,
            severity=Severity.HIGH,
            kind=PAT,
            pattern=r"verify\s*=\s*False|rejectUnauthorized\s*:\s*false|InsecureSkipVerify\s*:\s*true|NODE_TLS_REJECT_UNAUTHORIZED",
            instruction="Desligar a verificação de certificado abre espaço para interceptação.",
            suggestion="Mantenha a verificação e configure o certificado da CA interna.",
        ),
        _r(
            ("geral", "arquitetura"),
            code="ARQ-001",
            title="Camadas respeitadas",
            category=A,
            severity=Severity.MEDIUM,
            kind=AI,
            instruction="Respeite a separação de camadas descrita no contexto do perfil: a camada de entrada (rotas, controllers, handlers) não acessa banco nem clientes externos diretamente; regras de negócio ficam na camada de serviço/domínio; o domínio não importa infraestrutura.",
        ),
        _r(
            ("geral", "estrutura"),
            code="EST-001",
            title="Responsabilidade única",
            category=ST,
            severity=Severity.LOW,
            kind=AI,
            instruction="Funções e classes novas devem ter uma responsabilidade clara. Aponte funções adicionadas com mais de ~60 linhas ou que misturam I/O, regra de negócio e formatação.",
        ),
        _r(
            ("geral", "testes"),
            code="TST-001",
            title="Mudança de comportamento com teste",
            category=T,
            severity=Severity.MEDIUM,
            kind=AI,
            instruction="Toda regra de negócio nova ou alterada precisa de teste automatizado no mesmo PR. Aponte quando o PR muda comportamento em código de produção e não adiciona nem altera testes correspondentes.",
        ),
        _r(
            ("geral", "desempenho"),
            code="PER-001",
            title="Consulta dentro de laço (N+1)",
            category=P,
            severity=Severity.MEDIUM,
            kind=AI,
            instruction="Evite chamadas ao banco ou a APIs dentro de laços sobre coleções; carregue em lote.",
        ),
        _r(
            ("geral", "documentação"),
            code="DOC-001",
            title="Contrato público documentado",
            category=D,
            severity=Severity.INFO,
            kind=AI,
            instruction="Endpoints, eventos ou funções públicas novos precisam de descrição (docstring, OpenAPI ou README) explicando entrada, saída e erros.",
        ),
        # ------------------------------------------------------------------ python
        _r(
            ("python",),
            code="PY-001",
            title="print usado para depuração",
            category=PD,
            severity=Severity.LOW,
            kind=PAT,
            pattern=r"^\s*print\(",
            paths=["**/*.py"],
            exclude_paths=[*TEST_PATHS, "**/scripts/**"],
            instruction="Use o logger do módulo em vez de print.",
            suggestion="logger = logging.getLogger(__name__); logger.info(...)",
        ),
        _r(
            ("python",),
            code="PY-002",
            title="Exceção genérica engolida",
            category=PD,
            severity=Severity.MEDIUM,
            kind=AI,
            paths=["**/*.py"],
            instruction="Não capture Exception/BaseException (ou except sem tipo) sem relançar ou registrar com contexto. Capture a exceção específica.",
        ),
        _r(
            ("python",),
            code="PY-003",
            title="Tipagem nas funções públicas",
            category=PD,
            severity=Severity.LOW,
            kind=AI,
            paths=["**/*.py"],
            instruction="Funções e métodos públicos adicionados devem ter anotações de tipo nos parâmetros e no retorno.",
        ),
        _r(
            ("python", "fastapi"),
            code="PY-010",
            title="Rota sem modelo de resposta",
            category=PD,
            severity=Severity.LOW,
            kind=AI,
            paths=["**/*.py"],
            instruction="Rotas FastAPI novas declaram response_model (ou tipo de retorno) e usam modelos Pydantic na entrada, nunca dict solto.",
        ),
        # ------------------------------------------------------------------ typescript / react
        _r(
            ("typescript",),
            code="TS-001",
            title="console.log esquecido",
            category=PD,
            severity=Severity.LOW,
            kind=PAT,
            pattern=r"\bconsole\.(log|debug)\(",
            paths=["**/*.{ts,tsx,js,jsx}"],
            exclude_paths=TEST_PATHS,
            instruction="Remova logs de depuração antes do merge.",
        ),
        _r(
            ("typescript",),
            code="TS-002",
            title="Uso de any",
            category=PD,
            severity=Severity.LOW,
            kind=PAT,
            pattern=r":\s*any\b|\bas any\b|<any>",
            paths=["**/*.{ts,tsx}"],
            instruction="Evite any: tipe a estrutura ou use unknown com validação.",
        ),
        _r(
            ("react", "segurança"),
            code="WEB-001",
            title="HTML injetado sem sanitização",
            category=S,
            severity=Severity.HIGH,
            kind=AI,
            paths=["**/*.{ts,tsx,js,jsx}"],
            instruction="dangerouslySetInnerHTML, innerHTML ou v-html só com conteúdo sanitizado (ex.: DOMPurify) e nunca com dado vindo do usuário sem tratamento.",
        ),
        _r(
            ("react", "segurança"),
            code="WEB-002",
            title="Token em armazenamento do navegador",
            category=S,
            severity=Severity.HIGH,
            kind=AI,
            paths=["**/*.{ts,tsx,js,jsx}"],
            instruction="Tokens de acesso e dados sensíveis não vão para localStorage/sessionStorage/cookies sem httpOnly.",
        ),
        _r(
            ("react", "arquitetura"),
            code="WEB-010",
            title="Chamada HTTP fora da camada de API",
            category=A,
            severity=Severity.MEDIUM,
            kind=AI,
            paths=["**/*.{ts,tsx,js,jsx}"],
            instruction="Componentes não chamam fetch/axios diretamente: usam o cliente/hook da camada de API do projeto.",
        ),
        _r(
            ("react",),
            code="WEB-011",
            title="Acessibilidade básica",
            category=PD,
            severity=Severity.MEDIUM,
            kind=AI,
            paths=["**/*.{tsx,jsx}"],
            instruction="Imagens com alt, botões e ícones clicáveis com rótulo acessível, campos de formulário com label associado e nada clicável que não seja botão ou link.",
        ),
        # ------------------------------------------------------------------ java
        _r(
            ("java",),
            code="JAVA-001",
            title="System.out em código de produção",
            category=PD,
            severity=Severity.LOW,
            kind=PAT,
            pattern=r"System\.(out|err)\.print|\.printStackTrace\(\)",
            paths=["**/*.java"],
            exclude_paths=TEST_PATHS,
            instruction="Use o logger (SLF4J) com contexto.",
        ),
        _r(
            ("java", "spring"),
            code="JAVA-010",
            title="Injeção por construtor",
            category=PD,
            severity=Severity.LOW,
            kind=PAT,
            pattern=r"^\s*@Autowired\s*$",
            paths=["**/*.java"],
            exclude_paths=TEST_PATHS,
            instruction="Prefira injeção por construtor (campos final) em vez de @Autowired em campo.",
        ),
        _r(
            ("java", "spring", "segurança"),
            code="JAVA-020",
            title="CORS ou autorização amplos demais",
            category=S,
            severity=Severity.HIGH,
            kind=AI,
            paths=["**/*.java"],
            instruction='Não use @CrossOrigin("*"), permitAll() em rotas de negócio ou desligue CSRF sem justificativa registrada.',
        ),
        # ------------------------------------------------------------------ terraform
        _r(
            ("terraform", "segurança"),
            code="IAC-001",
            title="Liberação para a internet inteira",
            category=S,
            severity=Severity.HIGH,
            kind=PAT,
            pattern=r"0\.0\.0\.0/0|::/0",
            paths=["**/*.tf"],
            instruction="Regras de rede abertas para qualquer origem precisam de aprovação explícita da segurança.",
        ),
        _r(
            ("terraform", "segurança"),
            code="IAC-002",
            title="Recurso público ou sem criptografia",
            category=S,
            severity=Severity.BLOCKER,
            kind=AI,
            paths=["**/*.tf"],
            instruction="Buckets, bancos e filas não podem ser públicos e devem ter criptografia em repouso habilitada.",
        ),
        _r(
            ("terraform",),
            code="IAC-010",
            title="Tags obrigatórias",
            category=PD,
            severity=Severity.LOW,
            kind=AI,
            paths=["**/*.tf"],
            instruction="Recursos novos têm as tags de dono, sistema e ambiente definidas no contexto do perfil.",
        ),
        _r(
            ("terraform", "arquitetura"),
            code="IAC-020",
            title="Módulo sem versão fixa",
            category=A,
            severity=Severity.MEDIUM,
            kind=AI,
            paths=["**/*.tf"],
            instruction="Módulos externos usam versão fixa (ref de tag ou version), nunca branch.",
        ),
        # ------------------------------------------------------------------ containers e pipelines
        _r(
            ("docker",),
            code="OPS-001",
            title="Imagem base sem versão fixa",
            category=S,
            severity=Severity.MEDIUM,
            kind=PAT,
            pattern=r"^\s*FROM\s+(?!scratch\b|\$)[^\s:@]+(:latest)?(\s+AS\s+\S+)?\s*$",
            ignore_case=True,
            paths=["**/Dockerfile*", "**/*.dockerfile"],
            instruction="Use tag de versão (ou digest) na imagem base para builds reproduzíveis.",
        ),
        _r(
            ("docker", "segurança"),
            code="OPS-002",
            title="Container rodando como root",
            category=S,
            severity=Severity.MEDIUM,
            kind=AI,
            paths=["**/Dockerfile*"],
            instruction="A imagem final define um USER sem privilégios.",
        ),
        _r(
            ("pipeline", "segurança"),
            code="OPS-010",
            title="Action sem versão fixa",
            category=S,
            severity=Severity.LOW,
            kind=PAT,
            pattern=r"uses:\s*[^@\s]+@(main|master|HEAD)\b",
            paths=[".github/workflows/**"],
            instruction="Fixe actions de terceiros por tag ou SHA.",
        ),
        _r(
            ("pipeline", "segurança"),
            code="OPS-011",
            title="Segredo exposto no pipeline",
            category=S,
            severity=Severity.BLOCKER,
            kind=AI,
            paths=[
                ".github/workflows/**",
                "**/.gitlab-ci.yml",
                "**/Jenkinsfile",
                "**/azure-pipelines.yml",
            ],
            instruction="Segredos vêm de variáveis protegidas/mascaradas; nunca são impressos (echo), gravados em artefatos ou passados em linha de comando visível.",
        ),
    ]
}


@dataclass(frozen=True)
class Template:
    key: str
    name: str
    description: str
    path_globs: tuple[str, ...]
    instructions: str
    rules: tuple[str, ...]


TEMPLATES: dict[str, Template] = {
    t.key: t
    for t in [
        Template(
            "python-api",
            "API Python (FastAPI)",
            "Serviços HTTP em Python com FastAPI, SQLAlchemy e Pydantic.",
            ("**/*.py", "pyproject.toml", "requirements*.txt"),
            "Arquitetura em camadas: routers/ (entrada HTTP, só validação e chamada de serviço) → "
            "services/ (regra de negócio) → repositories/ (acesso a dados). Configuração só por "
            "variáveis de ambiente. Logs estruturados com logger por módulo.",
            (
                "SEC-001",
                "SEC-002",
                "SEC-003",
                "SEC-004",
                "SEC-005",
                "SEC-006",
                "ARQ-001",
                "EST-001",
                "TST-001",
                "PER-001",
                "PY-001",
                "PY-002",
                "PY-003",
                "PY-010",
                "DOC-001",
            ),
        ),
        Template(
            "react-frontend",
            "Front-end React (TypeScript)",
            "SPAs em React + TypeScript.",
            ("**/*.{ts,tsx,js,jsx}", "**/*.css", "package.json"),
            "Componentes de tela em pages/, componentes reutilizáveis em components/, acesso à API "
            "só pelo cliente em api/ (hooks de consulta). Estado do servidor em react-query.",
            (
                "SEC-001",
                "SEC-003",
                "SEC-004",
                "WEB-001",
                "WEB-002",
                "WEB-010",
                "WEB-011",
                "TS-001",
                "TS-002",
                "EST-001",
                "TST-001",
            ),
        ),
        Template(
            "java-spring",
            "Serviço Java (Spring Boot)",
            "APIs e workers em Java com Spring Boot.",
            ("**/*.java", "**/pom.xml", "**/*.gradle*", "**/application*.yml"),
            "Controller → Service → Repository. Controllers só convertem DTOs e delegam. Regras de "
            "negócio em services com transação declarada. Exceções de negócio tratadas por "
            "@ControllerAdvice.",
            (
                "SEC-001",
                "SEC-002",
                "SEC-003",
                "SEC-004",
                "SEC-005",
                "JAVA-020",
                "ARQ-001",
                "EST-001",
                "TST-001",
                "PER-001",
                "JAVA-001",
                "JAVA-010",
            ),
        ),
        Template(
            "terraform",
            "Infraestrutura (Terraform)",
            "Módulos e stacks Terraform.",
            ("**/*.tf", "**/*.tfvars"),
            "Tags obrigatórias: owner, sistema, ambiente. Recursos só via módulos internos "
            "versionados. Nada público sem aprovação da segurança.",
            ("SEC-001", "SEC-002", "IAC-001", "IAC-002", "IAC-010", "IAC-020"),
        ),
        Template(
            "containers-pipelines",
            "Containers e pipelines",
            "Dockerfiles e pipelines de CI/CD (GitHub Actions, GitLab CI).",
            ("**/Dockerfile*", "**/*.dockerfile", ".github/workflows/**", "**/.gitlab-ci.yml"),
            "Imagens a partir das bases aprovadas, usuário sem privilégios, segredos só de "
            "variáveis protegidas.",
            ("SEC-001", "SEC-002", "OPS-001", "OPS-002", "OPS-010", "OPS-011"),
        ),
    ]
}


def template_profile(key: str) -> ProfileSpec:
    t = TEMPLATES[key]
    return ProfileSpec(
        name=t.name,
        description=t.description,
        instructions=t.instructions,
        path_globs=list(t.path_globs),
        rules=[RULES[code].rule for code in t.rules],
    )


def template_categories(key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for code in TEMPLATES[key].rules:
        cat = RULES[code].rule.category.value
        out[cat] = out.get(cat, 0) + 1
    return out
