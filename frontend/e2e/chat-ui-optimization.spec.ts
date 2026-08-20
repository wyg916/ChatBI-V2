import fs from 'node:fs';
import path from 'node:path';
import { expect, request as requestFactory, test, type APIRequestContext, type APIResponse, type Page } from '@playwright/test';
import { analystCredentials, apiBase, loginApi } from './auth';
import { captureRuntimeErrors } from './runtime-errors';

type JsonRecord = Record<string, any>;

const viewports = [
  { width: 1920, height: 1080 },
  { width: 1440, height: 900 },
  { width: 1366, height: 768 },
] as const;

const screenshotRoot = process.env.CHATBI_SCREENSHOT_ROOT
  ? path.resolve(process.env.CHATBI_SCREENSHOT_ROOT)
  : path.resolve('..', 'artifacts', 'chat-ui-optimization-20260819', 'final-integration');

function parseSse(text: string) {
  return text.split(/\r?\n\r?\n/).filter((block) => block.trim()).map((block) => {
    const event = block.match(/^event:\s*(.+)$/m)?.[1]?.trim();
    const data = block.match(/^data:\s*(.+)$/m)?.[1]?.trim();
    expect(event, block).toBeTruthy();
    expect(data, block).toBeTruthy();
    const payload = JSON.parse(data!) as JsonRecord;
    expect(payload.event_type, block).toBe(event);
    return payload;
  });
}

async function json(response: APIResponse) {
  expect(response.ok(), `${response.status()} ${response.url()}\n${await response.text()}`).toBeTruthy();
  return response.json() as Promise<JsonRecord>;
}

async function createConversation(request: APIRequestContext, title = `qa-chat-ui-${Date.now()}`) {
  return json(await request.post(`${apiBase}/conversations`, { data: { title } }));
}

async function deleteConversation(request: APIRequestContext, id: string) {
  const response = await request.delete(`${apiBase}/conversations/${id}`);
  expect([204, 404]).toContain(response.status());
}

async function streamQuestion(request: APIRequestContext, conversationId: string, content: string) {
  const response = await request.post(`${apiBase}/chat/stream`, {
    headers: { Accept: 'text/event-stream' },
    data: {
      conversation_id: conversationId,
      content,
      client_message_id: `qa-${crypto.randomUUID()}`,
      attachment_ids: [],
    },
  });
  expect(response.ok(), `${response.status()} ${await response.text()}`).toBeTruthy();
  return parseSse(await response.text());
}

async function dispatchFile(page: Page, selector: string, eventName: 'drop' | 'paste', filePath: string, mimeType: string, filename = path.basename(filePath)) {
  const bytes = Array.from(fs.readFileSync(filePath));
  await page.locator(selector).evaluate((node, input) => {
    const transfer = new DataTransfer();
    transfer.items.add(new File([new Uint8Array(input.bytes)], input.filename, { type: input.mimeType }));
    const event = input.eventName === 'drop'
      ? new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: transfer })
      : new ClipboardEvent('paste', { bubbles: true, cancelable: true, clipboardData: transfer });
    node.dispatchEvent(event);
  }, { bytes, filename, mimeType, eventName });
}

