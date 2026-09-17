import path from 'node:path';
import { expect, test, type Page } from '@playwright/test';

async function startFreshConversation(page: Page) {
  await page.getByRole('button', { name: '＋ 新会话' }).click();
  await expect(page.locator('.conversation-item.local.active')).toContainText('发送消息后保存');
  await expect(page.getByRole('textbox', { name: '输入业务问题' })).toBeVisible();
}

test('Phase2 recorded vision fixture completes the multimodal follow-up', async ({ page }) => {
  await page.goto('/');
  await startFreshConversation(page);
  const fileInput = page.locator('input[type="file"]');
  const image = path.resolve('..', 'docs', 'ui', '03_问数据_分析结果.png');
  await fileInput.setInputFiles(image);
  await expect(page.getByRole('button', { name: '删除附件 03_问数据_分析结果.png' })).toBeVisible();

  const input = page.getByRole('textbox', { name: '输入业务问题' });
  await input.fill('左侧导航当前高亮项和内容区粗体主标题相同，它们是哪三个字？');
  const assistantCount = await page.locator('.chat-assistant-message').count();
  await expect(page.getByRole('button', { name: '提交问题' })).toBeEnabled();
  await input.press('Enter');
  await expect(page.locator('.chat-assistant-message')).toHaveCount(assistantCount + 1, { timeout: 60_000 });
  await expect(page.locator('.chat-assistant-message').last()).toContainText('问数据', { timeout: 60_000 });
});
