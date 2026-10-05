import { useQueryClient } from '@tanstack/react-query';
import {
  AppShell,
  ContextSwitcher,
  FullScreenLoader,
  type NavEntry,
  NotFound,
  SidebarStatus,
  StatusCard,
  Tag,
  Button,
  LinkButton,
  UserMenu,
} from 'broto-ui';
import {
  Bot,
  BookCheck,
  FolderGit2,
  GitPullRequest,
  KeyRound,
  LayoutDashboard,
  LogOut,
  PlugZap,
  ScrollText,
  Server,
  Users,
} from 'lucide-react';
import { useEffect, useMemo } from 'react';
import { Navigate, Outlet, useLocation, useParams } from 'react-router';
import { signOut } from '../api/auth';
import { useDashboard, useMe } from '../api/queries';
import { openStream, setGlobalStreamStatus, useGlobalStreamStatus } from '../api/sse';
import { useConfig, TeamContext } from '../lib/context';
import { ROLE } from '../lib/labels';
import { makeCan, rolesFor, topRole } from '../lib/permissions';
import { SentinelaBrand } from './Brand';

/** `/` → primeiro time visível. */
export function TeamRedirect() {
  const me = useMe();
  if (me.isLoading) return <FullScreenLoader brand={<SentinelaBrand tone="dark" />} label="Carregando…" />;
  const first = me.data?.teams[0];
  if (!first) {
    return (
      <StatusCard
        brand={<SentinelaBrand tone="dark" />}
        title="Você ainda não participa de nenhum time"
        description="Peça a um administrador para incluir você em um time do Sentinela."
        action={
          <Button variant="secondary" onClick={() => void signOut()}>
            Sair
          </Button>
        }
      />
    );
  }
  return <Navigate to={`/t/${first.name}`} replace />;
}

function useTeamEvents(team: string) {
  const qc = useQueryClient();
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const pending = new Set<string>();
    const flush = () => {
      timer = undefined;
      for (const key of pending) void qc.invalidateQueries({ queryKey: [key, team] });
      pending.clear();
    };
    const close = openStream(`/teams/${encodeURIComponent(team)}/events`, {
      onEvent: (type, data) => {
        const prId = (data as { pull_request_id?: string } | null)?.pull_request_id;
        pending.add('prs');
        pending.add('dashboard');
        if (prId) void qc.invalidateQueries({ queryKey: ['pr', team, prId] });
        if (type === 'review' || type === 'gate') pending.add('repos');
        if (!timer) timer = setTimeout(flush, 400);
      },
      onStatus: setGlobalStreamStatus,
    });
    return () => {
      close();
      if (timer) clearTimeout(timer);
    };
  }, [qc, team]);
}

export function TeamLayout() {
  const { team: teamName = '' } = useParams();
  const { pathname } = useLocation();
  const config = useConfig();
  const me = useMe();
  const status = useGlobalStreamStatus();
  const team = me.data?.teams.find((x) => x.name === teamName);
  const dash = useDashboard(teamName);
  useTeamEvents(teamName);

  const value = useMemo(() => {
    if (!me.data || !team) return null;
    return { team, me: me.data, can: makeCan(me.data, team.name), base: `/t/${team.name}` };
  }, [me.data, team]);

  if (me.isLoading) return <FullScreenLoader brand={<SentinelaBrand tone="dark" />} label="Carregando…" />;
  if (!me.data) return <Navigate to="/login" replace />;
  if (!value) {
    return (
      <NotFound
        title="Time não encontrado"
        description={`O time "${teamName}" não existe ou você não tem acesso a ele.`}
        action={
          <LinkButton href="/" variant="primary">
            Ir para o início
          </LinkButton>
        }
      />
    );
  }

  const { base, can } = value;
  const roles = rolesFor(me.data, teamName);
  const role = me.data.is_superadmin ? 'Administrador global' : (topRole(roles) && ROLE[topRole(roles)!]) || '';
  const awaiting = dash.data?.kpis.awaiting_approval;
  const nav: NavEntry[] = [
    { label: 'Painel', href: base, icon: <LayoutDashboard size={20} />, end: true },
    {
      label: 'Pull requests',
      href: `${base}/pull-requests`,
      icon: <GitPullRequest size={20} />,
      badge: awaiting ? awaiting : undefined,
    },
    { label: 'Padrões', href: `${base}/padroes`, icon: <BookCheck size={20} /> },
    { label: 'Repositórios', href: `${base}/repositorios`, icon: <FolderGit2 size={20} /> },
    { label: 'Auditoria', href: `${base}/auditoria`, icon: <ScrollText size={20} />, hidden: !can('audit.view') },
    { heading: 'Administração' },
    { label: 'IA e modelos', href: `${base}/admin/ia`, icon: <Bot size={20} /> },
    { label: 'Integrações', href: `${base}/admin/integracoes`, icon: <PlugZap size={20} />, hidden: !can('global.admin') },
    { label: 'Runners', href: `${base}/admin/runners`, icon: <Server size={20} /> },
    { label: 'Acesso', href: `${base}/admin/acesso`, icon: <Users size={20} />, hidden: !can('team.admin') },
  ];

  return (
    <TeamContext.Provider value={value}>
      <AppShell
        brand={<SentinelaBrand />}
        brandHref={base}
        nav={nav}
        currentPath={pathname}
        storageKey="sentinela.sidebar"
        sidebarFooter={
          <SidebarStatus
            live={status === 'open'}
            label={status === 'open' ? 'Tempo real ativo' : status === 'reconnecting' ? 'Reconectando…' : 'Conectando…'}
            detail={`v${config.version}`}
          />
        }
        topbarStart={
          <ContextSwitcher
            label="Time"
            value={value.team.display_name}
            icon={<Users size={16} />}
            badge={me.data.teams.length > 1 ? <Tag mono>{me.data.teams.length}</Tag> : undefined}
            items={me.data.teams.map((x) => ({ label: x.display_name, href: `/t/${x.name}` }))}
            aria-label="Trocar de time"
          />
        }
        topbarEnd={
          <UserMenu
            name={me.data.display_name || me.data.username}
            role={role}
            items={[
              { heading: me.data.username },
              ...(me.data.github_login ? [{ label: `GitHub: ${me.data.github_login}`, icon: <KeyRound size={16} />, disabled: true }] : []),
              { label: 'Sair', icon: <LogOut size={16} />, onSelect: () => void signOut() },
            ]}
          />
        }
      >
        <Outlet />
      </AppShell>
    </TeamContext.Provider>
  );
}
