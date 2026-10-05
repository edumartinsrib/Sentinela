// Autenticação do console.
// - modo `dev`: o usuário digita um nome na tela de login; vai no cabeçalho X-Sentinela-User.
// - modo `oidc`: authorization code + PKCE com oidc-client-ts; o access token vai como Bearer.

import type { UserManager } from 'oidc-client-ts';
import { readStorage, writeStorage } from 'broto-ui';
import { configureClient } from './client';
import type { Config } from './types';

const DEV_USER_KEY = 'sentinela.devUser';
export const CALLBACK_PATH = '/auth/callback';

let manager: UserManager | null = null;
let mode: Config['auth']['mode'] = 'dev';

export function getDevUser(): string | null {
  return readStorage(DEV_USER_KEY);
}

export function setDevUser(username: string): void {
  writeStorage(DEV_USER_KEY, username.trim().toLowerCase());
}

export function clearDevUser(): void {
  writeStorage(DEV_USER_KEY, null);
}

export function authMode(): Config['auth']['mode'] {
  return mode;
}

function currentPath(): string {
  return window.location.pathname + window.location.search + window.location.hash;
}

export async function signIn(returnTo = currentPath()): Promise<void> {
  if (mode === 'oidc' && manager) {
    await manager.signinRedirect({ state: { returnTo } });
    return;
  }
  const next = returnTo && !returnTo.startsWith('/login') ? `?next=${encodeURIComponent(returnTo)}` : '';
  window.location.assign(`/login${next}`);
}

export async function signOut(): Promise<void> {
  if (mode === 'oidc' && manager) {
    await manager.removeUser();
    try {
      await manager.signoutRedirect();
    } catch {
      window.location.assign('/');
    }
    return;
  }
  clearDevUser();
  window.location.assign('/login');
}

export type AuthBootResult = { status: 'ready' } | { status: 'redirecting' };

export async function initAuth(config: Config): Promise<AuthBootResult> {
  mode = config.auth.mode;

  if (mode === 'dev') {
    configureClient({
      headers: async (): Promise<Record<string, string>> => {
        const user = getDevUser();
        return user ? { 'X-Sentinela-User': user } : {};
      },
      onUnauthorized: () => {
        if (!window.location.pathname.startsWith('/login')) {
          clearDevUser();
          void signIn();
        }
      },
    });
    return { status: 'ready' };
  }

  const { UserManager, WebStorageStateStore } = await import('oidc-client-ts');
  const requested = config.auth.scopes ?? [];
  const scopes = Array.from(new Set(['openid', 'profile', ...requested])).join(' ');
  manager = new UserManager({
    authority: config.auth.authority ?? '',
    client_id: config.auth.client_id ?? '',
    redirect_uri: `${window.location.origin}${CALLBACK_PATH}`,
    post_logout_redirect_uri: `${window.location.origin}/`,
    response_type: 'code',
    scope: scopes,
    automaticSilentRenew: true,
    userStore: new WebStorageStateStore({ store: window.sessionStorage }),
  });

  const mgr = manager;
  configureClient({
    headers: async (): Promise<Record<string, string>> => {
      const user = await mgr.getUser();
      return user?.access_token ? { Authorization: `Bearer ${user.access_token}` } : {};
    },
    onUnauthorized: () => {
      void signIn();
    },
  });

  if (window.location.pathname === CALLBACK_PATH) {
    const user = await mgr.signinRedirectCallback();
    const state = user.state as { returnTo?: string } | undefined;
    const target = state?.returnTo && state.returnTo !== CALLBACK_PATH ? state.returnTo : '/';
    window.history.replaceState(null, '', target);
    return { status: 'ready' };
  }

  const user = await mgr.getUser();
  if (!user || user.expired) {
    try {
      await mgr.signinSilent();
      return { status: 'ready' };
    } catch {
      await mgr.signinRedirect({ state: { returnTo: currentPath() } });
      return { status: 'redirecting' };
    }
  }
  return { status: 'ready' };
}
