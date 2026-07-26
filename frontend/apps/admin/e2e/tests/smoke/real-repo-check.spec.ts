import { test, expect } from '@playwright/test';
import { seedSmokeAuthState } from '../../fixtures/smoke-auth';

test.skip(() => !process.env.E2E_SMOKE, 'Requires running backend (set E2E_SMOKE=1)');

const DEFAULT_REPO_URL =
  process.env.E2E_REPO_CHECK_URL ?? 'https://github.com/Turing222/dewflow';

test.describe('Real backend: repo credibility check', () => {
  test('analyzes this repository and renders a completed report', async ({ page, request }) => {
    test.setTimeout(300_000);

    await seedSmokeAuthState(page, request);
    await page.goto('/repo-check');
    await expect(page.getByRole('heading', { name: 'AI 项目可信度初筛报告' })).toBeVisible();

    await page.getByRole('textbox', { name: 'GitHub repository URL' }).fill(DEFAULT_REPO_URL);
    await page.getByRole('button', { name: '开始分析' }).click();

    await expect(page).toHaveURL(/run_id=/);

    await expect.poll(
      async () => page.getByText('已完成').count(),
      { timeout: 240_000 },
    ).toBeGreaterThan(0);

    await expect(page.getByRole('heading', { name: /dewflow/i, level: 2 })).toBeVisible();
    await expect(page.getByText('评估结论').first()).toBeVisible();
    await expect(page.getByRole('heading', { name: '关键发现', level: 3 })).toBeVisible();
    await expect(page.getByRole('button', { name: '复制富文本报告' })).toBeVisible();
    await expect(page.getByText('可信信号').first()).toBeVisible();
  });
});
