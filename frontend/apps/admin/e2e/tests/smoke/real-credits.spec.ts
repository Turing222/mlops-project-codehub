import { test, expect } from '@playwright/test';
import { seedSmokeAuthState } from '../../fixtures/smoke-auth';

test.skip(() => !process.env.E2E_SMOKE, 'Requires running backend (set E2E_SMOKE=1)');

test.describe('Real backend: Credits Center', () => {
  test('unauthorized placeholder, login, view balance, perform check-in, and check transactions', async ({ page, request }) => {
    // Print browser console logs to terminal
    page.on('console', msg => console.log(`[BROWSER CONSOLE] ${msg.type().toUpperCase()}: ${msg.text()}`));

    // 1. Visit credits page as guest
    await page.goto('/credits');

    // Verify guest placeholder elements are visible
    await expect(page.getByText('积分中心', { exact: true })).toBeVisible();
    await expect(page.getByText('登录后探索积分中心', { exact: false })).toBeVisible();

    // 2. Log in through the real backend credentials path.
    await seedSmokeAuthState(page, request);
    await page.goto('/credits');

    // Wait until login completes and the guest view is replaced by the authentic Credits dashboard
    await expect(page.locator('text=当前可用积分')).toBeVisible({ timeout: 15000 });

    // 3. Verify Credit Balance and Elements
    await expect(page.getByText('本月签到记录', { exact: true })).toBeVisible();
    await expect(page.getByText('收支明细', { exact: true })).toBeVisible();

    // 4. Click Check In if available
    const checkinBtn = page.getByRole('button', { name: '签到领积分' });
    const checkedBadge = page.locator('text=今日已签到');

    if (await checkinBtn.isVisible()) {
      await checkinBtn.click();
      // Verify successful checkin message and state change
      await expect(checkedBadge).toBeVisible({ timeout: 10000 });
    } else {
      // Already checked in today (from previous test run or seed data)
      await expect(checkedBadge).toBeVisible();
    }

    // 5. Verify transaction log contains the checkin record
    await expect(page.locator('text=每日签到').first()).toBeVisible();

    // 6. Test Navigation Back to Chat/Home
    await page.getByRole('button', { name: '返回主页' }).click();
    await expect(page).toHaveURL('/');
  });
});
