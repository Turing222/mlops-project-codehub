# Figma Setup Guide

> Figma 文件链接（填你的）：`___________________________________`

## 文件结构

```text
Dewflow Design
├── Foundations
│   ├── Colors (Variables 预览)
│   ├── Typography scale
│   └── Spacing / Radius reference frame
├── Chat
│   ├── Chat / Empty State
│   ├── Chat / Active Conversation
│   └── Chat / Input States
└── Admin
    ├── Admin / Dashboard
    └── Admin / Table States
```

画布尺寸：**1440 × 900**（Web 桌面标准）。

---

## Step 1：创建 Variable Collection

1. 右侧面板 → Local variables → Create collection
2. 命名：`Core`
3. Add mode：`Light`（默认）、`Dark`

---

## Step 2：颜色 Variables（与 colors.json 1:1）

| Variable 名 | Light | Dark |
|-------------|-------|------|
| `color/primary` | `#1677ff` | `#1677ff` |
| `color/primary-hover` | `#4096ff` | `#4096ff` |
| `color/primary-subtle` | `#1677ff` 15% | 同左 |
| `color/bg-page` | `#fafbfc` | `#141414` |
| `color/bg-container` | `#ffffff` | `#1f1f1f` |
| `color/bg-subtle` | `#fafafa` | `#262626` |
| `color/border` | `#f0f0f0` | `#303030` |
| `color/text-main` | `#1a1a2e` | `#e5e7eb` |
| `color/text-desc` | `#999999` | `#8c8c8c` |
| `color/text-light` | `#ffffff` | `#ffffff` |
| `color/icon-muted` | `#bfbfbf` | `#595959` |
| `color/error` | `#cf1322` | `#ff4d4f` |
| `color/error-bg` | `#fff1f0` | `#2a1215` |
| `color/success` | `#52c41a` | `#73d13d` |
| `color/coin` | `#d97706` | `#fbbf24` |
| `color/admin-header` | `#1e293b` | `#1e293b` |
| `color/admin-header-border` | `#334155` | `#334155` |
| `color/overlay` | `#000000` 45% | `#000000` 55% |

命名用 `/` 分组，方便 Dev Mode 浏览。

---

## Step 3：间距 Variables（Float）

| Variable | Value |
|----------|-------|
| `space/1` | 4 |
| `space/2` | 8 |
| `space/3` | 12 |
| `space/4` | 16 |
| `space/5` | 20 |
| `space/6` | 24 |
| `space/7` | 32 |
| `space/8` | 40 |

间距变量不分 Light/Dark。

---

## Step 4：圆角 Variables

| Variable | Value |
|----------|-------|
| `radius/sm` | 8 |
| `radius/md` | 12 |
| `radius/lg` | 16 |
| `radius/pill` | 20 |
| `radius/bubble-tail` | 4 |

---

## Step 5：字体样式（Text Styles，非 Variable）

| Style 名 | Font | Size | Weight | Line |
|----------|------|------|--------|------|
| `text/xs` | Inter | 11 | 500 | 1.5 |
| `text/sm` | Inter | 13 | 500 | 1.5 |
| `text/base` | Inter | 14 | 400 | 1.6 |
| `text/md` | Inter | 15 | 600 | 1.5 |
| `text/lg` | Inter | 16 | 600 | 1.5 |
| `text/xl` | Inter | 18 | 600 | 1.5 |

---

## Step 6：标杆帧绑定 Variables

画 Frame 时：

- 矩形填充 → 绑定 `color/bg-page` 等
- Auto layout gap → 手动填 `space/N` 数值（Figma 暂不支持 gap 绑 variable）
- 圆角 → 填 `radius/md` 数值

**动效**：用 Sticky note 标注，不做 Smart Animate：

```text
message-enter: 300ms cubic-bezier(0.16, 1, 0.3, 1), Y+8→0
modal-zoom: 300ms cubic-bezier(0.34, 1.56, 0.64, 1)
```

---

## Step 7：导出与协作

- 截图：Frame 右键 → Copy as PNG → 存入 `design/showcase/`
- 分享：Share → Anyone with link can view（作品集用）
- Dev Mode：免费版有限，L1 用截图 + 本对照表足够

---

## 常见错误

| 错误 | 正确做法 |
|------|----------|
| 只画 Light | 每帧旁放 Dark 版或切换 Mode 各导一张 |
| 每个页面都画 | 只画清单里 5 帧 |
| 在 Figma 做复杂动效 | 标注数值，代码里实现 |
| Variable 与 JSON 不一致 | 以 `tokens/colors.json` 为准，改完同步两边 |
