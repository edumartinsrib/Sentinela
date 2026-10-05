// Consultas e mutações (TanStack Query) sobre a API do Sentinela.

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, type Query } from './client';
import type {
  AiEngine,
  AiModel,
  AuditEntry,
  Dashboard,
  Finding,
  Integration,
  Library,
  Me,
  Page,
  Profile,
  ProfileSummary,
  ProtectionReport,
  PullRequest,
  PullRequestDetail,
  RegistrationToken,
  RemoteRepository,
  Repository,
  Review,
  RoleBinding,
  Rule,
  RuleSpec,
  Runner,
  Team,
  User,
  WebhookDelivery,
} from './types';

const t = (team: string) => `/teams/${encodeURIComponent(team)}`;

// ------------------------------------------------------------------------- leitura
export const useMe = () => useQuery({ queryKey: ['me'], queryFn: () => api.get<Me>('/me'), staleTime: 60_000 });

export const useDashboard = (team: string) =>
  useQuery({ queryKey: ['dashboard', team], queryFn: () => api.get<Dashboard>(`${t(team)}/dashboard`) });

export interface PrFilters {
  state?: string;
  gate?: string[];
  repository?: string;
  q?: string;
  limit?: number;
  offset?: number;
}

export const usePullRequests = (team: string, filters: PrFilters) =>
  useQuery({
    queryKey: ['prs', team, filters],
    queryFn: () => api.get<Page<PullRequest>>(`${t(team)}/pull-requests`, filters as Query),
    placeholderData: keepPreviousData,
  });

export const usePullRequest = (team: string, id: string) =>
  useQuery({
    queryKey: ['pr', team, id],
    queryFn: () => api.get<PullRequestDetail>(`${t(team)}/pull-requests/${id}`),
  });

export const useReviewLogs = (team: string, id: string | undefined) =>
  useQuery({
    queryKey: ['review-logs', team, id],
    queryFn: () => api.get<{ lines: { ts: string; stream: string; text: string }[] }>(`${t(team)}/reviews/${id}/logs`),
    enabled: !!id,
  });

export const useProfiles = (team: string) =>
  useQuery({ queryKey: ['profiles', team], queryFn: () => api.get<ProfileSummary[]>(`${t(team)}/profiles`) });

export const useProfile = (team: string, id: string) =>
  useQuery({ queryKey: ['profile', team, id], queryFn: () => api.get<Profile>(`${t(team)}/profiles/${id}`) });

export const useLibrary = () =>
  useQuery({ queryKey: ['library'], queryFn: () => api.get<Library>('/library'), staleTime: 10 * 60_000 });

export const useRepositories = (team: string) =>
  useQuery({ queryKey: ['repos', team], queryFn: () => api.get<Repository[]>(`${t(team)}/repositories`) });

export const useProtection = (team: string, id: string | null) =>
  useQuery({
    queryKey: ['protection', team, id],
    queryFn: () => api.get<ProtectionReport>(`${t(team)}/repositories/${id}/protection`),
    enabled: !!id,
    retry: false,
    meta: { silent: true },
  });

export const useIntegrations = () =>
  useQuery({ queryKey: ['integrations'], queryFn: () => api.get<Integration[]>('/integrations') });

export const useRemoteRepositories = (integrationId: string | null, search: string) =>
  useQuery({
    queryKey: ['remote-repos', integrationId, search],
    queryFn: () =>
      api.get<RemoteRepository[]>(`/integrations/${integrationId}/remote-repositories`, { search }),
    enabled: !!integrationId,
    retry: false,
    meta: { silent: true },
  });

export const useDeliveries = (integrationId: string | null) =>
  useQuery({
    queryKey: ['deliveries', integrationId],
    queryFn: () => api.get<WebhookDelivery[]>(`/integrations/${integrationId}/deliveries`),
    enabled: !!integrationId,
  });

export const useEngines = () => useQuery({ queryKey: ['engines'], queryFn: () => api.get<AiEngine[]>('/ai/engines') });
export const useModels = () => useQuery({ queryKey: ['models'], queryFn: () => api.get<AiModel[]>('/ai/models') });
export const useRunners = () =>
  useQuery({ queryKey: ['runners'], queryFn: () => api.get<Runner[]>('/runners'), refetchInterval: 15_000 });
export const useRunnerTokens = (enabled: boolean) =>
  useQuery({ queryKey: ['runner-tokens'], queryFn: () => api.get<RegistrationToken[]>('/runner-tokens'), enabled });
export const useUsers = (enabled = true) =>
  useQuery({ queryKey: ['users'], queryFn: () => api.get<User[]>('/users'), enabled });
export const useTeamRoles = (team: string, enabled: boolean) =>
  useQuery({ queryKey: ['roles', team], queryFn: () => api.get<RoleBinding[]>(`${t(team)}/roles`), enabled });
export const useGlobalRoles = (enabled: boolean) =>
  useQuery({ queryKey: ['global-roles'], queryFn: () => api.get<RoleBinding[]>('/roles'), enabled });
export const useTeams = () => useQuery({ queryKey: ['teams'], queryFn: () => api.get<Team[]>('/teams') });

