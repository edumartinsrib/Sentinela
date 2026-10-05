import {
  Badge,
  Button,
  Callout,
  Card,
  DataTable,
  Dialog,
  EmptyState,
  ErrorState,
  Field,
  FormGrid,
  Input,
  Menu,
  Page,
  PageHeader,
  Select,
  Stack,
  Switch,
  Tag,
  TagInput,
  Textarea,
  toast,
  useConfirm,
  useDocumentTitle,
} from 'broto-ui';
import { Bot, KeyRound, Pencil, Plus, Star, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useAdminActions, useEngines } from '../../api/queries';
import type { AiEngine, AiModel, EngineKind } from '../../api/types';
import { useTeam } from '../../lib/context';
import { ENGINE_LABEL } from '../../lib/labels';

const SECRET_HINT: Record<EngineKind, string> = {
  claude_code: 'ANTHROPIC_API_KEY (ou CLAUDE_CODE_USE_BEDROCK=1 / CLAUDE_CODE_USE_VERTEX=1 com as credenciais da nuvem no runner)',
  copilot_cli: 'COPILOT_GITHUB_TOKEN (token com a permissão “Copilot Requests”)',
  fake: 'Não usa segredos',
};

export function AiPage() {
  const { can } = useTeam();
  const engines = useEngines();
  const admin = can('global.admin');
  const [engineDialog, setEngineDialog] = useState<{ open: boolean; engine: AiEngine | null }>({ open: false, engine: null });
  const [modelDialog, setModelDialog] = useState<{ open: boolean; engine: AiEngine | null; model: AiModel | null }>({
    open: false,
    engine: null,
    model: null,
  });
  const [secretEngine, setSecretEngine] = useState<AiEngine | null>(null);
  useDocumentTitle('IA e modelos', 'Sentinela');

  return (
    <Page>
      <PageHeader
        title="IA e modelos"
        description="Ferramentas que os runners usam para revisar (Claude Code e GitHub Copilot CLI) e os modelos disponíveis. O padrão global vale para todos os repositórios; perfis e repositórios podem usar outro."
        actions={
          admin && (
            <Button variant="primary" icon={<Plus size={16} />} onClick={() => setEngineDialog({ open: true, engine: null })}>
              Novo motor
            </Button>
          )
        }
      />
      {!admin && <Callout tone="info">Só administradores globais alteram motores e modelos.</Callout>}
      {engines.isError ? (
        <Card>
          <ErrorState error={engines.error} onRetry={() => void engines.refetch()} />
        </Card>
      ) : (
        (engines.data ?? []).map((engine) => (
          <Card
            key={engine.id}
            box
            title={
              <span className="snt-inline">
                <Bot size={18} /> {engine.name} <Tag mono>{ENGINE_LABEL[engine.kind] ?? engine.kind}</Tag>
                {!engine.enabled && <Badge tone="neutral">desabilitado</Badge>}
              </span>
            }
            subtitle={engine.description}
            actions={
              admin && (
                <Menu
                  label={`Ações de ${engine.name}`}
                  items={[
                    { label: 'Editar motor', icon: <Pencil size={16} />, onSelect: () => setEngineDialog({ open: true, engine }) },
                    { label: 'Segredos do motor', icon: <KeyRound size={16} />, onSelect: () => setSecretEngine(engine), hidden: engine.kind === 'fake' },
                    { label: 'Novo modelo', icon: <Plus size={16} />, onSelect: () => setModelDialog({ open: true, engine, model: null }) },
                  ]}
                />
              )
            }
          >
            <Stack gap={12}>
              <div className="snt-inline snt-small snt-muted">
                <span>até {engine.max_turns} turnos</span>·<span>tempo limite {Math.round(engine.timeout_s / 60)} min</span>
                {engine.max_budget_usd && (
                  <>
                    ·<span>teto US$ {engine.max_budget_usd.toFixed(2)} por revisão</span>
                  </>
                )}
                ·
                <span>
                  {engine.runners_online
                    ? `${engine.runners_online} runner(s) online com esta ferramenta`
                    : 'nenhum runner online com esta ferramenta'}
                </span>
                {engine.secret_env_names.length > 0 && (
                  <>
                    ·<span>segredos: {engine.secret_env_names.join(', ')}</span>
                  </>
                )}
              </div>
              <ModelsTable engine={engine} admin={admin} onEdit={(model) => setModelDialog({ open: true, engine, model })} />
            </Stack>
          </Card>
        ))
      )}
      {(engines.data ?? []).length === 0 && !engines.isLoading && (
        <Card>
          <EmptyState title="Nenhum motor" />
        </Card>
      )}
      <EngineDialog {...engineDialog} onClose={() => setEngineDialog({ open: false, engine: null })} />
      <ModelDialog {...modelDialog} onClose={() => setModelDialog({ open: false, engine: null, model: null })} />
      <SecretsDialog engine={secretEngine} onClose={() => setSecretEngine(null)} />
    </Page>
  );
}

