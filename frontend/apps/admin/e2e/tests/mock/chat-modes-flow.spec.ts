import { test, expect } from '@playwright/test';
import { mockLoginRoute, performLogin } from '../../fixtures/auth';
import { mockChatSSERoute, mockSessionsRoute } from '../../fixtures/sse';
import { mockDefaultKnowledgeRoute } from '../../fixtures/knowledge';
import { mockSession } from '../../fixtures/api-mocks';

test.describe('Chat mode happy paths', () => {
  test.beforeEach(async ({ page }) => {
    await mockLoginRoute(page);
    await mockSessionsRoute(page, [mockSession()]);
    await mockDefaultKnowledgeRoute(page);
    await page.goto('/');
    await performLogin(page);
    await expect(page.getByText('开始你的对话')).toBeVisible();
  });

  test('RAG mode sends a question and receives a streamed answer', async ({ page }) => {
    await mockChatSSERoute(page, {
      sessionId: 'session-rag-1',
      sessionTitle: 'RAG Session',
      chunks: ['Knowledge', ' base', ' answer', '.'],
    });

    await page.getByRole('heading', { name: '知识库问答 RAG' }).click();
    await page.getByTestId('chat-input').fill('What is in my knowledge base?');
    await page.getByTestId('send-btn').click();

    await expect(page.locator('.chat-message.assistant .message-text')).toContainText(
      'Knowledge base answer.',
      { timeout: 15000 },
    );
  });

  test('Web RAG mode sends a question and receives a streamed answer', async ({ page }) => {
    await mockChatSSERoute(page, {
      sessionId: 'session-web-rag-1',
      sessionTitle: 'Web RAG Session',
      chunks: ['Web', ' enhanced', ' answer', '.'],
    });

    await page.getByRole('heading', { name: '增强 RAG' }).click();
    await page.getByTestId('chat-input').fill('What is the latest public info?');
    await page.getByTestId('send-btn').click();

    await expect(page.locator('.chat-message.assistant .message-text')).toContainText(
      'Web enhanced answer.',
      { timeout: 15000 },
    );
  });

  test('repo check mode card opens the dedicated analysis page', async ({ page }) => {
    await page.getByRole('heading', { name: '仓库可信度初筛' }).click();
    await expect(page).toHaveURL(/\/repo-check$/);
    await expect(page.getByRole('heading', { name: 'AI 项目可信度初筛报告' })).toBeVisible();
  });
});
