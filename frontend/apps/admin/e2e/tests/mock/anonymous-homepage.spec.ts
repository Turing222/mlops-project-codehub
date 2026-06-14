import { test, expect } from '@playwright/test';

test.describe('Anonymous homepage', () => {
  test('shows chat page with login hint and no user avatar', async ({ page }) => {
    await page.route('**/api/v1/**', (route) => route.abort());

    await page.goto('/');

    await expect(page.locator('.chat-page')).toBeVisible();

    await expect(page.locator('.sidebar-hint')).toHaveText('登录后可查看历史记录');

    await expect(page.locator('.avatar-badge.guest')).toBeVisible();

    await expect(page.locator('.avatar-badge:not(.guest)')).not.toBeVisible();

    await expect(page.getByText('开始你的对话')).toBeVisible();
  });
});
