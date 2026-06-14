import { test, expect } from '@playwright/test';
import { mockAdminLoginRoute, seedAuthState } from '../../fixtures/auth';
import { mockUser } from '../../fixtures/api-mocks';
import { mockSessionsRoute } from '../../fixtures/sse';

test.describe('Admin user management', () => {
  test('admin can search and edit a user', async ({ page }) => {
    await mockAdminLoginRoute(page);
    await mockSessionsRoute(page, []);
    await seedAuthState(page);

    const searchedUser = mockUser({
      id: 'user-2',
      username: 'johndoe',
      email: 'john@example.com',
      used_tokens: 2000,
      max_tokens: 5000,
    });

    const updatedUser = { ...searchedUser, username: 'johndoe_updated', max_tokens: 10000 };

    let currentResult = searchedUser;

    await page.route('**/api/v1/users/user-2', async (route) => {
      if (route.request().method() === 'PATCH') {
        currentResult = updatedUser;
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(updatedUser),
        });
      }
    });

    await page.route('**/api/v1/users?**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(currentResult),
      });
    });

    await page.goto('/admin');

    await expect(page.locator('.admin-layout')).toBeVisible();
    await expect(page.locator('.header-title')).toHaveText('管理后台');

    const searchInput = page.getByPlaceholder('搜索用户名或邮箱');
    await searchInput.fill('johndoe');
    await searchInput.press('Enter');

    await expect(page.locator('.ant-table-row').first()).toContainText('johndoe');
    await expect(page.locator('.ant-table-row').first()).toContainText('john@example.com');

    await page.locator('.ant-table-row').first().locator('button').first().click();

    await expect(page.locator('.ant-modal')).toBeVisible();

    const usernameInput = page.locator('.ant-modal').getByPlaceholder('用户名');
    await usernameInput.clear();
    await usernameInput.fill('johndoe_updated');

    await page.locator('.ant-modal button[type="submit"]').click();

    await expect(page.locator('.ant-modal')).not.toBeVisible();
    await expect(page.locator('.ant-table-row').first()).toContainText('johndoe_updated');
  });
});
