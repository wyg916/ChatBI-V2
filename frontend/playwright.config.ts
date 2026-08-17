import { defineConfig } from '@playwright/test';

const webBase = process.env.CHATBI_WEB_BASE ?? 'http://127.0.0.1:5173';
const webPort = new URL(webBase).port || '5173';

export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  timeout: 90_000,
  fullyParallel: false,
  retries: 0,
  preserveOutput: 'always',
  reporter: [['list']],
  use: {
    baseURL: webBase,
    browserName: 'chromium',
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
  },
  webServer: {
    command: `npm run dev -- --host 127.0.0.1 --port ${webPort}`,
    url: webBase,
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
