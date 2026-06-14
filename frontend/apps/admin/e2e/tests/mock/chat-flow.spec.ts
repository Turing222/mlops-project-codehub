import { test, expect } from '@playwright/test';
import { mockLoginRoute, performLogin } from '../../fixtures/auth';
import { mockChatSSERoute, mockSessionsRoute } from '../../fixtures/sse';
import { mockSession } from '../../fixtures/api-mocks';

test.describe('Chat flow with SSE streaming', () => {
  test('user sends a message and receives streaming response', async ({ page }) => {
    await mockLoginRoute(page);

    const session = mockSession({ id: 'session-1', title: 'New Chat' });
    await mockSessionsRoute(page, [session]);

    await mockChatSSERoute(page, {
      sessionId: 'session-1',
      sessionTitle: 'New Chat',
      chunks: ['Hello', ' from', ' AI', ' assistant', '.'],
    });

    await page.goto('/');
    await performLogin(page);

    await expect(page.getByText('开始你的对话')).toBeVisible();

    await page.getByTestId('chat-input').fill('What is AI?');
    await page.getByTestId('send-btn').click();

    await expect(page.locator('.chat-message.user .message-text')).toHaveText('What is AI?');

    await expect(page.locator('.chat-message.assistant .message-text')).toContainText('Hello from AI assistant');

    await expect(page.locator('.cursor-blink')).not.toBeVisible();

    await expect(page.getByTestId('session-item')).toContainText('New Chat');

    await expect(page.locator('.chat-header-title')).toHaveText('New Chat');
  });
});
