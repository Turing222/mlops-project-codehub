# L1 最小清单（个人开发者 · 中上水平）

> 总耗时约 **2–3 天**（每天 3–4 小时）。完成后可展示、可复用、可扩展到 CLI/移动端。

## 验收标准（Definition of Done）

全部打勾 = L1 完成，达到个人项目中上水平：

- [ ] `design/tokens/` 六类 token 齐全，亮暗色双模式
- [ ] `design/principles.md` 定稿，Chat / Admin 气质词明确
- [ ] Figma 文件含 **5 个标杆帧**（清单见 Phase 2–3）
- [ ] Figma Variables 与 `colors.json` 数值一致
- [ ] Web 标杆页代码与 Figma 视觉偏差 < 主观「一眼无明显违和」
- [ ] `design/showcase/` 含 **4 张截图**（Chat/Admin × Light/Dark）
- [ ] Admin 硬编码色至少迁移 **header + card** 到 CSS 变量
- [ ] 能用一句话向他人解释设计系统结构

---

## Phase 0 · 基础设施（≈2h）

| # | 任务 | 产出 |
|---|------|------|
| 0.1 | 确认 `design/` 目录已存在，通读 README + principles | 理解分层 |
| 0.2 | 注册 Figma，新建文件 `Dewflow Design` | 空白文件 |
| 0.3 | 建 3 个 Section：`Foundations` / `Chat` / `Admin` | 画布分区 |
| 0.4 | 新建 `design/showcase/` 文件夹 | 存最终截图 |

**不做**：买 Figma 付费、装插件、建组件库。

---

## Phase 1 · Token 录入（≈3h）

### 1.1 Figma Variables（按 [figma-setup.md](./figma-setup.md)）

- [ ] 创建 Collection `Core`，Modes：`Light` / `Dark`
- [ ] 录入 `colors.json` 全部颜色（约 20 个）
- [ ] 录入 spacing 8 档、radius 5 档、font-size 6 档

### 1.2 代码对齐（可选同日完成）

- [ ] 对照 `tokens/motion.json`，在 `index.css` 增加 motion 变量（见下方片段）
- [ ] 确认 `theme-store` 的 `brandColor` 仍覆盖 primary

**`index.css` 建议追加（motion token 化）：**

```css
:root {
  --motion-micro: 150ms ease;
  --motion-fast: 200ms cubic-bezier(0.4, 0, 0.2, 1);
  --motion-enter: 300ms cubic-bezier(0.16, 1, 0.3, 1);
  --motion-page: 400ms cubic-bezier(0.16, 1, 0.3, 1);
  --motion-emphasis: 300ms cubic-bezier(0.34, 1.56, 0.64, 1);
  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 16px;
}
```

---

## Phase 2 · Chat 标杆帧（≈4h）

在 Figma `Chat` Section 画 **3 帧**（1440×900 画布）：

### Frame 1：`Chat / Empty State`

| 元素 | 规格（来自 token） |
|------|-------------------|
| 背景 | `bg-page` |
| 侧边栏宽 | 260px expanded |
| 空状态标题 | 18px semibold `text-main` |
| 空状态副文案 | 14px `text-desc` |
| 模式选择卡片 | radius-lg，gap 16px |

### Frame 2：`Chat / Active Conversation`

| 元素 | 规格 |
|------|------|
| 消息区 max-width | 800px 居中 |
| 消息间距 | 12px |
| 气泡 | radius-md，padding 10×14 |
| User 气泡底 | `primary-subtle` 背景，右下 tail 4px |
| Assistant 气泡 | `bg-container` + `border` + shadow-bubble |
| 字号 | 14px，line-height 1.6 |

### Frame 3：`Chat / Input States`

画 3 个输入框横排或上下：

- Default：border `border`，radius-md
- Focus：border `primary`，shadow `primary-subtle` 2px spread
- Disabled：opacity 0.7，`bg-subtle`

**标注（文字 sticky note 即可）：**