test('Chat UI 三视口布局、品牌、单主滚动和优化后截图', async ({ page }) => {
  fs.mkdirSync(screenshotRoot, { recursive: true });
  const errors = captureRuntimeErrors(page);
  const blockingResponses: string[] = [];
  page.on('response', (response) => {
    if (response.status() >= 400) blockingResponses.push(`${response.status()} ${response.url()}`);
  });

  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    await page.goto('/?new=1');
    await expect(page.getByRole('heading', { name: '今天想了解哪些业务数据？' })).toBeVisible();
    await expect(page.getByRole('dialog', { name: 'SQL 与执行明细' })).toHaveCount(0);
    await expect(page.locator('.sidebar')).toHaveCSS('width', '236px');
    await expect(page.locator('.hero-mark')).toHaveCSS('color', 'rgb(255, 255, 255)');
    const heroBackground = await page.locator('.hero-mark').evaluate((node) => getComputedStyle(node).backgroundImage);
    expect(heroBackground).toContain('linear-gradient');
    expect(heroBackground).toContain('rgb(108, 93, 255)');
    expect(heroBackground).toContain('rgb(81, 68, 238)');
    const composerToolbar = page.locator('.composer-toolbar');
    await expect(composerToolbar.getByRole('button')).toHaveCount(2);
    await expect(composerToolbar.getByRole('button', { name: '添加文件或图片' })).toBeVisible();
    await expect(composerToolbar.getByRole('button', { name: '提交问题' })).toBeVisible();
    await expect(page.getByRole('button', { name: /麦克风|语音|录音/ })).toHaveCount(0);
    expect(await page.locator('.chat-message-area').evaluate((node) => getComputedStyle(node).overflowY)).toBe('auto');
    expect(await page.locator('.chat-panel').evaluate((node) => getComputedStyle(node).overflow)).toBe('hidden');
    expect(await page.locator('.conversation-list').evaluate((node) => getComputedStyle(node).overflowY)).toBe('auto');
    expect(await page.evaluate(() => ({
      body: document.body.scrollWidth <= window.innerWidth,
      html: document.documentElement.scrollWidth <= window.innerWidth,
      vertical: document.documentElement.scrollHeight <= window.innerHeight + 1,
    }))).toEqual({ body: true, html: true, vertical: true });

    const [panel, composer, messageArea] = await Promise.all([
      page.locator('.chat-panel').boundingBox(),
      page.locator('.chat-composer-zone').boundingBox(),
      page.locator('.chat-message-area').boundingBox(),
    ]);
    expect(panel && composer && messageArea).toBeTruthy();
    expect(composer!.y).toBeGreaterThanOrEqual(messageArea!.y + messageArea!.height - 1);
    expect(composer!.y + composer!.height).toBeLessThanOrEqual(panel!.y + panel!.height + 1);
    await page.screenshot({ path: path.join(screenshotRoot, `chat-ui-${viewport.width}x${viewport.height}.png`), fullPage: false });
  }

  expect(errors.consoleErrors).toEqual([]);
  expect(errors.pageErrors).toEqual([]);
  expect(errors.blockingRequestErrors).toEqual([]);
  expect(blockingResponses).toEqual([]);
});

test('成功回答支持复制和重新生成且 Assistant 无巨大外层卡片', async ({ page, request }) => {
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.goto('/?new=1');
  const question = '统计全部订单收入';
  const input = page.getByRole('textbox', { name: '输入业务问题' });
  await input.fill(question);
  const [created] = await Promise.all([
    page.waitForResponse((response) => response.url().endsWith('/api/v1/conversations') && response.request().method() === 'POST'),
    input.press('Enter'),
  ]);
  const conversation = await created.json() as JsonRecord;
  try {
    await expect(page.getByTestId('result-state-VALUE')).toBeVisible({ timeout: 60_000 });
    const firstAnswer = page.locator('.chat-assistant-message').last();
    const shellStyle = await firstAnswer.evaluate((node) => {
      const shell = getComputedStyle(node);
      const response = getComputedStyle(node.querySelector('.assistant-response')!);
      return {
        shellBackground: shell.backgroundColor,
        shellBorder: shell.borderTopWidth,
        shellShadow: shell.boxShadow,
        responseBackground: response.backgroundColor,
        responseBorder: response.borderTopWidth,
        responseShadow: response.boxShadow,
      };
    });
    expect(shellStyle).toEqual({
      shellBackground: 'rgba(0, 0, 0, 0)',
      shellBorder: '0px',
      shellShadow: 'none',
      responseBackground: 'rgba(0, 0, 0, 0)',
      responseBorder: '0px',
      responseShadow: 'none',
    });

    await firstAnswer.getByRole('button', { name: '复制回答' }).click();
    await expect(firstAnswer.getByRole('status')).toHaveText('已复制');
    expect((await page.evaluate(() => navigator.clipboard.readText())).trim().length).toBeGreaterThan(0);

    const answerCount = await page.locator('.chat-assistant-message').count();
    const userCount = await page.locator('.chat-user-bubble').count();
    const regenerated = page.waitForResponse((response) => response.url().endsWith('/api/v1/chat/stream') && response.request().method() === 'POST');
    await firstAnswer.getByRole('button', { name: '重新生成', exact: true }).click();
    expect((await regenerated).status()).toBe(200);
    await expect(page.locator('.chat-assistant-message')).toHaveCount(answerCount + 1, { timeout: 60_000 });
    await expect(page.locator('.chat-user-bubble')).toHaveCount(userCount + 1);
    await expect(page.getByTestId('result-state-VALUE').last()).toBeVisible();
    await expect(page.locator('.chat-user-bubble').last()).toContainText(question);
  } finally {
    await deleteConversation(request, conversation.id);
  }
});

