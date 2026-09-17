import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const runtimeEnv = (
  globalThis as typeof globalThis & {
    process?: { env?: Record<string, string | undefined> };
  }
).process?.env;
const proxyTarget = runtimeEnv?.CHATBI_PROXY_TARGET ?? runtimeEnv?.VITE_BACKEND_PROXY_TARGET ?? 'http://localhost:8000';

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          const normalized = id.replaceAll('\\', '/');
          if (normalized.includes('/node_modules/zrender/')) return 'zrender';
          return undefined;
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: proxyTarget, changeOrigin: true },
      '/health': { target: proxyTarget, changeOrigin: true },
    },
  },
});
