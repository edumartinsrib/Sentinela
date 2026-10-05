import {
  Badge,
  Button,
  Callout,
  Card,
  Checkbox,
  DataTable,
  Dialog,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Menu,
  MetaItem,
  Page,
  PageHeader,
  PageLoading,
  RelativeTime,
  SearchInput,
  Select,
  Switch,
  Tag,
  TagInput,
  Textarea,
  toast,
  useConfirm,
  useDocumentTitle,
} from 'broto-ui';
import { BookPlus, Download, FolderGit2, Pencil, Plus, Trash2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { downloadFile } from '../api/client';
import { useLibrary, useModels, useProfile, useProfileActions } from '../api/queries';
import type { Profile, Rule, RuleSpec } from '../api/types';
import { RuleDialog } from '../components/RuleDialog';
import { useTeam } from '../lib/context';
import { CATEGORY, SeverityBadge } from '../lib/labels';

export function ProfilePage() {
  const { id = '' } = useParams();
  const { team } = useTeam();
  const profile = useProfile(team.name, id);
  useDocumentTitle(profile.data?.name ?? 'Perfil', 'Sentinela');
  if (profile.isLoading) return <PageLoading />;
  if (profile.isError || !profile.data) {
    return (
      <Page>
        <Card>
          <ErrorState error={profile.error} onRetry={() => void profile.refetch()} />
        </Card>
      </Page>
    );
  }
  return <ProfileView profile={profile.data} />;
}

function ProfileView({ profile }: { profile: Profile }) {
  const { team, base, can } = useTeam();
  const navigate = useNavigate();
  const confirm = useConfirm();
  const actions = useProfileActions(team.name);
  const canWrite = can('standards.write');
  const [editing, setEditing] = useState(false);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [ruleDialog, setRuleDialog] = useState<{ open: boolean; rule: Rule | null }>({ open: false, rule: null });

  const saveRule = async (spec: RuleSpec) => {
    if (ruleDialog.rule) {
      await actions.updateRule.mutateAsync({ profileId: profile.id, ruleId: ruleDialog.rule.id, body: spec });
      toast.success('Regra atualizada');
    } else {
      await actions.createRule.mutateAsync({ profileId: profile.id, body: spec });
      toast.success('Regra criada');
    }
    setRuleDialog({ open: false, rule: null });
  };

  const removeRule = async (rule: Rule) => {
    const r = await confirm({ title: `Excluir a regra ${rule.code}?`, description: 'Revisões já feitas não mudam.', confirmLabel: 'Excluir' });
    if (r.confirmed) await actions.deleteRule.mutateAsync({ profileId: profile.id, ruleId: rule.id });
  };

  const removeProfile = async () => {
    const r = await confirm({
      title: `Excluir o perfil ${profile.name}?`,
      description: profile.repositories.length
        ? `Ele deixa de valer em ${profile.repositories.length} repositório(s).`
        : 'O perfil não está em uso.',
      confirmLabel: 'Excluir perfil',
    });
    if (!r.confirmed) return;
    await actions.remove.mutateAsync(profile.id);
    navigate(`${base}/padroes`);
  };

  return (
    <Page>
      <PageHeader
        crumbs={[{ label: 'Padrões', href: `${base}/padroes` }, { label: profile.name }]}
        title={profile.name}
        description={profile.description ?? undefined}
        badge={profile.enabled ? <Badge tone="success">ativo</Badge> : <Badge tone="neutral">desabilitado</Badge>}
        meta={
          <>
            <MetaItem>
              {profile.rules_enabled} regras ativas · {profile.rules_by_kind.ai ?? 0} de IA · {profile.rules_by_kind.pattern ?? 0} de padrão
            </MetaItem>
            {profile.model_label && <MetaItem>modelo: {profile.model_label}</MetaItem>}
            {profile.updated_at && (
              <MetaItem>
                alterado <RelativeTime value={profile.updated_at} />
                {profile.updated_by ? ` por ${profile.updated_by}` : ''}
              </MetaItem>
            )}
          </>
        }
        actions={
          <>
            <Button
              variant="secondary"
              icon={<Download size={16} />}
              onClick={() => void downloadFile(`/teams/${team.name}/profiles/${profile.id}/export`, 'perfil.yaml')}
            >
              Exportar YAML
            </Button>
            {canWrite && (
              <>
                <Button variant="secondary" icon={<Pencil size={16} />} onClick={() => setEditing(true)}>
                  Editar
                </Button>
                <Menu
                  label="Mais ações"
                  items={[
                    { label: 'Adicionar da biblioteca', icon: <BookPlus size={16} />, onSelect: () => setLibraryOpen(true) },
                    'separator',
                    { label: 'Excluir perfil', icon: <Trash2 size={16} />, danger: true, onSelect: () => void removeProfile() },
                  ]}
                />
              </>
            )}
          </>
        }
      />

      <Card title="Onde vale" box>
        <div className="snt-stack">
          <div className="snt-inline">
            <span className="snt-small snt-muted">Arquivos:</span>
            {profile.path_globs.length ? (
              profile.path_globs.map((g) => (
                <Tag key={g} mono>
                  {g}
                </Tag>
              ))
            ) : (
              <Tag mono>todos</Tag>
            )}
          </div>
          <div className="snt-inline">
            <span className="snt-small snt-muted">Repositórios:</span>
            {profile.repositories.length ? (
              profile.repositories.map((r) => (
                <Tag key={r.id} icon={<FolderGit2 size={12} />}>
                  {r.name}
                </Tag>
              ))
            ) : (
              <span className="snt-small">nenhum ainda — vincule em Repositórios</span>
            )}
          </div>
          {profile.instructions ? (
            <div>
              <div className="snt-small snt-muted">Contexto de arquitetura entregue à IA:</div>
              <div className="snt-rule-instruction">{profile.instructions}</div>
            </div>
          ) : (
            <Callout tone="info">
              Descreva a arquitetura e as convenções do time em “Editar”: a IA usa esse contexto para avaliar as regras.
            </Callout>
          )}
        </div>
      </Card>

      <Card
        title="Regras"
        subtitle="A severidade e a categoria vêm daqui; a IA não consegue rebaixar nem inventar bloqueios."
        flush
        actions={
          canWrite && (
            <Button size="sm" variant="primary" icon={<Plus size={14} />} onClick={() => setRuleDialog({ open: true, rule: null })}>
              Nova regra
            </Button>
          )
        }
      >
        <DataTable<Rule>
          rows={profile.rules}
          getRowId={(r) => r.id}
          rowClassName={(r) => (r.enabled ? undefined : 'snt-muted')}
          renderExpanded={(r) => (
            <div className="snt-stack" style={{ padding: '4px 0 8px' }}>
              {r.kind === 'pattern' && (
                <div className="snt-small">
                  Regex: <code className="snt-mono">{r.pattern}</code>
                  {r.ignore_case ? ' (ignora maiúsculas)' : ''}
                </div>
              )}
              {r.instruction && <div className="snt-rule-instruction">{r.instruction}</div>}
              {r.suggestion && <div className="snt-suggestion">Como corrigir: {r.suggestion}</div>}
            </div>
          )}
          empty={<EmptyState compact title="Nenhuma regra" description="Crie uma regra ou adicione da biblioteca." />}
          columns={[
            {
              key: 'code',
              header: 'Código',
              cell: (r) => (
                <Tag mono variant="outline">
                  {r.code}
                </Tag>
              ),
              nowrap: true,
            },
            { key: 'title', header: 'Regra', cell: (r) => <strong>{r.title}</strong> },
            { key: 'cat', header: 'Categoria', cell: (r) => CATEGORY[r.category], nowrap: true },
            { key: 'sev', header: 'Severidade', cell: (r) => <SeverityBadge status={r.severity} size="sm" />, nowrap: true },
            {
              key: 'kind',
              header: 'Tipo',
              cell: (r) => <Tag variant={r.kind === 'ai' ? 'green' : 'neutral'}>{r.kind === 'ai' ? 'IA' : 'regex'}</Tag>,
            },
            {
              key: 'scope',
              header: 'Escopo',
              cell: (r) =>
                r.paths.length || r.exclude_paths.length ? (
                  <span className="snt-small snt-mono">
                    {r.paths.join(', ')}
                    {r.exclude_paths.length ? ` exceto ${r.exclude_paths.join(', ')}` : ''}
                  </span>
                ) : (
                  <span className="snt-small snt-muted">perfil todo</span>
                ),
            },
            { key: 'hits', header: '30 dias', cell: (r) => r.violations_30d || '—', align: 'right' },
            {
              key: 'enabled',
              header: 'Ativa',
              cell: (r) => (
                <Switch
                  aria-label={`Regra ${r.code} ativa`}
                  checked={r.enabled}
                  disabled={!canWrite}
                  onCheckedChange={(v) =>
                    void actions.updateRule.mutateAsync({ profileId: profile.id, ruleId: r.id, body: { enabled: v } })
                  }
                />
              ),
            },
            {
              key: 'actions',
              header: '',
              actions: true,
              hidden: !canWrite,
              cell: (r) => (
                <Menu
                  label={`Ações da regra ${r.code}`}
                  items={[
                    { label: 'Editar', icon: <Pencil size={16} />, onSelect: () => setRuleDialog({ open: true, rule: r }) },
                    { label: 'Excluir', icon: <Trash2 size={16} />, danger: true, onSelect: () => void removeRule(r) },
                  ]}
                />
              ),
            },
          ]}
        />
      </Card>

      {canWrite && (
        <>
          <RuleDialog
            open={ruleDialog.open}
            rule={ruleDialog.rule}
            onClose={() => setRuleDialog({ open: false, rule: null })}
            onSave={saveRule}
            saving={actions.createRule.isPending || actions.updateRule.isPending}
          />
          <EditProfileDialog open={editing} profile={profile} onClose={() => setEditing(false)} />
          <LibraryDialog open={libraryOpen} profile={profile} onClose={() => setLibraryOpen(false)} />
        </>
      )}
    </Page>
  );
}

function EditProfileDialog({ open, profile, onClose }: { open: boolean; profile: Profile; onClose: () => void }) {
  const { team, can } = useTeam();
  const { update } = useProfileActions(team.name);
  const models = useModels();
  const admin = can('global.admin');
  const [form, setForm] = useState({ name: '', description: '', instructions: '', path_globs: [] as string[], enabled: true, model_id: '' });
  useEffect(() => {
    if (open)
      setForm({
        name: profile.name,
        description: profile.description ?? '',
        instructions: profile.instructions,
        path_globs: profile.path_globs,
        enabled: profile.enabled,
        model_id: profile.model_id ?? '',
      });
  }, [open, profile]);
  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title="Editar perfil"
      onSubmit={async () => {
        const body: Record<string, unknown> = {
          name: form.name,
          description: form.description || null,
          instructions: form.instructions,
          path_globs: form.path_globs,
          enabled: form.enabled,
        };
        if (admin) body.model_id = form.model_id || null;
        await update.mutateAsync({ id: profile.id, body });
        toast.success('Perfil salvo');
        onClose();
      }}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit" variant="primary" loading={update.isPending}>
            Salvar
          </Button>
        </>
      }
    >
      <div className="snt-stack">
        <Field label="Nome" required>
          <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </Field>
        <Field label="Descrição">
          <Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
        </Field>
        <Field label="Arquivos do perfil" hint="Globs: **/*.py, web/**/*.{ts,tsx}, !**/gerado/**. Vazio = todos.">
          <TagInput value={form.path_globs} onChange={(v) => setForm({ ...form, path_globs: v })} placeholder="**/*.py" />
        </Field>
        <Field label="Contexto de arquitetura e convenções" hint="Entregue à IA junto com as regras (camadas, nomes, bibliotecas aprovadas…)">
          <Textarea rows={7} value={form.instructions} onChange={(e) => setForm({ ...form, instructions: e.target.value })} />
        </Field>
        {admin && (
          <Field label="Modelo de IA deste perfil" hint="Só administradores. Vazio = o padrão global (ou o do repositório).">
            <Select value={form.model_id} onChange={(e) => setForm({ ...form, model_id: e.target.value })}>
              <option value="">Padrão</option>
              {(models.data ?? [])
                .filter((m) => m.enabled)
                .map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.engine_name} · {m.label}
                  </option>
                ))}
            </Select>
          </Field>
        )}
        <Switch checked={form.enabled} onCheckedChange={(v) => setForm({ ...form, enabled: v })} label="Perfil ativo" />
      </div>
    </Dialog>
  );
}