test('ZERO 与 NULL_VALUE 用户态语义明确且不展示伪造可信度或空金额', async ({ page, request }) => {
  for (const scenario of [
    { semantic: 'ZERO', question: 'SELECT COUNT(*) AS revenue FROM demo_business.orders WHERE 1 = 0', notice: '当前条件下结果为 0' },
    { semantic: 'NULL_VALUE', question: 'SELECT CAST(NULL AS NUMERIC) AS revenue', notice: '查询到记录，但指标字段为空' },
  ] as const) {
    await page.goto('/?new=1');
    const input = page.getByRole('textbox', { name: '输入业务问题' });
    await input.fill(scenario.question);
    const [created] = await Promise.all([
      page.waitForResponse((response) => response.url().endsWith('/api/v1/conversations') && response.request().method() === 'POST'),
      input.press('Enter'),
    ]);
    const conversation = await created.json() as JsonRecord;
    try {
      const answer = page.getByTestId(`result-state-${scenario.semantic}`).last();
      await expect(answer).toBeVisible({ timeout: 60_000 });
      await expect(answer).toContainText(scenario.notice);
      await expect(answer).not.toContainText(/可信度\s*100\s*%/);
      await expect(answer).not.toContainText(/—\s*元/);
      if (scenario.semantic === 'ZERO') await expect(answer.getByTestId('query-success')).toBeVisible();
      else await expect(answer.getByTestId('query-success')).toHaveCount(0);
    } finally {
      await deleteConversation(request, conversation.id);
    }
  }
});

test('真实 chat SSE 严格递增、多 delta、成对 phase、唯一终态并与持久化一致', async ({ request }) => {
  const conversation = await createConversation(request);
  try {
    const frames = await streamQuestion(request, conversation.id, '综合分析各地区收入与利润表现，结合收入口径和成本口径给出完整经营洞察、风险与后续建议');
    const types = frames.map((item) => item.event_type);
    expect(types[0]).toBe('run.started');
    expect(types.at(-1)).toBe('run.completed');
    expect(types).not.toEqual(expect.arrayContaining(['progress', 'result']));
    expect(types.filter((item) => ['run.completed', 'run.failed', 'run.cancelled'].includes(item))).toHaveLength(1);
    expect(frames.map((item) => item.seq)).toEqual(frames.map((_, index) => index + 1));
    expect(new Set(frames.map((item) => item.run_id)).size).toBe(1);
    expect(new Set(frames.map((item) => item.conversation_id))).toEqual(new Set([conversation.id]));
    expect(frames.every((item) => item.timestamp && item.message_id && item.event_type)).toBe(true);

    const phaseStarted = frames.filter((item) => item.event_type === 'phase.started').map((item) => item.phase);
    const phaseCompleted = frames.filter((item) => item.event_type === 'phase.completed').map((item) => item.phase);
    expect(phaseStarted).toEqual(phaseCompleted);
    expect(phaseStarted.every((phase) => ['understanding', 'semantic_mapping', 'querying_data', 'retrieving_knowledge', 'verifying', 'composing_answer'].includes(phase))).toBe(true);
    const deltas = frames.filter((item) => item.event_type === 'answer.delta').map((item) => item.delta);
    expect(deltas.length).toBeGreaterThanOrEqual(2);
    const terminal = frames.at(-1)!;
    expect(terminal.response.assistant_message.content).toBe(deltas.join(''));
    expect(terminal.result_semantic).toBe('VALUE');

    const persisted = await json(await request.get(`${apiBase}/conversations/${conversation.id}`));
    expect(persisted.messages.at(-1).content).toBe(deltas.join(''));
    expect(persisted.messages.at(-1).response_payload.result_semantic).toBe('VALUE');
  } finally {
    await deleteConversation(request, conversation.id);
  }
});

