# sentinela-core

Contratos compartilhados entre a API e o runner. Não acessa banco nem rede.

| Módulo | O que tem |
| --- | --- |
| `enums` | Papéis, severidades, categorias, estados de revisão, achado e gate, modos do gate |
| `paths` | Globs no estilo `.gitignore` (`src/**/*.py`, `*.{ts,tsx}`, `!gerado/**`) |
| `diff` | Leitura do diff unificado do git (arquivos, hunks, linhas adicionadas com número) |
| `rules` | `ProfileSpec` / `RuleSpec` (formato do YAML de import/export) e as regras por regex |
| `findings` | Formato de resposta da IA (JSON Schema), leitura tolerante e normalização dos achados |
| `prompt` | Prompt de revisão (sistema + usuário) com as regras de IA dos perfis aplicados |
| `gate` | Regra do gate: IA aprova sem apontamentos; com apontamentos, exige humano |

A severidade e a categoria de um achado vêm sempre da regra cadastrada. A IA só escolhe
severidade em achados fora das regras (`GERAL`), limitada a **Média**: quem decide o que
bloqueia é o padrão do time.

```bash
uv run pytest sentinela-core/tests
```
