// Permissões do console derivadas de Me.roles para o time atual (espelham security/auth.py).

import type { Me, Role } from '../api/types';

export type Action =
  | 'standards.write'
  | 'repo.write'
  | 'review.run'
  | 'gate.approve'
  | 'audit.view'
  | 'team.admin'
  | 'global.admin';

const ALLOWED: Record<Exclude<Action, 'global.admin'>, Role[]> = {
  'standards.write': ['admin', 'tech_lead'],
  'repo.write': ['admin', 'tech_lead'],
  'review.run': ['admin', 'tech_lead', 'reviewer', 'developer'],
  'gate.approve': ['admin', 'tech_lead', 'reviewer'],
  'audit.view': ['admin', 'tech_lead'],
  'team.admin': ['admin'],
};

export function rolesFor(me: Me | undefined, team: string | undefined): Set<Role> {
  const set = new Set<Role>();
  if (!me) return set;
  for (const r of me.roles) if (r.team === null || r.team === team) set.add(r.role);
  return set;
}

export function makeCan(me: Me | undefined, team: string | undefined): (action: Action) => boolean {
  const roles = rolesFor(me, team);
  const superadmin = !!me?.is_superadmin;
  return (action) => {
    if (superadmin) return true;
    if (action === 'global.admin') return false;
    return ALLOWED[action].some((r) => roles.has(r));
  };
}

export function topRole(roles: Set<Role>): Role | null {
  for (const r of ['admin', 'tech_lead', 'reviewer', 'developer', 'reader'] as Role[]) if (roles.has(r)) return r;
  return null;
}
