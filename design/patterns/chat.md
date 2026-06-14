# Chat 交互模式（L2 概念层）

> 实现：`frontend/apps/admin/src/pages/Chat/`  
> Token：`tokens/colors.json`、`spacing.json`（usage.chat）、`layout.json`（layout.chat）

## 页面结构

```text
┌──────────┬─────────────────────────────────┐
│ Sidebar  │ Header (56px)                   │
│ 260/64px ├─────────────────────────────────┤
│          │ Message List (scroll, max 800)  │
│          ├─────────────────────────────────┤
│          │ Input Area (centered, max 800)  │
└──────────┴─────────────────────────────────┘
```

## 核心模式

### 1. 消息气泡

| 状态 | 背景 | 边框 | 特殊 |
|------|------|------|------|
| User | `primary-subtle` | 无 | 右下 tail 4px |
| Assistant | `bg-container` | `border` 1px | 左下 tail 4px，shadow-bubble |
| Error | `error-bg` | — | 红色文案 + 重试链接 |
| Streaming | 同 Assistant | — | cursor-blink + 可选 thinking dots |

入场：`motion preset message-enter`。

### 2. 空状态

- 垂直居中，图标 `icon-muted`
- 标题 `text/xl` + 副文案 `text/base` desc 色
- 模式选择：横向卡片，gap `space/4`，radius `radius/lg`

### 3. 输入区

| 状态 | 边框 | 背景 |
|------|------|------|
| Default | `border` | `bg-page` |
| Focus | `primary` + 2px primary-subtle glow | 同左 |
| Disabled | `border` | `bg-subtle`，opacity 0.7 |

发送按钮：radius 10px（介于 sm/md），高 32px。

### 4. 侧边栏

- Expanded 260px / Collapsed 64px
- 会话项 hover：`bg-subtle`，150ms
- 选中态：`primary-subtle` 背景或左边框 2px `primary`

### 5. Modal（Profile / KB Files）

- Overlay：`overlay` + blur 10px
- Container：radius `lg`，shadow-modal
- 入场：overlay `standard` + container `emphasis`

## 跨平台映射

| 模式 | CLI 近似 | 小程序 |
|------|----------|--------|
| 消息流 | 逐行输出，用户 `>` 前缀 | scroll-view + 气泡组件 |
| 空状态 | 居中 ASCII 框 | 同 Web 结构 |
| 输入 | 底部 prompt | fixed input-bar |
| Thinking | `...` 动画字符 | 三点 loading 组件 |

## 新颖感调节旋钮（优先改这 5 个）

1. 消息间距 `space/3` → `space/4`
2. 气泡 radius `md` → 全圆角 vs tail
3. 页面底 `bg-page` 冷暖（微调 hex）
4. 入场 translateY 8px → 12px
5. Assistant 气泡 shadow 有无

改一处 → 截图 → 确认 → 写入 token。
