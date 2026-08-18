import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

const runtimeEnv = (
  globalThis as typeof globalThis & {
    process?: { env?: Record<string, string | undefined> };
  }
).process?.env;
const proxyTarget = runtimeEnv?.CHATBI_PROXY_TARGET ?? runtimeEnv?.VITE_BACKEND_PROXY_TARGET ?? 'http://localhost:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: proxyTarget, changeOrigin: true },
      '/health': { target: proxyTarget, changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    include: ['src/**/*.test.{ts,tsx}'],
    css: true,
  },
});
