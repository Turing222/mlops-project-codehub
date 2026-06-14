import type { Page } from '@playwright/test';
import { mockAuthResponse, mockUser } from './api-mocks';

const AUTH_STORAGE_KEY = 'auth-storage';

export async function mockLoginRoute(
  page: Page,
  userOverrides: Record<string, unknown> = {},
  authOverrides: Record<string, unknown> = {},
) {
  const user = mockUser(userOverrides);
  await page.route('**/api/v1/auth/login', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockAuthResponse(authOverrides)),
    });
  });
  await page.route('**/api/v1/auth/sms/send', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ message: 'Code sent' }),
    });
  });
  await page.route('**/api/v1/auth/sms/login', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockAuthResponse(authOverrides)),
    });
  });
  await page.route('**/api/v1/users/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(user),
    });
  });
  return user;
}

export async function mockAdminLoginRoute(
  page: Page,
  overrides: Record<string, unknown> = {},
) {
  return mockLoginRoute(page, {
    id: 'admin-1',
    username: 'admin',
    email: 'admin@example.com',
    role: 'admin',
    is_superuser: true,
    ...overrides,
  });
}

/**
 * Seeds the Zustand auth store in localStorage so the app boots already authenticated.
 * Navigates to the app first (localStorage needs an origin), writes the token, then reloads.
 */
export async function seedAuthState(page: Page, token = 'mock-jwt-token-abc123') {
  await page.goto('/');
  await page.evaluate(({ key, val }) => {
    localStorage.setItem(key, JSON.stringify({ state: { token: val }, version: 0 }));
  }, { key: AUTH_STORAGE_KEY, val: token });
  await page.reload();
}

export async function performLogin(
  page: Page,
  phone = '13800000000',
  code = '123456',
) {
  await page.getByTestId('user-menu-btn').click();
  await page.locator('.auth-modal').locator('input#phone-login_phone').fill(phone);
  await page.locator('.auth-modal').locator('input[maxlength="6"]').fill(code);
  await page.locator('.auth-modal').locator('button[type="submit"]').click();
}
