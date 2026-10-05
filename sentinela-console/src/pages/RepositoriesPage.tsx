import {
  Badge,
  Button,
  Callout,
  Card,
  CellTitle,
  Checkbox,
  CopyButton,
  DataTable,
  Dialog,
  Drawer,
  EmptyState,
  ErrorState,
  Field,
  FormGrid,
  FormSection,
  Input,
  InlineCode,
  Page,
  PageHeader,
  RelativeTime,
  SearchInput,
  Segmented,
  Select,
  Spinner,
  Switch,
  TabPanel,
  Tabs,
  Tag,
  TagInput,
  toast,
  useConfirm,
  useDebounced,
  useDocumentTitle,
} from 'broto-ui';
import { CircleAlert, CircleCheck, FolderGit2, Lock, Plus, RefreshCw, Trash2, Webhook } from 'lucide-react';
import { useEffect, useState } from 'react';
import {
  useIntegrations,
  useModels,
  useProfiles,
  useProtection,
  useRemoteRepositories,
  useRepositories,
  useRepositoryActions,
} from '../api/queries';
import type { ApprovalMode, Enforcement, GateMode, MergeMethod, Repository, Severity } from '../api/types';
import { useTeam } from '../lib/context';
import { APPROVAL_MODE, ENFORCEMENT, GATE_MODE, SEVERITY, SEVERITY_ORDER } from '../lib/labels';

export function RepositoriesPage() {
  const { team, can } = useTeam();
  const repos = useRepositories(team.name);
  const [adding, setAdding] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  useDocumentTitle('Repositórios', 'Sentinela');
  const current = repos.data?.find((r) => r.id === openId) ?? null;

  return (
    <Page>
      <PageHeader
        title="Repositórios"
        description="Repositórios do time no GitHub ou GitLab, os perfis de padrão de cada um e como o gate trava o merge."
        actions={
          can('repo.write') && (
            <Button variant="primary" icon={<Plus size={16} />} onClick={() => setAdding(true)}>
              Adicionar repositório
            </Button>
          )
        }
      />
      <Card flush>
        {repos.isError ? (
          <ErrorState error={repos.error} onRetry={() => void repos.refetch()} />
        ) : (
          <DataTable<Repository>
            aria-label="Repositórios"
            rows={repos.data}
            loading={repos.isLoading}
            getRowId={(r) => r.id}
            activeRowId={openId}
            onRowClick={(r) => setOpenId(r.id)}
            empty={
              <EmptyState
                compact
                icon={<FolderGit2 size={22} />}
                title="Nenhum repositório"
                description="Adicione um repositório de uma integração do GitHub ou GitLab."
              />
            }
            columns={[
              {
                key: 'name',
                header: 'Repositório',
                cell: (r) => <CellTitle title={r.full_name} sub={`${r.integration.name} · ${r.gated_branches.join(', ')}`} />,
              },
              {
                key: 'profiles',
                header: 'Perfis',
                cell: (r) =>
                  r.profiles.length ? (
                    <span className="snt-inline">
                      {r.profiles.map((p) => (
                        <Tag key={p.id}>{p.name}</Tag>
                      ))}
                    </span>
                  ) : (
                    <Badge tone="danger" size="sm">
                      sem perfil
                    </Badge>
                  ),
              },
              { key: 'mode', header: 'Bloqueio', cell: (r) => <span className="snt-small">{GATE_MODE[r.gate_mode]}</span> },
              {
                key: 'enf',
                header: 'Situação',
                cell: (r) =>
                  !r.enabled ? (
                    <Badge tone="neutral">desabilitado</Badge>
                  ) : (
                    <Badge tone={r.enforcement === 'enforce' ? 'success' : 'info'}>{ENFORCEMENT[r.enforcement]}</Badge>
                  ),
                nowrap: true,
              },
              {
                key: 'hook',
                header: 'Webhook',
                cell: (r) =>
                  r.last_webhook_at ? (
                    <span className="snt-small">
                      <RelativeTime value={r.last_webhook_at} />
                    </span>
                  ) : (
                    <Badge tone="pending" size="sm">
                      nenhum recebido
                    </Badge>
                  ),
                nowrap: true,
              },
              { key: 'prs', header: 'PRs abertos', cell: (r) => r.open_pull_requests, align: 'right' },
            ]}
          />
        )}
      </Card>
      {current && <RepositoryDrawer repo={current} onClose={() => setOpenId(null)} />}
      <AddRepositoryDialog open={adding} onClose={() => setAdding(false)} onCreated={(id) => setOpenId(id)} />
    </Page>
  );
}

