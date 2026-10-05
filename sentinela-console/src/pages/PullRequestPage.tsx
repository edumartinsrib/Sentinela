import { useQueryClient } from '@tanstack/react-query';
import {
  Badge,
  Button,
  Callout,
  Card,
  Chip,
  DataTable,
  Dialog,
  Duration,
  EmptyState,
  ErrorState,
  EventList,
  Field,
  FilterBar,
  Grid,
  KeyValue,
  LogViewer,
  Menu,
  MetaItem,
  Page,
  PageHeader,
  PageLoading,
  RelativeTime,
  Select,
  Stepper,
  type Step,
  TabPanel,
  Tabs,
  Tag,
  formatDateTime,
  formatNumber,
  toast,
  useConfirm,
  useDocumentTitle,
} from 'broto-ui';
import {
  CircleCheck,
  CircleX,
  ExternalLink,
  GitBranch,
  GitCommitHorizontal,
  GitMerge,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  User,
} from 'lucide-react';
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { useParams } from 'react-router';
import { useModels, usePrActions, usePullRequest, useReviewLogs } from '../api/queries';
import { openStream } from '../api/sse';
import type { Finding, PullRequestDetail, Review, Severity } from '../api/types';
import { FindingCard } from '../components/FindingCard';
import { useTeam } from '../lib/context';
import {
  APPROVAL_MODE,
  ENGINE_LABEL,
  GateBadge,
  PHASES,
  ReviewBadge,
  SEVERITY,
  SEVERITY_ORDER,
  shortSha,
} from '../lib/labels';

type TabId = 'findings' | 'review' | 'history' | 'description';
type FindingFilter = 'open' | 'resolved' | 'all';

export function PullRequestPage() {
  const { id = '' } = useParams();
  const { team, base } = useTeam();
  const query = usePullRequest(team.name, id);
  useDocumentTitle(query.data ? `#${query.data.number} ${query.data.title}` : 'Pull request', 'Sentinela');

  if (query.isLoading) return <PageLoading label="Carregando o pull request…" />;
  if (query.isError || !query.data) {
    return (
      <Page>
        <Card>
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        </Card>
      </Page>
    );
  }
  return <PullRequestView pr={query.data} base={base} team={team.name} />;
}

