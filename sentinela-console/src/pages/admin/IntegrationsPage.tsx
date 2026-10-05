import {
  Badge,
  Button,
  Callout,
  Card,
  CopyButton,
  DataTable,
  Dialog,
  Drawer,
  EmptyState,
  ErrorState,
  Field,
  FormGrid,
  Input,
  KeyValue,
  Page,
  PageHeader,
  RelativeTime,
  SecretBox,
  Segmented,
  Stack,
  Switch,
  Tag,
  formatDateTime,
  toast,
  useConfirm,
  useDocumentTitle,
} from 'broto-ui';
import { KeyRound, Plus, PlugZap, RefreshCw, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useAdminActions, useDeliveries, useIntegrations } from '../../api/queries';
import type { Integration, Provider, WebhookDelivery } from '../../api/types';

export function IntegrationsPage() {
  const integrations = useIntegrations();
  const [creating, setCreating] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  useDocumentTitle('Integrações', 'Sentinela');
  const current = integrations.data?.find((i) => i.id === openId) ?? null;

  return (
    <Page>
      <PageHeader
        title="Integrações"
        description="Conexões com GitHub (github.com ou Enterprise) e GitLab (gitlab.com ou self-managed). O token fica cifrado no cofre; cada integração tem a própria URL e o próprio segredo de webhook."
        actions={
          <Button variant="primary" icon={<Plus size={16} />} onClick={() => setCreating(true)}>
            Nova integração
          </Button>
        }
      />
      <Card flush>
        {integrations.isError ? (
          <ErrorState error={integrations.error} onRetry={() => void integrations.refetch()} />
        ) : (
          <DataTable<Integration>
            rows={integrations.data}
            loading={integrations.isLoading}
            getRowId={(i) => i.id}
            activeRowId={openId}
            onRowClick={(i) => setOpenId(i.id)}
            empty={<EmptyState compact icon={<PlugZap size={22} />} title="Nenhuma integração" description="Cadastre o GitHub ou o GitLab da empresa." />}
            columns={[
              { key: 'name', header: 'Nome', cell: (i) => <strong>{i.name}</strong> },
              { key: 'provider', header: 'Provedor', cell: (i) => <Tag display>{i.provider === 'github' ? 'GitHub' : 'GitLab'}</Tag> },
              { key: 'url', header: 'Endereço', cell: (i) => <span className="snt-mono">{i.web_url}</span> },
              { key: 'bot', header: 'Usuário-robô', cell: (i) => i.bot_login ?? '—' },
              {
                key: 'check',
                header: 'Conexão',
                cell: (i) =>
                  i.last_check_ok === null ? (
                    <Badge tone="neutral">não testada</Badge>
                  ) : i.last_check_ok ? (
                    <Badge tone="success">ok</Badge>
                  ) : (
                    <Badge tone="danger" title={i.last_check_detail ?? ''}>
                      falhou
                    </Badge>
                  ),
              },
              { key: 'repos', header: 'Repositórios', cell: (i) => i.repositories, align: 'right' },
            ]}
          />
        )}
      </Card>
      <CreateIntegrationDialog open={creating} onClose={() => setCreating(false)} />
      {current && <IntegrationDrawer integration={current} onClose={() => setOpenId(null)} />}
    </Page>
  );
}

function CreateIntegrationDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const actions = useAdminActions();
  const [provider, setProvider] = useState<Provider>('github');
  const [name, setName] = useState('');
  const [webUrl, setWebUrl] = useState('');
  const [apiUrl, setApiUrl] = useState('');
  const [token, setToken] = useState('');
  useEffect(() => {
    if (open) {
      setName('');
      setWebUrl('');
      setApiUrl('');
      setToken('');
    }
  }, [open]);
  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title="Nova integração"
      onSubmit={async () => {
        const created = await actions.createIntegration.mutateAsync({
          name,
          provider,
          web_url: webUrl || null,
          api_url: apiUrl || null,
          token,
        });
        if (created.last_check_ok) toast.success('Integração criada', `Autenticado como ${created.bot_login}.`);
        else toast.warning('Integração criada, mas o teste falhou', created.last_check_detail ?? '');
        onClose();
      }}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit" variant="primary" disabled={!name || !token} loading={actions.createIntegration.isPending}>
            Criar e testar
          </Button>
        </>
      }
    >
      <Stack gap={14}>
        <Segmented<Provider>
          value={provider}
          onChange={setProvider}
          options={[
            { value: 'github', label: 'GitHub' },
            { value: 'gitlab', label: 'GitLab' },
          ]}
        />
        <FormGrid>
          <Field label="Nome" required>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={provider === 'github' ? 'GitHub da empresa' : 'GitLab da empresa'} />
          </Field>
          <Field label="Endereço web" hint={provider === 'github' ? 'Vazio = https://github.com' : 'Vazio = https://gitlab.com'}>
            <Input value={webUrl} onChange={(e) => setWebUrl(e.target.value)} placeholder={provider === 'github' ? 'https://github.empresa.com' : 'https://gitlab.empresa.com'} />
          </Field>
          <Field label="Endereço da API" hint="Vazio = calculado a partir do endereço web">
            <Input value={apiUrl} onChange={(e) => setApiUrl(e.target.value)} />
          </Field>
          <Field label="Token" required hint={provider === 'github' ? 'GitHub App, PAT fine-grained ou token do usuário-robô' : 'Token de projeto/grupo ou do usuário-robô, escopo api'}>
            <Input type="password" value={token} onChange={(e) => setToken(e.target.value)} autoComplete="off" />
          </Field>
        </FormGrid>
        <Callout tone="info" title="Permissões do token">
          {provider === 'github'
            ? 'Contents: leitura · Pull requests: leitura e escrita · Commit statuses: leitura e escrita · Webhooks: escrita (para criar o webhook) · Administration: leitura (diagnóstico da proteção).'
            : 'Escopo api (status de commit, notas, merge e webhooks) e read_repository. Para o merge pela plataforma, o usuário precisa poder fazer merge na branch protegida.'}
        </Callout>
      </Stack>
    </Dialog>
  );
}