export const useAudit = (team: string, filters: Query) =>
  useQuery({
    queryKey: ['audit', team, filters],
    queryFn: () => api.get<Page<AuditEntry>>(`${t(team)}/audit`, filters),
    placeholderData: keepPreviousData,
  });

// ------------------------------------------------------------------------- escrita
function useInvalidate() {
  const qc = useQueryClient();
  return (...keys: unknown[][]) => Promise.all(keys.map((queryKey) => qc.invalidateQueries({ queryKey })));
}

export function usePrActions(team: string, prId: string) {
  const qc = useQueryClient();
  const invalidate = useInvalidate();
  const refresh = (data?: PullRequestDetail) => {
    if (data) qc.setQueryData(['pr', team, prId], data);
    return invalidate(['pr', team, prId], ['prs', team], ['dashboard', team]);
  };
  const base = `${t(team)}/pull-requests/${prId}`;
  return {
    approve: useMutation({
      mutationFn: (comment: string | null) => api.post<PullRequestDetail>(`${base}/approve`, { comment }),
      onSuccess: refresh,
    }),
    reject: useMutation({
      mutationFn: (comment: string) => api.post<PullRequestDetail>(`${base}/reject`, { comment }),
      onSuccess: refresh,
    }),
    override: useMutation({
      mutationFn: (reason: string) => api.post<PullRequestDetail>(`${base}/override`, { reason }),
      onSuccess: refresh,
    }),
    rerun: useMutation({
      mutationFn: (modelId: string | null) => api.post<Review>(`${base}/reviews`, { model_id: modelId }),
      onSuccess: () => refresh(),
    }),
    merge: useMutation({
      mutationFn: (method: string | null) =>
        api.post<{ merged: boolean; sha: string | null; message: string | null }>(`${base}/merge`, { method }),
      onSuccess: () => refresh(),
    }),
    finding: useMutation({
      mutationFn: ({ id, action, reason }: { id: string; action: string; reason: string }) =>
        api.post<Finding>(`${t(team)}/findings/${id}/${action}`, { reason }),
      onSuccess: () => refresh(),
    }),
    cancelReview: useMutation({
      mutationFn: (reviewId: string) => api.post<Review>(`${t(team)}/reviews/${reviewId}/cancel`),
      onSuccess: () => refresh(),
    }),
  };
}

export function useProfileActions(team: string) {
  const invalidate = useInvalidate();
  const done = (id?: string) => invalidate(['profiles', team], id ? ['profile', team, id] : ['profile', team]);
  return {
    create: useMutation({
      mutationFn: (body: Record<string, unknown>) => api.post<Profile>(`${t(team)}/profiles`, body),
      onSuccess: (p) => done(p.id),
    }),
    update: useMutation({
      mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) =>
        api.patch<Profile>(`${t(team)}/profiles/${id}`, body),
      onSuccess: (p) => done(p.id),
    }),
    remove: useMutation({
      mutationFn: (id: string) => api.delete(`${t(team)}/profiles/${id}`),
      onSuccess: () => done(),
    }),
    importYaml: useMutation({
      mutationFn: (body: { yaml: string; replace: boolean }) => api.post<Profile>(`${t(team)}/profiles/import`, body),
      onSuccess: (p) => done(p.id),
    }),
    addLibrary: useMutation({
      mutationFn: ({ id, keys }: { id: string; keys: string[] }) =>
        api.post<Profile>(`${t(team)}/profiles/${id}/library`, { keys }),
      onSuccess: (p) => done(p.id),
    }),
    createRule: useMutation({
      mutationFn: ({ profileId, body }: { profileId: string; body: RuleSpec }) =>
        api.post<Rule>(`${t(team)}/profiles/${profileId}/rules`, body),
      onSuccess: (_r, v) => done(v.profileId),
    }),
    updateRule: useMutation({
      mutationFn: ({ profileId, ruleId, body }: { profileId: string; ruleId: string; body: Partial<RuleSpec> }) =>
        api.patch<Rule>(`${t(team)}/profiles/${profileId}/rules/${ruleId}`, body),
      onSuccess: (_r, v) => done(v.profileId),
    }),
    deleteRule: useMutation({
      mutationFn: ({ profileId, ruleId }: { profileId: string; ruleId: string }) =>
        api.delete(`${t(team)}/profiles/${profileId}/rules/${ruleId}`),
      onSuccess: (_r, v) => done(v.profileId),
    }),
  };
}

export function useRepositoryActions(team: string) {
  const invalidate = useInvalidate();
  const done = () => invalidate(['repos', team], ['profiles', team], ['prs', team]);
  return {
    create: useMutation({
      mutationFn: (body: Record<string, unknown>) => api.post<Repository>(`${t(team)}/repositories`, body),
      onSuccess: done,
    }),
    update: useMutation({
      mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) =>
        api.patch<Repository>(`${t(team)}/repositories/${id}`, body),
      onSuccess: done,
    }),
    remove: useMutation({
      mutationFn: (id: string) => api.delete(`${t(team)}/repositories/${id}`),
      onSuccess: done,
    }),
    sync: useMutation({
      mutationFn: (id: string) =>
        api.post<{ pull_requests: number; reviews_queued: number }>(`${t(team)}/repositories/${id}/sync`),
      onSuccess: done,
    }),
    webhook: useMutation({
      mutationFn: (id: string) => api.post<Repository>(`${t(team)}/repositories/${id}/webhook`),
      onSuccess: done,
    }),
  };
}