// ----------------------------------------------------------------------------- adicionar
function AddRepositoryDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (id: string) => void }) {
  const { team } = useTeam();
  const integrations = useIntegrations();
  const profiles = useProfiles(team.name);
  const { create } = useRepositoryActions(team.name);
  const [integrationId, setIntegrationId] = useState('');
  const [search, setSearch] = useState('');
  const [fullName, setFullName] = useState('');
  const [profileIds, setProfileIds] = useState<string[]>([]);
  const [gateMode, setGateMode] = useState<GateMode>('status_check');
  const [enforcement, setEnforcement] = useState<Enforcement>('observe');
  const debounced = useDebounced(search, 350);
  const remote = useRemoteRepositories(integrationId || null, debounced);

  useEffect(() => {
    if (!open) return;
    setFullName('');
    setSearch('');
    setProfileIds([]);
    setEnforcement('observe');
    const first = integrations.data?.find((i) => i.enabled);
    setIntegrationId(first?.id ?? '');
  }, [open, integrations.data]);

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title="Adicionar repositório"
      description="Recomendado: comece em modo observação por alguns dias para calibrar as regras, depois passe a bloquear."
      onSubmit={async () => {
        const repo = await create.mutateAsync({
          integration_id: integrationId,
          full_name: fullName,
          profile_ids: profileIds,
          gate_mode: gateMode,
          enforcement,
        });
        toast.success('Repositório adicionado', 'Configure o webhook e a proteção da branch.');
        onClose();
        onCreated(repo.id);
      }}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit" variant="primary" loading={create.isPending} disabled={!integrationId || !fullName}>
            Adicionar
          </Button>
        </>
      }
    >
      <div className="snt-stack">
        {integrations.data?.length === 0 && (
          <Callout tone="warning">Nenhuma integração cadastrada. Um administrador cria em Administração → Integrações.</Callout>
        )}
        <FormGrid>
          <Field label="Integração" required>
            <Select value={integrationId} onChange={(e) => setIntegrationId(e.target.value)}>
              <option value="">Selecione</option>
              {(integrations.data ?? []).map((i) => (
                <option key={i.id} value={i.id} disabled={!i.enabled}>
                  {i.name} ({i.provider === 'github' ? 'GitHub' : 'GitLab'})
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Repositório" hint="dono/nome ou grupo/subgrupo/projeto" required>
            <Input value={fullName} onChange={(e) => setFullName(e.target.value)} className="snt-mono" />
          </Field>
        </FormGrid>
        {integrationId && (
          <Card title="Repositórios visíveis para o token" flush>
            <div style={{ padding: 12 }}>
              <SearchInput placeholder="Filtrar" value={search} onChange={(e) => setSearch(e.target.value)} />
            </div>
            {remote.isLoading ? (
              <div style={{ padding: 12 }}>
                <Spinner label="Consultando o provedor…" />
              </div>
            ) : remote.isError ? (
              <div style={{ padding: 12 }}>
                <Callout tone="warning">Não foi possível listar: digite o nome do repositório acima.</Callout>
              </div>
            ) : (
              <div style={{ maxHeight: 220, overflow: 'auto', padding: '0 12px 12px' }}>
                {(remote.data ?? []).map((r) => (
                  <label key={r.full_name} className="snt-inline" style={{ padding: '4px 0' }}>
                    <input
                      type="radio"
                      name="remote-repo"
                      checked={fullName === r.full_name}
                      disabled={!!r.imported_in}
                      onChange={() => setFullName(r.full_name)}
                    />
                    <span className="snt-mono">{r.full_name}</span>
                    {r.imported_in && <Tag variant="neutral">já no time {r.imported_in}</Tag>}
                  </label>
                ))}
                {remote.data?.length === 0 && <span className="snt-muted snt-small">Nada encontrado.</span>}
              </div>
            )}
          </Card>
        )}
        <Field label="Perfis de padrão">
          <div className="snt-inline">
            {(profiles.data ?? []).map((p) => (
              <Checkbox
                key={p.id}
                label={p.name}
                checked={profileIds.includes(p.id)}
                onChange={(e) => setProfileIds((ids) => (e.target.checked ? [...ids, p.id] : ids.filter((x) => x !== p.id)))}
              />
            ))}
            {profiles.data?.length === 0 && <span className="snt-small snt-muted">Crie um perfil em Padrões antes.</span>}
          </div>
        </Field>
        <FormGrid>
          <Field label="Como o merge é travado">
            <Select value={gateMode} onChange={(e) => setGateMode(e.target.value as GateMode)}>
              {(Object.keys(GATE_MODE) as GateMode[]).map((m) => (
                <option key={m} value={m}>
                  {GATE_MODE[m]}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Começar">
            <Segmented<Enforcement>
              value={enforcement}
              onChange={setEnforcement}
              options={[
                { value: 'observe', label: 'Observando' },
                { value: 'enforce', label: 'Bloqueando' },
              ]}
            />
          </Field>
        </FormGrid>
      </div>
    </Dialog>
  );
}

// ----------------------------------------------------------------------------- detalhe
type DrawerTab = 'settings' | 'protection' | 'webhook';

function RepositoryDrawer({ repo, onClose }: { repo: Repository; onClose: () => void }) {
  const { team, can } = useTeam();
  const [tab, setTab] = useState<DrawerTab>('settings');
  const canWrite = can('repo.write');
  return (
    <Drawer open onClose={onClose} size="lg" title={repo.full_name} description={`${repo.integration.name} · ${repo.gated_branches.join(', ')}`}>
      <Tabs<DrawerTab>
        idPrefix="repo"
        value={tab}
        onChange={setTab}
        tabs={[
          { id: 'settings', label: 'Configuração' },
          { id: 'protection', label: 'Bloqueio do merge' },
          { id: 'webhook', label: 'Webhook e sincronização' },
        ]}
      />
      <TabPanel id="settings" idPrefix="repo">
        {tab === 'settings' && <SettingsForm repo={repo} team={team.name} canWrite={canWrite} onRemoved={onClose} />}
      </TabPanel>
      <TabPanel id="protection" idPrefix="repo">
        {tab === 'protection' && <ProtectionPanel repo={repo} team={team.name} />}
      </TabPanel>
      <TabPanel id="webhook" idPrefix="repo">
        {tab === 'webhook' && <WebhookPanel repo={repo} team={team.name} canWrite={canWrite} />}
      </TabPanel>
    </Drawer>
  );
}

function SettingsForm({ repo, team, canWrite, onRemoved }: { repo: Repository; team: string; canWrite: boolean; onRemoved: () => void }) {
  const { can } = useTeam();
  const profiles = useProfiles(team);
  const models = useModels();
  const { update, remove } = useRepositoryActions(team);
  const confirm = useConfirm();
  const admin = can('global.admin');
  const [form, setForm] = useState(() => toForm(repo));
  useEffect(() => setForm(toForm(repo)), [repo]);
  const set = <K extends keyof ReturnType<typeof toForm>>(k: K, v: ReturnType<typeof toForm>[K]) => setForm((f) => ({ ...f, [k]: v }));

  const save = async () => {
    const body: Record<string, unknown> = { ...form, min_approvals: Number(form.min_approvals) || 1 };
    if (!admin) delete body.model_id;
    else body.model_id = form.model_id || null;
    await update.mutateAsync({ id: repo.id, body });
    toast.success('Repositório salvo');
  };

  return (
    <form
      className="snt-stack"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <fieldset disabled={!canWrite} style={{ border: 0, padding: 0, margin: 0 }} className="snt-stack">
        <FormSection>Perfis aplicados</FormSection>
        <div className="snt-inline">
          {(profiles.data ?? []).map((p) => (
            <Checkbox
              key={p.id}
              label={p.name}
              checked={form.profile_ids.includes(p.id)}
              onChange={(e) =>
                set('profile_ids', e.target.checked ? [...form.profile_ids, p.id] : form.profile_ids.filter((x) => x !== p.id))
              }
            />
          ))}
        </div>

        <FormSection>Gate</FormSection>
        <FormGrid>
          <Field label="Situação">
            <Segmented<Enforcement>
              value={form.enforcement}
              onChange={(v) => set('enforcement', v)}
              options={[
                { value: 'observe', label: 'Observando' },
                { value: 'enforce', label: 'Bloqueando' },
              ]}
            />
          </Field>
          <Field label="Como o merge é travado">
            <Select value={form.gate_mode} onChange={(e) => set('gate_mode', e.target.value as GateMode)}>
              {(Object.keys(GATE_MODE) as GateMode[]).map((m) => (
                <option key={m} value={m}>
                  {GATE_MODE[m]}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Branches com gate" hint="Globs: main, release/*">
            <TagInput value={form.gated_branches} onChange={(v) => set('gated_branches', v)} />
          </Field>
          <Field label="Nome do status" hint="O mesmo nome configurado como obrigatório no provedor">
            <Input value={form.status_context} onChange={(e) => set('status_context', e.target.value)} className="snt-mono" />
          </Field>
          <Field label="Método do merge pela plataforma">
            <Select value={form.merge_method} onChange={(e) => set('merge_method', e.target.value as MergeMethod)}>
              <option value="merge">Merge commit</option>
              <option value="squash">Squash</option>
              <option value="rebase">Rebase (GitHub)</option>
            </Select>
          </Field>
        </FormGrid>

        <FormSection>Política de aprovação</FormSection>
        <FormGrid>
          <Field label="Quem aprova">
            <Select value={form.approval_mode} onChange={(e) => set('approval_mode', e.target.value as ApprovalMode)}>
              {(Object.keys(APPROVAL_MODE) as ApprovalMode[]).map((m) => (
                <option key={m} value={m}>
                  {APPROVAL_MODE[m]}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Exige humano a partir de" hint="Apontamentos abaixo disso não impedem a aprovação da IA">
            <Select value={form.human_min_severity} onChange={(e) => set('human_min_severity', e.target.value as Severity)}>
              {SEVERITY_ORDER.map((s) => (
                <option key={s} value={s}>
                  {SEVERITY[s].label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Bloqueia a partir de" hint="Exige justificativa do tech lead antes de aprovar">
            <Select value={form.block_severity} onChange={(e) => set('block_severity', e.target.value as Severity)}>
              {SEVERITY_ORDER.map((s) => (
                <option key={s} value={s}>
                  {SEVERITY[s].label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Aprovações humanas necessárias">
            <Input type="number" min={1} max={5} value={form.min_approvals} onChange={(e) => set('min_approvals', e.target.value)} />
          </Field>
        </FormGrid>
        <Switch checked={form.carry_waivers} onCheckedChange={(v) => set('carry_waivers', v)} label="Manter justificativas e falsos positivos nos próximos commits do PR" />
        <Switch checked={form.post_comments} onCheckedChange={(v) => set('post_comments', v)} label="Comentar o resumo no PR/MR" />
        <Switch checked={form.review_drafts} onCheckedChange={(v) => set('review_drafts', v)} label="Revisar PRs em rascunho" />
        <Switch checked={form.enabled} onCheckedChange={(v) => set('enabled', v)} label="Repositório habilitado" />

        {admin && (
          <>
            <FormSection>IA (administrador)</FormSection>
            <Field label="Modelo deste repositório" hint="Vazio = o do perfil ou o padrão global">
              <Select value={form.model_id} onChange={(e) => set('model_id', e.target.value)}>
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
          </>
        )}
      </fieldset>
      {canWrite && (
        <div className="snt-between">
          <Button
            variant="ghost-danger"
            icon={<Trash2 size={16} />}
            onClick={async () => {
              const r = await confirm({ title: `Remover ${repo.full_name}?`, description: 'PRs, gates e revisões do repositório são apagados.', confirmLabel: 'Remover' });
              if (!r.confirmed) return;
              await remove.mutateAsync(repo.id);
              onRemoved();
            }}
          >
            Remover
          </Button>
          <Button type="submit" variant="primary" loading={update.isPending}>
            Salvar
          </Button>
        </div>
      )}
    </form>
  );
}

function toForm(r: Repository) {
  return {
    profile_ids: r.profiles.map((p) => p.id),
    enforcement: r.enforcement,
    gate_mode: r.gate_mode,
    gated_branches: r.gated_branches,
    status_context: r.status_context,
    merge_method: r.merge_method,
    approval_mode: r.approval_mode,
    human_min_severity: r.human_min_severity,
    block_severity: r.block_severity,
    min_approvals: String(r.min_approvals),
    carry_waivers: r.carry_waivers,
    post_comments: r.post_comments,
    review_drafts: r.review_drafts,
    enabled: r.enabled,
    model_id: r.model_id ?? '',
  };
}

function ProtectionPanel({ repo, team }: { repo: Repository; team: string }) {
  const report = useProtection(team, repo.id);
  const github = repo.integration.provider === 'github';
  return (
    <div className="snt-stack">
      <div className="snt-between">
        <strong>Diagnóstico da branch {report.data?.branch ?? repo.gated_branches[0]}</strong>
        <Button size="sm" variant="secondary" icon={<RefreshCw size={14} />} onClick={() => void report.refetch()} loading={report.isFetching}>
          Verificar de novo
        </Button>
      </div>
      {report.isLoading ? (
        <Spinner label="Consultando o provedor…" />
      ) : report.isError ? (
        <Callout tone="warning" title="Não foi possível consultar">
          {(report.error as Error).message}. O token precisa de permissão de administração para ler a proteção da branch.
        </Callout>
      ) : (
        report.data && (
          <Card>
            {report.data.checks.map((c) => (
              <div key={c.name} className="snt-check">
                {c.ok ? (
                  <CircleCheck size={18} className="snt-check-ok" />
                ) : (
                  <CircleAlert size={18} className={c.required ? 'snt-check-fail' : 'snt-check-warn'} />
                )}
                <div>
                  <strong>{c.name}</strong> {!c.required && <Tag variant="neutral">recomendado</Tag>}
                  <div className="snt-small snt-muted">{c.detail}</div>
                </div>
              </div>
            ))}
          </Card>
        )
      )}
      <Callout tone="info" title={github ? 'Como travar o merge no GitHub' : 'Como travar o merge no GitLab'} icon={<Lock size={18} />}>
        {github ? (
          <ol style={{ margin: 0, paddingLeft: 18 }}>
            <li>
              Settings → Rules → Rulesets (ou Branches → Branch protection) na branch {repo.gated_branches.join(', ')}.
            </li>
            <li>
              Ative “Require status checks to pass” e adicione <InlineCode>{repo.status_context}</InlineCode>; de preferência
              vindo do GitHub App do Sentinela.
            </li>
            <li>Desmarque o bypass de administradores.</li>
            {repo.gate_mode !== 'status_check' && <li>Para o merge pela plataforma, restrinja quem faz push/merge ao usuário-robô.</li>}
          </ol>
        ) : (
          <ol style={{ margin: 0, paddingLeft: 18 }}>
            <li>Settings → Repository → Protected branches: proteja {repo.gated_branches.join(', ')}.</li>
            <li>
              Settings → Merge requests: ative “Pipelines must succeed”. O status <InlineCode>{repo.status_context}</InlineCode> entra
              no pipeline do MR.
            </li>
            <li>Desative “Skipped pipelines are considered successful”.</li>
            {repo.gate_mode !== 'status_check' && <li>Em “Allowed to merge”, deixe só o usuário-robô do Sentinela.</li>}
          </ol>
        )}
      </Callout>
    </div>
  );
}

function WebhookPanel({ repo, team, canWrite }: { repo: Repository; team: string; canWrite: boolean }) {
  const { webhook, sync } = useRepositoryActions(team);
  return (
    <div className="snt-stack">
      <Field label="URL do webhook" hint={`Evento: ${repo.integration.provider === 'github' ? 'Pull requests' : 'Merge request events'}; o segredo fica na integração`}>
        <div className="snt-inline">
          <code className="snt-mono" style={{ wordBreak: 'break-all' }}>
            {repo.webhook_url}
          </code>
          <CopyButton value={repo.webhook_url} label="Copiar URL" />
        </div>
      </Field>
      <div className="snt-inline">
        {repo.webhook_configured ? (
          <Badge tone="success">
            {repo.last_webhook_at ? (
              <>
                último evento <RelativeTime value={repo.last_webhook_at} />
              </>
            ) : (
              'criado'
            )}
          </Badge>
        ) : (
          <Badge tone="pending">nenhum evento recebido</Badge>
        )}
      </div>
      {canWrite && (
        <div className="snt-inline">
          <Button
            variant="secondary"
            icon={<Webhook size={16} />}
            loading={webhook.isPending}
            onClick={async () => {
              await webhook.mutateAsync(repo.id);
              toast.success('Webhook criado no provedor');
            }}
          >
            Configurar webhook automaticamente
          </Button>
          <Button
            variant="secondary"
            icon={<RefreshCw size={16} />}
            loading={sync.isPending}
            onClick={async () => {
              const r = await sync.mutateAsync(repo.id);
              toast.success('Sincronizado', `${r.pull_requests} PR(s) aberto(s), ${r.reviews_queued} revisão(ões) na fila.`);
            }}
          >
            Sincronizar PRs abertos
          </Button>
        </div>
      )}
      <span className="snt-small snt-muted">
        Última sincronização: {repo.last_sync_at ? <RelativeTime value={repo.last_sync_at} /> : 'nunca'}. Use quando o
        webhook ficou fora do ar: o Sentinela busca os PRs abertos e revisa os commits que ainda não viu.
      </span>
    </div>
  );
}
