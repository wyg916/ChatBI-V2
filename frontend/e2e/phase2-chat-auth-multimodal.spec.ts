import path from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import { adminCredentials, apiBase } from './auth';

async function startFreshConversation(page: Page) {
  const [response] = await Promise.all([
    page.waitForResponse((response) => response.url().endsWith('/api/v1/conversations') && response.request().method() === 'POST'),
    page.getByRole('button', { name: '＋ 新会话' }).click(),
  ]);
  const conversation = await response.json() as { id: string };
  await page.waitForFunction((id) => localStorage.getItem('chatbi_conversation_id') === id, conversation.id);
  await expect(page.locator(`.conversation-list .active[data-conversation-id="${conversation.id}"]`)).toBeVisible();
  await expect(page.getByRole('textbox', { name: '输入业务问题' })).toBeVisible();
}

test('Phase2 unauthenticated browser, API and invalid session are blocked', async ({ browser }) => {
  const anonymous = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const page = await anonymous.newPage();
  await page.goto('/datasources');
  await expect(page).toHaveURL(/\/login$/);
  expect((await anonymous.request.get(`${apiBase}/datasources`)).status()).toBe(401);

  await anonymous.addCookies([{
    name: 'chatbi_session', value: 'invalid-session-token', domain: '127.0.0.1', path: '/',
    httpOnly: true, sameSite: 'Strict', secure: false,
  }]);
  expect((await anonymous.request.get(`${apiBase}/auth/me`)).status()).toBe(401);
  await anonymous.close();
});

test('Phase2 composer remains at the bottom and keyboard behavior uses the real chat runtime', async ({ page }) => {
  const runtimeErrors: string[] = [];
  page.on('console', (message) => { if (message.type() === 'error') runtimeErrors.push(`console:${message.text()}`); });
  page.on('pageerror', (error) => runtimeErrors.push(`page:${error.message}`));
  page.on('requestfailed', (request) => {
    if (request.failure()?.errorText !== 'net::ERR_ABORTED') runtimeErrors.push(`request:${request.url()} ${request.failure()?.errorText ?? ''}`);
  });

  for (const viewport of [{ width: 1366, height: 768 }, { width: 1440, height: 900 }, { width: 1920, height: 1080 }]) {
    await page.setViewportSize(viewport);
    await page.goto('/');
    await startFreshConversation(page);
    const panel = page.locator('.chat-panel');
    const messages = page.locator('.chat-message-area');
    const composer = page.locator('.chat-composer');
    await expect(composer).toBeVisible();
    expect(await messages.evaluate((node) => getComputedStyle(node).overflowY)).toBe('auto');
    const [panelBox, composerBox] = await Promise.all([panel.boundingBox(), composer.boundingBox()]);
    expect(panelBox && composerBox).toBeTruthy();
    expect(Math.abs((panelBox!.y + panelBox!.height) - (composerBox!.y + composerBox!.height))).toBeLessThanOrEqual(20);
  }

  const input = page.getByRole('textbox', { name: '输入业务问题' });
  await input.fill('第一行');
  await input.press('Shift+Enter');
  await input.type('第二行');
  await expect(input).toHaveValue('第一行\n第二行');
  await input.fill('统计全部订单收入');
  await expect(page.getByRole('button', { name: '提交问题' })).toBeEnabled();
  await input.press('Enter');
  await expect(page.locator('.chat-user-bubble').last()).toContainText('统计全部订单收入');
  await expect(page.getByTestId('query-success')).toBeVisible({ timeout: 30_000 });
  await expect(page.locator('.chat-composer')).toBeVisible();
  await page.reload();
  await expect(page.locator('.chat-user-bubble').last()).toContainText('统计全部订单收入');

  await startFreshConversation(page);
  const imeInput = page.getByRole('textbox', { name: '输入业务问题' });
  await imeInput.fill('组合输入');
  await imeInput.dispatchEvent('compositionstart');
  await imeInput.dispatchEvent('keydown', { key: 'Enter', code: 'Enter', isComposing: true });
  await expect(imeInput).toHaveValue('组合输入');
  await expect(page.locator('.chat-user-bubble')).toHaveCount(0);
  await imeInput.dispatchEvent('compositionend');
  expect(runtimeErrors).toEqual([]);
});

test('Phase2 CSV and image uploads complete real file and multimodal follow-ups', async ({ page }) => {
  await page.goto('/');
  await startFreshConversation(page);
  const fileInput = page.locator('input[type="file"]');
  const csv = path.resolve('..', 'evaluation', 'fixtures', 'phase2-regional-revenue.csv');
  await fileInput.setInputFiles(csv);
  await expect(page.getByRole('button', { name: '删除附件 phase2-regional-revenue.csv' })).toBeVisible();
  const input = page.getByRole('textbox', { name: '输入业务问题' });
  await input.fill('请计算华东收入合计，只给出数字。');
  await input.press('Enter');
  await expect(page.locator('.chat-assistant-message').last()).toContainText('270', { timeout: 60_000 });
  await expect(page.getByTestId('file-analysis-evidence')).toContainText('270');
  await expect(page.getByRole('img', { name: '文件分析结果图表' })).toBeVisible();
  await expect(page.getByRole('link', { name: '下载 CSV Artifact' })).toBeVisible();
  await expect(page.getByRole('link', { name: '下载 JSON Artifact' })).toBeVisible();
  await expect(page.getByRole('button', { name: '提交问题' })).toBeEnabled();
  await page.getByRole('button', { name: '删除附件 phase2-regional-revenue.csv' }).click();
  await expect(page.getByText('phase2-regional-revenue.csv')).toHaveCount(0);

  const image = path.resolve('..', 'docs', 'ui', '03_问数据_分析结果.png');
  await fileInput.setInputFiles(image);
  await expect(page.getByRole('button', { name: '删除附件 03_问数据_分析结果.png' })).toBeVisible();
  await input.fill('左侧导航当前高亮项和内容区粗体主标题相同，它们是哪三个字？');
  const assistantCount = await page.locator('.chat-assistant-message').count();
  await expect(page.getByRole('button', { name: '提交问题' })).toBeEnabled();
  await input.press('Enter');
  await expect(page.locator('.chat-assistant-message')).toHaveCount(assistantCount + 1, { timeout: 60_000 });
  await expect(page.locator('.chat-assistant-message').last()).toContainText('问数据', { timeout: 60_000 });
});

test('Phase2 logout revokes only the current server session', async ({ browser }) => {
  const isolated = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const login = await isolated.request.post(`${apiBase}/auth/login`, {
    data: { email: adminCredentials.email, password: adminCredentials.password },
  });
  expect(login.status()).toBe(200);
  expect((await isolated.request.get(`${apiBase}/auth/me`)).status()).toBe(200);
  expect((await isolated.request.post(`${apiBase}/auth/logout`)).status()).toBe(204);
  expect((await isolated.request.get(`${apiBase}/auth/me`)).status()).toBe(401);
  const page = await isolated.newPage();
  await page.goto('/dashboards');
  await expect(page).toHaveURL(/\/login$/);
  await isolated.close();
});
