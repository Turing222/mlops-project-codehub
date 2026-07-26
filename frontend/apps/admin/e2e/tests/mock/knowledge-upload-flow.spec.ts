import { test, expect } from '@playwright/test';
import { mockLoginRoute, performLogin } from '../../fixtures/auth';
import { mockSessionsRoute } from '../../fixtures/sse';
import { mockKnowledgeUploadInstantRoute } from '../../fixtures/knowledge';

test.describe('Knowledge base upload', () => {
  test('uploads a markdown file and completes ingestion', async ({ page }) => {
    await mockLoginRoute(page);
    await mockSessionsRoute(page, []);
    await mockKnowledgeUploadInstantRoute(page);
    await page.goto('/');
    await performLogin(page);

    await expect(page.getByText('开始你的对话')).toBeVisible();

    const fileChooserPromise = page.waitForEvent('filechooser');
    await page.getByTitle('上传文件').click();
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles({
      name: 'playwright-notes.md',
      mimeType: 'text/markdown',
      buffer: Buffer.from('# Playwright Notes\n\nHappy path upload fixture.\n'),
    });

    await expect(page.getByText('文件入库成功 (秒传匹配)！')).toBeVisible({ timeout: 15000 });
  });
});
