import { expect, test, type APIResponse } from '@playwright/test';
import { analystCredentials, loginApi } from './auth';
import { captureRuntimeErrors } from './runtime-errors';

const apiBase = process.env.CHATBI_API_BASE ?? 'http://127.0.0.1:8000/api/v1';

type JsonRecord = Record<string, any>;

async function json(response: APIResponse): Promise<any> {
  expect(response.ok(), `${response.status()} ${response.url()}\n${await response.text()}`).toBeTruthy();
  return response.json();
}

test('Day4-RBAC01 ANALYST 仅访问授权资源且拒绝事件进入审计', async ({ request }) => {
  const sources = await json(await request.get(`${apiBase}/datasources`)) as JsonRecord[];
  const restricted = sources.find((item) => item.type === 'mysql');
  expect(restricted).toBeTruthy();
  const models = await json(await request.get(`${apiBase}/semantic-models`)) as JsonRecord[];
  const restrictedModel = models.find((item) => item.datasource_id === restricted.id);
  expect(restrictedModel).toBeTruthy();

  const analyst = await loginApi(analystCredentials.email, analystCredentials.password);
  const visibleSources = await json(await analyst.get(`${apiBase}/datasources`)) as JsonRecord[];
  expect(visibleSources.length).toBeGreaterThan(0);
  expect(visibleSources.every((item) => item.type === 'postgresql')).toBe(true);
  expect((await analyst.get(`${apiBase}/datasources/${restricted.id}`)).status()).toBe(403);
  expect((await analyst.get(`${apiBase}/semantic-models/${restrictedModel.id}`)).status()).toBe(403);
  expect((await analyst.get(`${apiBase}/model-providers`)).status()).toBe(403);
  expect((await analyst.get(`${apiBase}/security/overview`)).status()).toBe(403);
  await analyst.dispose();

  const overview = await json(await request.get(`${apiBase}/security/overview`));
  expect(overview.users.map((item: JsonRecord) => item.role)).toEqual(expect.arrayContaining(['ADMIN', 'ANALYST']));
  expect(overview.audit_events.some((item: JsonRecord) => item.actor_email === 'analyst@chatbi.local' && item.status === 'DENIED')).toBe(true);
});

test('Day4-UI14 Permission Denied 使用真实 Backend 403 状态', async ({ page }) => {
  const runtime = captureRuntimeErrors(page, [403]);
  await page.context().clearCookies();
  const login = await page.request.post(`${apiBase}/auth/login`, { data: analystCredentials });
  expect(login.ok()).toBeTruthy();
  await page.goto('/settings/security');
  await expect(page.getByTestId('permission-denied')).toContainText('仅 ADMIN');
  await expect(page.getByRole('heading', { name: '用户、角色与审计' })).toBeVisible();
  expect(runtime).toEqual({ consoleErrors: [], pageErrors: [], blockingRequestErrors: [] });
});
