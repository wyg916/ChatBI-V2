import { expect, test, type APIResponse } from '@playwright/test';

const apiBase = process.env.CHATBI_API_BASE ?? 'http://127.0.0.1:8000/api/v1';
const analystHeaders = { 'X-ChatBI-Actor': 'analyst@chatbi.local' };

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

  const visibleSources = await json(await request.get(`${apiBase}/datasources`, { headers: analystHeaders })) as JsonRecord[];
  expect(visibleSources.length).toBeGreaterThan(0);
  expect(visibleSources.every((item) => item.type === 'postgresql')).toBe(true);
  expect((await request.get(`${apiBase}/datasources/${restricted.id}`, { headers: analystHeaders })).status()).toBe(403);
  expect((await request.get(`${apiBase}/semantic-models/${restrictedModel.id}`, { headers: analystHeaders })).status()).toBe(403);
  expect((await request.get(`${apiBase}/model-providers`, { headers: analystHeaders })).status()).toBe(403);
  expect((await request.get(`${apiBase}/security/overview`, { headers: analystHeaders })).status()).toBe(403);

  const overview = await json(await request.get(`${apiBase}/security/overview`));
  expect(overview.users.map((item: JsonRecord) => item.role)).toEqual(expect.arrayContaining(['ADMIN', 'ANALYST']));
  expect(overview.audit_events.some((item: JsonRecord) => item.actor_email === 'analyst@chatbi.local' && item.status === 'DENIED')).toBe(true);
});

test('Day4-UI14 Permission Denied 使用真实 Backend 403 状态', async ({ page }) => {
  await page.route('**/api/v1/security/overview', async (route) => {
    await route.continue({ headers: { ...route.request().headers(), ...analystHeaders } });
  });
  await page.goto('/settings/security');
  await expect(page.getByTestId('permission-denied')).toContainText('仅 ADMIN');
  await expect(page.getByRole('heading', { name: '用户、角色与审计' })).toBeVisible();
});
