import { expect, test } from '@playwright/test';

test('Day2 问数据结果页三视口无裁切并保存 1440x900 证据', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('console', (message) => { if (message.type() === 'error') errors.push(`console: ${message.text()}`); });
  page.on('pageerror', (error) => errors.push(`page: ${error.message}`));
  page.on('requestfailed', (request) => {
    if (request.failure()?.errorText !== 'net::ERR_ABORTED') errors.push(`request: ${request.url()} ${request.failure()?.errorText ?? ''}`);
  });
  for (const viewport of [
    { width: 1366, height: 768 },
    { width: 1440, height: 900 },
    { width: 1920, height: 1080 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto(`/ask/results?q=${encodeURIComponent('2026年按地区按月统计已支付订单收入趋势')}`);
    await expect(page.getByTestId('query-success')).toBeVisible({ timeout: 30_000 });
    expect(await page.locator('body').evaluate((body) => body.scrollWidth <= window.innerWidth), `${viewport.width}x${viewport.height}`).toBe(true);
    if (viewport.width === 1440) {
      const screenshotPath = testInfo.outputPath('ask-result-1440x900.png');
      await page.screenshot({ path: screenshotPath, fullPage: false });
      await testInfo.attach('ask-result-1440x900', { path: screenshotPath, contentType: 'image/png' });
    }
  }
  expect(errors).toEqual([]);
});
