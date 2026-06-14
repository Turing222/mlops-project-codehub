import { test, expect } from '@playwright/test';
import { ensureDailyCheckinOnCreditsPage } from '../../fixtures/smoke-credits';
import { seedSmokeAuthState } from '../../fixtures/smoke-auth';

test.skip(() => !process.env.E2E_SMOKE, 'Requires running backend (set E2E_SMOKE=1)');

test.describe('Real backend: minimal chat chain', () => {
  test('send a short question, receive a streamed response', async ({ page, request }) => {
    await seedSmokeAuthState(page, request);
    await expect(page.locator('.avatar-badge:not(.guest)')).toBeVisible();

    // Ensure the user has credits by visiting the credits page and performing checkin
    await page.goto('/credits');
    await expect(page.getByText('本月签到记录', { exact: true })).toBeVisible();
    await ensureDailyCheckinOnCreditsPage(page);

    // Go back to the chat page to send the question
    await page.goto('/');
    await expect(page.getByTestId('chat-input')).toBeVisible();

    const assistantMessages = page.locator('.chat-message.assistant .message-text');
    const previousAssistantCount = await assistantMessages.count();

    await page.getByTestId('chat-input').fill('你好');
    await page.getByTestId('send-btn').click();

    await expect(assistantMessages.nth(previousAssistantCount)).toBeVisible({
      timeout: 30000,
    });

    await expect.poll(
      async () => (await assistantMessages.nth(previousAssistantCount).textContent())?.trim().length ?? 0,
      { timeout: 30000 },
    ).toBeGreaterThan(0);

    const responseText = await assistantMessages.nth(previousAssistantCount).textContent();
    expect(responseText!.length).toBeGreaterThan(0);
  });
});
