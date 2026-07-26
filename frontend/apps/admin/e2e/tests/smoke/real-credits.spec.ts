import { test, expect } from '@playwright/test';
import { ensureDailyCheckinOnCreditsPage } from '../../fixtures/smoke-credits';
import { seedSmokeAuthState } from '../../fixtures/smoke-auth';

test.skip(() => !process.env.E2E_SMOKE, 'Requires running backend (set E2E_SMOKE=1)');

test.describe('Real backend: Credits Center', () => {
  test('unauthorized placeholder, login, view balance, perform check-in, and check transactions', async ({ page, request }) => {
    // Print browser console logs to terminal
    page.on('console', msg => console.log(`[BROWSER CONSOLE] ${msg.type().toUpperCase()}: ${msg.text()}`));

    // 1. Visit credits page as guest
    await page.goto('/credits');

    // Verify guest placeholder elements are visible
    // B1 起 AppShell 顶栏也含「积分中心」(导航项 + 页名),guest 标题限定在 main 内查找
    await expect(page.getByRole('main').getByText('积分中心', { exact: true })).toBeVisible();
    await expect(page.getByText('登录后探索积分中心', { exact: false })).toBeVisible();

    // 2. Log in through the real backend credentials path.
    await seedSmokeAuthState(page, request);
    await page.goto('/credits');

    // Wait until login completes and the guest view is replaced by the authentic Credits dashboard
    await expect(page.locator('text=当前可用积分')).toBeVisible({ timeout: 15000 });

    // 3. Verify Credit Balance and Elements
    await expect(page.getByText('本月签到记录', { exact: true })).toBeVisible();
    await expect(page.getByText('收支明细', { exact: true })).toBeVisible();

    // 4. Ensure daily check-in (idempotent across repeated smoke runs)
    await ensureDailyCheckinOnCreditsPage(page);

    // 5. Verify transaction log contains the checkin record
    await expect(page.locator('text=每日签到').first()).toBeVisible();

    // 6. Test Navigation Back to Chat/Home(B1 起经 AppShell 全局导航,原「返回主页」按钮已移除)
    await page
        .getByRole('navigation', { name: '全局导航' })
        .getByRole('button', { name: '对话' })
        .click();
    await expect(page).toHaveURL('/');
  });
});
