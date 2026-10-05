# Funcionalidades e próximos passos

## O que o Sentinela já entrega

**Padrões do time, por tipo de implementação**
- Perfis com caminhos (monorepo: cada pasta com seu padrão), contexto de arquitetura para a
  IA e regras de IA ou regex, cada uma com severidade, categoria, escopo e "como corrigir".
- Biblioteca com 32 regras e 5 modelos (API Python, React, Java/Spring, Terraform,
  containers e pipelines), importação e exportação em YAML, teste de regex no diálogo.
- Tech lead e admin do time editam; tudo auditado; cada revisão guarda a cópia dos perfis
  usados.

**Revisão automática**
- Segurança, estrutura e padrão de código, arquitetura, testes, desempenho e documentação.
- Claude Code ou Copilot CLI em modo só leitura, com o repositório inteiro disponível para
  consulta (não só o diff). O admin troca motores e modelos e escolhe o padrão, o modelo de
  cada repositório ou perfil e o modelo de uma reexecução.
- Regex instantâneas sem custo de IA; severidade sempre da regra; achados fora das regras
  limitados a média; segredos mascarados nas evidências.
- Runners escaláveis com fila no Postgres, cancelamento, drenagem e logs ao vivo.

**Gate de merge**
- Gate por commit: a IA aprova o que vem limpo; com apontamento, alguém que não é o autor
  aprova; bloqueantes exigem exceção do tech lead.
- Exceções justificadas, falsos positivos, contestação com argumento, comentários,
  reprovação, liberação emergencial com motivo.
- Herança de justificativas entre commits do mesmo PR; reexecução não "lava" um commit.
- Status obrigatório e/ou merge pela plataforma no GitHub e no GitLab; diagnóstico da
  proteção da branch; detecção de merge sem gate e de status adulterado.
- Política por repositório: humano sempre, severidade que exige humano e que bloqueia,
  número de aprovações, branches com gate, rascunhos, modo observação para adoção gradual.

**Visibilidade**
- Comentário-resumo no PR com link para o console.
- Painel do time: fila de aprovação, bloqueados, aprovações (IA × pessoas), tempo até a
  aprovação humana, regras mais violadas (com exceções e falsos positivos), categorias,
  merges sem gate, runners.
- Auditoria completa com antes e depois.

## O que vale a pena agregar

Ordenado pelo valor para quem usa e pelo esforço.

### Próximos (alto valor, esforço baixo ou médio)

1. **Comentários na linha do diff.** Publicar cada apontamento como comentário de revisão
   na linha (GitHub review comments / GitLab discussions), com a sugestão no formato
   *suggested change* quando houver. O dev vê e corrige sem sair do PR.
2. **Revisão incremental.** Num novo push, mandar para a IA só os arquivos que mudaram
   desde o último commit revisado e herdar o resto. Corta custo e tempo nos PRs com muitos
   pushes.
3. **Exceções com prazo e dívida técnica.** A exceção ganha data de validade e, se o time
   quiser, abre um item no backlog (Jira, Azure Boards, GitLab Issues) com dono. Painel de
   dívida aceita por repositório.
4. **Notificações.** Slack/Teams/e-mail: "seu PR está bloqueado (SEC-005)", "3 PRs
   aguardam sua aprovação", lembrete de PRs parados. Página "Minha fila" no console.
5. **Aprovação por área.** Aprovadores por categoria ou caminho, no estilo CODEOWNERS:
   apontamento de segurança exige alguém do grupo de segurança; mudança em `infra/**`
   exige o time de plataforma. Aprovação dupla para bloqueantes aceitos como exceção.
6. **Qualidade das regras.** Taxa de falso positivo e de contestação por regra e por
   modelo, com alerta "esta regra está gerando ruído". Ajudar o tech lead a calibrar.
7. **Exemplos nas regras.** Campos "exemplo correto" e "exemplo incorreto" na regra,
   enviados à IA (few-shot) e mostrados no apontamento. Melhora a precisão e ensina o
   padrão.

### Médio prazo

8. **Revisão antes do PR.** Comando local (`sentinela review`) ou comentário
   `/sentinela revisar` no PR rascunho, com as mesmas regras, para o dev corrigir antes de
   pedir revisão.
9. **Importar outros scanners.** Resultados SARIF de Semgrep, SonarQube, Trivy, gitleaks
   e Dependabot viram achados com a mesma regra de gate, exceção e auditoria. O Sentinela
   vira o ponto único de decisão do merge.
10. **Linha de base do repositório.** Rodar os perfis na branch principal para mapear a
    dívida existente; o gate cobra só o que o PR introduz e o painel mostra a evolução.
11. **Padrões como código (GitOps).** Perfis versionados num repositório de padrões e
    sincronizados; mudança de padrão também passa por PR. Herança organização → time →
    repositório.
12. **Contexto de arquitetura do repositório.** ADRs, `docs/arquitetura.md` e contratos
    (OpenAPI) entram como referência da IA, além das instruções do perfil.
13. **Custos e orçamento.** Custo por revisão, por repositório e por time; teto mensal por
    time com alerta; troca automática para um modelo mais barato em PRs pequenos.
14. **Comparação de modelos.** Modo sombra: um segundo modelo revisa em paralelo sem afetar
    o gate, para comparar precisão e custo antes de trocar o padrão.
15. **Relatório de conformidade.** Exportação (CSV/PDF) de merges, exceções, liberações
    emergenciais e aprovadores por período, para auditoria interna e regulatória.

### Explorar

16. **Correção assistida.** Botão "propor correção" que gera um commit ou PR de correção
    num modo separado com escrita, sempre revisado pelo próprio gate.
17. **Conversa sobre o apontamento.** Perguntar "por que isso é um problema aqui?" ou
    contestar com ajuda da IA, dentro do contexto do achado.
18. **Saúde do PR.** Regras estruturais além do código: PR grande demais (sugerir dividir),
    descrição vazia, PR sem item de backlog vinculado, dependência nova fora da lista de
    permitidas, mudança de licença.
19. **Outros provedores.** Azure DevOps e Bitbucket (a camada de provedor já isola GitHub e
    GitLab).
20. **Eventos para fora.** Webhooks de saída e envio de eventos de auditoria para o SIEM.
21. **Janelas de congelamento.** Períodos em que o merge exige aprovação adicional
    (fechamento de mês, release), com exceção auditada.
