/**
 * UI 现代化基线截图 harness（Phase A1）。
 * 无断言——只产出 5 页 × 亮/暗 × 3 视口的截图，供各阶段 before/after 对比。
 * 运行：pnpm --filter admin test:e2e:screens；SCREENS_PHASE=after 切换输出目录。
 * 输出：e2e/screenshots/<phase>/<slug>-<theme>-<width>.png（目录已 gitignore）。
 */
import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test, type Page } from '@playwright/test';
import { mockAdminLoginRoute, mockAuthConfigRoute } from '../fixtures/auth';
import { mockDefaultKnowledgeRoute } from '../fixtures/knowledge';
import { mockSessionsRoute, mockSessionDetailRoute } from '../fixtures/sse';
import {
  mockChatMessage,
  mockSession,
  mockSessionDetail,
  mockUser,
} from '../fixtures/api-mocks';
import { mockRepoAnalysisRoutes } from '../fixtures/repo-analysis';

const PHASE = process.env.SCREENS_PHASE ?? 'before';
const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = path.resolve(HERE, '..', 'screenshots', PHASE);
mkdirSync(OUT_DIR, { recursive: true });

const THEMES = ['light', 'dark'] as const;
const VIEWPORTS = [
  { width: 1440, height: 900 },
  { width: 768, height: 1024 },
  { width: 390, height: 844 },
] as const;

async function seedClientState(page: Page, theme: (typeof THEMES)[number]) {
  await page.addInitScript(
    ({ authKey, themeKey, themeVal }) => {
      localStorage.setItem(
        authKey,
        JSON.stringify({ state: { token: 'mock-jwt-token-abc123' }, version: 0 }),
      );
      localStorage.setItem(themeKey, themeVal);
    },
    {
      authKey: 'auth-storage',
      themeKey: 'dewflow-theme-settings',
      themeVal: JSON.stringify({
        state: { theme, brandColor: process.env.SCREENS_BRAND ?? '#1677ff' },
        version: 0,
      }),
    },
  );
}

/** 所有页面共用的全局接口:登录态、鉴权配置、头部积分、KB 列表、打点。 */
async function setupCommon(page: Page) {
  await mockAdminLoginRoute(page);
  await mockAuthConfigRoute(page);
  await mockDefaultKnowledgeRoute(page);
  await page.route('**/api/v1/telemetry/**', async (route) => {
    await route.fulfill({ status: 204, body: '' });
  });
  await mockCreditsAccountRoute(page);
}

async function mockCreditsAccountRoute(page: Page) {
  const now = new Date('2026-07-20T10:00:00Z').toISOString();
  await page.route('**/api/v1/credits/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'acct-1',
        user_id: 'user-1',
        balance: 1280,
        is_checked_in_today: false,
        created_at: now,
        updated_at: now,
      }),
    });
  });
}

async function setupChat(page: Page) {
  const session = mockSession({ id: 'session-1', title: '架构方案讨论' });
  await mockSessionsRoute(page, [
    session,
    mockSession({ id: 'session-2', title: '周报草稿' }),
  ]);
  await mockSessionDetailRoute(
    page,
    'session-1',
    mockSessionDetail({
      session,
      messages: [
        mockChatMessage({
          id: 'msg-1',
          role: 'user',
          content: '帮我评审这版 Redis 隔离方案的风险点。',
        }),
        mockChatMessage({
          id: 'msg-2',
          role: 'assistant',
          content:
            '方案整体可行，主要风险有三点：一是 broker 切换窗口内的任务丢失，' +
            '二是 noeviction 策略下的内存上限告警缺失，三是恢复扫描的幂等边界。' +
            '建议先在 smoke 环境演练一次全量重启，确认三条路径都能收敛。',
        }),
      ],
    }),
  );
}

/** 打开第一条会话，让消息区有内容；失败不阻塞截图（空态也是合法基线）。 */
async function openFirstSession(page: Page) {
  try {
    await page.getByTestId('session-item').first().click({ timeout: 5000 });
    await page
      .locator('.chat-message.assistant')
      .first()
      .waitFor({ state: 'visible', timeout: 5000 });
  } catch {
    // 保持当前状态截图
  }
}

async function setupAdmin(page: Page) {
  await page.route('**/api/v1/users?**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(
        mockUser({ id: 'user-2', username: 'johndoe', email: 'john@example.com' }),
      ),
    });
  });
}

async function setupCredits(page: Page) {
  const now = new Date('2026-07-20T10:00:00Z').toISOString();
  await page.route('**/api/v1/credits/transactions**', async (route) => {
    const item = (id: string, amount: number, source: string) => ({
      id,
      account_id: 'acct-1',
      amount,
      source,
      expires_at: null,
      idempotency_key: null,
      created_at: now,
    });
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: [
          item('tx-1', 50, 'checkin'),
          item('tx-2', -12, 'chat'),
          item('tx-3', -30, 'repo_analysis'),
          item('tx-4', 100, 'admin_grant'),
        ],
        total: 4,
      }),
    });
  });
}

type PageDef = {
  slug: string;
  path: string;
  setup?: (page: Page) => Promise<void>;
  after?: (page: Page) => Promise<void>;
};

const PAGES: PageDef[] = [
  { slug: 'chat', path: '/', setup: setupChat, after: openFirstSession },
  { slug: 'admin', path: '/admin', setup: setupAdmin },
  { slug: 'credits', path: '/credits', setup: setupCredits },
  {
    slug: 'repo-check',
    path: '/repo-check',
    setup: async (page) => {
      await mockRepoAnalysisRoutes(page);
    },
  },
  { slug: 'oauth-callback', path: '/auth/google/callback' },
];

for (const pageDef of PAGES) {
  for (const theme of THEMES) {
    for (const viewport of VIEWPORTS) {
      test(`${pageDef.slug} ${theme} ${viewport.width}`, async ({ page }) => {
        page.on('response', (response) => {
          if (response.status() >= 400) {
            console.log(`[http ${response.status()}] ${response.url()}`);
          }
        });
        await page.setViewportSize(viewport);
        await seedClientState(page, theme);
        await setupCommon(page);
        await pageDef.setup?.(page);
        await page.goto(pageDef.path, { waitUntil: 'load' });
        await pageDef.after?.(page);
        // 字体加载与入场动效落定；Google Fonts 拉取失败也在 3s 后放行。
        await page.evaluate(() =>
          Promise.race([
            document.fonts.ready,
            new Promise((resolve) => setTimeout(resolve, 3000)),
          ]),
        );
        await page.waitForTimeout(600);
        await page.screenshot({
          path: path.join(OUT_DIR, `${pageDef.slug}-${theme}-${viewport.width}.png`),
        });
      });
    }
  }
}
