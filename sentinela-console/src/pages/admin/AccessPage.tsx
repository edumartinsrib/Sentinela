import {
  Badge,
  Button,
  Callout,
  Card,
  DataTable,
  Dialog,
  EmptyState,
  Field,
  FormGrid,
  Input,
  KeyValue,
  Page,
  PageHeader,
  RelativeTime,
  Segmented,
  Select,
  Stack,
  Switch,
  Tag,
  toast,
  useDocumentTitle,
} from 'broto-ui';
import { Pencil, Plus, UserPlus } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useAdminActions, useGlobalRoles, useRoleActions, useTeamRoles, useUsers } from '../../api/queries';
import type { Role, RoleBinding, User } from '../../api/types';
import { useTeam } from '../../lib/context';
import { ROLE, ROLE_HINT } from '../../lib/labels';

export function AccessPage() {
  const { team, can } = useTeam();
  const admin = can('global.admin');
  const roles = useTeamRoles(team.name, can('team.admin'));
  const globalRoles = useGlobalRoles(admin);
  const users = useUsers(can('team.admin'));
  const [granting, setGranting] = useState<'team' | 'global' | null>(null);
  const [editing, setEditing] = useState<User | null>(null);
  const [creatingTeam, setCreatingTeam] = useState(false);
  const teamActions = useRoleActions(team.name);
  const globalActions = useRoleActions(null);
  useDocumentTitle('Acesso', 'Sentinela');

  const roleColumns = (revoke: (id: string) => void) => [
    {
      key: 'who',
      header: 'Pessoa ou grupo',
      cell: (b: RoleBinding) => (b.username ? <strong>{b.display_name || b.username}</strong> : <Tag mono>grupo: {b.group}</Tag>),
    },
    { key: 'role', header: 'Papel', cell: (b: RoleBinding) => <Badge tone="brand">{ROLE[b.role]}</Badge> },
    { key: 'hint', header: 'Pode', cell: (b: RoleBinding) => <span className="snt-small snt-muted">{ROLE_HINT[b.role]}</span> },
    { key: 'by', header: 'Concedido por', cell: (b: RoleBinding) => b.created_by ?? '—' },
    {
      key: 'actions',
      header: '',
      actions: true,
      cell: (b: RoleBinding) => (
        <Button size="sm" variant="ghost-danger" onClick={() => revoke(b.id)}>
          Remover
        </Button>
      ),
    },
  ];

  return (
    <Page>
      <PageHeader
        title="Acesso"
        description="Papéis no time e logins dos provedores. O login do GitHub/GitLab de cada pessoa é o que impede o autor de aprovar o próprio PR."
        actions={
          <>
            {admin && (
              <Button variant="secondary" icon={<Plus size={16} />} onClick={() => setCreatingTeam(true)}>
                Novo time
              </Button>
            )}
            <Button variant="primary" icon={<UserPlus size={16} />} onClick={() => setGranting('team')}>
              Dar papel no time
            </Button>
          </>
        }
      />
      <Card title={`Papéis em ${team.display_name}`} flush>
        <DataTable<RoleBinding>
          rows={roles.data}
          loading={roles.isLoading}
          getRowId={(b) => b.id}
          empty={<EmptyState compact title="Ninguém com papel neste time" />}
          columns={roleColumns((id) => void teamActions.revoke.mutateAsync(id))}
        />
      </Card>
      {admin && (
        <Card
          title="Papéis em todos os times"
          subtitle="Ex.: grupo do Entra ID de tech leads"
          flush
          actions={
            <Button size="sm" variant="secondary" icon={<Plus size={14} />} onClick={() => setGranting('global')}>
              Papel global
            </Button>
          }
        >
          <DataTable<RoleBinding>
            rows={globalRoles.data}
            loading={globalRoles.isLoading}
            getRowId={(b) => b.id}
            empty={<EmptyState compact title="Nenhum papel global" />}
            columns={roleColumns((id) => void globalActions.revoke.mutateAsync(id))}
          />
        </Card>
      )}
      <Card title="Usuários" flush>
        <DataTable<User>
          rows={users.data}
          loading={users.isLoading}
          getRowId={(u) => u.id}
          columns={[
            {
              key: 'name',
              header: 'Usuário',
              cell: (u) => (
                <span>
                  <strong>{u.display_name || u.username}</strong>
                  {u.is_superadmin && (
                    <>
                      {' '}
                      <Badge tone="brand" size="sm">
                        admin global
                      </Badge>
                    </>
                  )}
                  <br />
                  <span className="snt-small snt-muted">{u.username}</span>
                </span>
              ),
            },
            { key: 'gh', header: 'GitHub', cell: (u) => (u.github_login ? <Tag mono>{u.github_login}</Tag> : '—') },
            { key: 'gl', header: 'GitLab', cell: (u) => (u.gitlab_username ? <Tag mono>{u.gitlab_username}</Tag> : '—') },
            { key: 'last', header: 'Último acesso', cell: (u) => <RelativeTime value={u.last_login_at} fallback="nunca" /> },
            {
              key: 'actions',
              header: '',
              actions: true,
              hidden: !admin,
              cell: (u) => (
                <Button size="sm" variant="ghost" icon={<Pencil size={14} />} onClick={() => setEditing(u)}>
                  Editar
                </Button>
              ),
            },
          ]}
        />
      </Card>
      <GrantDialog scope={granting} onClose={() => setGranting(null)} />
      <UserDialog user={editing} onClose={() => setEditing(null)} />
      <TeamDialog open={creatingTeam} onClose={() => setCreatingTeam(false)} />
    </Page>
  );
}

