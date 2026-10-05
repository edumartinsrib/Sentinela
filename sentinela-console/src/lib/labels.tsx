// Rótulos e tons dos estados do domínio (sobre os tons da broto-ui).

import { createStatusBadge, toneColor, type Tone } from 'broto-ui';
import type {
  ApprovalMode,
  Category,
  Enforcement,
  FindingStatus,
  GateMode,
  GateStatus,
  ReviewStatus,
  Role,
  Severity,
} from '../api/types';

export const GateBadge = createStatusBadge<GateStatus>({
  reviewing: { label: 'Em revisão', tone: 'live', pulse: true },
  blocked: { label: 'Bloqueado', tone: 'danger' },
  awaiting_approval: { label: 'Aguardando aprovação', tone: 'pending' },
  approved: { label: 'Aprovado', tone: 'success' },
  rejected: { label: 'Reprovado', tone: 'danger' },
  error: { label: 'Falha na revisão', tone: 'orange' },
  overridden: { label: 'Liberado (emergência)', tone: 'orange' },
  stale: { label: 'Substituído', tone: 'neutral' },
  merged: { label: 'Merge feito', tone: 'brand' },
});

export const ReviewBadge = createStatusBadge<ReviewStatus>({
  queued: { label: 'Na fila', tone: 'pending' },
  running: { label: 'Revisando', tone: 'live', pulse: true },
  completed: { label: 'Concluída', tone: 'success' },
  failed: { label: 'Falhou', tone: 'danger' },
  canceled: { label: 'Cancelada', tone: 'neutral' },
});

export const FindingStatusBadge = createStatusBadge<FindingStatus>({
  open: { label: 'Em aberto', tone: 'pending' },
  disputed: { label: 'Contestado', tone: 'info' },
  waived: { label: 'Exceção aceita', tone: 'brand' },
  false_positive: { label: 'Falso positivo', tone: 'neutral' },
});

export const SEVERITY_ORDER: Severity[] = ['blocker', 'high', 'medium', 'low', 'info'];

export const SEVERITY: Record<Severity, { label: string; tone: Tone }> = {
  blocker: { label: 'Bloqueante', tone: 'danger' },
  high: { label: 'Alta', tone: 'orange' },
  medium: { label: 'Média', tone: 'pending' },
  low: { label: 'Baixa', tone: 'info' },
  info: { label: 'Informativa', tone: 'neutral' },
};

export const SeverityBadge = createStatusBadge<Severity>(SEVERITY);

export const CATEGORY: Record<Category, string> = {
  security: 'Segurança',
  architecture: 'Arquitetura',
  structure: 'Estrutura',
  standards: 'Padrão de código',
  tests: 'Testes',
  performance: 'Desempenho',
  docs: 'Documentação',
  other: 'Outros',
};

export const CATEGORY_COLOR: Record<Category, string> = {
  security: toneColor.danger,
  architecture: toneColor.brand,
  structure: toneColor.info,
  standards: toneColor.success,
  tests: toneColor.pending,
  performance: toneColor.orange,
  docs: toneColor.neutral,
  other: toneColor.dark,
};

export const ROLE: Record<Role, string> = {
  admin: 'Administrador',
  tech_lead: 'Tech lead',
  reviewer: 'Revisor',
  developer: 'Desenvolvedor',
  reader: 'Leitor',
};

export const ROLE_HINT: Record<Role, string> = {
  admin: 'Tudo no time, inclusive papéis',
  tech_lead: 'Define padrões e repositórios, aceita exceções e aprova',
  reviewer: 'Aprova gates e descarta falsos positivos',
  developer: 'Reexecuta revisões, contesta apontamentos e faz merge liberado',
  reader: 'Só visualiza',
};

export const GATE_MODE: Record<GateMode, string> = {
  status_check: 'Check obrigatório no PR',
  platform_merge: 'Merge pelo Sentinela',
  both: 'Check obrigatório + merge pelo Sentinela',
};

export const ENFORCEMENT: Record<Enforcement, string> = {
  enforce: 'Bloqueando',
  observe: 'Modo observação',
};

export const APPROVAL_MODE: Record<ApprovalMode, string> = {
  ai_when_clean: 'IA aprova quando não há apontamentos',
  always_human: 'Sempre exige aprovação humana',
};

export const ENGINE_LABEL: Record<string, string> = {
  claude_code: 'Claude Code',
  copilot_cli: 'Copilot CLI',
  fake: 'Simulador local',
  none: 'Sem modelo',
};

export const PHASES: Record<string, string> = {
  claimed: 'Reivindicada',
  cloning: 'Baixando o código',
  diff: 'Calculando o diff',
  patterns: 'Regras de padrão',
  ai: 'Revisando com IA',
  reporting: 'Enviando resultado',
};

export function shortSha(sha: string | null | undefined): string {
  return sha ? sha.slice(0, 8) : '—';
}
