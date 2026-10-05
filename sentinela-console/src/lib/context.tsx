import { createContext, useContext } from 'react';
import type { Config, Me, Team } from '../api/types';
import type { Action } from './permissions';

export const ConfigContext = createContext<Config | null>(null);

export function useConfig(): Config {
  const ctx = useContext(ConfigContext);
  if (!ctx) throw new Error('ConfigContext ausente');
  return ctx;
}

export interface TeamContextValue {
  team: Team;
  me: Me;
  can: (action: Action) => boolean;
  /** Prefixo das rotas do time atual: `/t/<nome>`. */
  base: string;
}

export const TeamContext = createContext<TeamContextValue | null>(null);

export function useTeam(): TeamContextValue {
  const ctx = useContext(TeamContext);
  if (!ctx) throw new Error('TeamContext ausente');
  return ctx;
}