function PullRequestView({ pr, base, team }: { pr: PullRequestDetail; base: string; team: string }) {
  const [tab, setTab] = useState<TabId>('findings');
  const gate = pr.current_gate;
  const review = pr.review;
  const actions = usePrActions(team, pr.id);
  const confirm = useConfirm();
  const [rerunOpen, setRerunOpen] = useState(false);
  const openCount = pr.findings.filter((f) => f.status === 'open' || f.status === 'disputed').length;

  const approve = async () => {
    const r = await confirm({
      title: 'Aprovar o gate deste commit?',
      description: gate?.human_required
        ? `Você assume a revisão humana de ${pr.findings.length} apontamento(s). O status no ${providerName(pr)} fica verde.`
        : 'O status no provedor fica verde.',
      confirmLabel: 'Aprovar',
      tone: 'primary',
      reason: { label: 'Comentário (opcional)' },
    });
    if (!r.confirmed) return;
    await actions.approve.mutateAsync(r.reason || null);
    toast.success('Gate aprovado', `Commit ${shortSha(gate?.head_sha)} liberado.`);
  };
  const reject = async () => {
    const r = await confirm({
      title: 'Reprovar este commit?',
      description: 'O status fica vermelho até você aprovar ou um novo commit chegar.',
      confirmLabel: 'Reprovar',
      reason: { label: 'O que precisa mudar?', required: true },
    });
    if (!r.confirmed || !r.reason) return;
    await actions.reject.mutateAsync(r.reason);
    toast.info('Gate reprovado');
  };
  const override = async () => {
    const r = await confirm({
      title: 'Liberar em caráter emergencial?',
      description:
        'Ignora apontamentos e aprovações. Use só em incidente; a liberação fica destacada na auditoria e no painel.',
      confirmLabel: 'Liberar mesmo assim',
      reason: { label: 'Motivo (incidente, chamado, responsável)', required: true },
    });
    if (!r.confirmed || !r.reason) return;
    await actions.override.mutateAsync(r.reason);
    toast.warning('Gate liberado em caráter emergencial');
  };
  const merge = async () => {
    const r = await confirm({
      title: `Fazer o merge de #${pr.number}?`,
      description: `${pr.source_branch} → ${pr.target_branch}, commit ${shortSha(gate?.head_sha)}. O ${providerName(pr)} confere de novo o status antes de aceitar.`,
      confirmLabel: 'Fazer merge',
      tone: 'primary',
    });
    if (!r.confirmed) return;
    await actions.merge.mutateAsync(null);
    toast.success('Merge realizado');
  };
  const onFinding = async (f: Finding, action: string, reason: string) => {
    await actions.finding.mutateAsync({ id: f.id, action, reason });
  };

  const headerActions = (
    <>
      {pr.permissions.approve ? (
        <Button variant="primary" icon={<CircleCheck size={16} />} onClick={() => void approve()} loading={actions.approve.isPending}>
          Aprovar
        </Button>
      ) : (
        gate &&
        gate.status !== 'approved' &&
        gate.status !== 'merged' && (
          <Button variant="primary" icon={<CircleCheck size={16} />} disabled title={pr.permissions.approve_reason ?? ''}>
            Aprovar
          </Button>
        )
      )}
      {pr.merge_via_platform && pr.state === 'open' && (
        <Button
          variant={pr.permissions.merge ? 'primary' : 'secondary'}
          icon={<GitMerge size={16} />}
          disabled={!pr.permissions.merge}
          title={pr.permissions.merge_reason ?? ''}
          onClick={() => void merge()}
          loading={actions.merge.isPending}
        >
          Fazer merge
        </Button>
      )}
      <Menu
        label="Mais ações"
        items={[
          {
            label: 'Reprovar commit',
            icon: <CircleX size={16} />,
            onSelect: () => void reject(),
            hidden: !pr.permissions.reject,
          },
          {
            label: 'Revisar de novo',
            icon: <RefreshCw size={16} />,
            onSelect: () => setRerunOpen(true),
            hidden: !pr.permissions.rerun,
          },
          {
            label: 'Cancelar revisão em andamento',
            icon: <CircleX size={16} />,
            onSelect: () => review && void actions.cancelReview.mutateAsync(review.id),
            hidden: !(review && (review.status === 'queued' || review.status === 'running') && pr.permissions.rerun),
          },
          { label: `Abrir no ${providerName(pr)}`, icon: <ExternalLink size={16} />, href: pr.web_url ?? '#', external: true, hidden: !pr.web_url },
          'separator',
          {
            label: 'Liberar em caráter emergencial',
            icon: <ShieldAlert size={16} />,
            danger: true,
            onSelect: () => void override(),
            hidden: !pr.permissions.override,
          },
        ]}
      />
    </>
  );

  return (
    <Page>
      <PageHeader
        crumbs={[
          { label: 'Pull requests', href: `${base}/pull-requests` },
          { label: `${pr.repository.full_name} #${pr.number}` },
        ]}
        title={pr.title}
        badge={gate ? <GateBadge status={gate.status} /> : <Badge tone="neutral">Fora do gate</Badge>}
        actions={headerActions}
        meta={
          <>
            <MetaItem icon={<User size={14} />}>{pr.author_login ?? '—'}</MetaItem>
            <MetaItem icon={<GitBranch size={14} />}>
              {pr.source_branch} → {pr.target_branch}
            </MetaItem>
            <MetaItem icon={<GitCommitHorizontal size={14} />}>
              <span className="snt-mono">{shortSha(gate?.head_sha ?? pr.head_sha)}</span>
            </MetaItem>
            {pr.state !== 'open' && !(pr.state === 'merged' && gate?.status === 'merged') && (
              <MetaItem>
                <Tag variant={pr.state === 'merged' ? 'green' : 'neutral'}>{pr.state === 'merged' ? 'merge feito' : 'fechado'}</Tag>
              </MetaItem>
            )}
            {pr.draft && (
              <MetaItem>
                <Tag>rascunho</Tag>
              </MetaItem>
            )}
          </>
        }
      />

      {pr.merged_without_gate && (
        <Callout tone="danger" title="Merge sem o gate liberado">
          O merge foi feito no {providerName(pr)} com o gate em situação diferente de aprovado
          {pr.merged_by ? ` (por ${pr.merged_by})` : ''}. Verifique a proteção da branch e a auditoria.
        </Callout>
      )}
      {pr.enforcement === 'observe' && (
        <Callout tone="info" title="Repositório em modo observação">
          O Sentinela revisa e mostra tudo, mas publica sucesso no status para não travar o merge.
        </Callout>
      )}
      {!pr.gated && (
        <Callout tone="info" title="Este PR não passa pelo gate">
          A branch de destino {pr.target_branch} não está entre as branches protegidas pelo Sentinela neste repositório.
        </Callout>
      )}

      {gate && <GateCard pr={pr} />}

      <Card bare>
        <Tabs<TabId>
          idPrefix="pr"
          inset
          value={tab}
          onChange={setTab}
          aria-label="Detalhes do pull request"
          tabs={[
            { id: 'findings', label: 'Apontamentos', count: openCount || undefined },
            { id: 'review', label: 'Revisão automática' },
            { id: 'history', label: 'Histórico', count: pr.history.length > 1 ? pr.history.length : undefined },
            { id: 'description', label: 'Descrição' },
          ]}
        />
        <div style={{ padding: 16 }}>
          <TabPanel id="findings" idPrefix="pr" flush>
            {tab === 'findings' && (
              <FindingsPanel pr={pr} onAction={onFinding} busy={actions.finding.isPending} />
            )}
          </TabPanel>
          <TabPanel id="review" idPrefix="pr" flush>
            {tab === 'review' && (review ? <ReviewPanel review={review} team={team} /> : <EmptyState compact title="Sem revisão" />)}
          </TabPanel>
          <TabPanel id="history" idPrefix="pr" flush>
            {tab === 'history' && <HistoryPanel pr={pr} />}
          </TabPanel>
          <TabPanel id="description" idPrefix="pr" flush>
            {tab === 'description' &&
              (pr.description ? (
                <div style={{ whiteSpace: 'pre-wrap' }}>{pr.description}</div>
              ) : (
                <EmptyState compact title="O PR não tem descrição" />
              ))}
          </TabPanel>
        </div>
      </Card>

      <RerunDialog
        open={rerunOpen}
        onClose={() => setRerunOpen(false)}
        loading={actions.rerun.isPending}
        onConfirm={async (modelId) => {
          await actions.rerun.mutateAsync(modelId);
          setRerunOpen(false);
          setTab('review');
          toast.success('Revisão enfileirada');
        }}
      />
    </Page>
  );
}

