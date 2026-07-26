# 前端 UI 现代化升级（Phase A–C）

> 状态：Planned（2026-07-26 立项）
>
> 分支：`feat/frontend-ui-modernization`
>
> 执行范围：`frontend/apps/admin` 全部 5 个路由页面 + 全局样式层
>
> 设计依据：仓库根目录 [`design/`](../../../../design/README.md)（token、principles、patterns）

## 1. 立项背景

`design/` 目录已有一套完整的 L1 设计系统规范（W3C DTCG 格式 token、双轨气质定义、Chat/Admin 交互模式），
由 commit `d8daf55` 一次性加入，但**至今 0% 落到代码**：`design/L1-checklist.md` 的验收清单一项未勾，
`design/showcase/` 为空，`tokens/` 里的 spacing / radius / typography / motion 在代码中没有任何对应的 CSS 变量。

当前代码的实际状态是：**只有一层颜色变量，没有其余任何设计 token**。因此问题不是"审美过时"，
而是"基础层缺失导致每个页面各自发明一套视觉"。三档计划按依赖顺序修复这一点。

## 2. 现状基线（2026-07-26 实测）

| 维度 | 数值 |
|---|---|
| 路由页面 | 5（`/`、`/admin`、`/credits`、`/repo-check`、`/auth/google/callback`） |
| CSS 文件 / 行数 | 13 个 / 4432 行（1 个全局 `index.css`，其余为 CSS Modules） |
| 生产组件 TSX | ~3800 行（最大 `RepoAnalysisCard.tsx` 728 行） |
| `var(--*)` 使用 | 422 次，覆盖 23 个颜色变量 |
| 硬编码 hex | 156 个（另有 132 个 `rgba()`、`App.tsx` 内 ~75 个） |
| 裸 px 字面量 | 954 个（无任何 spacing / radius / font-size 变量） |
| `@media` 查询 | 6 个（等同没有响应式） |
| `focus-visible` / `prefers-reduced-motion` | 0 / 0（但有 32 个 `@keyframes`） |
| 打包体积 | 469 KB gzip，上限 573 KB，余量 ~104 KB |

### 已确认的结构性缺陷

1. **主题被三套机制同时驱动且互相覆盖**：antd `ConfigProvider` algorithm、`index.css` 的
   `:root` / `[data-theme='dark']`、以及 `App.tsx` 用 JS 写入的**行内**变量。行内优先级最高，
   导致 `index.css` 中 `[data-theme='dark']` 对 `--color-bg-page`、`--color-bg-container`、
   `--color-bg-subtle`、`--color-border` 的定义是死代码。
2. **`BRAND_PALETTES` 与 design token 冲突**：`App.tsx:20-126` 把页面底色做成品牌色染色
   （橙色主题下 `page: #fff7ed`），而 `design/tokens/colors.json` 规定中性底色（亮 `#fafbfc` / 暗 `#141414`）。
   两者是矛盾的设计决策，**Phase A 必须先裁决**。
3. **没有应用外壳**：`App.tsx` 直接渲染 `<Routes>`，4 个页面各自手写 header 与返回按钮；
   导航全部锁在 Chat 页的 Sidebar 内，进入其余页面后无跨页导航。
4. **两个文件几乎完全绕开 token 体系**：`RepoCheckPage.module.css`（86 个 hex，占全站 55%）
   自建了一整套 slate/green/red/amber 语义色板；`AdminDashboard.module.css` 用 `!important`
   手写亮暗两套色，因此既不跟随品牌色也不跟随暗色模式。
5. **两个 CSS 变量被消费但从未定义**：`--color-primary-active`（无 fallback，直接失效）、
   `--color-primary-border`（有 fallback）。均在 `AgentTracePanel.module.css`。

## 3. 三档划分与执行顺序

三档**严格串行**，前一档未通过验收门不开始后一档。

```text
Phase A 设计基础层（8–12h）
  -> Phase B 应用外壳 + 标杆页（12–16h）
  -> Phase C 全站覆盖 + 交付物（15–20h）
```

| 档 | 目标 | 预估 | 文档 |
|---|---|---|---|
| A | 建立完整 token 层，收敛三套主题机制为一套 | 8–12h | [01-phase-a-design-foundation.md](01-phase-a-design-foundation.md) |
| B | 抽出共享外壳，重塑 Chat / Admin 两个标杆页 | 12–16h | [02-phase-b-shell-and-flagship.md](02-phase-b-shell-and-flagship.md) |
| C | 覆盖剩余页面、响应式体系、showcase 交付 | 15–20h | [03-phase-c-full-coverage.md](03-phase-c-full-coverage.md) |

**顺序不可调换的原因**：token 层不统一时，每改一个页面都是在往沙子上盖楼；
应用外壳会改动所有页面最外层 DOM，越晚做返工越多。

