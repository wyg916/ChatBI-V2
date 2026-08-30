import path from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import { adminCredentials, apiBase } from './auth';

async function startFreshConversation(page: Page) {
  let createRequests = 0;
  const observeCreate = (request: { url(): string; method(): string }) => {
    if (request.url().endsWith('/api/v1/conversations') && request.method() === 'POST') createRequests += 1;
  };
  page.on('request', observeCreate);
  await page.getByRole('button', { name: '＋ 新会话' }).click();
  await page.waitForTimeout(250);
  expect(createRequests, '点击新会话只应进入本地空态').toBe(0);
  expect(await page.evaluate(() => localStorage.getItem('chatbi_conversation_id'))).toBeNull();
  await expect(page.locator('.conversation-item.local.active')).toContainText('发送消息后保存');
  await expect(page.getByRole('textbox', { name: '输入业务问题' })).toBeVisible();
  page.off('request', observeCreate);
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
    const composerZone = page.locator('.chat-composer-zone');
    await expect(composer).toBeVisible();
    expect(await messages.evaluate((node) => getComputedStyle(node).overflowY)).toBe('auto');
    const [panelBox, messagesBox, zoneBox] = await Promise.all([panel.boundingBox(), messages.boundingBox(), composerZone.boundingBox()]);
    expect(panelBox && messagesBox && zoneBox).toBeTruthy();
    expect(Math.abs((panelBox!.y + panelBox!.height) - (zoneBox!.y + zoneBox!.height))).toBeLessThanOrEqual(2);
    expect((messagesBox!.y + messagesBox!.height) - zoneBox!.y).toBeLessThanOrEqual(2);
  }

  const input = page.getByRole('textbox', { name: '输入业务问题' });
  await input.fill('第一行');
  await input.press('Shift+Enter');
  await input.type('第二行');
  await expect(input).toHaveValue('第一行\n第二行');
  await input.fill('统计全部订单收入');
  await expect(page.getByRole('button', { name: '提交问题' })).toBeEnabled();
  const [created] = await Promise.all([
    page.waitForResponse((response) => response.url().endsWith('/api/v1/conversations') && response.request().method() === 'POST'),
    input.press('Enter'),
  ]);
  expect(created.status()).toBe(201);
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

test('Phase2 CSV uploads complete the real file-analysis follow-up', async ({ page }) => {
  await page.goto('/');
  await startFreshConversation(page);
  const fileInput = page.locator('input[type="file"]');
  const csv = path.resolve('..', 'evaluation', 'fixtures', 'phase2-regional-revenue.csv');
  const [created] = await Promise.all([
    page.waitForResponse((response) => response.url().endsWith('/api/v1/conversations') && response.request().method() === 'POST'),
    fileInput.setInputFiles(csv),
  ]);
  expect(created.status()).toBe(201);
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
  await expect(page.getByRole('button', { name: '删除附件 phase2-regional-revenue.csv' })).toHaveCount(0);
  await expect(page.locator('.attachment-strip')).toHaveCount(0);
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