for (const scenario of [
  { semantic: 'VALUE', question: '统计全部订单收入' },
  { semantic: 'ZERO', question: 'SELECT COUNT(*) AS revenue FROM demo_business.orders WHERE 1 = 0' },
  { semantic: 'NO_ROWS', question: 'SELECT order_id FROM demo_business.orders WHERE 1 = 0' },
  { semantic: 'NULL_VALUE', question: 'SELECT CAST(NULL AS NUMERIC) AS revenue' },
  { semantic: 'FAILED', question: 'DROP TABLE demo_business.orders' },
] as const) {
  test(`真实回答保留 ${scenario.semantic} 结果语义`, async ({ request }) => {
    const conversation = await createConversation(request, `qa-semantic-${scenario.semantic}-${Date.now()}`);
    try {
      const frames = await streamQuestion(request, conversation.id, scenario.question);
      const terminal = frames.at(-1)!;
      expect(['run.completed', 'run.failed']).toContain(terminal.event_type);
      expect(terminal.event_type === 'run.completed' ? terminal.result_semantic : 'FAILED').toBe(scenario.semantic);
      if (scenario.semantic === 'FAILED') {
        expect(terminal.retryable).toBeDefined();
        expect(terminal.event_type).toBe('run.failed');
      } else {
        expect(terminal.response.assistant_message.response_payload.result_semantic).toBe(scenario.semantic);
      }
    } finally {
      await deleteConversation(request, conversation.id);
    }
  });
}

