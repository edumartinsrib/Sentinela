import { Badge, Button, RelativeTime, Tag, toneColor, useConfirm } from 'broto-ui';
import { Ban, Check, ExternalLink, MessageSquare, RotateCcw, ShieldQuestion } from 'lucide-react';
import type { Finding, Permissions } from '../api/types';
import { CATEGORY, FindingStatusBadge, SEVERITY, SeverityBadge } from '../lib/labels';

const ACTION_TEXT: Record<string, string> = {
  waive: 'aceitou como exceção',
  dismiss: 'marcou como falso positivo',
  dispute: 'contestou',
  reopen: 'reabriu',
  comment: 'comentou',
};

export interface FindingActionFn {
  (finding: Finding, action: 'waive' | 'dismiss' | 'dispute' | 'reopen' | 'comment', reason: string): Promise<unknown>;
}

export function FindingCard({
  finding,
  permissions,
  onAction,
  busy,
}: {
  finding: Finding;
  permissions: Permissions;
  onAction: FindingActionFn;
  busy?: boolean;
}) {
  const confirm = useConfirm();
  const resolved = finding.status === 'waived' || finding.status === 'false_positive';
  const open = finding.status === 'open' || finding.status === 'disputed';

  const ask = async (
    action: 'waive' | 'dismiss' | 'dispute' | 'reopen' | 'comment',
    title: string,
    label: string,
    confirmLabel: string,
    description?: string,
  ) => {
    const result = await confirm({
      title,
      description,
      confirmLabel,
      tone: 'primary',
      reason: { label, required: true },
    });
    if (result.confirmed && result.reason) await onAction(finding, action, result.reason);
  };

  const location = finding.file ? `${finding.file}${finding.line ? `:${finding.line}` : ''}` : null;

  return (
    <article
      className={`snt-finding${resolved ? ' is-resolved' : ''}`}
      style={{ ['--snt-sev' as string]: toneColor[SEVERITY[finding.severity].tone] }}
      aria-label={`${SEVERITY[finding.severity].label}: ${finding.title}`}
    >
      <div className="snt-finding-head">
        <SeverityBadge status={finding.severity} />
        <Tag mono variant="outline">
          {finding.rule_code}
        </Tag>
        <span className="snt-finding-title">{finding.title}</span>
        <FindingStatusBadge status={finding.status} size="sm" />
        {finding.blocking && (
          <Badge tone="danger" size="sm" dot={false}>
            Bloqueia o merge
          </Badge>
        )}
      </div>

      <div className="snt-inline snt-small snt-muted">
        <span>{CATEGORY[finding.category]}</span>
        <span>·</span>
        <span>{finding.source === 'pattern' ? 'Regra de padrão (regex)' : 'Revisão por IA'}</span>
        {finding.rule_title && finding.rule_code !== 'GERAL' && (
          <>
            <span>·</span>
            <span>{finding.rule_title}</span>
          </>
        )}
        {finding.profile_name && (
          <>
            <span>·</span>
            <span>perfil {finding.profile_name}</span>
          </>
        )}
        {!finding.in_diff && (
          <Tag variant="neutral" title="O trecho apontado não está nas linhas alteradas do PR">
            fora do diff
          </Tag>
        )}
      </div>

      {location &&
        (finding.file_url ? (
          <a className="snt-finding-loc" href={finding.file_url} target="_blank" rel="noreferrer">
            {location} <ExternalLink size={12} aria-hidden />
          </a>
        ) : (
          <span className="snt-finding-loc">{location}</span>
        ))}

      {finding.description && <p>{finding.description}</p>}
      {finding.evidence && <div className="snt-evidence">{finding.evidence}</div>}
      {finding.suggestion && (
        <div className="snt-suggestion">
          <strong>Como corrigir: </strong>
          {finding.suggestion}
        </div>
      )}

      {finding.status_reason && (
        <div className="snt-small">
          <strong>{finding.status === 'disputed' ? 'Contestação' : 'Justificativa'}</strong>
          {finding.status_by && <span className="snt-muted"> · {finding.status_by}</span>}
          {finding.inherited && <span className="snt-muted"> · herdada de um commit anterior</span>}
          <div className="snt-muted">{finding.status_reason}</div>
        </div>
      )}

      <div className="snt-inline">
        {open && permissions.waive && (
          <Button
            size="sm"
            variant="secondary"
            icon={<Check size={14} />}
            disabled={busy}
            onClick={() =>
              void ask(
                'waive',
                'Aceitar como exceção?',
                'Justificativa (fica na auditoria)',
                'Aceitar exceção',
                'O apontamento continua registrado, mas deixa de bloquear o gate.',
              )
            }
          >
            Aceitar exceção
          </Button>
        )}
        {/* Falso positivo num apontamento que bloqueia o merge é decisão do tech lead. */}
        {open && permissions.dismiss && (!finding.blocking || permissions.waive) && (
          <Button
            size="sm"
            variant="ghost"
            icon={<Ban size={14} />}
            disabled={busy}
            onClick={() =>
              void ask('dismiss', 'Marcar como falso positivo?', 'Por que não procede?', 'Marcar falso positivo')
            }
          >
            Falso positivo
          </Button>
        )}
        {finding.status === 'open' && permissions.dispute && (
          <Button
            size="sm"
            variant="ghost"
            icon={<ShieldQuestion size={14} />}
            disabled={busy}
            onClick={() =>
              void ask(
                'dispute',
                'Contestar o apontamento?',
                'Argumento para o tech lead',
                'Contestar',
                'A contestação não libera o gate: um tech lead ou revisor decide.',
              )
            }
          >
            Contestar
          </Button>
        )}
        {!open && (permissions.dismiss || permissions.waive) && (
          <Button
            size="sm"
            variant="ghost"
            icon={<RotateCcw size={14} />}
            disabled={busy}
            onClick={() => void ask('reopen', 'Reabrir o apontamento?', 'Motivo', 'Reabrir')}
          >
            Reabrir
          </Button>
        )}
        <Button
          size="sm"
          variant="ghost"
          icon={<MessageSquare size={14} />}
          disabled={busy}
          onClick={() => void ask('comment', 'Comentar', 'Comentário', 'Comentar')}
        >
          Comentar
        </Button>
      </div>

      {finding.events.length > 0 && (
        <div className="snt-events">
          {finding.events.map((e, i) => (
            <div key={i}>
              <strong>{e.actor}</strong> {ACTION_TEXT[e.action] ?? e.action} <RelativeTime value={e.at} />
              {e.comment && <span className="snt-muted">: {e.comment}</span>}
            </div>
          ))}
        </div>
      )}
    </article>
  );
}
