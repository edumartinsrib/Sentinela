# Padrões e regras

## Perfil

Um **perfil** é o padrão de um tipo de implementação: API Python, front-end React, serviço
Java, Terraform, Dockerfiles e pipelines. Um repositório aplica um ou mais perfis; cada
perfil escolhe os arquivos pelos caminhos (`path_globs`). Num monorepo, o perfil de front
cobre `web/**` e o de API cobre `api/**/*.py`, cada um com suas regras.

| Campo | O que é |
| --- | --- |
| `name`, `description` | Nome e descrição |
| `instructions` | Contexto de arquitetura e convenções do time, entregue à IA como referência (camadas, onde fica cada coisa, bibliotecas aprovadas) |
| `path_globs` | Arquivos a que o perfil se aplica, estilo `.gitignore` (`src/**/*.py`, `*.{ts,tsx}`, `!gerado/**`). Vazio = todos |
| `rules` | As regras |

Quem cria e muda perfis: **tech lead** e **admin do time**. Toda mudança fica na auditoria,
e a revisão guarda uma cópia dos perfis usados (a mesma revisão é reproduzível depois).

## Regra

| Campo | O que é |
| --- | --- |
| `code` | Código citado nos apontamentos (`SEC-001`, `ARQ-002`). `GERAL` é reservado |
| `title` | Nome curto |
| `category` | `security`, `architecture`, `structure`, `standards`, `tests`, `performance`, `docs`, `other` |
| `severity` | `blocker`, `high`, `medium`, `low`, `info` |
| `kind` | `ai` (instrução em linguagem natural) ou `pattern` (expressão regular) |
| `instruction` | Para a IA: o que é proibido ou obrigatório **e por quê** |
| `pattern`, `ignore_case` | Para regex: aplicada a cada linha **adicionada** do diff |
| `paths`, `exclude_paths` | Recorte dentro do perfil (ex.: só `**/routers/**`, nunca `**/tests/**`) |
| `suggestion` | "Como corrigir", mostrado no apontamento |
| `reference_url` | Link para o padrão interno |
| `enabled` | Liga/desliga sem apagar |

**Quem decide a severidade é a regra, não a IA.** A IA aponta citando o código da regra;
o Sentinela aplica a severidade e a categoria cadastradas (se a mesma regra estiver em dois
perfis, vale a maior). Apontamentos fora das regras (`GERAL`) são aceitos só para problemas
evidentes de segurança ou bugs, e ficam limitados a **média**: não bloqueiam sozinhos.

### Regra de IA ou de regex?

| Use regex quando | Use IA quando |
| --- | --- |
| O problema é textual e inequívoco (`print(`, `console.log`, `verify=False`, `FROM x:latest`) | Precisa de contexto (camadas, validação de entrada, teste para a mudança, N+1) |
| Precisa ser instantâneo e sem custo | O padrão é descrito melhor em palavras do que em expressão |
| Falso positivo é raro | Há julgamento ("responsabilidade única", "nome claro") |

As regex rodam com tempo limite por linha (uma expressão com retrocesso catastrófico é
interrompida e aparece no log da revisão) e podem ser testadas no próprio diálogo da regra.

### Escrevendo boas instruções

- Diga **o que** e **por quê**: "Rotas não acessam o banco direto; a regra de negócio fica
  em `services/` para ser testável sem HTTP".
- Diga **onde não vale**: "Scripts em `tools/` podem usar `print`".
- Uma regra, um assunto. Regras genéricas ("código limpo") geram ruído.
- Comece em **informativa** ou **baixa**, veja os apontamentos por algumas semanas
  (**Regras mais violadas** no painel mostra também exceções e falsos positivos) e só
  depois suba a severidade.

## Biblioteca

O Sentinela vem com 32 regras e 5 modelos de perfil. Um perfil novo pode partir de um
modelo, e regras da biblioteca podem ser adicionadas a qualquer perfil.

| Modelo | Regras |
| --- | --- |
| API Python (FastAPI) | SEC-001…006, ARQ-001, EST-001, TST-001, PER-001, PY-001/002/003/010, DOC-001 |
| Front-end React (TypeScript) | SEC-001/003/004, WEB-001/002/010/011, TS-001/002, EST-001, TST-001 |
| Serviço Java (Spring Boot) | SEC-001…005, JAVA-001/010/020, ARQ-001, EST-001, TST-001, PER-001 |
| Infraestrutura (Terraform) | SEC-001/002, IAC-001/002/010/020 |
| Containers e pipelines | SEC-001/002, OPS-001/002/010/011 |

