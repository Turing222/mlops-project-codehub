import type { Page } from '@playwright/test';

export async function mockDefaultKnowledgeRoute(page: Page) {
  await page.route('**/api/v1/knowledge/default', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'kb-default-1',
        name: 'Default Knowledge Base',
      }),
    });
  });
}

export async function mockKnowledgeUploadInstantRoute(page: Page) {
  await page.route('**/api/v1/knowledge/default/upload', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        task_id: 'task-upload-1',
        file_id: 'file-1',
        kb_id: 'kb-default-1',
        file_status: 'completed',
        task_status: 'completed',
        deduplicated: true,
      }),
    });
  });
}
