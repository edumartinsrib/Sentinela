import {
  Card,
  CellTitle,
  DataTable,
  EmptyState,
  ErrorState,
  Grid,
  Hero,
  Kpi,
  Legend,
  LinkButton,
  LivePill,
  MetricList,
  Page,
  RelativeTime,
  StackBar,
  StackedBarChart,
  Tag,
  formatNumber,
  pluralize,
  toneColor,
  useDocumentTitle,
} from 'broto-ui';
import { Bot, CircleCheck, Clock3, GitPullRequest, Hourglass, ShieldAlert, ShieldX } from 'lucide-react';
import { useNavigate } from 'react-router';
import { useDashboard } from '../api/queries';
import { useGlobalStreamStatus } from '../api/sse';
import type { Category, Dashboard, PullRequest } from '../api/types';
import { SeverityCounts } from '../components/SeverityCounts';
import { useTeam } from '../lib/context';
import { CATEGORY, CATEGORY_COLOR, GateBadge, SEVERITY } from '../lib/labels';

function minutes(value: number | null): string {
  if (value === null) return '—';
  if (value < 60) return `${Math.round(value)} min`;
  return `${(value / 60).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} h`;
}

export function DashboardPage() {
  const { team, base } = useTeam();
  const dash = useDashboard(team.name);
  const status = useGlobalStreamStatus();
  useDocumentTitle('Painel', 'Sentinela');

  return (
    <Page>
      <Hero
        eyebrow={team.display_name}
        title="Visão geral"
        description="Cada commit de PR passa pelos padrões do time. Sem apontamentos, a IA libera; com apontamentos, alguém que não é o autor decide."
        actions={
          <>
            <LivePill live={status === 'open'}>{status === 'open' ? 'Ao vivo' : 'Conectando…'}</LivePill>
            <LinkButton variant="hero" href={`${base}/pull-requests?gate=awaiting_approval`} icon={<GitPullRequest size={16} />}>
              Aguardando aprovação
            </LinkButton>
          </>
        }
      />
      {dash.isError && !dash.data ? (
        <Card>
          <ErrorState error={dash.error} onRetry={() => void dash.refetch()} />
        </Card>
      ) : (
        <DashboardBody data={dash.data} base={base} />
      )}
    </Page>
  );
}

