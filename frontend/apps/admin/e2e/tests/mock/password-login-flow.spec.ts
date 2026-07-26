import { test, expect } from '@playwright/test';
import {
  mockAuthConfigRoute,
  mockLoginRoute,
  performPasswordLogin,
} from '../../fixtures/auth';
import { mockSessionsRoute } from '../../fixtures/sse';

test.describe('Staff password login flow', () => {
  test('user can login with username and password when flag is enabled', async ({ page }) => {
    await mockAuthConfigRoute(page, { 'enable-password-login': true });
    await mockLoginRoute(page, { username: 'staff_user' });
    await mockSessionsRoute(page, []);
    await page.goto('/');

    await performPasswordLogin(page, 'staff_user', 'password123');

    await expect(page.locator('.auth-modal')).not.toBeVisible();

    const avatarBadge = page.locator('.avatar-badge:not(.guest)');
    await expect(avatarBadge).toBeVisible();
    await expect(avatarBadge).toHaveText('S');

    await expect(page.locator('.sidebar-hint')).toHaveText('暂无对话记录');
  });

  test('password login form stays hidden when flag is disabled', async ({ page }) => {
    await mockAuthConfigRoute(page, { 'enable-password-login': false });
    await mockLoginRoute(page);
    await page.goto('/');

    await page.getByTestId('user-menu-btn').click();

    await expect(page.getByTestId('password-login-username')).not.toBeVisible();
    await expect(page.locator('input#phone-login_phone')).toBeVisible();
  });
});
