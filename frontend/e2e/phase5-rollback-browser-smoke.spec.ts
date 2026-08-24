import { expect, test } from '@playwright/test';


test('isolated rollback deployment keeps the ChatBI product shell usable', async ({ page }) => {
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('requestfailed', (request) => {
    failedRequests.push(`${request.method()} ${request.url()}`);
  });

  await page.goto('/ask', { waitUntil: 'networkidle' });
  const workspaceNav = page.getByRole('navigation', { name: '一级导航' });
  await expect(workspaceNav.getByRole('link')).toHaveCount(6);
  for (const label of ['问数据', '数据源', '语义模型', '答案库', '看板', '评测中心']) {
    await expect(workspaceNav.getByRole('link', { name: new RegExp(`${label}$`) })).toBeVisible();
  }
  await workspaceNav.getByRole('link', { name: /看板$/ }).click();
  await expect(page).toHaveURL(/\/dashboards/);
  await expect(page.locator('body')).not.toContainText('Application error');

  expect(consoleErrors, consoleErrors.join('\n')).toEqual([]);
  expect(failedRequests, failedRequests.join('\n')).toEqual([]);
});
