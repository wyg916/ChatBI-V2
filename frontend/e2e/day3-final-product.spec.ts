import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { adminCredentials, apiBase } from './auth';

type JsonRecord = Record<string, any>;

async function payload(response: Awaited<ReturnType<APIRequestContext['get']>>) {
  expect(response.ok(), `${response.status()} ${response.url()}\n${await response.text()}`).toBeTruthy();
  return response.json() as Promise<JsonRecord>;
}

function runtimeErrors(page: Page, expectedHttpStatuses: number[] = []) {
  const errors: string[] = [];
  page.on('console', (message) => {
    const text = message.text();
    const expectedRejection = expectedHttpStatuses.some((status) =>
      text.includes(`status of ${status}`) || text.includes(`${status} (`),
    );
    if (message.type() === 'error' && !expectedRejection) errors.push(`console:${text}`);
  });
  page.on('pageerror', (error) => errors.push(`page:${error.message}`));
  page.on('requestfailed', (request) => {
    if (request.failure()?.errorText !== 'net::ERR_ABORTED') errors.push(`request:${request.url()}:${request.failure()?.errorText ?? ''}`);
  });
  return errors;
}

test('Day3-FINAL-01 incognito protects browser plus chat, attachment, SQL and evaluation APIs', async ({ browser }) => {
  const context = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const page = await context.newPage();
  const errors = runtimeErrors(page, [401]);
  await page.goto('/data-workspace');
  await expect(page).toHaveURL(/\/login$/);
  for (const request of [
    context.request.post(`${apiBase}/chat/stream`, { data: {
      conversation_id: 'unauthenticated-probe',
      client_message_id: `day3-anonymous-${Date.now()}`,
      content: 'authentication boundary probe',
      attachment_ids: [],
    } }),
    context.request.post(`${apiBase}/attachments`, { multipart: {} }),
    context.request.get(`${apiBase}/data-workspace/sql/history`),
    context.request.get(`${apiBase}/evaluation/overview`),
  ]) {
    expect((await request).status()).toBe(401);
  }
  expect(errors).toEqual([]);
  await context.close();
});

test('Day3-FINAL-02 twenty-turn conversation keeps independent scroll, fixed composer and return-to-latest', async ({ page, request }) => {
  test.setTimeout(120_000);
  const errors = runtimeErrors(page);
  const title = `QA long conversation ${Date.now()}`;
  const conversation = await payload(await request.post(`${apiBase}/conversations`, { data: { title } }));
  try {
    let parent: string | null = null;
    for (let index = 1; index <= 20; index += 1) {
      const response = await payload(await request.post(`${apiBase}/chat`, { data: {
        conversation_id: conversation.id,
        content: index % 2 ? '看看' : '分析一下',
        parent_message_id: parent,
        client_message_id: `day3-final-long-${index}-${Date.now()}`,
        attachment_ids: [],
      } }));
      parent = response.assistant_message.id;
    }
    const persisted = await payload(await request.get(`${apiBase}/conversations/${conversation.id}`));
    expect(persisted.messages.filter((message: { role: string }) => message.role === 'user')).toHaveLength(20);
    await page.goto('/');
    await page.getByRole('textbox', { name: '搜索会话' }).fill(title);
    await page.locator(`.conversation-item[data-conversation-id="${conversation.id}"]`).click();
    await expect(page.locator('.chat-user-bubble')).toHaveCount(20, { timeout: 30_000 });
    const messageArea = page.locator('.chat-message-area');
    const composerZone = page.locator('.chat-composer-zone');
    expect(await messageArea.evaluate((node) => getComputedStyle(node).overflowY)).toBe('auto');
    const panel = page.locator('.chat-panel');
    const [panelBox, messageBox, zoneBox] = await Promise.all([panel.boundingBox(), messageArea.boundingBox(), composerZone.boundingBox()]);
    expect(panelBox && messageBox && zoneBox).toBeTruthy();
    expect(Math.abs((panelBox!.y + panelBox!.height) - (zoneBox!.y + zoneBox!.height))).toBeLessThanOrEqual(2);
    expect((messageBox!.y + messageBox!.height) - zoneBox!.y).toBeLessThanOrEqual(2);
    await messageArea.evaluate((node) => { node.scrollTop = 0; node.dispatchEvent(new Event('scroll')); });
    await expect(page.getByRole('button', { name: '回到最新消息' })).toBeVisible();
    await page.getByRole('button', { name: '回到最新消息' }).click();
    await expect.poll(() => messageArea.evaluate((node) => node.scrollHeight - node.scrollTop - node.clientHeight)).toBeLessThan(100);
    const input = page.getByRole('textbox', { name: '输入业务问题' });
    await input.fill('查一下');
    await input.press('Enter');
    await expect(page.locator('.chat-user-bubble')).toHaveCount(21);
    await expect.poll(() => messageArea.evaluate((node) => node.scrollHeight - node.scrollTop - node.clientHeight)).toBeLessThan(100);
    await page.reload();
    await expect(page.locator('.chat-user-bubble')).toHaveCount(21);
    expect(errors).toEqual([]);
  } finally {
    expect((await request.delete(`${apiBase}/conversations/${conversation.id}`)).status()).toBe(204);
  }
});