function IntegrationDrawer({ integration, onClose }: { integration: Integration; onClose: () => void }) {
  const actions = useAdminActions();
  const deliveries = useDeliveries(integration.id);
  const confirm = useConfirm();
  const [secret, setSecret] = useState<string | null>(null);
  const [token, setToken] = useState('');
  return (
    <Drawer open onClose={onClose} size="lg" title={integration.name} description={integration.web_url}>
      <Stack gap={16}>
        <KeyValue
          items={[
            ['Provedor', integration.provider === 'github' ? 'GitHub' : 'GitLab'],
            ['API', <span className="snt-mono">{integration.api_url}</span>],
            ['Usuário-robô', integration.bot_login ?? '—'],
            ['Último teste', integration.last_check_at ? `${formatDateTime(integration.last_check_at)} — ${integration.last_check_detail ?? ''}` : '—'],
            [
              'URL do webhook',
              <span className="snt-inline">
                <span className="snt-mono" style={{ wordBreak: 'break-all' }}>
                  {integration.webhook_url}
                </span>
                <CopyButton value={integration.webhook_url} />
              </span>,
            ],
          ]}
        />
        <div className="snt-inline">
          <Button
            variant="secondary"
            icon={<RefreshCw size={16} />}
            loading={actions.checkIntegration.isPending}
            onClick={async () => {
              const r = await actions.checkIntegration.mutateAsync(integration.id);
              if (r.ok) toast.success('Conexão ok', r.detail);
              else toast.error('Conexão falhou', r.detail);
            }}
          >
            Testar conexão
          </Button>
          <Button
            variant="secondary"
            icon={<KeyRound size={16} />}
            onClick={async () => {
              const r = await actions.webhookSecret.mutateAsync(integration.id);
              setSecret(r.webhook_secret);
            }}
          >
            Mostrar segredo do webhook
          </Button>
          <Switch
            checked={integration.enabled}
            onCheckedChange={(v) => void actions.updateIntegration.mutateAsync({ id: integration.id, body: { enabled: v } })}
            label="Habilitada"
          />
        </div>
        {secret && (
          <Card title="Segredo do webhook" subtitle="Use no campo Secret (GitHub) ou Secret token (GitLab). A leitura fica na auditoria.">
            <SecretBox value={secret} />
          </Card>
        )}
        <Card title="Trocar o token">
          <form
            className="snt-inline"
            onSubmit={async (e) => {
              e.preventDefault();
              await actions.updateIntegration.mutateAsync({ id: integration.id, body: { token } });
              setToken('');
              toast.success('Token atualizado');
            }}
          >
            <Input type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="novo token" autoComplete="off" />
            <Button type="submit" variant="secondary" disabled={!token}>
              Salvar token
            </Button>
            <Button
              variant="ghost"
              onClick={async () => {
                const r = await confirm({
                  title: 'Gerar um novo segredo de webhook?',
                  description: 'Os webhooks já configurados param de ser aceitos até receberem o novo segredo.',
                  confirmLabel: 'Gerar',
                });
                if (r.confirmed) {
                  await actions.updateIntegration.mutateAsync({ id: integration.id, body: { rotate_webhook_secret: true } });
                  toast.success('Novo segredo gerado');
                }
              }}
            >
              Gerar novo segredo de webhook
            </Button>
          </form>
        </Card>
        <Card title="Webhooks recebidos" subtitle="Últimas 50 entregas" flush>
          <DataTable<WebhookDelivery>
            compact
            rows={deliveries.data}
            loading={deliveries.isLoading}
            getRowId={(d) => String(d.id)}
            empty={<EmptyState compact title="Nenhuma entrega ainda" />}
            columns={[
              { key: 'at', header: 'Quando', cell: (d) => <RelativeTime value={d.received_at} />, nowrap: true },
              { key: 'ev', header: 'Evento', cell: (d) => <span className="snt-small">{[d.event, d.action].filter(Boolean).join(' / ')}</span> },
              { key: 'repo', header: 'Repositório', cell: (d) => <span className="snt-small snt-mono">{d.repository ?? '—'}{d.number ? ` #${d.number}` : ''}</span> },
              {
                key: 'out',
                header: 'Resultado',
                cell: (d) => (
                  <Badge tone={d.outcome === 'processed' ? 'success' : d.outcome === 'rejected' ? 'danger' : 'neutral'} title={d.detail ?? ''}>
                    {d.outcome === 'processed' ? 'processado' : d.outcome === 'rejected' ? 'recusado' : 'ignorado'}
                  </Badge>
                ),
              },
            ]}
          />
        </Card>
        <div>
          <Button
            variant="ghost-danger"
            icon={<Trash2 size={16} />}
            disabled={integration.repositories > 0}
            title={integration.repositories > 0 ? 'Remova os repositórios antes' : ''}
            onClick={async () => {
              const r = await confirm({ title: `Excluir ${integration.name}?`, confirmLabel: 'Excluir' });
              if (r.confirmed) {
                await actions.deleteIntegration.mutateAsync(integration.id);
                onClose();
              }
            }}
          >
            Excluir integração
          </Button>
        </div>
      </Stack>
    </Drawer>
  );
}