export function useAdminActions() {
  const invalidate = useInvalidate();
  return {
    createEngine: useMutation({
      mutationFn: (body: Record<string, unknown>) => api.post<AiEngine>('/ai/engines', body),
      onSuccess: () => invalidate(['engines'], ['models']),
    }),
    updateEngine: useMutation({
      mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) =>
        api.patch<AiEngine>(`/ai/engines/${id}`, body),
      onSuccess: () => invalidate(['engines'], ['models']),
    }),
    engineSecrets: useMutation({
      mutationFn: ({ id, values }: { id: string; values: Record<string, string | null> }) =>
        api.put<AiEngine>(`/ai/engines/${id}/secrets`, { values }),
      onSuccess: () => invalidate(['engines']),
    }),
    createModel: useMutation({
      mutationFn: (body: Record<string, unknown>) => api.post<AiModel>('/ai/models', body),
      onSuccess: () => invalidate(['engines'], ['models']),
    }),
    updateModel: useMutation({
      mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) =>
        api.patch<AiModel>(`/ai/models/${id}`, body),
      onSuccess: () => invalidate(['engines'], ['models']),
    }),
    deleteModel: useMutation({
      mutationFn: (id: string) => api.delete(`/ai/models/${id}`),
      onSuccess: () => invalidate(['engines'], ['models']),
    }),
    setDefaultModel: useMutation({
      mutationFn: (modelId: string) => api.put<AiModel>('/ai/default', { model_id: modelId }),
      onSuccess: () => invalidate(['engines'], ['models']),
    }),
    createIntegration: useMutation({
      mutationFn: (body: Record<string, unknown>) => api.post<Integration>('/integrations', body),
      onSuccess: () => invalidate(['integrations']),
    }),
    updateIntegration: useMutation({
      mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) =>
        api.patch<Integration>(`/integrations/${id}`, body),
      onSuccess: () => invalidate(['integrations']),
    }),
    checkIntegration: useMutation({
      mutationFn: (id: string) => api.post<{ ok: boolean; login: string | null; detail: string }>(`/integrations/${id}/check`),
      onSuccess: () => invalidate(['integrations']),
    }),
    deleteIntegration: useMutation({
      mutationFn: (id: string) => api.delete(`/integrations/${id}`),
      onSuccess: () => invalidate(['integrations']),
    }),
    webhookSecret: useMutation({
      mutationFn: (id: string) => api.get<{ webhook_url: string; webhook_secret: string }>(`/integrations/${id}/webhook-secret`),
    }),
    updateRunner: useMutation({
      mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) => api.patch<Runner>(`/runners/${id}`, body),
      onSuccess: () => invalidate(['runners']),
    }),
    deleteRunner: useMutation({
      mutationFn: (id: string) => api.delete(`/runners/${id}`),
      onSuccess: () => invalidate(['runners']),
    }),
    createToken: useMutation({
      mutationFn: (body: { description: string; expires_in_days: number | null }) =>
        api.post<RegistrationToken>('/runner-tokens', body),
      onSuccess: () => invalidate(['runner-tokens']),
    }),
    revokeToken: useMutation({
      mutationFn: (id: string) => api.delete(`/runner-tokens/${id}`),
      onSuccess: () => invalidate(['runner-tokens']),
    }),
    createUser: useMutation({
      mutationFn: (body: Record<string, unknown>) => api.post<User>('/users', body),
      onSuccess: () => invalidate(['users']),
    }),
    updateUser: useMutation({
      mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) => api.patch<User>(`/users/${id}`, body),
      onSuccess: () => invalidate(['users'], ['me']),
    }),
    createTeam: useMutation({
      mutationFn: (body: Record<string, unknown>) => api.post<Team>('/teams', body),
      onSuccess: () => invalidate(['teams'], ['me']),
    }),
  };
}

export function useRoleActions(team: string | null) {
  const invalidate = useInvalidate();
  const base = team ? `${t(team)}/roles` : '/roles';
  const key = team ? ['roles', team] : ['global-roles'];
  return {
    grant: useMutation({
      mutationFn: (body: { username?: string; group?: string; role: string }) => api.post<RoleBinding>(base, body),
      onSuccess: () => invalidate(key, ['me']),
    }),
    revoke: useMutation({
      mutationFn: (id: string) => api.delete(`${base}/${id}`),
      onSuccess: () => invalidate(key, ['me']),
    }),
  };
}

export const patternTest = (team: string, body: { pattern: string; sample: string; ignore_case: boolean }) =>
  api.post<{ valid: boolean; error: string | null; matches: { line: number; text: string; match: string }[] }>(
    `${t(team)}/pattern-test`,
    body,
  );
