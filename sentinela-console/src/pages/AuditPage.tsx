import {
  Card,
  DataTable,
  EmptyState,
  ErrorState,
  FilterBar,
  JsonView,
  Page,
  PageHeader,
  Pagination,
  SearchInput,
  Select,
  Tag,
  formatDateTime,
  useDebounced,
  useDocumentTitle,
} from 'broto-ui';
import { ChevronDown, ChevronRight, ScrollText } from 'lucide-react';
import { useState } from 'react';
import { useAudit } from '../api/queries';
import type { AuditEntry } from '../api/types';
import { useTeam } from '../lib/context';

const ACTIONS: [string, string][] = [
  ['', 'Todas as ações'],
  ['gate.', 'Gate (aprovação, reprovação, emergência, adulteração)'],
  ['finding.', 'Apontamentos (exceção, falso positivo, contestação)'],
  ['pull_request.', 'Merge (inclusive sem gate)'],
  ['profile.', 'Perfis'],
  ['rule.', 'Regras'],
  ['repository.', 'Repositórios'],
  ['review.', 'Revisões'],
  ['role.', 'Papéis'],
];
const LIMIT = 50;

export function AuditPage() {
  const { team } = useTeam();
  const [action, setAction] = useState('');
  const [actor, setActor] = useState('');
  const [offset, setOffset] = useState(0);
  // Antes/depois só aparecem na linha que a pessoa abrir.
  const [expanded, setExpanded] = useState<Set<number>>(() => new Set());
  const toggle = (id: number) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const hasChange = (a: AuditEntry) => Boolean(a.before || a.after);
  const debouncedActor = useDebounced(actor, 300);
  const audit = useAudit(team.name, { action: action || undefined, actor: debouncedActor || undefined, limit: LIMIT, offset });
  useDocumentTitle('Auditoria', 'Sentinela');

  return (
    <Page>
      <PageHeader
        title="Auditoria"
        description="Toda escrita do time fica registrada: quem aceitou exceções, quem aprovou, liberações emergenciais, merges sem gate e mudanças de padrão."
      />
      <Card flush>
        <FilterBar>
          <Select controlSize="sm" value={action} onChange={(e) => (setAction(e.target.value), setOffset(0))} aria-label="Ação">
            {ACTIONS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </Select>
          <SearchInput placeholder="Usuário exato" value={actor} onChange={(e) => (setActor(e.target.value), setOffset(0))} aria-label="Usuário" />
        </FilterBar>
        {audit.isError ? (
          <ErrorState error={audit.error} onRetry={() => void audit.refetch()} />
        ) : (
          <DataTable<AuditEntry>
            rows={audit.data?.items}
            loading={audit.isLoading}
            getRowId={(a) => String(a.id)}
            empty={<EmptyState compact icon={<ScrollText size={22} />} title="Nenhum registro" />}
            onRowClick={(a) => hasChange(a) && toggle(a.id)}
            renderExpanded={(a) =>
              expanded.has(a.id) && hasChange(a) ? (
                <div className="snt-audit-change">
                  {a.before && (
                    <div>
                      <div className="snt-small snt-muted">Antes</div>
                      <JsonView value={a.before} />
                    </div>
                  )}
                  {a.after && (
                    <div>
                      <div className="snt-small snt-muted">Depois</div>
                      <JsonView value={a.after} />
                    </div>
                  )}
                </div>
              ) : null
            }
            columns={[
              {
                key: 'open',
                header: '',
                cell: (a) =>
                  hasChange(a) ? (
                    expanded.has(a.id) ? (
                      <ChevronDown size={16} aria-label="Fechar mudança" />
                    ) : (
                      <ChevronRight size={16} aria-label="Ver mudança" />
                    )
                  ) : null,
                nowrap: true,
              },
              { key: 'at', header: 'Quando', cell: (a) => formatDateTime(a.at, { seconds: true }), nowrap: true },
              { key: 'actor', header: 'Quem', cell: (a) => (a.actor_type === 'user' ? a.actor : <Tag variant="neutral">{a.actor}</Tag>) },
              {
                key: 'action',
                header: 'Ação',
                cell: (a) => (
                  <Tag mono variant={a.action.includes('override') || a.action.includes('without_gate') || a.action.includes('tampered') ? 'solid' : 'outline'}>
                    {a.action}
                  </Tag>
                ),
                nowrap: true,
              },
              { key: 'detail', header: 'Detalhe', cell: (a) => <span className="snt-small">{a.detail ?? `${a.resource_type} ${a.resource_id ?? ''}`}</span> },
            ]}
            footer={
              audit.data && audit.data.total > LIMIT ? (
                <Pagination total={audit.data.total} limit={LIMIT} offset={offset} onChange={setOffset} noun="registros" />
              ) : undefined
            }
          />
        )}
      </Card>
    </Page>
  );
}
