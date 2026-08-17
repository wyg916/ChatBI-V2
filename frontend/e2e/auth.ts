import fs from 'node:fs';
import path from 'node:path';
import { request, type APIRequestContext } from '@playwright/test';

export const apiBase = process.env.CHATBI_API_BASE ?? 'http://127.0.0.1:8000/api/v1';
export const adminStorageState = path.resolve('test-results/.auth/admin.json');

function localEnvironment(): Record<string, string> {
  const envPath = path.resolve('..', '.env');
  if (!fs.existsSync(envPath)) return {};
  return Object.fromEntries(
    fs.readFileSync(envPath, 'utf8').split(/\r?\n/).flatMap((line) => {
      const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/);
      if (!match) return [];
      return [[match[1], match[2].replace(/^(['"])(.*)\1$/, '$2')]];
    }),
  );
}

const local = localEnvironment();

export const adminCredentials = {
  email: 'admin@chatbi.local',
  password: process.env.CHATBI_BOOTSTRAP_ADMIN_PASSWORD ?? local.CHATBI_BOOTSTRAP_ADMIN_PASSWORD ?? '',
};

export const analystCredentials = {
  email: 'analyst@chatbi.local',
  password: process.env.CHATBI_BOOTSTRAP_ANALYST_PASSWORD ?? local.CHATBI_BOOTSTRAP_ANALYST_PASSWORD ?? '',
};

export async function loginApi(email: string, password: string): Promise<APIRequestContext> {
  if (!password) throw new Error(`Missing local bootstrap password for ${email}`);
  const context = await request.newContext();
  const response = await context.post(`${apiBase}/auth/login`, { data: { email, password } });
  if (!response.ok()) {
    await context.dispose();
    throw new Error(`Login failed for ${email}: HTTP ${response.status()}`);
  }
  return context;
}
