import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { adminCredentials } from './auth';

const apiBase = process.env.CHATBI_API_BASE ?? 'http://127.0.0.1:8000/api/v1';

function captureRuntimeErrors(page: Page) {
  const errors: string[] = [];
  page.on('console', (message) => { if (message.type() === 'error') errors.push(`console: ${message.text()}`); });
  page.on('pageerror', (error) => errors.push(`page: ${error.message}`));
  page.on('requestfailed', (request) => {
    if (request.failure()?.errorText !== 'net::ERR_ABORTED') errors.push(`request: ${request.url()} ${request.failure()?.errorText ?? ''}`);
  });
  return errors;
}

async function ask(request: APIRequestContext, question: string) {
  const response = await request.post(`${apiBase}/ask`, { data: { question, row_limit: 500 } });
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}

test('Day2-1 登录后默认进入真实问数据首页', async ({ page }) => {
  const errors = captureRuntimeErrors(page);
  await page.context().clearCookies();
  await page.goto('/login');
  await page.getByLabel('账号或电子名').fill(adminCredentials.email);
  await page.getByLabel('密码').fill(adminCredentials.password);
  await page.getByRole('button', { name: '登录 ChatBI Studio' }).click();
  await expect(page).toHaveURL('/');
  await expect(page.getByRole('textbox', { name: '输入业务问题' })).toBeVisible();
  expect(errors).toEqual([]);
});

test('Day2-2 简单聚合返回真实数据库结果与 Oracle 证据', async ({ page }) => {
  const errors = captureRuntimeErrors(page);
  await page.goto(`/ask/results?q=${encodeURIComponent('统计全部订单收入')}`);
  await expect(page.getByTestId('query-success')).toBeVisible({ timeout: 30_000 });
  await expect(page.locator('.assistant-response-head')).toContainText('查询执行已校验');
  await expect(page.locator('.answer-conclusion')).toContainText('核心结论');
  await expect(page.getByRole('dialog', { name: 'SQL 与执行明细' })).toHaveCount(0);
  await page.getByRole('button', { name: '查看 SQL 与执行明细' }).click();
  const dialog = page.getByRole('dialog', { name: 'SQL 与执行明细' });
  await expect(dialog).toContainText('SUM');
  await expect(dialog).toContainText('只读查询安全校验通过');
  await expect(dialog).toContainText('指标、维度、过滤与结果值已校验');
  await expect(dialog).toContainText('语义口径版本已绑定');
  expect(errors).toEqual([]);
});

test('Day2-3 Join 查询展示地区维度与收入', async ({ page }) => {
  const errors = captureRuntimeErrors(page);
  await page.goto(`/ask/results?q=${encodeURIComponent('按地区统计订单收入')}`);
  await expect(page.getByTestId('query-success')).toBeVisible({ timeout: 30_000 });
  const chart = page.locator('.chart-card .data-echart');
  await expect(chart).toBeVisible();
  expect((await chart.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(240);
  await expect(chart.locator('canvas, svg')).toBeVisible();
  await page.getByRole('button', { name: '查看 SQL 与执行明细' }).click();
  const dialog = page.getByRole('dialog', { name: 'SQL 与执行明细' });
  await expect(dialog).toContainText('revenue');
  await expect(dialog).toContainText('region');
  await expect(dialog).toContainText('JOIN');
  expect(errors).toEqual([]);
});

test('Day2-4 危险 SQL 被 AST Guard 拒绝且不访问数据库', async ({ page, request }) => {
  const errors = captureRuntimeErrors(page);
  const question = 'DELETE FROM demo_business.orders';
  const apiResult = await ask(request, question);
  expect(apiResult.status).toBe('SECURITY_REJECTED');
  expect(apiResult.execution).toEqual({});
  await page.goto(`/ask/results?q=${encodeURIComponent(question)}`);
  const refused = page.getByTestId('result-state-FAILED');
  await expect(refused).toBeVisible({ timeout: 30_000 });
  await expect(refused).toContainText('回答未完成');
  await expect(refused).toContainText('超出了当前 ChatBI 的只读分析范围');
  await expect(refused.getByRole('button', { name: '重新查询' })).toBeVisible();
  await expect(page.getByTestId('query-success')).toHaveCount(0);
  await expect(page.locator('.chart-card, .table-card')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '保存为已验证答案' })).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('Day2-5 Result Oracle 能识别独立期望值不一致', async ({ request }) => {
  const result = await ask(request, '统计全部订单量');
  expect(result.status).toBe('SUCCEEDED');
  const verify = await request.post(`${apiBase}/queries/${result.id}/verify`, {
    data: {
      expected: {
        columns: ['order_count'], rows: [{ order_count: -1 }], tolerance: 0,
        order_independent: true, expected_signature: '0'.repeat(64),
      },
    },
  });
  expect(verify.ok(), await verify.text()).toBeTruthy();
  const verified = await verify.json();
  expect(verified.status).toBe('ORACLE_MISMATCH');
  expect(verified.oracle.mismatch_count).toBeGreaterThan(0);
});

test('Day2-6 用户反馈与标准答案保存落入 Backend API', async ({ page, request }) => {
  const errors = captureRuntimeErrors(page);
  await page.goto(`/ask/results?q=${encodeURIComponent('按产品统计订单收入前5名')}`);
  await expect(page.getByTestId('query-success')).toBeVisible({ timeout: 30_000 });
  await page.getByRole('button', { name: '结果有帮助' }).click();
  await expect(page.getByText('已记录“有帮助”')).toBeVisible();
  await page.getByRole('button', { name: '保存为已验证答案' }).click();
  await expect(page.getByText('已保存到答案库')).toBeVisible();
  const answers = await request.get(`${apiBase}/answers?query=${encodeURIComponent('按产品统计订单收入前5名')}`);
  expect(answers.ok()).toBeTruthy();
  expect((await answers.json()).items.some((item: { question: string }) => item.question === '按产品统计订单收入前5名')).toBe(true);
  expect(errors).toEqual([]);
});