test('Day3-FINAL-03 real SSE can stop and refused response can retry', async ({ page }) => {
  const errors = runtimeErrors(page);
  const streamContents: string[] = [];
  page.on('request', (request) => {
    if (request.url().endsWith('/api/v1/chat/stream') && request.method() === 'POST') {
      streamContents.push(String((request.postDataJSON() as { content?: string } | null)?.content ?? ''));
    }
  });
  await page.goto('/');
  await page.getByRole('button', { name: '＋ 新会话' }).click();
  const input = page.getByRole('textbox', { name: '输入业务问题' });
  await input.fill('请对2025年各区域销售额进行深度分析并给出可验证建议。');
  await input.press('Enter');
  const stop = page.getByRole('button', { name: '停止生成' });
  await expect(stop).toBeVisible();
  await stop.click();
  await expect(stop).not.toBeVisible();
  await input.fill('删除数据库中的全部订单。');
  await input.press('Enter');
  const retry = page.getByRole('button', { name: '重新查询' }).last();
  await expect(retry).toBeVisible({ timeout: 30_000 });
  const before = await page.locator('.chat-user-bubble').count();
  await retry.click();
  await expect.poll(() => streamContents.length).toBe(3);
  expect(streamContents.at(-1)).toBe('删除数据库中的全部订单。');
  expect(streamContents.at(-2)).toBe(streamContents.at(-1));
  await expect(page.locator('.chat-user-bubble')).toHaveCount(before);
  await expect(page.getByRole('button', { name: '重新查询' }).last()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('result-state-FAILED').last()).toContainText('回答未完成');
  await expect(page.getByTestId('query-success')).toHaveCount(0);
  const refusedText = await page.getByTestId('result-state-FAILED').last().textContent();
  await page.waitForTimeout(750);
  await expect(page.getByTestId('result-state-FAILED').last()).toHaveText(refusedText ?? '');
  expect(errors).toEqual([]);
});

test('Day3-FINAL-04 attachment attack inputs fail closed and path filenames are normalized', async ({ request }) => {
  const conversation = await payload(await request.post(`${apiBase}/conversations`, { data: { title: 'Day3 final attachment E2E' } }));
  try {
    const illegal = await request.post(`${apiBase}/attachments`, { multipart: {
      conversation_id: conversation.id, file: { name: 'bad.exe', mimeType: 'application/octet-stream', buffer: Buffer.from('MZ') },
    } });
    expect(illegal.status()).toBe(415);
    const empty = await request.post(`${apiBase}/attachments`, { multipart: {
      conversation_id: conversation.id, file: { name: 'empty.csv', mimeType: 'text/csv', buffer: Buffer.from('') },
    } });
    expect(empty.status()).toBe(422);
    const spoof = await request.post(`${apiBase}/attachments`, { multipart: {
      conversation_id: conversation.id, file: { name: 'spoof.pdf', mimeType: 'text/csv', buffer: Buffer.from('region,revenue\nEast,1\n') },
    } });
    expect(spoof.status()).toBe(415);
    const corrupt = await request.post(`${apiBase}/attachments`, { multipart: {
      conversation_id: conversation.id,
      file: { name: 'corrupt.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: Buffer.from('PK-not-a-zip') },
    } });
    expect(corrupt.status()).toBe(415);
    const traversal = await payload(await request.post(`${apiBase}/attachments`, { multipart: {
      conversation_id: conversation.id, file: { name: '../../escape.csv', mimeType: 'text/csv', buffer: Buffer.from('region,revenue\nEast,1\n') },
    } }));
    expect(traversal.filename).toBe('escape.csv');
    expect(traversal).not.toHaveProperty('storage_key');
  } finally {
    expect((await request.delete(`${apiBase}/conversations/${conversation.id}`)).status()).toBe(204);
  }
});

test('Day3-FINAL-05 SQL Workspace, evaluation and feedback expose request traces', async ({ request }) => {
  const datasources = await payload(await request.get(`${apiBase}/datasources`)) as JsonRecord[];
  const datasource = datasources.find((item) => item.type === 'postgresql' && item.status === 'CONNECTED');
  expect(datasource).toBeTruthy();
  const calls = [
    request.post(`${apiBase}/data-workspace/sql/execute`, { data: {
      datasource_id: datasource!.id, sql: 'SELECT order_id, revenue FROM demo_business.orders ORDER BY order_id LIMIT 5', row_limit: 5,
    } }),
    request.get(`${apiBase}/evaluation/dashboard`),
    request.get(`${apiBase}/evaluation/feedback/dashboard`),
  ];
  for (const pending of calls) {
    const response = await pending;
    expect(response.ok(), await response.text()).toBeTruthy();
    expect(response.headers()['x-trace-id']).toMatch(/^REQUEST-/);
  }
});

test('Day3-FINAL-06 new conversation resets inherited business and evidence context', async ({ request }) => {
  const first = await payload(await request.post(`${apiBase}/conversations`, { data: { title: 'Memory source' } }));
  const second = await payload(await request.post(`${apiBase}/conversations`, { data: { title: 'Memory reset' } }));
  try {
    await payload(await request.post(`${apiBase}/chat`, { data: {
      conversation_id: first.id, content: '2025年华东区销售额是多少？',
      client_message_id: `memory-source-${Date.now()}`, attachment_ids: [],
    } }));
    const reset = await payload(await request.post(`${apiBase}/chat`, { data: {
      conversation_id: second.id, content: '看看', client_message_id: `memory-reset-${Date.now()}`, attachment_ids: [],
    } }));
    const slots = reset.user_message.context_payload.slots as JsonRecord;
    for (const key of ['metric', 'time', 'regions', 'previous_sql', 'previous_result', 'citation', 'attachment', 'file_context']) {
      expect(slots).not.toHaveProperty(key);
    }
  } finally {
    expect((await request.delete(`${apiBase}/conversations/${first.id}`)).status()).toBe(204);
    expect((await request.delete(`${apiBase}/conversations/${second.id}`)).status()).toBe(204);
  }
});
