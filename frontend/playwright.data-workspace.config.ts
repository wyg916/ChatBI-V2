import { defineConfig } from '@playwright/test';
import { adminStorageState } from './e2e/auth';

export default defineConfig({
  testDir: './e2e',
  testMatch: 'data-workspace.spec.ts',
  globalSetup: './e2e/global-setup.ts',
  timeout: 90_000,
  fullyParallel: false,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:5174',
    browserName: 'chromium',
    viewport: { width: 1440, height: 900 },
    storageState: adminStorageState,
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 5174',
    url: 'http://127.0.0.1:5174',
    reuseExistingServer: true,
    timeout: 60_000,
    env: { VITE_BACKEND_PROXY_TARGET: 'http://127.0.0.1:8020' },
  },
});
