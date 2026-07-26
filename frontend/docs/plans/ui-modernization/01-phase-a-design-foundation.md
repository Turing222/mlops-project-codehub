# Phase A — 设计基础层

> 状态：Planned
>
> 预估：8–12h
>
> 前置：无（本轮第一档）
>
> 后续：[Phase B 应用外壳 + 标杆页](02-phase-b-shell-and-flagship.md)

本档**不改任何页面布局**，只建基础层。目标是让后面两档有一个可依赖的地基：
改完之后页面形态几乎不变，但暗色模式和品牌色第一次做到全站真正生效。

## A0 · 决策门（必须先做）

Phase A 开工前需要拍板一个产品问题，其余任务全部依赖它：

**页面底色是跟随品牌色染色，还是回归中性？**

| 选项 | 含义 | 代价 |
|---|---|---|
| 保留染色 | 沿用 `App.tsx` 的 `BRAND_PALETTES`，5 套品牌各有自己的页面底色 | 需把 5×2 套色值反向补进 `design/tokens/colors.json`，token 文件变复杂 |
| 回归中性 | 采纳 `design/tokens/colors.json` 现有定义，品牌色只影响 primary 系 | 视觉变化明显（用户会察觉），但 token 体系干净、可跨平台复用 |

`design/principles.md` 的既定立场是"安静，不抢内容"，倾向中性；但这是**产品决策不是技术决策**，需显式确认。
决策结果写回本文件后再开工。

## A1 · 截图基线 harness

### 现状

Playwright 1.60 + chromium 已装，`e2e/fixtures/` 已有全套 API mock，但没有任何视觉基线工具。
每次改样式只能靠肉眼和记忆判断有没有改坏。

### 改动

在 `e2e/` 下新增一个截图脚本（不进 `tests/`，避免混入 CI 断言）：

- 复用 `fixtures/auth.ts`、`fixtures/sse.ts`、`fixtures/repo-analysis.ts` 造出内容填充完整的页面。
- 遍历 5 个路由 × { light, dark } × { 1440px, 768px, 390px } 视口。
- 输出到 gitignore 的本地目录，文件名形如 `chat-dark-1440.png`。
- 提供 `before/` 与 `after/` 两个目录，方便逐档对比。

先在**未改任何代码时**跑一次，存为全局 before 基线。

### 验收

- 脚本一条命令跑完，无需手工登录、无需后端。
- 5 页 × 2 主题 × 3 视口 = 30 张图全部产出且内容非空白。

## A2 · 补齐 token 层

### 现状

`index.css` 只有 23 个颜色变量。`design/tokens/` 里的 spacing（8 档）、radius（6 档）、
typography（6 档字号 + 4 档字重 + 2 档行高）、motion（5 档时长 + 4 条缓动曲线）、
shadow（bubble / card / modal）**在代码中完全不存在**。
后果是 954 个裸 px 值散落各处，其中约 90 个是 `11px`/`13px`/`15px`/`5px`/`3px`/`0.5px` 这类脱离 4px 栅格的漂移值。

### 改动

- 按 `design/tokens/*.json` 把 spacing / radius / typography / motion / shadow 全部落成 `index.css` 的 CSS 变量。
- 补上目前缺失的暗色滚动条样式（`::-webkit-scrollbar-thumb` 现在是硬编码 `#d9d9d9`，不跟随主题）。
- 统一等宽字体：现有三套并存的 stack（`SFMono-Regular…`、`'Courier New'…`、裸 `monospace`）收敛为一个 `--font-mono`。
- 补 `--color-primary-active` 与 `--color-primary-border`——这两个变量已被 `AgentTracePanel.module.css` 消费但从未定义。

本步**只新增变量，不改任何页面 CSS 的取值**，因此视觉零变化，风险最低。

### 验收

- `design/tokens/` 六类 token 与 `index.css` 变量一一对应，无遗漏、无多余。
- 截图 harness 输出与 A1 的 before 基线**像素级一致**（本步不应产生任何视觉变化）。

## A3 · 收敛三套主题机制

### 现状

主题同时被三处驱动，且第三处（JS 行内样式）优先级最高，把第二处的暗色定义变成死代码：

1. `App.tsx:184-194` — antd `ConfigProvider`，只配了 3 个 seed token。
2. `index.css:11-67` — `:root` 与 `[data-theme='dark']`。
3. `App.tsx:163-181` — `document.documentElement.style.setProperty(...)` 写入 13 个行内变量。

附带问题：`--color-primary-hover` 用字符串拼接透明度后缀实现（`` `${brandColor}cc` ``），
换成非 6 位色值会静默失效；品牌色清单在 `App.tsx` 的 `BRAND_PALETTES` 和
`UserProfileModal.tsx` 的 `BRAND_PRESETS` 里各写了一遍。

### 改动

- 开启 antd 6 的 `cssVar` 模式，让 antd design token 以 `--ant-*` 暴露，
  CSS Modules 可直接消费，消除"两套 token 体系手工同步"。
