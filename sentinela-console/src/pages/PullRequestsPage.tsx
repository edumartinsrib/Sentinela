import {
  Card,
  CellTitle,
  Chip,
  DataTable,
  EmptyState,
  ErrorState,
  FilterBar,
  Page,
  PageHeader,
  Pagination,
  RelativeTime,
  SearchInput,
  Segmented,
  Select,
  Tag,
  useDebounced,
  useDocumentTitle,
} from 'broto-ui';
import { GitPullRequest } from 'lucide-react';
import { useNavigate, useSearchParams } from 'react-router';
import { usePullRequests, useRepositories } from '../api/queries';
import type { GateStatus, PullRequest } from '../api/types';
import { SeverityCounts } from '../components/SeverityCounts';
import { useTeam } from '../lib/context';
import { GateBadge } from '../lib/labels';

const GATE_FILTERS: { value: GateStatus; label: string; tone: 'pending' | 'danger' | 'live' | 'success' | 'orange' }[] = [
  { value: 'awaiting_approval', label: 'Aguardando aprovação', tone: 'pending' },
  { value: 'blocked', label: 'Bloqueados', tone: 'danger' },
  { value: 'reviewing', label: 'Em revisão', tone: 'live' },
  { value: 'approved', label: 'Aprovados', tone: 'success' },
  { value: 'error', label: 'Com falha', tone: 'orange' },
];
const LIMIT = 25;

export function PullRequestsPage() {
  const { team, base } = useTeam();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  useDocumentTitle('Pull requests', 'Sentinela');
  const state = params.get('state') ?? 'open';
  const gates = (params.get('gate') ?? '').split(',').filter(Boolean);
  const repository = params.get('repo') ?? '';
  const q = params.get('q') ?? '';
  const offset = Number(params.get('offset') ?? 0);
  const search = useDebounced(q, 300);
  const repos = useRepositories(team.name);
  const prs = usePullRequests(team.name, {
    state,
    gate: gates.length ? gates : undefined,
    repository: repository || undefined,
    q: search || undefined,
    limit: LIMIT,
    offset,
  });

  const update = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v) next.set(k, v);
      else next.delete(k);
    }
    if (!('offset' in patch)) next.delete('offset');
    setParams(next, { replace: true });
  };
  const toggleGate = (value: string) => {
    const set = new Set(gates);
    if (set.has(value)) set.delete(value);
    else set.add(value);
    update({ gate: [...set].join(',') || null });
  };

  return (
    <Page>
      <PageHeader
        title="Pull requests"
        description="PRs dos repositórios do time, com a situação do gate do commit mais recente."
      />
      <Card flush>
        <FilterBar>
          <Segmented
            aria-label="Situação do PR"
            value={state}
            onChange={(v) => update({ state: v === 'open' ? null : v })}
            options={[
              { value: 'open', label: 'Abertos' },
              { value: 'merged', label: 'Com merge' },
              { value: 'closed', label: 'Fechados' },
              { value: 'all', label: 'Todos' },
            ]}
          />
          <SearchInput
            placeholder="Título, repositório, branch, autor ou #número"
            value={q}
            onChange={(e) => update({ q: e.target.value || null })}
            aria-label="Buscar"
            style={{ minWidth: 260 }}
          />
          <Select
            aria-label="Repositório"
            value={repository}
            onChange={(e) => update({ repo: e.target.value || null })}
            controlSize="sm"
          >
            <option value="">Todos os repositórios</option>
            {(repos.data ?? []).map((r) => (
              <option key={r.id} value={r.id}>
                {r.full_name}
              </option>
            ))}
          </Select>
        </FilterBar>
        <FilterBar>
          {GATE_FILTERS.map((g) => (
            <Chip key={g.value} tone={g.tone} pressed={gates.includes(g.value)} onPressedChange={() => toggleGate(g.value)}>
              {g.label}
            </Chip>
          ))}
        </FilterBar>
        {prs.isError && !prs.data ? (
          <ErrorState error={prs.error} onRetry={() => void prs.refetch()} />
        ) : (
          <DataTable<PullRequest>
            aria-label="Pull requests"
            rows={prs.data?.items}
            loading={prs.isLoading}
            getRowId={(pr) => pr.id}
            onRowClick={(pr) => navigate(`${base}/pull-requests/${pr.id}`)}
            empty={
              <EmptyState
                compact
                icon={<GitPullRequest size={22} />}
                title="Nenhum pull request"
                description="Os PRs aparecem aqui quando o GitHub/GitLab avisa o Sentinela pelo webhook (ou numa sincronização)."
              />
            }
            columns={[
              {
                key: 'pr',
                header: 'Pull request',
                cell: (pr) => (
                  <CellTitle
                    href={`${base}/pull-requests/${pr.id}`}
                    title={pr.title}
                    sub={
                      <>
                        {pr.repository.full_name} #{pr.number}
                        {pr.draft ? ' · rascunho' : ''}
                      </>
                    }
                  />
                ),
              },
              { key: 'author', header: 'Autor', cell: (pr) => pr.author_login ?? '—', nowrap: true },
              {
                key: 'branch',
                header: 'Destino',
                cell: (pr) => <Tag mono>{pr.target_branch}</Tag>,
              },
              {
                key: 'gate',
                header: 'Gate',
                cell: (pr) =>
                  pr.gate ? (
                    <GateBadge status={pr.gate.status} />
                  ) : pr.state === 'open' ? (
                    <Tag variant="neutral">fora do gate</Tag>
                  ) : (
                    <Tag variant="neutral">{pr.state === 'merged' ? 'merge feito' : 'fechado'}</Tag>
                  ),
                nowrap: true,
              },
              { key: 'findings', header: 'Em aberto', cell: (pr) => <SeverityCounts gate={pr.gate} /> },
              {
                key: 'updated',
                header: 'Atualizado',
                cell: (pr) => <RelativeTime value={pr.updated_at} />,
                nowrap: true,
                align: 'right',
              },
            ]}
            footer={
              prs.data && prs.data.total > LIMIT ? (
                <Pagination
                  total={prs.data.total}
                  limit={LIMIT}
                  offset={offset}
                  noun="pull requests"
                  onChange={(o) => update({ offset: o ? String(o) : null })}
                />
              ) : undefined
            }
          />
        )}
      </Card>
    </Page>
  );
}
