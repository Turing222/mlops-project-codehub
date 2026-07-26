import { test, expect } from '@playwright/test';
import { mockLoginRoute, performLogin } from '../../fixtures/auth';
import {
  buildChatSSEBody,
  mockSessionDetailRoute,
  mockSessionsRoute,
} from '../../fixtures/sse';
import {
  mockChatMessage,
  mockSession,
  mockSessionDetail,
} from '../../fixtures/api-mocks';

const session = mockSession({ id: 'retry-session', title: 'Retry History' });
const failedUserMessage = mockChatMessage({
  id: 'retry-user-message',
  session_id: session.id,
  role: 'user',
  content: 'Please retry this request',
});
const failedAssistantMessage = mockChatMessage({
  id: 'retry-assistant-message',
  session_id: session.id,
  content: 'The original generation failed.',
  status: 'failed',
  generation_request_id: 'generation-request-1',
  attempt: 3,
  retryable: true,
  error_code: 'CHAT_GENERATION_FAILED',
});

function failedSessionDetail() {
  return mockSessionDetail({
    session,
    messages: [failedUserMessage, failedAssistantMessage],
  });
}

test.describe('Chat explicit retry rollout', () => {
  test('flag off hides retry for a refreshed failed message', async ({ page }) => {
    let retryRequests = 0;
    await mockLoginRoute(page, {
      features: { 'chat-explicit-retry': false },
    });
    await mockSessionsRoute(page, [session]);
    await mockSessionDetailRoute(page, session.id as string, failedSessionDetail());
    await page.route('**/api/v1/chat/requests/*/retry', async (route) => {
      retryRequests += 1;
      await route.abort();
    });

    await page.goto('/');
    await performLogin(page);
    await page.getByRole('button', { name: 'Retry History' }).click();

    await expect(page.getByText('The original generation failed.')).toBeVisible();
    await expect(page.getByRole('button', { name: '重试' })).toHaveCount(0);
    expect(retryRequests).toBe(0);
  });

  test('flag on retries a refreshed failure with durable identity only', async ({ page }) => {
    let detailReads = 0;
    let retryBody: unknown;
    let queryStreamRequests = 0;
    const recoveredAssistantMessage = mockChatMessage({
      ...failedAssistantMessage,
      content: 'Recovered after refresh.',
      status: 'success',
      attempt: 4,
      retryable: false,
      error_code: null,
    });
    const recoveredDetail = mockSessionDetail({
      session,
      messages: [failedUserMessage, recoveredAssistantMessage],
    });

    await mockLoginRoute(page, {
      features: { 'chat-explicit-retry': true },
    });
    await mockSessionsRoute(page, [session]);
    await mockSessionDetailRoute(page, session.id as string, () => {
      detailReads += 1;
      return detailReads === 1 ? failedSessionDetail() : recoveredDetail;
    });
    await page.route('**/api/v1/chat/query_stream', async (route) => {
      queryStreamRequests += 1;
      await route.abort();
    });
    await page.route(
      '**/api/v1/chat/requests/generation-request-1/retry',
      async (route) => {
        retryBody = route.request().postDataJSON();
        await route.fulfill({
          status: 200,
          headers: {
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache',
          },
          body: buildChatSSEBody({
            sessionId: session.id as string,
            sessionTitle: session.title as string,
            chunks: ['Recovered', ' after', ' refresh.'],
            meta: {
              message_id: failedAssistantMessage.id,
              generation_request_id: 'generation-request-1',
              attempt: 4,
            },
          }),
        });
      },
    );

    await page.goto('/');
    await performLogin(page);
    await page.getByRole('button', { name: 'Retry History' }).click();

    const retryButton = page.getByRole('button', { name: '重试' });
    await expect(retryButton).toBeVisible();
    await retryButton.click();

    await expect(page.getByText('Recovered after refresh.')).toBeVisible();
    expect(retryBody).toEqual({ expected_attempt: 3 });
    expect(queryStreamRequests).toBe(0);
    await expect(page.locator('.chat-message.assistant')).toHaveCount(1);
  });
});
