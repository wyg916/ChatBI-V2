import { expect, test } from '@playwright/test';
import type { APIRequestContext } from '@playwright/test';
import { captureRuntimeErrors } from './runtime-errors';


async function createConversation(request: APIRequestContext, title: string) {
  const response = await request.post('/api/v1/conversations', { data: { title } });
  expect(response.status()).toBe(201);
  return response.json() as Promise<{ id: string; title: string }>;
}


test('project binding, controlled sharing, revoke and anonymous read-only access form one real flow', async ({ browser, page, request }) => {
  const suffix = Date.now();
  const title = `Phase4 conversation governance ${suffix}`;
  const projectResponse = await request.post('/api/v1/projects', {
    data: { name: `Phase4 project ${suffix}`, description: 'Playwright governed project' },
  });
  expect(projectResponse.status()).toBe(201);
  const project = await projectResponse.json() as { id: string };
  const conversation = await createConversation(request, title);

  expect((await request.put(`/api/v1/conversations/${conversation.id}/project`, {
    data: { project_id: project.id },
  })).status()).toBe(200);
  expect((await request.post(`/api/v1/conversations/${conversation.id}/pin`)).status()).toBe(200);

  await page.goto('/');
  await page.getByRole('textbox', { name: '搜索会话' }).fill(title);
  await expect(page.getByRole('button', { name: new RegExp(title) })).toBeVisible();
  await expect(page.locator(`[data-conversation-id="${conversation.id}"]`)).toContainText('★');

  const shareResponse = await request.post(`/api/v1/conversations/${conversation.id}/shares`, {
    data: { expires_in_hours: 24 },
  });
  expect(shareResponse.status()).toBe(201);
  const share = await shareResponse.json() as { id: string; share_path: string };

  const anonymous = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const sharedPage = await anonymous.newPage();
  await sharedPage.goto(share.share_path);
  await expect(sharedPage.getByTestId('shared-conversation-page')).toBeVisible();
  await expect(sharedPage.getByRole('heading', { name: title })).toBeVisible();
  await expect(sharedPage.getByText('只读共享')).toBeVisible();
  await expect(sharedPage.getByRole('textbox')).toHaveCount(0);

  expect((await request.post(`/api/v1/conversation-shares/${share.id}/revoke`)).status()).toBe(200);
  await sharedPage.reload();
  await expect(sharedPage.getByRole('alert')).toContainText('共享内容不可用');
  await anonymous.close();

  expect((await request.delete(`/api/v1/conversations/${conversation.id}`)).status()).toBe(204);
  expect((await request.post(`/api/v1/projects/${project.id}/archive`)).status()).toBe(200);
});


test('multi-select batch archive and delete are reflected by server-side list state', async ({ page, request }) => {
  const suffix = Date.now();
  const titlePrefix = `Phase4 batch ${suffix}`;
  const left = await createConversation(request, `${titlePrefix} left`);
  const right = await createConversation(request, `${titlePrefix} right`);

  await page.goto('/');
  await page.getByRole('textbox', { name: '搜索会话' }).fill(titlePrefix);
  await expect(page.locator(`[data-conversation-id="${left.id}"]`)).toBeVisible();
  await expect(page.locator(`[data-conversation-id="${right.id}"]`)).toBeVisible();
  await page.getByRole('button', { name: '批量操作' }).click();
  await page.getByRole('checkbox', { name: `选择会话 ${left.title}` }).check();
  await page.getByRole('checkbox', { name: `选择会话 ${right.title}` }).check();
  await page.getByRole('button', { name: '批量归档' }).click();
  await expect(page.locator(`[data-conversation-id="${left.id}"]`)).toHaveCount(0);

  const archivedResponse = await request.get(`/api/v1/conversations?state=archived&q=${encodeURIComponent(titlePrefix)}`);
  expect(archivedResponse.status()).toBe(200);
  const archived = await archivedResponse.json() as Array<{ id: string }>;
  expect(new Set(archived.map((item) => item.id))).toEqual(new Set([left.id, right.id]));

  const deleted = await request.post('/api/v1/conversations/batch/delete', {
    data: { conversation_ids: [left.id, right.id] },
  });
  expect(deleted.status()).toBe(200);
  expect(await deleted.json()).toMatchObject({ affected_count: 2 });
});


test('cost, ONE_TRACE, model and evaluation dashboards use real governance APIs without browser errors', async ({ page }) => {
  const runtime = captureRuntimeErrors(page);

  await page.goto('/settings/models?view=cost');
  await expect(page.getByTestId('governance-center-page')).toBeVisible();
  await expect(page.getByRole('heading', { name: '成本与用量' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '最近调用台账' })).toBeVisible();
  await page.getByLabel('Provider').fill('deepseek');
  const filteredCost = page.waitForResponse((response) => response.url().includes('/api/v1/governance/cost') && response.url().includes('provider=deepseek'));
  await page.getByRole('button', { name: '应用筛选' }).click();
  expect((await filteredCost).status()).toBe(200);

  await page.getByRole('button', { name: 'ONE_TRACE' }).click();
  await expect(page.getByRole('heading', { name: 'ONE_TRACE 时序索引' })).toBeVisible();
  const traceLinks = page.locator('.governance-trace-link');
  await expect(traceLinks.first()).toBeVisible();
  await traceLinks.first().click();
  await expect(page.getByRole('heading', { name: 'Trace 阶段详情' })).toBeVisible();

  await page.getByRole('button', { name: '模型治理' }).click();
  await expect(page.getByRole('heading', { name: '路由政策' })).toBeVisible();
  await expect(page.locator('.governance-model-card')).toHaveCount(3);

  await page.getByRole('button', { name: '评测治理' }).click();
  await expect(page.getByRole('heading', { name: '评测套件与证据' })).toBeVisible();

  expect(runtime.consoleErrors).toEqual([]);
  expect(runtime.pageErrors).toEqual([]);
  expect(runtime.blockingRequestErrors).toEqual([]);
});
