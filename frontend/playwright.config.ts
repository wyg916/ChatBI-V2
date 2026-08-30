import { defineConfig } from '@playwright/test';
import { adminStorageState } from './e2e/auth';

const webBase = process.env.CHATBI_WEB_BASE ?? 'http://127.0.0.1:5173';
const webPort = new URL(webBase).port || '5173';
const storageState = process.env.CHATBI_E2E_STORAGE_STATE ?? adminStorageState;
const e2eProfile = process.env.CHATBI_E2E_PROFILE ?? 'core';
const coreProfileOnlyTests = [
  '**/data-workspace.spec.ts',
  '**/phase2-recorded-vision.spec.ts',
  '**/phase5-control-certification.spec.ts',
  '**/phase5-visible-control-inventory.spec.ts',
];

export default defineConfig({
  testDir: './e2e',
  testIgnore: e2eProfile === 'core' ? coreProfileOnlyTests : [],
  globalSetup: './e2e/global-setup.ts',
  timeout: 90_000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  preserveOutput: 'always',
  reporter: [['list']],
  use: {
    baseURL: webBase,
    browserName: 'chromium',
    viewport: { width: 1440, height: 900 },
    storageState,
    trace: 'retain-on-failure',
  },
  webServer: {
    command: `npm run dev -- --host 127.0.0.1 --port ${webPort}`,
    url: webBase,
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
