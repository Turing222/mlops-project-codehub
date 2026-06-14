import { test, expect } from '@playwright/test';
import { seedSmokeAuthState } from '../../fixtures/smoke-auth';

test.skip(() => !process.env.E2E_SMOKE, 'Requires running backend (set E2E_SMOKE=1)');

test.describe('Real backend: login + profile', () => {
  test('seed auth state with real credentials and fetch /users/me', async ({ page, request }) => {
    await seedSmokeAuthState(page, request);
    await expect(page.locator('.avatar-badge:not(.guest)')).toBeVisible();

    await expect(page.locator('.sidebar-hint, [data-testid="session-item"]').first()).toBeVisible({
      timeout: 15000,
    });
  });
});
