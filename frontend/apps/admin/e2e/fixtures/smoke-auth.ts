import type { APIRequestContext, Page } from '@playwright/test';

const AUTH_STORAGE_KEY = 'auth-storage';

type LoginResponse = {
  access_token?: string;
};

const requireSmokeCredential = (name: 'E2E_SMOKE_USER' | 'E2E_SMOKE_PASS'): string => {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`${name} is required for smoke e2e login`);
  }
  return value;
};

export async function seedSmokeAuthState(page: Page, request: APIRequestContext) {
  const username = requireSmokeCredential('E2E_SMOKE_USER');
  const password = requireSmokeCredential('E2E_SMOKE_PASS');
  const form = new URLSearchParams();
  form.set('username', username);
  form.set('password', password);

  const response = await request.post('/api/v1/auth/login', {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    data: form.toString(),
  });
  if (!response.ok()) {
    throw new Error(`Smoke login failed: ${response.status()} ${await response.text()}`);
  }

  const body = (await response.json()) as LoginResponse;
  if (!body.access_token) {
    throw new Error('Smoke login response did not include access_token');
  }

  await page.goto('/');
  await page.evaluate(
    ({ key, token }) => {
      localStorage.setItem(key, JSON.stringify({ state: { token }, version: 0 }));
    },
    { key: AUTH_STORAGE_KEY, token: body.access_token },
  );
  await page.reload();
}