function LibraryDialog({ open, profile, onClose }: { open: boolean; profile: Profile; onClose: () => void }) {
  const { team } = useTeam();
  const library = useLibrary();
  const { addLibrary } = useProfileActions(team.name);
  const [selected, setSelected] = useState<string[]>([]);
  const [q, setQ] = useState('');
  useEffect(() => {
    if (open) setSelected([]);
  }, [open]);
  const rules = useMemo(() => {
    const existing = new Set(profile.rules.map((r) => r.code));
    const needle = q.toLowerCase();
    return (library.data?.rules ?? []).filter(
      (r) => !existing.has(r.key) && `${r.key} ${r.rule.title} ${r.tags.join(' ')}`.toLowerCase().includes(needle),
    );
  }, [library.data, q, profile.rules]);
  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title="Adicionar regras da biblioteca"
      description="Regras prontas de segurança, arquitetura e padrão. Depois de adicionadas, ficam editáveis no perfil."
      onSubmit={async () => {
        await addLibrary.mutateAsync({ id: profile.id, keys: selected });
        toast.success(`${selected.length} regra(s) adicionada(s)`);
        onClose();
      }}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit" variant="primary" disabled={!selected.length} loading={addLibrary.isPending}>
            Adicionar {selected.length || ''}
          </Button>
        </>
      }
    >
      <div className="snt-stack">
        <SearchInput placeholder="Buscar por código, título ou tecnologia" value={q} onChange={(e) => setQ(e.target.value)} />
        {rules.length === 0 && <EmptyState compact title="Nada a adicionar" />}
        {rules.map((r) => (
          <label key={r.key} className="snt-inline" style={{ alignItems: 'flex-start' }}>
            <Checkbox
              checked={selected.includes(r.key)}
              onChange={(e) => setSelected((s) => (e.target.checked ? [...s, r.key] : s.filter((k) => k !== r.key)))}
            />
            <span>
              <Tag mono variant="outline">
                {r.key}
              </Tag>{' '}
              <strong>{r.rule.title}</strong> <SeverityBadge status={r.rule.severity} size="sm" />
              <br />
              <span className="snt-small snt-muted">
                {CATEGORY[r.rule.category]} · {r.rule.kind === 'ai' ? 'IA' : 'regex'} · {r.tags.join(', ')}
              </span>
            </span>
          </label>
        ))}
      </div>
    </Dialog>
  );
}
