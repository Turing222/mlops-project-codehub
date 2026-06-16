import { test, expect } from '@playwright/test';
import { mockLoginRoute, seedAuthState } from '../../fixtures/auth';
import { mockSessionsRoute } from '../../fixtures/sse';
import { mockRepoAnalysisRoutes } from '../../fixtures/repo-analysis';

test.describe('Repo credibility check page', () => {
  test('submits a GitHub URL and renders the completed report', async ({ page }) => {
    await mockLoginRoute(page);
    await mockSessionsRoute(page, []);
    await mockRepoAnalysisRoutes(page, {
      projectName: 'Dewflow Mock Report',
      repoUrl: 'https://github.com/mock-owner/mock-repo',
    });
    await seedAuthState(page);

    await page.goto('/repo-check');
    await expect(page.getByRole('heading', { name: 'AI 项目可信度初筛报告' })).toBeVisible();

    await page.getByRole('textbox', { name: 'GitHub repository URL' }).fill(
      'https://github.com/mock-owner/mock-repo',
    );
    await page.getByRole('button', { name: '开始分析' }).click();

    await expect(page).toHaveURL(/run_id=/);
    await expect(page.getByText('Dewflow Mock Report')).toBeVisible({ timeout: 15000 });
    await expect(page.getByText('评估结论')).toBeVisible();
    await expect(page.getByRole('button', { name: '复制富文本报告' })).toBeVisible();
    await expect(page.getByText('关键发现')).toBeVisible();
  });
});
