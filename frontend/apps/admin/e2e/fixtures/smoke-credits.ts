import { expect, type Page } from '@playwright/test';

/**
 * Wait for the credits dashboard check-in UI to settle, then ensure the user
 * has checked in today. Retries through React Query refreshes that swap the
 * button for the "already checked in" badge mid-click.
 */
export async function ensureDailyCheckinOnCreditsPage(page: Page) {
  const checkedBadge = page.locator('text=今日已签到');

  await expect(async () => {
    if (await checkedBadge.isVisible()) {
      return;
    }

    const checkinBtn = page.getByRole('button', { name: '签到领积分' });
    await expect(checkinBtn).toBeVisible();
    await checkinBtn.click();
    await expect(checkedBadge).toBeVisible();
  }).toPass({ timeout: 15000 });
}
