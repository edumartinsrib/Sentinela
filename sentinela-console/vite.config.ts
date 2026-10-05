import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// Proxy de desenvolvimento: a API fica atrás do mesmo host do console, como no nginx.
export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, process.cwd(), ''), ...process.env };
  const apiTarget = env.SENTINELA_API_UPSTREAM || 'http://localhost:8000';
  const proxy = {
    '/api': { target: apiTarget, changeOrigin: true },
    '/webhooks': { target: apiTarget, changeOrigin: true },
  };

  return {
    plugins: [react()],
    // broto-ui instalada a partir do .tgz: uma cópia só do React.
    resolve: { dedupe: ['react', 'react-dom'] },
    server: { port: 5173, proxy },
    preview: { port: 4173, proxy },
    build: { sourcemap: false, chunkSizeWarningLimit: 900 },
  };
});
