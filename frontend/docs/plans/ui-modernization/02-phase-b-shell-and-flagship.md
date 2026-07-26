# Phase B — 应用外壳 + 标杆页

> 状态：Done（2026-07-27 用户 review 通过）
>
> 预估：12–16h
>
> 前置：[Phase A 完成门](01-phase-a-design-foundation.md#phase-a-完成门)全部通过
>
> 后续：[Phase C 全站覆盖](03-phase-c-full-coverage.md)

本档开始改变页面形态。A 档解决"变量从哪来"，B 档解决"页面长什么样"——
统一应用外壳，并按 `design/patterns/` 把 Chat、Admin 两个标杆页重塑到位。
这是"内部工具感"与"现代产品感"的分界线。

## B1 · 应用外壳（AppShell / PageHeader / Container）

### 现状

`App.tsx` 直接渲染 `<Routes>`，没有任何共享布局：Chat 自建 56px header + 手写 Sidebar，
Admin 独自使用 antd `Layout/Header/Content`，Credits 与 RepoCheck 各自手写带返回箭头的 header。
跨页导航只存在于 Chat 页的 Sidebar——进入其余页面后，除返回箭头外无任何导航出口。

### 改动

- 新增三个共享组件：`AppShell`（全局导航 + 主题/品牌/用户入口）、`PageHeader`（标题 + 操作区）、
  `Container`（内容版心与页内间距）。
- 4 个业务页面全部接入（OAuth 回调页除外）；导航密度按双轨气质区分（Chat 侧 calm、管理侧 dense）。
- 保留 README §4.1 列出的全部 e2e 钩子 class；沿用双 class 模式。

### 验收

- 任意页面 ≤ 2 次点击可达其他任意页面。
- 5 页 chrome 一致（截图对比 header 区域）；`make frontend-check-full` 全绿；bundle 未穿上限。

## B2 · Chat 标杆页重塑（calm · fluid）

### 现状

`MessageList.module.css` 681 行 + `ChatPage.module.css` 399 行 + `Sidebar.module.css` 310 行，
气泡、空状态、输入区均为自造视觉，密度与 Admin 无区分，`design/patterns/chat.md` 的模式细则 0% 落地。

### 改动

按 [design/patterns/chat.md](../../../../design/patterns/chat.md) 逐项落实：
消息气泡（user / assistant 双形态）、空状态、输入区三态（idle / streaming / error）、
Sidebar 视觉与悬停节奏、滚动行为。动效全部取用 A2 落地的 motion token，一次只调一个维度。

### 验收

- `design/patterns/chat.md` 验收条目逐项勾选。
- chat 相关 mock e2e 全绿，`.cursor-blink` 断言保持有效；截图 before/after 归档。

## B3 · Admin 标杆页重塑（dense · crisp）

### 现状

`AdminDashboard.module.css` 仅 101 行（A4 已 token 化），但风格与全站脱节；
表格是 antd 默认样式，表头层级、操作区、状态标签均未按 `design/patterns/admin.md` 设计。

### 改动

- 接入 AppShell 后，按 [design/patterns/admin.md](../../../../design/patterns/admin.md) 调整
  信息密度、表头层级、行高与操作区；状态标签采用 A4 定义的语义 token。
- antd 表格样式经 `ConfigProvider.components` 定制，不再用 `:global()` 覆盖内部类名。

### 验收

- `design/patterns/admin.md` 验收条目逐项勾选;`.admin-layout`、`.ant-table-row` 钩子保留，admin e2e 全绿。

## Phase B 完成门

全部满足才进入 Phase C：

1. `make frontend-check-full` 全绿；bundle ≤ 504 KB gzip。
2. 5 品牌 × 亮暗 10 套组合走查通过。
3. 截图 before/after 已归档（外壳统一在 5 页截图中肉眼可辨）。
4. `design/patterns/chat.md` 与 `admin.md` 的验收条目全部勾选。
5. 本档不动 RepoCheck / Credits 页内部视觉（仅被外壳包裹）——留给 Phase C。