function ModelsTable({ engine, admin, onEdit }: { engine: AiEngine; admin: boolean; onEdit: (m: AiModel) => void }) {
  const actions = useAdminActions();
  const confirm = useConfirm();
  return (
    <DataTable<AiModel>
      compact
      rows={engine.models}
      getRowId={(m) => m.id}
      empty={<EmptyState compact title="Nenhum modelo" />}
      columns={[
        {
          key: 'label',
          header: 'Modelo',
          cell: (m) => (
            <span className="snt-inline">
              <strong>{m.label}</strong>
              {m.is_default && (
                <Badge tone="success" size="sm">
                  padrão global
                </Badge>
              )}
            </span>
          ),
        },
        { key: 'id', header: 'Valor de --model', cell: (m) => (m.model ? <Tag mono>{m.model}</Tag> : <span className="snt-muted">padrão da ferramenta</span>) },
        { key: 'desc', header: 'Observação', cell: (m) => <span className="snt-small snt-muted">{m.description ?? ''}</span> },
        {
          key: 'enabled',
          header: 'Habilitado',
          cell: (m) => (
            <Switch
              aria-label={`Modelo ${m.label} habilitado`}
              checked={m.enabled}
              disabled={!admin}
              onCheckedChange={(v) => void actions.updateModel.mutateAsync({ id: m.id, body: { enabled: v } })}
            />
          ),
        },
        {
          key: 'actions',
          header: '',
          actions: true,
          hidden: !admin,
          cell: (m) => (
            <Menu
              label={`Ações do modelo ${m.label}`}
              items={[
                {
                  label: 'Tornar padrão global',
                  icon: <Star size={16} />,
                  disabled: m.is_default || !m.enabled,
                  onSelect: async () => {
                    await actions.setDefaultModel.mutateAsync(m.id);
                    toast.success('Modelo padrão alterado', m.label);
                  },
                },
                { label: 'Editar', icon: <Pencil size={16} />, onSelect: () => onEdit(m) },
                {
                  label: 'Excluir',
                  icon: <Trash2 size={16} />,
                  danger: true,
                  onSelect: async () => {
                    const r = await confirm({ title: `Excluir o modelo ${m.label}?`, confirmLabel: 'Excluir' });
                    if (r.confirmed) await actions.deleteModel.mutateAsync(m.id);
                  },
                },
              ]}
            />
          ),
        },
      ]}
    />
  );
}

function EngineDialog({ open, engine, onClose }: { open: boolean; engine: AiEngine | null; onClose: () => void }) {
  const actions = useAdminActions();
  const [form, setForm] = useState({
    kind: 'claude_code' as EngineKind,
    name: '',
    description: '',
    enabled: true,
    max_turns: '30',
    timeout_s: '900',
    max_budget_usd: '',
    extra_args: [] as string[],
  });
  useEffect(() => {
    if (!open) return;
    setForm(
      engine
        ? {
            kind: engine.kind,
            name: engine.name,
            description: engine.description ?? '',
            enabled: engine.enabled,
            max_turns: String(engine.max_turns),
            timeout_s: String(engine.timeout_s),
            max_budget_usd: engine.max_budget_usd ? String(engine.max_budget_usd) : '',
            extra_args: engine.extra_args,
          }
        : { kind: 'claude_code', name: '', description: '', enabled: true, max_turns: '30', timeout_s: '900', max_budget_usd: '', extra_args: [] },
    );
  }, [open, engine]);
  const body = {
    name: form.name,
    description: form.description || null,
    enabled: form.enabled,
    max_turns: Number(form.max_turns),
    timeout_s: Number(form.timeout_s),
    max_budget_usd: form.max_budget_usd ? Number(form.max_budget_usd) : null,
    extra_args: form.extra_args,
  };
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={engine ? `Editar ${engine.name}` : 'Novo motor'}
      size="lg"
      onSubmit={async () => {
        if (engine) await actions.updateEngine.mutateAsync({ id: engine.id, body });
        else await actions.createEngine.mutateAsync({ ...body, kind: form.kind });
        toast.success('Motor salvo');
        onClose();
      }}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit" variant="primary" loading={actions.createEngine.isPending || actions.updateEngine.isPending}>
            Salvar
          </Button>
        </>
      }
    >
      <Stack gap={14}>
        <FormGrid>
          <Field label="Ferramenta">
            <Select value={form.kind} disabled={!!engine} onChange={(e) => setForm({ ...form, kind: e.target.value as EngineKind })}>
              <option value="claude_code">Claude Code</option>
              <option value="copilot_cli">GitHub Copilot CLI</option>
              <option value="fake">Simulador local</option>
            </Select>
          </Field>
          <Field label="Nome" required>
            <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </Field>
          <Field label="Máximo de turnos">
            <Input type="number" min={1} value={form.max_turns} onChange={(e) => setForm({ ...form, max_turns: e.target.value })} />
          </Field>
          <Field label="Tempo limite (segundos)">
            <Input type="number" min={30} value={form.timeout_s} onChange={(e) => setForm({ ...form, timeout_s: e.target.value })} />
          </Field>
          <Field label="Teto de custo por revisão (US$)" hint="Claude Code: --max-budget-usd">
            <Input type="number" step="0.01" min={0} value={form.max_budget_usd} onChange={(e) => setForm({ ...form, max_budget_usd: e.target.value })} />
          </Field>
          <Field label="Argumentos extras" hint="Ex.: --effort high">
            <TagInput value={form.extra_args} onChange={(v) => setForm({ ...form, extra_args: v })} separators={['Enter']} />
          </Field>
        </FormGrid>
        <Field label="Descrição">
          <Textarea rows={2} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
        </Field>
        <Switch checked={form.enabled} onCheckedChange={(v) => setForm({ ...form, enabled: v })} label="Habilitado" />
      </Stack>
    </Dialog>
  );
}