test('空态延迟创建、真实多轮、查询依据、滚动暂停、搜索、重命名和删除', async ({ page, request }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.goto('/?new=1');
  let createCount = 0;
  page.on('request', (req) => {
    if (req.url().endsWith('/api/v1/conversations') && req.method() === 'POST') createCount += 1;
  });
  await page.getByRole('button', { name: '＋ 新会话' }).click();
  await page.waitForTimeout(250);
  expect(createCount).toBe(0);
  expect(await page.evaluate(() => localStorage.getItem('chatbi_conversation_id'))).toBeNull();

  const input = page.getByRole('textbox', { name: '输入业务问题' });
  await input.fill('按地区统计订单收入并给出业务洞察');
  const [created] = await Promise.all([
    page.waitForResponse((response) => response.url().endsWith('/api/v1/conversations') && response.request().method() === 'POST'),
    input.press('Enter'),
  ]);
  const conversation = await created.json() as JsonRecord;
  expect(createCount).toBe(1);
  await expect(page.getByTestId('result-state-VALUE')).toBeVisible({ timeout: 60_000 });
  await expect(page.locator('.chat-user-bubble p').filter({ hasText: '按地区统计订单收入并给出业务洞察' })).toHaveCount(1);
  const chart = page.locator('.chart-card .data-echart').last();
  await expect(chart).toBeVisible();
  expect((await chart.boundingBox())!.height).toBeGreaterThanOrEqual(240);
  await expect(chart.locator('canvas, svg').first()).toBeVisible();
  await expect(page.getByRole('dialog', { name: 'SQL 与执行明细' })).toHaveCount(0);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.locator('.chat-message-area').evaluate((node) => { node.scrollTop = 0; });
  await page.waitForTimeout(150);
  await page.screenshot({ path: path.join(screenshotRoot, 'chat-ui-result-1440x900.png'), fullPage: false });
  const evidenceButton = page.getByRole('button', { name: '查看 SQL 与执行明细' }).last();
  await evidenceButton.scrollIntoViewIfNeeded();
  await evidenceButton.click();
  const drawer = page.getByRole('dialog', { name: 'SQL 与执行明细' });
  await expect(drawer).toBeVisible();
  const drawerBox = await drawer.boundingBox();
  expect(drawerBox!.width).toBeGreaterThanOrEqual(360);
  expect(drawerBox!.width).toBeLessThanOrEqual(420);
  await page.screenshot({ path: path.join(screenshotRoot, 'chat-ui-drawer-1440x900.png'), fullPage: false });
  await page.getByRole('button', { name: '关闭查询明细' }).click();

  await input.fill('再按产品拆分');
  await input.press('Enter');
  await expect(page.locator('.chat-user-bubble p').filter({ hasText: '再按产品拆分' })).toHaveCount(1);
  await expect(page.locator('.chat-assistant-message')).toHaveCount(2, { timeout: 60_000 });

  const messageArea = page.locator('.chat-message-area');
  expect(await messageArea.evaluate((node) => node.scrollHeight > node.clientHeight)).toBe(true);
  await messageArea.evaluate((node) => { node.scrollTop = 0; node.dispatchEvent(new Event('scroll', { bubbles: true })); });
  await expect(page.getByRole('button', { name: /回到最新消息/ })).toBeVisible();
  await page.getByRole('button', { name: /回到最新消息/ }).click();

  const active = page.locator(`.conversation-item[data-conversation-id="${conversation.id}"]`);
  await active.locator('summary').click();
  await active.getByRole('button', { name: '重命名' }).click();
  const rename = active.getByRole('textbox', { name: /重命名会话/ });
  const renamedTitle = `经营复盘 ${Date.now()}`;
  await rename.fill(renamedTitle);
  const [patched] = await Promise.all([
    page.waitForResponse((response) => response.url().endsWith(`/api/v1/conversations/${conversation.id}`) && response.request().method() === 'PATCH'),
    active.getByRole('button', { name: '保存' }).click(),
  ]);
  expect(patched.status()).toBe(200);
  await page.getByRole('textbox', { name: '搜索会话' }).fill(renamedTitle);
  await expect(active).toContainText(renamedTitle);
  await page.getByRole('textbox', { name: '搜索会话' }).fill('绝不存在的会话关键词');
  await expect(page.getByText('没有匹配的会话')).toBeVisible();
  await page.getByRole('textbox', { name: '搜索会话' }).fill('');

  await active.locator('summary').click();
  await active.getByRole('button', { name: '删除' }).click();
  await active.getByRole('button', { name: '确认删除' }).click();
  await expect(active).toHaveCount(0);
  expect((await request.get(`${apiBase}/conversations/${conversation.id}`)).status()).toBe(404);
});

test('停止生成立即取消且不持久化成功消息', async ({ page, request }, testInfo) => {
  await page.goto('/?new=1');
  const input = page.getByRole('textbox', { name: '输入业务问题' });
  const stopQuestion = `综合分析各地区收入并解释区域经营维度，给出完整可验证结论。运行标识：${testInfo.workerIndex}-${testInfo.repeatEachIndex}-${Date.now()}`;
  await input.fill(stopQuestion);
  const [created] = await Promise.all([
    page.waitForResponse((response) => response.url().endsWith('/api/v1/conversations') && response.request().method() === 'POST'),
    input.press('Enter'),
  ]);
  const conversation = await created.json() as JsonRecord;
  try {
    const stop = page.getByRole('button', { name: '停止生成' });
    await expect(stop).toBeVisible();
    await stop.click();
    await expect(page.getByText('已停止生成，不会继续追加内容。')).toBeVisible();
    const before = await page.locator('.chat-assistant-message').last().textContent();
    await page.waitForTimeout(750);
    expect(await page.locator('.chat-assistant-message').last().textContent()).toBe(before);
    const detail = await json(await request.get(`${apiBase}/conversations/${conversation.id}`));
    expect(detail.messages.filter((item: JsonRecord) => item.role === 'assistant' && item.status === 'SUCCEEDED')).toHaveLength(0);
  } finally {
    await deleteConversation(request, conversation.id);
  }
});

