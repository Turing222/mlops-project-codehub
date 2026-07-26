import { test, expect } from '@playwright/test';
import { mockAdminLoginRoute, mockAuthConfigRoute, seedAuthState } from '../../fixtures/auth';
import { mockSessionsRoute } from '../../fixtures/sse';

/**
 * C3 窄视口回归(断点见 design/tokens/layout.json breakpoint)。
 * 只断言布局契约:无横向溢出、窄屏侧栏默认折叠、输入区可达。
 */

async function setupCommon(page: import('@playwright/test').Page) {
    await mockAdminLoginRoute(page);
    await mockAuthConfigRoute(page);
    await mockSessionsRoute(page, []);
    await page.route('**/api/v1/credits/me', (route) =>
        route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
                id: 'acct-1',
                user_id: 'user-1',
                balance: 10,
                is_checked_in_today: false,
                created_at: null,
                updated_at: null,
            }),
        }),
    );
    await page.route('**/api/v1/telemetry/**', (route) => route.fulfill({ status: 204, body: '' }));
    await page.route('**/api/v1/knowledge/default', (route) =>
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [] }) }),
    );
}

test.describe('Responsive layout contracts', () => {
    test('390px chat: sidebar starts collapsed and input stays reachable', async ({ page }) => {
        await page.setViewportSize({ width: 390, height: 844 });
        await setupCommon(page);
        await seedAuthState(page);

        await expect(page.getByTestId('chat-input')).toBeVisible();
        // 折叠态没有「新对话」文字按钮,只有图标位
        await expect(page.getByRole('button', { name: '新对话' })).toHaveCount(0);
        const overflow = await page.evaluate(
            () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        );
        expect(overflow).toBeLessThanOrEqual(0);
    });

    test('768px admin: shell shows drawer trigger and no horizontal overflow', async ({ page }) => {
        await page.setViewportSize({ width: 768, height: 1024 });
        await setupCommon(page);
        await seedAuthState(page);
        await page.goto('/admin');

        await expect(page.getByRole('button', { name: '打开导航' })).toBeVisible();
        const overflow = await page.evaluate(
            () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        );
        expect(overflow).toBeLessThanOrEqual(0);
    });

    test('390px credits: page renders without horizontal overflow', async ({ page }) => {
        await page.setViewportSize({ width: 390, height: 844 });
        await setupCommon(page);
        await page.route('**/api/v1/credits/transactions**', (route) =>
            route.fulfill({
                status: 200,
                contentType: 'application/json',
                body: JSON.stringify({ items: [], total: 0 }),
            }),
        );
        await seedAuthState(page);
        await page.goto('/credits');

        await expect(page.getByText('当前可用积分')).toBeVisible();
        const overflow = await page.evaluate(
            () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        );
        expect(overflow).toBeLessThanOrEqual(0);
    });
});