- 消息入场：`motion-enter` + translateY 8px
- thinking dots：`1400ms` stagger `160ms`

---

## Phase 3 · Admin 标杆帧（≈3h）

在 Figma `Admin` Section 画 **2 帧**：

### Frame 4：`Admin / Dashboard`

| 元素 | 规格 |
|------|------|
| Header | 高 56px，背景 `admin-header`，文字 `text-light` |
| 内容区 padding | 16×24 |
| Card | `bg-container`，radius-md，shadow-card |
| 表格标题 | 18px semibold |

### Frame 5：`Admin / Table States`

同一表格画 4 行状态：

- Default row
- Hover row（`bg-subtle`）
- Loading（skeleton 或 spinner 占位）
- Empty（图标 + 14px 文案）

**Admin 动效约束**：仅 hover 150–200ms，**无** page bounce。

---

## Phase 4 · 代码回写（≈4h）

优先级从高到低：

| # | 任务 | 文件 |
|---|------|------|
| 4.1 | Admin header/card 色改 CSS 变量 | `AdminDashboard.module.css` |
| 4.2 | 消息列表间距/圆角对齐 token | `MessageList.module.css` |
| 4.3 | 输入框 focus 态对齐 Frame 3 | `MessageList.module.css` |
| 4.4 | 页面入场改用 `--motion-page` | `ChatPage.module.css` |
| 4.5 | Modal 动效改用 `--motion-emphasis` | `UserProfileModal.module.css` |

**工作方式**：

1. Figma 定稿 → 截图贴 chat
2. Cursor 按截图 + token 改 CSS
3. 你在 DevTools 微调 2–3 个数值
4. 把最终数值同步回 `tokens/*.json` 和 Figma

---

## Phase 5 · 展示打包（≈2h）

### 5.1 截图（4 张必拍）

```text
design/showcase/
  chat-light.png
  chat-dark.png
  admin-light.png
  admin-dark.png
```

拍法：浏览器全屏，1440 宽，标杆内容填满。

### 5.2 作品集/README 可写的三句话

```text
· 双轨设计系统（对话 calm / 管理 crisp），亮暗色 token 驱动
· Figma 标杆 + JSON token，可扩展到 CLI / 移动端
· 动效分级：micro 150ms → enter 300ms，管理端克制
```

### 5.3 可选加分项（中上 → 上）

- [ ] 录 15s 屏：消息发送 + modal 打开（放 README gif）
- [ ] `styling.md` 加一行指向 `design/`
- [ ] 导出 Figma 链接写入 `design/figma-setup.md` 顶部

---

## 时间总览

| Phase | 内容 | 时间 |
|-------|------|------|
| 0 | 基础设施 | 2h |
| 1 | Token 录入 | 3h |
| 2 | Chat 标杆 | 4h |
| 3 | Admin 标杆 | 3h |
| 4 | 代码回写 | 4h |
| 5 | 展示打包 | 2h |
| **合计** | | **18h ≈ 2–3 天** |

---

## 复用检查（新平台时）

开 CLI / 小程序 / 客户端前，只问 5 个问题：

1. `principles.md` 气质词还适用吗？
2. `colors.json` 亮暗色要加模式吗？
3. 布局常量从 `layout.json` 哪些键取值？
4. 动效在目标平台能实现哪几档？（CLI 通常只有 micro）
5. 交互模式见 `patterns/chat.md` 或 `patterns/admin.md` 哪几条？

全部能答 → 可直接开工，不必重画 Figma 全站。

---

## 升级信号（何时做 L2）

| 信号 | 升级到 |
|------|--------|
| 第 3 个平台开工 | Style Dictionary 自动导出 |
| 5+ 页面颜色不一致 | Storybook + 共享组件 |
| 协作者加入 | Figma Dev Mode 正式 handoff |
| 反复改同一 token | CI 检查 token ↔ CSS 同步 |

L1 完成前，**不要**提前做 L2。
