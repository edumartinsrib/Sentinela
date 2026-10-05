import { Badge } from 'broto-ui';
import type { GateSummary } from '../api/types';
import { SEVERITY, SEVERITY_ORDER } from '../lib/labels';

/** Apontamentos em aberto por severidade (ex.: "2 Bloqueante · 1 Média"). */
export function SeverityCounts({ gate }: { gate: GateSummary | null }) {
  if (!gate) return <span className="snt-muted">—</span>;
  if (gate.review_status && gate.review_status !== 'completed') return <span className="snt-muted">…</span>;
  const items = SEVERITY_ORDER.filter((s) => gate.by_severity[s]);
  if (!items.length) {
    return gate.findings_total ? (
      <span className="snt-muted snt-small">{gate.findings_total} tratado(s)</span>
    ) : (
      <span className="snt-muted snt-small">nenhum</span>
    );
  }
  return (
    <span className="snt-sev-row">
      {items.map((s) => (
        <Badge key={s} tone={SEVERITY[s].tone} size="sm" title={SEVERITY[s].label}>
          {gate.by_severity[s]} {SEVERITY[s].label.toLowerCase()}
        </Badge>
      ))}
    </span>
  );
}
