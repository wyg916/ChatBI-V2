import { expect, test, type Page } from '@playwright/test';
import { apiBase } from './auth';

function runtimeErrors(page: Page) {
  const errors: string[] = [];
  page.on('console', (message) => { if (message.type() === 'error') errors.push(`console: ${message.text()}`); });
  page.on('pageerror', (error) => errors.push(`page: ${error.message}`));
  page.on('requestfailed', (request) => {
    if (request.failure()?.errorText !== 'net::ERR_ABORTED') errors.push(`request: ${request.url()} ${request.failure()?.errorText ?? ''}`);
  });
  return errors;
}

test('C Data Workspace provides a real guarded 10M user loop', async ({ page, request }) => {
  const sourceResponse = await request.get(`${apiBase}/datasources`);
  expect(sourceResponse.ok()).toBeTruthy();
  const sources = await sourceResponse.json() as Array<{ id: string; type: string; schema?: string }>;
  const source = sources.find((item) => item.schema === 'chatbi_benchmark_v21');
  expect(source, '10M benchmark datasource').toBeTruthy();
  const errors = runtimeErrors(page);

  await page.goto(`/datasources/${source!.id}/workspace`);
  await expect(page.getByRole('heading', { name: '数据工作台' })).toBeVisible();
  await expect(page.getByText('全链路只读安全执行')).toBeVisible();
  await page.getByLabel('工作台 Schema').selectOption('chatbi_benchmark_v21');
  await page.getByRole('button', { name: /^fact_sales \d+ 字段$/ }).click();
  await page.getByRole('button', { name: '懒加载样例值' }).click();
  await expect(page.getByText(/第 1 页 · 50 行/)).toBeVisible({ timeout: 30_000 });

  await page.getByRole('button', { name: 'SQL 工作区' }).click();
  const editor = page.getByLabel('SQL 编辑器');
  await editor.fill("SELECT region_id, COUNT(order_id) AS sale_count FROM chatbi_benchmark_v21.fact_sales WHERE order_date >= DATE '2026-12-01' AND order_date < DATE '2027-01-01' GROUP BY region_id ORDER BY region_id LIMIT 5");
  await page.getByTestId('execute-sql').click();
  await expect(page.locator('.sql-result-panel tbody tr')).toHaveCount(5, { timeout: 30_000 });
  await page.getByRole('button', { name: '保存为 Verified SQL' }).click();
  await expect(page.getByRole('status')).toContainText('Verified SQL 已保存到答案库');

  await editor.fill('DELETE FROM chatbi_benchmark_v21.fact_sales');
  await page.getByTestId('execute-sql').click();
  await expect(page.locator('.sql-result-panel')).toContainText('STATEMENT_NOT_ALLOWED');
  await page.getByRole('button', { name: '查询历史' }).click();
  await expect(page.locator('.workspace-history article').first()).toContainText('SECURITY_REJECTED');

  expect(await page.locator('body').evaluate((body) => body.scrollWidth <= window.innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});
