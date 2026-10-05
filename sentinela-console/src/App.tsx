import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ConfirmProvider, PageLoading, Toaster, UIProvider, toast } from 'broto-ui';
import { LucideProvider } from 'lucide-react';
import { lazy, Suspense, useState, type ComponentType } from 'react';
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from 'react-router';
import { authMode, getDevUser } from './api/auth';
import { isApiError } from './api/client';
import type { Config } from './api/types';
import { TeamLayout, TeamRedirect } from './components/Layout';
import { RouterLink } from './components/RouterLink';
import { ConfigContext } from './lib/context';
import { LoginPage } from './pages/LoginPage';
import { NotFoundPage } from './pages/NotFoundPage';

declare module '@tanstack/react-query' {
  interface Register {
    queryMeta: { silent?: boolean };
    mutationMeta: { silent?: boolean };
  }
}

function page<T extends Record<string, unknown>>(loader: () => Promise<T>, name: keyof T) {
  return lazy(async () => ({ default: (await loader())[name] as ComponentType }));
}

const DashboardPage = page(() => import('./pages/DashboardPage'), 'DashboardPage');
const PullRequestsPage = page(() => import('./pages/PullRequestsPage'), 'PullRequestsPage');
const PullRequestPage = page(() => import('./pages/PullRequestPage'), 'PullRequestPage');
const ProfilesPage = page(() => import('./pages/ProfilesPage'), 'ProfilesPage');
const ProfilePage = page(() => import('./pages/ProfilePage'), 'ProfilePage');
const RepositoriesPage = page(() => import('./pages/RepositoriesPage'), 'RepositoriesPage');
const AuditPage = page(() => import('./pages/AuditPage'), 'AuditPage');
const AiPage = page(() => import('./pages/admin/AiPage'), 'AiPage');
const IntegrationsPage = page(() => import('./pages/admin/IntegrationsPage'), 'IntegrationsPage');
const RunnersPage = page(() => import('./pages/admin/RunnersPage'), 'RunnersPage');
const AccessPage = page(() => import('./pages/admin/AccessPage'), 'AccessPage');

function errorMessage(error: unknown): { title: string; details?: string[] } {
  if (isApiError(error)) return { title: error.detail, details: error.errors };
  return { title: error instanceof Error ? error.message : 'Algo deu errado.' };
}

function makeQueryClient() {
  return new QueryClient({
    queryCache: new QueryCache({
      onError: (error, query) => {
        // Erros da primeira carga aparecem na própria tela; aqui só avisamos
        // quando uma atualização em segundo plano falha.
        if (query.meta?.silent || query.state.data === undefined) return;
        if (isApiError(error) && error.status === 401) return;
        toast.error('Falha ao atualizar os dados', errorMessage(error).title);
      },
    }),
    mutationCache: new MutationCache({
      onError: (error, _vars, _ctx, mutation) => {
        if (mutation.meta?.silent) return;
        if (isApiError(error) && error.status === 401) return;
        const { title, details } = errorMessage(error);
        toast.error(title, { details });
      },
    }),
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        refetchOnWindowFocus: false,
        retry: (count, error) => {
          if (isApiError(error) && [400, 401, 403, 404, 422].includes(error.status)) return false;
          return count < 2;
        },
      },
    },
  });
}

function RequireAuth() {
  const location = useLocation();
  if (authMode() === 'dev' && !getDevUser()) {
    const next = location.pathname + location.search;
    return <Navigate to={`/login${next && next !== '/' ? `?next=${encodeURIComponent(next)}` : ''}`} replace />;
  }
  return <Outlet />;
}

function PageSuspense() {
  return (
    <Suspense fallback={<PageLoading label="Abrindo a tela…" />}>
      <Outlet />
    </Suspense>
  );
}

export function App({ config }: { config: Config }) {
  const [client] = useState(makeQueryClient);
  return (
    <ConfigContext.Provider value={config}>
      <QueryClientProvider client={client}>
        <UIProvider linkComponent={RouterLink}>
          <LucideProvider strokeWidth={1.5} size={18}>
            <ConfirmProvider>
              <BrowserRouter>
                <Routes>
                  <Route path="/login" element={<LoginPage />} />
                  <Route path="/auth/callback" element={<Navigate to="/" replace />} />
                  <Route element={<RequireAuth />}>
                    <Route path="/" element={<TeamRedirect />} />
                    <Route path="/t/:team" element={<TeamLayout />}>
                      <Route element={<PageSuspense />}>
                        <Route index element={<DashboardPage />} />
                        <Route path="pull-requests" element={<PullRequestsPage />} />
                        <Route path="pull-requests/:id" element={<PullRequestPage />} />
                        <Route path="padroes" element={<ProfilesPage />} />
                        <Route path="padroes/:id" element={<ProfilePage />} />
                        <Route path="repositorios" element={<RepositoriesPage />} />
                        <Route path="auditoria" element={<AuditPage />} />
                        <Route path="admin/ia" element={<AiPage />} />
                        <Route path="admin/integracoes" element={<IntegrationsPage />} />
                        <Route path="admin/runners" element={<RunnersPage />} />
                        <Route path="admin/acesso" element={<AccessPage />} />
                        <Route path="*" element={<NotFoundPage inShell />} />
                      </Route>
                    </Route>
                  </Route>
                  <Route path="*" element={<NotFoundPage />} />
                </Routes>
              </BrowserRouter>
              <Toaster />
            </ConfirmProvider>
          </LucideProvider>
        </UIProvider>
      </QueryClientProvider>
    </ConfigContext.Provider>
  );
}