function providerName(pr: { repository: { provider: string } }) {
  return pr.repository.provider === 'gitlab' ? 'GitLab' : 'GitHub';
}

// ----------------------------------------------------------------------------- gate
function GateCard({ pr }: { pr: PullRequestDetail }) {
  const gate = pr.current_gate!;
  const policy = gate.policy as { approval_mode?: keyof typeof APPROVAL_MODE; block_severity?: Severity; human_min_severity?: Severity };
  const publishedTone = gate.published_state === 'success' ? 'success' : gate.published_state === 'pending' ? 'pending' : 'danger';
  const guidance = (() => {
    switch (gate.status) {
      case 'blocked':
        return `Há ${gate.blocking} apontamento(s) de severidade ${SEVERITY[policy.block_severity ?? 'high'].label.toLowerCase()} ou maior. Corrija no código (novo commit) ou peça ao tech lead para aceitar como exceção com justificativa.`;
      case 'awaiting_approval':
        return gate.human_required
          ? 'A revisão encontrou apontamentos: alguém que não seja o autor precisa aprovar este commit.'
          : 'Aguardando aprovação.';
      case 'approved':
        return gate.human_required
          ? `Aprovado por ${gate.approved_by.join(', ')}. O merge está liberado.`
          : 'A revisão automática não encontrou divergências: a IA aprovou e o merge está liberado.';
      case 'reviewing':
        return 'A revisão automática está em andamento. O status no provedor fica pendente até o fim.';
      case 'error':
        return 'A revisão automática falhou. Veja o log na aba Revisão automática e execute de novo.';
      case 'rejected':
        return `Reprovado por ${gate.rejected_by.join(', ')}. Um novo commit abre um gate novo.`;
      case 'overridden':
        return `Liberado em caráter emergencial por ${gate.override_by}: ${gate.override_reason}`;
      default:
        return gate.description;
    }
  })();

  return (
    <Card
      box
      corner
      title="Gate deste commit"
      subtitle={gate.description}
      actions={
        gate.published_state ? (
          <Badge tone={publishedTone} size="sm" title={gate.published_description ?? ''}>
            {pr.status_check ? 'Status publicado' : 'Comentário publicado'}: {gate.published_state}
          </Badge>
        ) : undefined
      }
    >
      <div className="snt-stack">
        <div className="snt-gate-summary">
          <Figure value={formatNumber(gate.unresolved)} label="apontamentos em aberto" />
          <Figure value={formatNumber(gate.blocking)} label="bloqueiam o merge" />
          <Figure
            value={gate.human_required ? `${gate.approvals}/${gate.approvals_required}` : 'IA'}
            label={gate.human_required ? 'aprovações humanas' : 'aprovação automática'}
          />
          <Figure value={policy.approval_mode === 'always_human' ? 'Sempre' : 'Com apontamento'} label="exige humano" />
        </div>
        <Callout
          tone={
            gate.status === 'merged' && pr.merged_without_gate
              ? 'warning'
              : gate.status === 'approved' || gate.status === 'merged'
                ? 'success'
                : gate.status === 'blocked' || gate.status === 'rejected' || gate.status === 'error'
                  ? 'danger'
                  : gate.status === 'overridden'
                    ? 'warning'
                    : 'info'
          }
        >
          {gate.status === 'merged' && pr.merged_without_gate ? 'Merge feito direto no provedor, sem passar pelo gate.' : guidance}
        </Callout>
        {pr.permissions.is_author && gate.status === 'awaiting_approval' && (
          <Callout tone="info">Você é o autor deste PR: a aprovação precisa vir de outra pessoa.</Callout>
        )}
        {gate.publish_error && (
          <Callout tone="warning" title="Falha ao publicar no provedor">
            {gate.publish_error}. O Sentinela tenta de novo automaticamente.
          </Callout>
        )}
      </div>
    </Card>
  );
}

