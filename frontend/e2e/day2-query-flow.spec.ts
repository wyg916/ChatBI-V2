import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

const apiBase = process.env.CHATBI_API_BASE ?? 'http://127.0.0.1:8000/api/v1';

function captureRuntimeErrors(page: Page) {
  const errors: string[] = [];
  page.on('console', (message) => { if (message.type() === 'error') errors.push(`console: ${message.text()}`); });
  page.on('pageerror', (error) => errors.push(`page: ${error.message}`));
  page.on('requestfailed', (request) => errors.push(`request: ${request.url()} ${request.failure()?.errorText ?? ''}`));
  return errors;
}

async function ask(request: APIRequestContext, question: string) {
  const response = await request.post(`${apiBase}/ask`, { data: { question, row_limit: 500 } });
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}

test('Day2-1 登录后默认进入真实问数据首页', async ({ page }) => {
  const errors = captureRuntimeErrors(page);
  await page.goto('/login');
  await page.getByLabel('账号或电子名').fill('day2.user');
  await page.getByRole('button', { name: '登录 ChatBI Studio' }).click();
  await expect(page).toHaveURL('/');
  await expect(page.getByRole('heading', { name: '今天想了解哪些业务数据？' })).toBeVisible();
  expect(errors).toEqual([]);
});

test('Day2-2 简单聚合返回真实数据库结果与 Oracle 证据', async ({ page }) => {
  const errors = captureRuntimeErrors(page);
  await page.goto(`/ask/results?q=${encodeURIComponent('统计全部订单收入')}`);
  await expect(page.getByTestId('query-success')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText('真实查询')).toBeVisible();
  await expect(page.getByText('结果通过校验')).toBeVisible();
  await page.getByRole('button', { name: '查看 SQL 与执行明细' }).click();
  await expect(page.getByRole('dialog', { name: 'SQL 与执行明细' })).toContainText('SUM');
  expect(errors).toEqual([]);
});

test('Day2-3 Join 查询展示地区维度与收入', async ({ page }) => {
  const errors = captureRuntimeErrors(page);
  await page.goto(`/ask/results?q=${encodeURIComponent('按地区统计订单收入')}`);
  await expect(page.getByTestId('query-success')).toBeVisible({ timeout: 30_000 });
  await expect(page.locator('.evidence-card')).toContainText('revenue');
  await expect(page.locator('.evidence-card')).toContainText('region');
  await expect(page.getByRole('img', { name: '真实查询结果图表' })).toBeVisible();
  await page.getByRole('button', { name: '查看 SQL 与执行明细' }).click();
  await expect(page.getByRole('dialog', { name: 'SQL 与执行明细' })).toContainText('JOIN');
  expect(errors).toEqual([]);
});

test('Day2-4 危险 SQL 被 AST Guard 拒绝且不访问数据库', async ({ page, request }) => {
  const errors = captureRuntimeErrors(page);
  const question = 'DELETE FROM demo_business.orders';
  const apiResult = await ask(request, question);
  expect(apiResult.status).toBe('SECURITY_REJECTED');
  expect(apiResult.execution).toEqual({});
  await page.goto(`/ask/results?q=${encodeURIComponent(question)}`);
  await expect(page.getByTestId('query-security')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('query-security')).toContainText('STATEMENT_NOT_ALLOWED');
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
