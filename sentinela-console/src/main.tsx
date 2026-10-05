import 'broto-ui/fonts.css';
import 'broto-ui/styles.css';
import './styles.css';

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { initAuth } from './api/auth';
import { request } from './api/client';
import type { Config } from './api/types';
import { App } from './App';
import { BootError, BootMessage } from './pages/BootScreens';

async function boot() {
  const container = document.getElementById('root');
  if (!container) throw new Error('#root ausente');
  const root = createRoot(container);

  let config: Config;
  try {
    config = await request<Config>('GET', '/config', { anonymous: true });
  } catch (error) {
    root.render(<BootError error={error} />);
    return;
  }

  try {
    const auth = await initAuth(config);
    if (auth.status === 'redirecting') {
      root.render(<BootMessage message="Redirecionando para o login…" />);
      return;
    }
  } catch (error) {
    root.render(<BootError error={error} title="Falha na autenticação" />);
    return;
  }

  root.render(
    <StrictMode>
      <App config={config} />
    </StrictMode>,
  );
}

void boot();