function ModelDialog({
  open,
  engine,
  model,
  onClose,
}: {
  open: boolean;
  engine: AiEngine | null;
  model: AiModel | null;
  onClose: () => void;
}) {
  const actions = useAdminActions();
  const [form, setForm] = useState({ model: '', label: '', description: '', enabled: true, is_default: false });
  useEffect(() => {
    if (!open) return;
    setForm(
      model
        ? { model: model.model, label: model.label, description: model.description ?? '', enabled: model.enabled, is_default: model.is_default }
        : { model: '', label: '', description: '', enabled: true, is_default: false },
    );
  }, [open, model]);
  const hint =
    engine?.kind === 'claude_code'
      ? 'Alias (sonnet, opus, haiku) ou nome completo do modelo'
      : engine?.kind === 'copilot_cli'
        ? 'Nome como aparece em /model na Copilot CLI; vazio = padrão'
        : '';
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={model ? `Editar ${model.label}` : `Novo modelo — ${engine?.name ?? ''}`}
      onSubmit={async () => {
        const body = { ...form, description: form.description || null };
        if (model) await actions.updateModel.mutateAsync({ id: model.id, body });
        else if (engine) await actions.createModel.mutateAsync({ ...body, engine_id: engine.id });
        toast.success('Modelo salvo');
        onClose();
      }}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit" variant="primary" loading={actions.createModel.isPending || actions.updateModel.isPending}>
            Salvar
          </Button>
        </>
      }
    >
      <Stack gap={14}>
        <Field label="Valor de --model" hint={hint}>
          <Input value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} className="snt-mono" />
        </Field>
        <Field label="Nome exibido" required>
          <Input value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} />
        </Field>
        <Field label="Observação">
          <Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
        </Field>
        <Switch checked={form.enabled} onCheckedChange={(v) => setForm({ ...form, enabled: v })} label="Habilitado" />
        <Switch checked={form.is_default} onCheckedChange={(v) => setForm({ ...form, is_default: v })} label="Padrão global" />
      </Stack>
    </Dialog>
  );
}

function SecretsDialog({ engine, onClose }: { engine: AiEngine | null; onClose: () => void }) {
  const actions = useAdminActions();
  const [name, setName] = useState('');
  const [value, setValue] = useState('');
  useEffect(() => {
    setName(engine?.kind === 'copilot_cli' ? 'COPILOT_GITHUB_TOKEN' : 'ANTHROPIC_API_KEY');
    setValue('');
  }, [engine]);
  if (!engine) return null;
  return (
    <Dialog
      open={!!engine}
      onClose={onClose}
      title={`Segredos de ${engine.name}`}
      description="Variáveis de ambiente entregues ao runner junto com cada revisão, cifradas no cofre. Os valores não voltam pela API e são mascarados nos logs."
      onSubmit={async () => {
        await actions.engineSecrets.mutateAsync({ id: engine.id, values: { [name.trim()]: value } });
        toast.success('Segredo salvo', name);
        onClose();
      }}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Fechar
          </Button>
          <Button type="submit" variant="primary" disabled={!name.trim() || !value} loading={actions.engineSecrets.isPending}>
            Salvar
          </Button>
        </>
      }
    >
      <Stack gap={14}>
        <Callout tone="info">{SECRET_HINT[engine.kind]}</Callout>
        {engine.secret_env_names.length > 0 && (
          <div className="snt-inline">
            {engine.secret_env_names.map((n) => (
              <Tag key={n} mono>
                {n}
                <button
                  type="button"
                  aria-label={`Remover ${n}`}
                  style={{ border: 0, background: 'none', cursor: 'pointer', marginLeft: 4 }}
                  onClick={() => void actions.engineSecrets.mutateAsync({ id: engine.id, values: { [n]: null } })}
                >
                  ×
                </button>
              </Tag>
            ))}
          </div>
        )}
        <Field label="Variável">
          <Input value={name} onChange={(e) => setName(e.target.value.toUpperCase())} className="snt-mono" />
        </Field>
        <Field label="Valor">
          <Input type="password" value={value} onChange={(e) => setValue(e.target.value)} autoComplete="off" />
        </Field>
        <span className="snt-small snt-muted">
          Alternativa: deixe a credencial só no ambiente do runner (variáveis do serviço ou do container).
        </span>
      </Stack>
    </Dialog>
  );
}
