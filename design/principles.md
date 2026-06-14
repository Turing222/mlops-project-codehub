# Dewflow Design Principles

> L0 层：全平台复用。换 Web / CLI / 手游 / 小程序时，这份文档不变。

## 产品气质（双轨）

| 轨道 | 方向词 | 留白 | 动效 | 信息密度 |
|------|--------|------|------|----------|
| **Chat**（对话产品） | calm · fluid | 松，消息区居中 max 800px | 允许入场、流式、thinking | 低，阅读优先 |
| **Admin**（管理后台） | dense · crisp | 紧，内容区 max 1600px | 克制，150–250ms | 高，扫视优先 |

两套共享 token（颜色、字号、圆角），差异在 **间距用量** 和 **动效幅度**。

## 视觉原则

1. **安静，不抢内容** — 不做营销页式渐变和大面积装饰。
2. **层次靠背景 + 边框** — 优先 `bg-page` → `bg-container` → `border`，阴影只作辅助。
3. **圆角三档** — `sm 8` / `md 12` / `lg 16`，全站不超出这三档（圆形 avatar 除外）。
4. **图标** — `lucide-react`，线宽一致，默认 18px 工具栏 / 16px 内联。
5. **字体** — Inter，正文 14px，标题 15–18px，辅助 11–13px。

## 动效原则

| 级别 | 时长 | 曲线 | 用于 |
|------|------|------|------|
| micro | 150ms | ease | hover、颜色过渡 |
| standard | 200–250ms | `cubic-bezier(0.4, 0, 0.2, 1)` | 侧边栏、按钮态 |
| enter | 280–400ms | `cubic-bezier(0.16, 1, 0.3, 1)` | 页面/消息入场 |
| emphasis | 300ms | `cubic-bezier(0.34, 1.56, 0.64, 1)` | 仅 modal 弹入，慎用 |

**禁止**：连续 bounce、无意义 parallax、超过 400ms 的过渡、管理端大面积 transform。

## 亮暗色

- 所有颜色必须定义 light + dark 两套（见 `tokens/colors.json`）。
- 暗色不靠纯黑，页面底 `#141414`，容器 `#1f1f1f`。
- `brandColor` 由用户设置，默认 `#1677ff`（antd 蓝）。

## 跨平台映射提示

| 概念 | Web | CLI | 小程序/手机 |
|------|-----|-----|-------------|
| 主色 | `--color-primary` | ANSI 256 / truecolor | `theme.json` |
| 页面底 | `--color-bg-page` | 终端背景色 | page 背景 |
| 容器 | `--color-bg-container` | 面板边框色 | card 背景 |
| 消息间距 | `space.3` (12px) | 行间距 1 blank | rpx 等比换算 |
| 入场 | CSS animation | 逐行 print delay | wxss animation |

## 不做的事（L1 边界）

- 不做全站高保真（只标杆页）
- 不做 Figma 复杂 prototype 动效
- 不做独立设计文档站（Markdown 够用）
- 不做自动化 token 管道（L2 再考虑 Style Dictionary）
