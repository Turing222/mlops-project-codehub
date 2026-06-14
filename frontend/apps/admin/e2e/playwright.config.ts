import { defineConfig } from '@playwright/test';

const baseURL = process.env.E2E_BASE_URL || 'http://localhost:5173';
// Boot the local Vite dev server only when targeting localhost. When E2E_BASE_URL
// points at an already-deployed origin (e.g. post-deploy smoke against Cloudflare
// Pages), there is nothing to launch locally.
const useLocalServer =
  baseURL.includes('localhost') || baseURL.includes('127.0.0.1');

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? 'github' : 'html',
  timeout: 30000,
  expect: { timeout: 10000 },
  use: {
    baseURL,
    locale: 'zh-CN',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'mock',
      testDir: './tests/mock',
    },
    {
      name: 'smoke',
      testDir: './tests/smoke',
      workers: 1,
      timeout: 60_000,
    },
  ],
  webServer: useLocalServer
    ? {
        command: 'pnpm --filter admin dev',
        port: 5173,
        reuseExistingServer: !process.env.CI,
        timeout: 30000,
      }
    : undefined,
});