| Código | Regra | Tipo | Severidade |
| --- | --- | --- | --- |
| SEC-001 | Segredo ou credencial no código | regex | bloqueante |
| SEC-002 | Chave privada no repositório | regex | bloqueante |
| SEC-003 | Dado pessoal ou sensível em log | IA | alta |
| SEC-004 | Validação da entrada externa | IA | alta |
| SEC-005 | Consulta SQL montada com concatenação | IA | alta |
| SEC-006 | Verificação de TLS desligada | regex | alta |
| ARQ-001 | Camadas respeitadas | IA | média |
| EST-001 | Responsabilidade única | IA | baixa |
| TST-001 | Mudança de comportamento com teste | IA | média |
| PER-001 | Consulta dentro de laço (N+1) | IA | média |
| DOC-001 | Contrato público documentado | IA | informativa |
| PY-001 | `print` usado para depuração | regex | baixa |
| PY-002 | Exceção genérica engolida | IA | média |
| PY-003 | Tipagem nas funções públicas | IA | baixa |
| PY-010 | Rota sem modelo de resposta | IA | baixa |
| WEB-001 | HTML injetado sem sanitização | IA | alta |
| WEB-002 | Token em armazenamento do navegador | IA | alta |
| WEB-010 | Chamada HTTP fora da camada de API | IA | média |
| WEB-011 | Acessibilidade básica | IA | média |
| TS-001 | `console.log` esquecido | regex | baixa |
| TS-002 | Uso de `any` | regex | baixa |
| JAVA-001 | `System.out` em código de produção | regex | baixa |
| JAVA-010 | Injeção por construtor | regex | baixa |
| JAVA-020 | CORS ou autorização amplos demais | IA | alta |
| IAC-001 | Liberação para a internet inteira | regex | alta |
| IAC-002 | Recurso público ou sem criptografia | IA | bloqueante |
| IAC-010 | Tags obrigatórias | IA | baixa |
| IAC-020 | Módulo sem versão fixa | IA | média |
| OPS-001 | Imagem base sem versão fixa | regex | média |
| OPS-002 | Container rodando como root | IA | média |
| OPS-010 | Action sem versão fixa | regex | baixa |
| OPS-011 | Segredo exposto no pipeline | IA | bloqueante |

## YAML

Perfis entram e saem em YAML (**Padrões → Importar YAML**, **Exportar YAML**), para
versionar o padrão do time num repositório e revisar mudanças de padrão por PR também.
Exemplos em [examples/perfis](../examples/perfis/).

```yaml
name: API Python (FastAPI)
description: Serviços HTTP em Python com FastAPI, SQLAlchemy e Pydantic.
instructions: >-
  Arquitetura em camadas: routers/ (entrada HTTP) → services/ (regra de negócio)
  → repositories/ (acesso a dados). Configuração só por variáveis de ambiente.
path_globs: ['**/*.py', pyproject.toml]
rules:
  - code: SEC-001
    title: Segredo ou credencial no código
    category: security
    severity: blocker
    kind: pattern
    pattern: (?i)(password|secret|api[_-]?key|token)[a-z0-9_]*['"]?\s*[:=]\s*['"][^'"\s]{8,}['"]
    exclude_paths: ['**/tests/**']
    suggestion: Remova o valor, revogue a credencial e leia de uma variável de ambiente.
  - code: ARQ-001
    title: Camadas respeitadas
    category: architecture
    severity: medium
    kind: ai
    instruction: >-
      A camada de entrada (rotas) não acessa banco nem clientes externos diretamente;
      regra de negócio fica em services/.
```

## Arquivos fora dos perfis

Se o PR altera arquivos que **nenhum perfil** do repositório cobre, eles não passam por
regra nem por IA. Para a IA não aprovar o que não revisou, a revisão gera um apontamento
**informativo** listando esses arquivos, e uma pessoa decide. Para evitar o apontamento,
inclua os caminhos num perfil (ex.: um perfil "Documentação" para `**/*.md`).

## Modelo de IA

O administrador global cadastra os motores (Claude Code, Copilot CLI) e os modelos de cada
um, e escolhe o padrão. A ordem de escolha numa revisão é: modelo pedido na reexecução
(admin) → modelo do repositório → modelo do perfil → padrão global.
