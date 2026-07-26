# Phase C — 全站覆盖 + 交付物

> 状态：Implemented（2026-07-27，待用户 review）
>
> 预估：15–20h
>
> 前置：[Phase B 完成门](02-phase-b-shell-and-flagship.md#phase-b-完成门)全部通过
>
> 后续：无（本档收官 L1 设计系统落地）

覆盖剩余两个页面与最大 Modal，补齐响应式体系，产出 `design/showcase/` 交付物，
并把 `design/L1-checklist.md` 全部勾完。

## C1 · RepoCheck 页重塑

### 现状

`RepoCheckPage.module.css` 831 行（全站最大 CSS）+ `RepoAnalysisCard.tsx` 728 行（全站最大组件）。
A4 已把它自建的 slate/green/red/amber 色板收编为语义 token，但输入区、进度态、
结果卡片的布局与层级仍是独立发明的一套。

### 改动

- 按管理侧（dense · crisp）气质重塑输入区、进度反馈与结果卡片层级；状态语义色沿用 A4 token。
- 只动样式层与展示结构：不改业务逻辑、不改组件 props 公开形状；
  `RepoAnalysisCard` 过大的样式段随重塑拆分为子模块文件。

### 验收

- repo-check 相关 e2e 全绿；截图 before/after 归档。
- 结果卡片在 390px 视口不横向溢出（与 C3 联动验收）。

## C2 · Credits 页 + UserProfileModal

### 现状

`CreditsPage.module.css` 445 行、`UserProfileModal.module.css` 489 行。
品牌色清单重复定义已在 A3 合并，但余额卡、流水表、Modal 内分区的视觉仍未按 patterns 调整。

### 改动

- Credits 的余额卡与流水表按管理侧气质重塑（外壳已由 B1 提供）。
- UserProfileModal 的品牌选择器、头像区、分区间距对齐 token 体系。

### 验收

- credits e2e 全绿；Modal 在 5 品牌 × 亮暗组合下走查通过；截图归档。

## C3 · 响应式断点体系

### 现状

全站 4432 行 CSS 只有 6 个 `@media`；`design/tokens/layout.json` 定义的断点从未被消费。
390px 视口下 Chat Sidebar、Admin 表格、RepoCheck 卡片均溢出或不可用。

### 改动

- 按 `design/tokens/layout.json` 断点建立全站响应式：AppShell 导航窄屏折叠为抽屉；
  表格进横向滚动容器；Chat 在 768 / 390 两档做布局降级；触控目标 ≥ 44px。

### 验收

- 截图 harness 的 768 / 390 两档全部可用：无横向滚动、无遮挡、主流程可完成。
- 补 2–3 条窄视口关键断言进 mock e2e。

## C4 · 交付物与收官

### 现状

`design/showcase/` 为空；`design/L1-checklist.md` 0 勾。

### 改动

- 从截图 harness 产物中挑 4 组亮暗对比图整理进 `design/showcase/`，由 `design/README.md` 索引。
- 逐项勾选 `design/L1-checklist.md`；确有不做的项标注 deferred 与理由。
- 可选（见 [README §7](README.md#7-生态工作流参考2026-07-调研)）：用 DesignSync 把 token 与
  组件预览推送到 claude.ai Design 项目，获得可浏览的 Design System pane；
  后续新页面可让 Claude Design 按既有品牌出稿。

### 验收

- showcase 非空且被索引；L1-checklist 全勾或注明 deferred。
- （若执行可选项）claude.ai Design 项目内可浏览本项目 Design System。

## Phase C 完成门（本轮收官）

1. `make frontend-check-full` 全绿；bundle ≤ 504 KB gzip。
2. 全站硬编码 hex 不超出 README §5 的保留清单；无死 CSS 变量。
3. 5 页 × 亮暗 × 3 视口截图全部归档，768 / 390 走查通过。
4. `design/L1-checklist.md` 收官；`design/showcase/` 交付。