function Figure({ value, label }: { value: ReactNode; label: string }) {
  return (
    <div className="snt-figure">
      <span className="snt-figure-value">{value}</span>
      <span className="snt-figure-label">{label}</span>
    </div>
  );
}

// ----------------------------------------------------------------------------- apontamentos
const isOpenFinding = (f: Finding) => f.status === 'open' || f.status === 'disputed';

function FindingsPanel({
  pr,
  onAction,
  busy,
}: {
  pr: PullRequestDetail;
  onAction: (f: Finding, action: string, reason: string) => Promise<void>;
  busy: boolean;
}) {
  // Sem nada em aberto (tudo tratado), abre direto em "Todos".
  const [filter, setFilter] = useState<FindingFilter>(() => (pr.findings.some(isOpenFinding) ? 'open' : 'all'));
  const [severity, setSeverity] = useState<Severity | null>(null);
  const review = pr.review;
  const inStatus = useMemo(
    () =>
      pr.findings.filter((f) => {
        if (filter === 'open') return isOpenFinding(f);
        if (filter === 'resolved') return !isOpenFinding(f);
        return true;
      }),
    [pr.findings, filter],
  );
  // As contagens por severidade seguem o filtro de situação escolhido.
  const counts = useMemo(() => {
    const out: Partial<Record<Severity, number>> = {};
    for (const f of inStatus) out[f.severity] = (out[f.severity] ?? 0) + 1;
    return out;
  }, [inStatus]);
  const shown = inStatus.filter((f) => !severity || f.severity === severity);

  if (!review || review.status === 'queued' || review.status === 'running') {
    return (
      <EmptyState
        compact
        icon={<Sparkles size={22} />}
        title="Revisão em andamento"
        description={review?.phase ? PHASES[review.phase] ?? review.phase : 'Aguardando um runner livre.'}
      />
    );
  }
  if (review.status === 'failed') {
    return <ErrorState compact title="A revisão falhou" description={review.error ?? undefined} />;
  }
  if (pr.findings.length === 0) {
    return (
      <EmptyState
        compact
        icon={<CircleCheck size={22} />}
        title="Nenhuma divergência"
        description="O código segue os padrões dos perfis aplicados."
      />
    );
  }
  return (
    <div className="snt-stack">
      <FilterBar>
        <Chip pressed={filter === 'open'} onPressedChange={() => setFilter('open')}>
          Em aberto
        </Chip>
        <Chip pressed={filter === 'resolved'} onPressedChange={() => setFilter('resolved')}>
          Tratados
        </Chip>
        <Chip pressed={filter === 'all'} onPressedChange={() => setFilter('all')}>
          Todos
        </Chip>
        <span style={{ width: 12 }} />
        {SEVERITY_ORDER.filter((s) => counts[s]).map((s) => (
          <Chip
            key={s}
            tone={SEVERITY[s].tone}
            pressed={severity === s}
            count={counts[s]}
            onPressedChange={(p) => setSeverity(p ? s : null)}
          >
            {SEVERITY[s].label}
          </Chip>
        ))}
      </FilterBar>
      {shown.length === 0 ? (
        <EmptyState compact title="Nada neste filtro" />
      ) : (
        shown.map((f) => <FindingCard key={f.id} finding={f} permissions={pr.permissions} onAction={onAction} busy={busy} />)
      )}
    </div>
  );
}

