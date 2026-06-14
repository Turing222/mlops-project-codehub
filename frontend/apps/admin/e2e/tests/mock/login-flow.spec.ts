import { test, expect } from '@playwright/test';
import { mockLoginRoute, performLogin } from '../../fixtures/auth';
import { mockSessionsRoute } from '../../fixtures/sse';

test.describe('Login flow', () => {
  test('user can login and see authenticated state', async ({ page }) => {
    await mockLoginRoute(page);
    await mockSessionsRoute(page, []);
    await page.goto('/');

    await performLogin(page);

    await expect(page.locator('.auth-modal')).not.toBeVisible();

    const avatarBadge = page.locator('.avatar-badge:not(.guest)');
    await expect(avatarBadge).toBeVisible();
    await expect(avatarBadge).toHaveText('T');

    await expect(page.locator('.sidebar-hint')).toHaveText('暂无对话记录');

    await expect(page.locator('.avatar-badge.guest')).not.toBeVisible();
  });
});