- 主题真相收敛到 CSS：`[data-theme]` 负责亮暗切换，JS 只负责写 `data-theme` 属性和**品牌色一个变量**，
  不再逐条 `setProperty` 背景/边框（按 A0 决策，若保留染色则改为切换 `data-brand` 属性 + CSS 侧定义各品牌变体）。
- 品牌色清单抽成单一常量模块，`App.tsx` 与 `UserProfileModal.tsx` 共用。
- 用 `color-mix()` 或预定义变量替换透明度字符串拼接。
- 把 `index.css` 里两条 `!important` 的 antd 覆盖（`.ant-btn-primary`、`.ant-spin-dot-item`）
  改为 `ConfigProvider` 的 `components` token。

### 验收

- `index.css` 中 `[data-theme='dark']` 的每一条定义都实际生效（DevTools 确认无被行内样式覆盖的死规则）。
- 5 个品牌色 × 亮暗 10 套组合逐一切换，无色串、无残留、无控制台警告。
- `src/test/theme-i18n.test.tsx` 仍通过。
- 品牌色常量全仓库只有一处定义。

## A4 · 高硬编码文件迁移

### 现状

两个文件几乎完全绕开 token 体系，合计占全站 156 个硬编码 hex 中的 97 个：

- `RepoCheckPage.module.css`（86 个）：自建 slate / green / red / amber 语义色板，
  且有约 10 处写成 `var(--color-text-desc, #64748b)` 这类重复 fallback。第 391-392 行还有一个硬编码的深色代码块。
- `AdminDashboard.module.css`（11 个）：用 `!important` 手写亮暗两套色，
  所以 Admin 页既不跟随品牌色也不跟随暗色模式。

另有 56 处生产代码里的内联 `style={{}}`，其中 `Admin/index.tsx:30` 把默认品牌蓝 `#1677ff` 写死在图标上。

### 改动

- 为 RepoCheck 的状态语义（verdict / risk 等级）定义一组**语义 token**（如 `--color-status-pass`），
  在 `design/tokens/colors.json` 中登记，而不是继续散落 hex。
- `AdminDashboard.module.css` 全量改用 token，删掉 `!important` 与手写暗色分支。
- 清理重复 fallback 写法：变量已定义则不再写 fallback。
- 处理内联样式里的颜色硬编码（4 个 Suspense fallback 的重复内联块一并抽成组件）。

### 验收

- CSS 中硬编码 hex 从 156 降到 30 以内（保留项：`PixelAvatar.module.css` 的插画用色、`index.css` 的 token 定义本身）。
- Admin 页在 5 品牌 × 亮暗下表现正确——这是本步最直接的可见成果。
- 截图对比：Admin 页暗色模式应有明显改善，其余页面无非预期变化。

## A5 · 全局细节层

### 现状

| 项 | 现状 |
|---|---|
| `focus-visible` | 0 处——键盘导航无任何焦点指示 |
| `prefers-reduced-motion` | 0 处，但有 32 个 `@keyframes` |
| `prefers-color-scheme` | 无检测，默认硬编码 `'light'` |
| 字体加载 | `index.css:1` 用 CSS `@import` 拉 Google Fonts——渲染阻塞且串行，最慢的一种方式 |
| `index.html` | 仍是 Vite 脚手架原样：标题 `admin`、favicon `vite.svg`、无 description、无 theme-color |

### 改动

- 全局补 `:focus-visible` 样式，覆盖按钮、输入框、可点击卡片、侧边栏项。
- 全局补 `@media (prefers-reduced-motion: reduce)`，关闭/弱化 32 个动画。
- 主题 store 首次加载时读取 `prefers-color-scheme` 作为默认值（用户显式选择过则不覆盖）。
- 字体自托管：把 Inter 的 woff2 放进 `public/`，改用 `@font-face` + `font-display: swap` + preload。
  顺带可从 CSP 白名单摘掉 `fonts.googleapis.com` / `fonts.gstatic.com`
  （改 `scripts/generate-pages-headers.mjs`）。
- `index.html` 补齐 title / description / theme-color / favicon。
- 修复 A1 发现的 `.cursor-blink` 失效断言（补裸 class 钩子）。

### 验收

- 键盘 Tab 走完主要流程，每一步都有可见焦点。
- 系统开启"减少动态效果"后，页面无位移类动画。
- Lighthouse 或 `web-vitals` 上报中 LCP 不劣于改动前（字体自托管应当改善）。
- `make frontend-build-pages-check` 通过，CSP 收紧后 `_headers` 校验仍合法。
- `.cursor-blink` 断言恢复效力（故意留下光标可让该测试失败，验证后改回）。

## Phase A 完成门

全部满足才进入 Phase B：

1. A0 决策已写回本文件。
2. `make frontend-check-full` 全绿。
3. 截图 harness 可用，after 基线已归档。
4. `design/tokens/` 与 `index.css` 变量完全对应。
5. 5 品牌 × 亮暗 10 套组合人工走查通过。
6. 硬编码 hex ≤ 30，无死 CSS 变量，无重复品牌色清单。
7. **页面布局与信息架构未发生变化**——本档不做视觉重塑，形态变化留给 Phase B。