## 4. 全阶段约束

- 不修改后端 API、response schema 或 SSE wire contract。
- 不修改组件的 props 公开形状；本轮是视觉层工作，不夹带业务逻辑重构。
- 不引入新的样式方案（不上 Tailwind、不上 CSS-in-JS）。继续 antd 6 + CSS Modules。
- 不引入 JS 动效库。`design/tokens/motion.json` 的四级动效用纯 CSS 实现，保护 bundle 余量。
- 新增/修改 token 必须同步回 `design/tokens/*.json`，保持该目录是单一真相。
- 圆角只允许 `design/tokens/radius.json` 定义的档位，不新增中间值。
- 每个阶段结束跑 `make frontend-check-full`。

### 4.1 测试耦合红线（重要）

13 个**全局 class 名**是 e2e 的定位钩子，改样式时**必须保留这些 class**：

```text
.admin-layout   .ant-modal        .ant-table-row    .auth-modal
.avatar-badge   .avatar-badge.guest                 .chat-header-title
.chat-message   .chat-message.user  .chat-message.assistant
.chat-page      .cursor-blink     .header-title     .sidebar-hint
```

现有组件用的是 `className={`${styles['x']} x`}` 双 class 模式——CSS Module 类负责样式，
裸 class 仅作测试钩子。**重构时沿用该模式**：样式改 module，裸 class 原样保留。

另有 3 个单元测试用 `querySelector` 定位：`AgentTracePanel.test.tsx`、`Sidebar.test.tsx`、
`KBFilesModal.test.tsx`。

**已确认的失效断言**：`chat-flow.spec.ts` 断言 `expect(page.locator('.cursor-blink')).not.toBeVisible()`，
但 `MessageList.tsx:363` 只写了 `className={styles['cursor-blink']}`（无裸 class）。
实测 build 产物中该类名被哈希为 `_cursor-blink_1w1y2_157`，裸选择器 `.cursor-blink` **匹配不到任何元素**，
该断言恒真、形同虚设（流式光标是否残留实际上从未被测到）。Phase A 顺手修复：
补上裸 class 钩子，使断言恢复效力。

## 5. 通用验收标准

每一档都必须同时满足：

1. `make frontend-check-full` 全绿（lint + typecheck + unit + build + bundle-check + mock e2e）。
2. `make frontend-bundle-check` 未突破 573 KB gzip 上限。
3. 5 个品牌色 × 亮/暗 = 10 套组合手工过一遍，无对比度失效或色串。
4. 本档新增/变更的 token 已同步进 `design/tokens/*.json`。
5. 视觉走查用 Playwright 截图对比（见 §6），不靠肉眼记忆。

## 6. 视觉验收工具链

**无需新增依赖**——仓库已具备完整条件：

- Playwright 1.60 + chromium 已装（`~/.cache/ms-playwright/chromium-1223`）。
- `e2e/playwright.config.ts` 的 `webServer` 会自动拉起 Vite dev server。
- `e2e/fixtures/` 已有 auth / sse / knowledge / repo-analysis 全套 mock，
  **无需后端即可渲染出内容填充完整的页面**。

因此 Phase A 第一步就建一个截图 harness（复用 mock fixtures，遍历 5 页 × 亮暗 2 态），
产出物直接充当 `design/showcase/` 的素材，也充当每一档的前后对比基线。

详见各档文档的「验收」小节。

## 7. 生态工作流参考（2026-07 调研）

调研结论：本计划的方法论与当前 Claude 生态的主流实践一致，另有一个可选的增量集成点。

- **Claude Design**（claude.ai/design，Anthropic Labs，2026-04-17 上线）：对话式设计工具，
  可读代码库/设计文件提取设计系统并按其出稿；2026-06 更新加入设计系统导入、画布编辑，
  以及与 Claude Code **双向同步的 `/design-sync`**。社区评价：设计系统提取是推断而非读取，
  边缘 token 会漏；生成代码非生产级。对本项目的适用位置在 **Phase C4（可选）**：
  把落地后的 token 与组件预览推送为 claude.ai Design 项目，后续新页面可按既有品牌出稿。
- **"设计规范进仓库、agent 直接读"**（DESIGN.md 模式）是 2026 社区共识——本仓库的
  `design/` 目录正是该模式的完整实现，无需引入额外工具。
- **截图迭代 + before/after 对比**是主流验收手段（社区有 /design-review 类 80 项视觉审计
  + 逐项修复的工作流）——即本计划的 A1 harness 与各档截图验收。
- **迭代纪律**：一次只调一个设计维度（typography / color / motion 分开提），
  一次只改一件事；重塑步骤（B2/B3/C1/C2）按此执行。