// ----------------------------------------------------------------------------- revisão
const PHASE_ORDER = ['claimed', 'cloning', 'diff', 'patterns', 'ai', 'reporting'];

function reviewSteps(review: Review): Step[] {
  const done = review.status === 'completed';
  const failed = review.status === 'failed' || review.status === 'canceled';
  const current = review.phase ? PHASE_ORDER.indexOf(review.phase) : review.status === 'queued' ? -1 : 0;
  return [
    { key: 'queued', label: 'Na fila', state: review.status === 'queued' ? 'current' : 'done', meta: formatDateTime(review.created_at, { seconds: true }) },
    ...PHASE_ORDER.slice(1).map((p, i): Step => {
      const idx = i + 1;
      let state: Step['state'] = 'pending';
      if (done) state = 'done';
      else if (failed) state = idx <= Math.max(current, 1) ? (idx === Math.max(current, 1) ? 'failed' : 'done') : 'halted';
      else if (review.status === 'running') state = idx < current ? 'done' : idx === current ? 'current' : 'pending';
      return { key: p, label: PHASES[p], state };
    }),
  ];
}

function ReviewPanel({ review, team }: { review: Review; team: string }) {
  const qc = useQueryClient();
  const logs = useReviewLogs(team, review.id);
  const refetchLogs = logs.refetch;
  const [live, setLive] = useState<{ ts: string; stream: string; text: string }[] | null>(null);
  const running = review.status === 'queued' || review.status === 'running';

  useEffect(() => {
    if (!running) {
      setLive(null);
      return;
    }
    const close = openStream(`/teams/${encodeURIComponent(team)}/reviews/${review.id}/stream`, {
      onEvent: (type, data) => {
        const d = data as { lines?: { ts: string; stream: string; text: string }[] };
        if (type === 'snapshot') setLive(d.lines ?? []);
        else if (type === 'log' && d.lines) setLive((prev) => [...(prev ?? []), ...d.lines!]);
        else if (type === 'status' || type === 'phase') {
          void qc.invalidateQueries({ queryKey: ['pr', team, review.pull_request_id] });
          if (type === 'status') void refetchLogs();
        }
      },
    });
    return close;
  }, [running, review.id, review.pull_request_id, team, qc, refetchLogs]);

  const stats = review.stats as Record<string, number | string | boolean | null | undefined>;
  const lines = (live ?? logs.data?.lines ?? []).map((l) => ({
    ts: l.ts,
    stream: l.stream,
    text: l.text,
    level: l.stream === 'stderr' ? 'warn' : undefined,
  }));

  return (
    <div className="snt-stack">
      <div className="snt-between">
        <div className="snt-inline">
          <ReviewBadge status={review.status} />
          <span className="snt-muted snt-small">
            {ENGINE_LABEL[review.engine_kind] ?? review.engine_kind} · {review.model_label || review.model || 'modelo padrão'}
          </span>
        </div>
        <span className="snt-muted snt-small">
          tentativa {review.attempt} · <Duration start={review.started_at} end={review.finished_at} fallback="—" />
        </span>
      </div>
      <Stepper steps={reviewSteps(review)} />
      {review.error && (
        <Callout tone="danger" title="Erro da revisão">
          <span style={{ whiteSpace: 'pre-wrap' }}>{review.error}</span>
        </Callout>
      )}
      {review.summary && (
        <Card title="Resumo da IA" box>
          <div style={{ whiteSpace: 'pre-wrap' }}>{review.summary}</div>
        </Card>
      )}
      <Grid layout="2">
        <Card title="Execução">
          <KeyValue
            items={[
              ['Runner', review.runner_name ?? '—'],
              ['Disparada por', review.requested_by ? `${review.requested_by} (${review.trigger})` : review.trigger],
              ['Início', review.started_at ? formatDateTime(review.started_at, { seconds: true }) : '—'],
              ['Perfis', review.profiles.join(', ') || '—'],
              ['Regras', formatNumber(review.rules)],
            ]}
          />
        </Card>
        <Card title="Números">
          <KeyValue
            items={[
              ['Arquivos alterados', stats.files_changed != null ? `${stats.files_changed} (+${stats.additions ?? 0} −${stats.deletions ?? 0})` : '—'],
              ['Enviados à IA', stats.files_reviewed_ai != null ? String(stats.files_reviewed_ai) : '—'],
              ['Ocorrências de regras de padrão', stats.pattern_hits != null ? String(stats.pattern_hits) : '—'],
              { label: 'Custo estimado da IA', value: `US$ ${Number(stats.cost_usd ?? 0).toFixed(4)}`, hidden: stats.cost_usd == null },
              { label: 'Turnos da IA', value: String(stats.turns ?? ''), hidden: stats.turns == null },
              { label: 'Diff truncado', value: 'sim (a IA leu o diff completo em arquivo)', hidden: !stats.diff_truncated },
            ]}
          />
        </Card>
      </Grid>
      <LogViewer
        title="Log da revisão"
        live={running}
        lines={lines}
        loading={logs.isLoading && !live}
        streams={[
          { id: 'system', label: 'runner' },
          { id: 'stderr', label: 'stderr' },
          { id: 'stdout', label: 'stdout' },
        ]}
        filterable
        emptyText={running ? 'Aguardando o runner…' : 'Sem linhas de log (o buffer expira após alguns dias).'}
        style={{ maxHeight: 420 }}
      />
    </div>
  );
}