function GrantDialog({ scope, onClose }: { scope: 'team' | 'global' | null; onClose: () => void }) {
  const { team } = useTeam();
  const actions = useRoleActions(scope === 'team' ? team.name : null);
  const [kind, setKind] = useState<'user' | 'group'>('user');
  const [who, setWho] = useState('');
  const [role, setRole] = useState<Role>('developer');
  useEffect(() => {
    if (scope) {
      setWho('');
      setRole('developer');
    }
  }, [scope]);
  return (
    <Dialog
      open={!!scope}
      onClose={onClose}
      title={scope === 'global' ? 'Papel em todos os times' : `Papel em ${team.display_name}`}
      onSubmit={async () => {
        await actions.grant.mutateAsync(kind === 'user' ? { username: who, role } : { group: who, role });
        toast.success('Papel concedido');
        onClose();
      }}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit" variant="primary" disabled={!who.trim()} loading={actions.grant.isPending}>
            Conceder
          </Button>
        </>
      }
    >
      <Stack gap={14}>
        <Segmented<'user' | 'group'>
          value={kind}
          onChange={setKind}
          options={[
            { value: 'user', label: 'Usuário' },
            { value: 'group', label: 'Grupo do SSO' },
          ]}
        />
        <Field label={kind === 'user' ? 'Usuário' : 'Grupo (id ou nome do claim groups)'} required>
          <Input value={who} onChange={(e) => setWho(e.target.value)} />
        </Field>
        <Field label="Papel" hint={ROLE_HINT[role]}>
          <Select value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {(Object.keys(ROLE) as Role[]).map((r) => (
              <option key={r} value={r}>
                {ROLE[r]}
              </option>
            ))}
          </Select>
        </Field>
      </Stack>
    </Dialog>
  );
}

function UserDialog({ user, onClose }: { user: User | null; onClose: () => void }) {
  const actions = useAdminActions();
  const [form, setForm] = useState({ display_name: '', email: '', github_login: '', gitlab_username: '', is_superadmin: false });
  useEffect(() => {
    if (user)
      setForm({
        display_name: user.display_name ?? '',
        email: user.email ?? '',
        github_login: user.github_login ?? '',
        gitlab_username: user.gitlab_username ?? '',
        is_superadmin: user.is_superadmin,
      });
  }, [user]);
  if (!user) return null;
  return (
    <Dialog
      open={!!user}
      onClose={onClose}
      title={`Editar ${user.username}`}
      onSubmit={async () => {
        await actions.updateUser.mutateAsync({ id: user.id, body: form });
        toast.success('Usuário salvo');
        onClose();
      }}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit" variant="primary" loading={actions.updateUser.isPending}>
            Salvar
          </Button>
        </>
      }
    >
      <Stack gap={14}>
        <KeyValue items={[['Usuário', user.username]]} />
        <FormGrid>
          <Field label="Nome">
            <Input value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
          </Field>
          <Field label="E-mail">
            <Input value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </Field>
          <Field label="Login no GitHub">
            <Input value={form.github_login} onChange={(e) => setForm({ ...form, github_login: e.target.value })} />
          </Field>
          <Field label="Usuário no GitLab">
            <Input value={form.gitlab_username} onChange={(e) => setForm({ ...form, gitlab_username: e.target.value })} />
          </Field>
        </FormGrid>
        <Switch checked={form.is_superadmin} onCheckedChange={(v) => setForm({ ...form, is_superadmin: v })} label="Administrador global" />
        <Callout tone="info">Só administradores globais mudam os logins: é o vínculo que impede a autoaprovação.</Callout>
      </Stack>
    </Dialog>
  );
}

function TeamDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const actions = useAdminActions();
  const [name, setName] = useState('');
  const [display, setDisplay] = useState('');
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Novo time"
      onSubmit={async () => {
        await actions.createTeam.mutateAsync({ name, display_name: display || name });
        toast.success('Time criado');
        setName('');
        setDisplay('');
        onClose();
      }}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit" variant="primary" disabled={!name} loading={actions.createTeam.isPending}>
            Criar
          </Button>
        </>
      }
    >
      <Stack gap={14}>
        <Field label="Identificador" hint="minúsculas, números e hífen (vai na URL)" required>
          <Input value={name} onChange={(e) => setName(e.target.value.toLowerCase())} className="snt-mono" />
        </Field>
        <Field label="Nome exibido">
          <Input value={display} onChange={(e) => setDisplay(e.target.value)} />
        </Field>
      </Stack>
    </Dialog>
  );
}
