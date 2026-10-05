import {
  Badge,
  Button,
  Callout,
  Card,
  CodeBlock,
  DataTable,
  Dialog,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Menu,
  Page,
  PageHeader,
  RelativeTime,
  SecretBox,
  SegmentBar,
  Select,
  Stack,
  Tag,
  formatDateTime,
  toast,
  useConfirm,
  useDocumentTitle,
} from 'broto-ui';
import { KeyRound, Pause, Play, Plus, Server, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useAdminActions, useRunnerTokens, useRunners } from '../../api/queries';
import type { RegistrationToken, Runner } from '../../api/types';
import { useConfig, useTeam } from '../../lib/context';
import { ENGINE_LABEL } from '../../lib/labels';

export function RunnersPage() {
  const { can } = useTeam();
  const admin = can('global.admin');
  const runners = useRunners();
  const tokens = useRunnerTokens(admin);
  const actions = useAdminActions();
  const confirm = useConfirm();
  const [creating, setCreating] = useState(false);
  useDocumentTitle('Runners', 'Sentinela');

  return (
    <Page>
      <PageHeader
        title="Runners"
        description="Agentes que pegam as revisões da fila, baixam o código do PR e executam o Claude Code ou a Copilot CLI em modo somente leitura. Rode quantos quiser: cada um anuncia as ferramentas instaladas."
        actions={
          admin && (
            <Button variant="primary" icon={<KeyRound size={16} />} onClick={() => setCreating(true)}>
              Token de registro
            </Button>
          )
        }
      />
      <Card flush>
        {runners.isError ? (
          <ErrorState error={runners.error} onRetry={() => void runners.refetch()} />
        ) : (
          <DataTable<Runner>
            rows={runners.data}
            loading={runners.isLoading}
            getRowId={(r) => r.id}
            empty={<EmptyState compact icon={<Server size={22} />} title="Nenhum runner registrado" description="Crie um token de registro e suba o sentinela-runner." />}
            columns={[
              {
                key: 'name',
                header: 'Runner',
                cell: (r) => (
                  <span>
                    <strong>{r.name}</strong>
                    <br />
                    <span className="snt-small snt-muted">
                      {r.hostname} · {r.os} · v{r.agent_version}
                    </span>
                  </span>
                ),
              },
              {
                key: 'status',
                header: 'Situação',
                cell: (r) =>
                  !r.enabled ? (
                    <Badge tone="neutral">desabilitado</Badge>
                  ) : r.draining ? (
                    <Badge tone="pending">drenando</Badge>
                  ) : r.status === 'online' ? (
                    <Badge tone="live" pulse={r.running_reviews.length > 0}>
                      online
                    </Badge>
                  ) : (
                    <Badge tone="danger">offline</Badge>
                  ),
                nowrap: true,
              },
              {
                key: 'engines',
                header: 'Ferramentas',
                cell: (r) => (
                  <span className="snt-inline">
                    {Object.entries(r.engines).map(([k, v]) => (
                      <Tag key={k} title={v}>
                        {ENGINE_LABEL[k] ?? k}
                      </Tag>
                    ))}
                  </span>
                ),
              },
              { key: 'slots', header: 'Ocupação', cell: (r) => <SegmentBar used={r.running_reviews.length} total={r.slots} unit="slots" /> },
              { key: 'hb', header: 'Último sinal', cell: (r) => <RelativeTime value={r.last_heartbeat_at} />, nowrap: true },
              {
                key: 'actions',
                header: '',
                actions: true,
                hidden: !admin,
                cell: (r) => (
                  <Menu
                    label={`Ações de ${r.name}`}
                    items={[
                      {
                        label: r.draining ? 'Retomar' : 'Drenar (termina as atuais e para de pegar)',
                        icon: r.draining ? <Play size={16} /> : <Pause size={16} />,
                        onSelect: () => void actions.updateRunner.mutateAsync({ id: r.id, body: { draining: !r.draining } }),
                      },
                      {
                        label: r.enabled ? 'Desabilitar' : 'Habilitar',
                        onSelect: () => void actions.updateRunner.mutateAsync({ id: r.id, body: { enabled: !r.enabled } }),
                      },
                      'separator',
                      {
                        label: 'Remover',
                        icon: <Trash2 size={16} />,
                        danger: true,
                        onSelect: async () => {
                          const c = await confirm({ title: `Remover ${r.name}?`, description: 'Ele precisará de um token de registro para voltar.', confirmLabel: 'Remover' });
                          if (c.confirmed) await actions.deleteRunner.mutateAsync(r.id);
                        },
                      },
                    ]}
                  />
                ),
              },
            ]}
          />
        )}
      </Card>
      {admin && (
        <Card title="Tokens de registro" subtitle="Usados só no primeiro boot do runner; depois ele usa o próprio token" flush>
          <DataTable<RegistrationToken>
            compact
            rows={tokens.data}
            loading={tokens.isLoading}
            getRowId={(t) => t.id}
            empty={<EmptyState compact title="Nenhum token" />}
            columns={[
              { key: 'desc', header: 'Descrição', cell: (t) => t.description },
              { key: 'by', header: 'Criado por', cell: (t) => t.created_by ?? '—' },
              { key: 'exp', header: 'Validade', cell: (t) => (t.expires_at ? formatDateTime(t.expires_at) : 'sem validade') },
              { key: 'used', header: 'Último uso', cell: (t) => <RelativeTime value={t.last_used_at} fallback="nunca" /> },
              {
                key: 'st',
                header: 'Situação',
                cell: (t) => (t.revoked_at ? <Badge tone="neutral">revogado</Badge> : <Badge tone="success">ativo</Badge>),
              },
              {
                key: 'actions',
                header: '',
                actions: true,
                cell: (t) =>
                  !t.revoked_at && (
                    <Button size="sm" variant="ghost-danger" onClick={() => void actions.revokeToken.mutateAsync(t.id)}>
                      Revogar
                    </Button>
                  ),
              },
            ]}
          />
        </Card>
      )}
      <TokenDialog open={creating} onClose={() => setCreating(false)} />
    </Page>
  );
}

function TokenDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const config = useConfig();
  const actions = useAdminActions();
  const [description, setDescription] = useState('runners linux');
  const [days, setDays] = useState('30');
  const [token, setToken] = useState<string | null>(null);
  const close = () => {
    setToken(null);
    onClose();
  };
  return (
    <Dialog
      open={open}
      onClose={close}
      size="lg"
      title="Token de registro de runner"
      onSubmit={
        token
          ? undefined
          : async () => {
              const created = await actions.createToken.mutateAsync({ description, expires_in_days: days ? Number(days) : null });
              setToken(created.token ?? null);
              toast.success('Token criado');
            }
      }
      footer={
        token ? (
          <Button variant="primary" onClick={close}>
            Concluir
          </Button>
        ) : (
          <>
            <Button variant="ghost" onClick={close}>
              Cancelar
            </Button>
            <Button type="submit" variant="primary" icon={<Plus size={16} />} loading={actions.createToken.isPending}>
              Criar token
            </Button>
          </>
        )
      }
    >
      {token ? (
        <Stack gap={14}>
          <Callout tone="warning">Copie agora: o token não é mostrado de novo.</Callout>
          <SecretBox value={token} />
          <CodeBlock>{`docker run -d --name sentinela-runner \\
  -e SENTINELA_API_URL=${config.public_api_url} \\
  -e SENTINELA_REGISTRATION_TOKEN=${token} \\
  -e ANTHROPIC_API_KEY=... \\
  -v sentinela-runner:/var/lib/sentinela-runner \\
  sentinela-runner:latest`}</CodeBlock>
        </Stack>
      ) : (
        <Stack gap={14}>
          <Field label="Descrição" required>
            <Input value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          <Field label="Validade">
            <Select value={days} onChange={(e) => setDays(e.target.value)}>
              <option value="1">1 dia</option>
              <option value="7">7 dias</option>
              <option value="30">30 dias</option>
              <option value="365">1 ano</option>
              <option value="">Sem validade</option>
            </Select>
          </Field>
        </Stack>
      )}
    </Dialog>
  );
}