// ----------------------------------------------------------------------------- histórico
function HistoryPanel({ pr }: { pr: PullRequestDetail }) {
  return (
    <div className="snt-stack">
      <Card title="Commits revisados" flush>
        <DataTable
          rows={pr.history}
          getRowId={(h) => h.gate.id}
          columns={[
            { key: 'sha', header: 'Commit', cell: (h) => <span className="snt-mono">{shortSha(h.gate.head_sha)}</span> },
            { key: 'gate', header: 'Gate', cell: (h) => <GateBadge status={h.gate.status} size="sm" /> },
            {
              key: 'review',
              header: 'Revisão',
              cell: (h) => (h.review ? <ReviewBadge status={h.review.status} size="sm" /> : '—'),
            },
            {
              key: 'findings',
              header: 'Apontamentos',
              cell: (h) => `${h.gate.findings_total} (${h.gate.findings_open} em aberto)`,
            },
            { key: 'when', header: 'Quando', cell: (h) => <RelativeTime value={h.gate.created_at} />, nowrap: true },
          ]}
        />
      </Card>
      <EventList
        summary={`Decisões neste commit (${pr.decisions.length})`}
        defaultOpen
        items={pr.decisions.map((d) => ({
          key: d.id,
          time: formatDateTime(d.created_at),
          title: (
            <>
              <strong>{d.display_name || d.username}</strong> {d.decision === 'approve' ? 'aprovou' : 'reprovou'}
              {!d.current && <span className="snt-muted"> (antes da última revisão; não vale mais)</span>}
            </>
          ),
          detail: d.comment ?? undefined,
        }))}
      />
    </div>
  );
}

// ----------------------------------------------------------------------------- reexecutar
function RerunDialog({
  open,
  onClose,
  onConfirm,
  loading,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: (modelId: string | null) => Promise<void>;
  loading: boolean;
}) {
  const { can } = useTeam();
  const admin = can('global.admin');
  const models = useModels();
  const [modelId, setModelId] = useState('');
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Revisar este commit de novo?"
      description="Use quando os padrões mudaram ou a revisão falhou. As aprovações deste commit deixam de valer."
      onSubmit={() => void onConfirm(modelId || null)}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit" variant="primary" loading={loading} icon={<RefreshCw size={16} />}>
            Revisar de novo
          </Button>
        </>
      }
    >
      {admin ? (
        <Field label="Modelo" hint="Só administradores escolhem outro modelo para uma reexecução.">
          <Select value={modelId} onChange={(e) => setModelId(e.target.value)}>
            <option value="">O configurado para o repositório</option>
            {(models.data ?? [])
              .filter((m) => m.enabled)
              .map((m) => (
                <option key={m.id} value={m.id}>
                  {m.engine_name} · {m.label}
                </option>
              ))}
          </Select>
        </Field>
      ) : (
        <p className="snt-muted">A revisão usa o modelo configurado pelo administrador.</p>
      )}
    </Dialog>
  );
}