test('真实拖拽、图片粘贴、上传进度、删除、失败与重试', async ({ page, request }) => {
  await page.goto('/?new=1');
  await page.evaluate(() => {
    (window as any).__uploadProgress = [];
    new MutationObserver(() => {
      document.querySelectorAll('.attachment-strip small').forEach((node) => {
        const text = node.textContent || '';
        if (/^\d+%$/.test(text)) (window as any).__uploadProgress.push(text);
      });
    }).observe(document.body, { childList: true, subtree: true, characterData: true });
  });

  const csv = path.resolve('..', 'evaluation', 'fixtures', 'phase2-regional-revenue.csv');
  const [created, csvUpload] = await Promise.all([
    page.waitForResponse((response) => response.url().endsWith('/api/v1/conversations') && response.request().method() === 'POST'),
    page.waitForResponse((response) => response.url().endsWith('/api/v1/attachments') && response.request().method() === 'POST'),
    dispatchFile(page, '.chat-composer', 'drop', csv, 'text/csv'),
  ]);
  expect(created.status()).toBe(201);
  expect(csvUpload.status()).toBe(201);
  const conversation = await created.json() as JsonRecord;
  try {
    await expect(page.getByRole('button', { name: '删除附件 phase2-regional-revenue.csv' })).toBeVisible();
    expect(await page.evaluate(() => (window as any).__uploadProgress.length)).toBeGreaterThan(0);
    await page.getByRole('button', { name: '删除附件 phase2-regional-revenue.csv' }).click();
    await expect(page.getByText('phase2-regional-revenue.csv')).toHaveCount(0);

    const image = path.resolve('..', 'docs', 'ui', '03_问数据_分析结果.png');
    const imageUploadPromise = page.waitForResponse((response) => response.url().endsWith('/api/v1/attachments') && response.request().method() === 'POST');
    await dispatchFile(page, 'textarea[aria-label="输入业务问题"]', 'paste', image, 'image/png');
    expect((await imageUploadPromise).status()).toBe(201);
    await expect(page.getByRole('button', { name: '删除附件 03_问数据_分析结果.png' })).toBeVisible();

    const failedUpload = page.waitForResponse((response) => response.url().endsWith('/api/v1/attachments') && response.request().method() === 'POST');
    await page.locator('.chat-composer').evaluate((node) => {
      const transfer = new DataTransfer();
      transfer.items.add(new File([new Uint8Array([1, 2, 3, 4])], 'broken.pdf', { type: 'application/pdf' }));
      node.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: transfer }));
    });
    expect((await failedUpload).status()).toBe(415);
    await expect(page.locator('.attachment-strip').getByText('File signature does not match PDF')).toBeVisible();
    const retryUpload = page.waitForResponse((response) => response.url().endsWith('/api/v1/attachments') && response.request().method() === 'POST');
    await page.locator('.attachment-strip').getByRole('button', { name: '重试' }).click();
    expect((await retryUpload).status()).toBe(415);
  } finally {
    await deleteConversation(request, conversation.id);
  }
});

test('匿名与跨用户会话、流式和附件访问失败关闭', async ({ request }) => {
  const conversation = await createConversation(request, `qa-rbac-${Date.now()}`);
  const anonymous = await requestFactory.newContext({ storageState: { cookies: [], origins: [] } });
  const analyst = await loginApi(analystCredentials.email, analystCredentials.password);
  try {
    expect((await anonymous.get(`${apiBase}/conversations/${conversation.id}`)).status()).toBe(401);
    expect((await anonymous.post(`${apiBase}/chat/stream`, { data: {
      conversation_id: conversation.id,
      content: '统计收入',
      client_message_id: `qa-anon-${crypto.randomUUID()}`,
      attachment_ids: [],
    } })).status()).toBe(401);
    expect((await analyst.get(`${apiBase}/conversations/${conversation.id}`)).status()).toBe(403);
    expect((await analyst.post(`${apiBase}/chat/stream`, { data: {
      conversation_id: conversation.id,
      content: '统计收入',
      client_message_id: `qa-cross-user-${crypto.randomUUID()}`,
      attachment_ids: [],
    } })).status()).toBe(403);
    expect((await analyst.get(`${apiBase}/attachments?conversation_id=${conversation.id}`)).status()).toBe(403);
  } finally {
    await anonymous.dispose();
    await analyst.dispose();
    await deleteConversation(request, conversation.id);
  }
});