function DashboardBody({ data, base }: { data: Dashboard | undefined; base: string }) {
  const navigate = useNavigate();
  const k = data?.kpis;
  const loading = !data;
  const categories = Object.entries(data?.by_category ?? {}) as [Category, number][];
  const maxRule = Math.max(1, ...(data?.top_rules ?? []).map((r) => r.count));

  return (
    <>
      <Grid layout="kpi">
        <Kpi
          variant="featured"
          icon={<Hourglass size={18} />}
          label="Aguardando aprovação"
          value={formatNumber(k?.awaiting_approval)}
          loading={loading}
          href={`${base}/pull-requests?gate=awaiting_approval`}
          foot={k ? `${formatNumber(k.reviewing)} em revisão agora` : undefined}
        />
        <Kpi
          variant={k && k.blocked > 0 ? 'danger' : 'default'}
          icon={<ShieldX size={18} />}
          label="Bloqueados"
          value={formatNumber(k?.blocked)}
          loading={loading}
          href={`${base}/pull-requests?gate=blocked`}
          foot={k ? (k.errors ? `${formatNumber(k.errors)} com falha na revisão` : 'apontamentos sem justificativa') : undefined}
        />
        <Kpi
          variant="success"
          icon={<CircleCheck size={18} />}
          label="Aprovados em 7 dias"
          value={formatNumber(k?.approved_7d)}
          loading={loading}
          foot={
            k
              ? [`${formatNumber(k.approved_by_ai_7d)} pela IA`, `${formatNumber(k.approved_7d - k.approved_by_ai_7d)} por pessoas`]
              : undefined
          }
        />
        <Kpi
          icon={<Clock3 size={18} />}
          label="Até a aprovação humana"
          value={minutes(k?.median_approval_minutes_7d ?? null)}
          loading={loading}
          foot="mediana em 7 dias"
        />
        <Kpi
          variant={k && k.merged_without_gate_30d + k.overrides_30d > 0 ? 'alert' : 'default'}
          icon={<ShieldAlert size={18} />}
          label="Merges sem gate (30 dias)"
          value={formatNumber(k?.merged_without_gate_30d)}
          loading={loading}
          foot={k ? pluralize(k.overrides_30d, 'liberação emergencial', 'liberações emergenciais') : undefined}
        />
      </Grid>

      <Grid layout="main-side">
        <div className="snt-stack">
          <Card title="Gates por dia" subtitle="Commits revisados nos últimos 14 dias, pelo resultado">
            {data && (
              <>
                <StackedBarChart
                  aria-label="Gates por dia"
                  height={200}
                  data={data.daily.map((d) => ({
                    label: d.day.slice(8, 10) + '/' + d.day.slice(5, 7),
                    values: { ai: d.approved_ai, human: d.approved_human, blocked: d.blocked, other: d.other },
                  }))}
                  series={[
                    { key: 'ai', label: 'Aprovado pela IA', color: toneColor.live },
                    { key: 'human', label: 'Aprovado por pessoa', color: toneColor.success },
                    { key: 'blocked', label: 'Bloqueado/reprovado', color: toneColor.danger },
                    { key: 'other', label: 'Em andamento/outros', color: toneColor.pending },
                  ]}
                />
                <Legend
                  items={[
                    { label: 'Aprovado pela IA', color: toneColor.live },
                    { label: 'Aprovado por pessoa', color: toneColor.success },
                    { label: 'Bloqueado/reprovado', color: toneColor.danger },
                    { label: 'Em andamento/outros', color: toneColor.pending },
                  ]}
                />
              </>
            )}
          </Card>
          <Card title="Precisam da sua aprovação" subtitle="Você tem papel de aprovador e não é o autor" flush>
            <DataTable<PullRequest>
              rows={data?.my_queue}
              loading={loading}
              getRowId={(pr) => pr.id}
              onRowClick={(pr) => navigate(`${base}/pull-requests/${pr.id}`)}
              empty={<EmptyState compact icon={<CircleCheck size={22} />} title="Nada esperando por você" />}
              columns={[
                {
                  key: 'pr',
                  header: 'Pull request',
                  cell: (pr) => (
                    <CellTitle href={`${base}/pull-requests/${pr.id}`} title={pr.title} sub={`${pr.repository.full_name} #${pr.number} · ${pr.author_login ?? ''}`} />
                  ),
                },
                { key: 'sev', header: 'Apontamentos', cell: (pr) => <SeverityCounts gate={pr.gate} /> },
                { key: 'since', header: 'Desde', cell: (pr) => <RelativeTime value={pr.gate?.updated_at} />, nowrap: true },
              ]}
            />
          </Card>
        </div>
        <div className="snt-stack">
          <Card title="Regras mais violadas" subtitle="30 dias">
            {data && data.top_rules.length === 0 ? (
              <EmptyState compact title="Sem apontamentos no período" />
            ) : (
              <MetricList
                items={(data?.top_rules ?? []).map((r) => ({
                  key: r.rule_code,
                  title: (
                    <>
                      <Tag mono variant="outline">
                        {r.rule_code}
                      </Tag>{' '}
                      {r.rule_title ?? CATEGORY[r.category]}
                    </>
                  ),
                  sub: `${SEVERITY[r.severity].label} · ${r.waived} exceção(ões) · ${r.dismissed} falso(s) positivo(s)`,
                  value: r.count,
                  progress: (r.count / maxRule) * 100,
                }))}
              />
            )}
          </Card>
          <Card title="Apontamentos por categoria" subtitle="30 dias">
            {categories.length === 0 ? (
              <EmptyState compact title="Nada no período" />
            ) : (
              <div className="snt-stack">
                <StackBar
                  segments={categories.map(([c, v]) => ({ key: c, label: CATEGORY[c], value: v, color: CATEGORY_COLOR[c] }))}
                />
                <Legend items={categories.map(([c, v]) => ({ label: CATEGORY[c], color: CATEGORY_COLOR[c], value: formatNumber(v) }))} />
              </div>
            )}
          </Card>
          <Card title="Runners">
            <div className="snt-inline">
              <Bot size={18} />
              <span>
                <strong>{formatNumber(data?.runners_online)}</strong> de {formatNumber(data?.runners_total)} online
              </span>
              <LinkButton size="sm" variant="ghost" href={`${base}/admin/runners`}>
                Ver runners
              </LinkButton>
            </div>
          </Card>
        </div>
      </Grid>

      <Card title="Atividade recente" flush>
        <DataTable<PullRequest>
          rows={data?.recent}
          loading={loading}
          getRowId={(pr) => pr.id}
          onRowClick={(pr) => navigate(`${base}/pull-requests/${pr.id}`)}
          empty={<EmptyState compact icon={<GitPullRequest size={22} />} title="Nenhum PR ainda" description="Cadastre um repositório e configure o webhook." />}
          columns={[
            {
              key: 'pr',
              header: 'Pull request',
              cell: (pr) => <CellTitle href={`${base}/pull-requests/${pr.id}`} title={pr.title} sub={`${pr.repository.full_name} #${pr.number}`} />,
            },
            { key: 'author', header: 'Autor', cell: (pr) => pr.author_login ?? '—' },
            {
              key: 'gate',
              header: 'Gate',
              cell: (pr) => (pr.gate ? <GateBadge status={pr.gate.status} /> : <Tag variant="neutral">fora do gate</Tag>),
              nowrap: true,
            },
            { key: 'updated', header: 'Atualizado', cell: (pr) => <RelativeTime value={pr.updated_at} />, nowrap: true, align: 'right' },
          ]}
        />
      </Card>
    </>
  );
}
