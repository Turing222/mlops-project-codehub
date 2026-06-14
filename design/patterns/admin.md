# Admin 交互模式（L2 概念层）

> 实现：`frontend/apps/admin/src/pages/Admin/`、`features/admin/`  
> Token：`colors.json`（含 admin-header）、`spacing.json`（usage.admin）、`layout.json`

## 页面结构

```text
┌─────────────────────────────────────────────┐
│ Admin Header (56px, admin-header 背景)      │
├─────────────────────────────────────────────┤
│  Content (padding 16×24, max 1600 居中)     │
│  ┌─────────────────────────────────────┐    │
│  │ Card (radius-md, shadow-card)       │    │
│  │  ├─ Card Header (h2 + actions)      │    │
│  │  └─ Table / Form / Stats            │    │
│  └─────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
```

## 核心模式

### 1. Shell（顶栏）

| 元素 | 规格 |
|------|------|
| 高度 | 56px |
| 背景 | `admin-header`（`#1e293b`） |
| 底边 | `admin-header-border` 1px |
| 标题 | 16px semibold，`text-light` |
| 用户信息 | 13px，`text-desc` 亮色变体 |

**注意**：Admin shell 是**深色顶栏 + 浅色内容**，与 Chat 全 token 主题不同，但颜色仍来自 token。

### 2. 内容卡片

| 属性 | 值 |
|------|-----|
| 背景 | `bg-container` |
| 边框 | `border` 1px |
| 圆角 | `radius/md` (12px) |
| 阴影 | shadow-card |
| 内边距 | 16×20 |
| 标题 | 18px semibold + lucide 图标 gap 8px |

### 3. 表格行

| 状态 | 样式 |
|------|------|
| Default | 无背景 |
| Hover | `bg-subtle`，150ms |
| Selected | `primary-subtle` 浅底 |
| Loading | antd Spin 或 skeleton |
| Empty | 居中图标 + 14px desc 文案 |

动效：**仅颜色过渡**，不用 scale / translate。

### 4. 搜索 / 筛选栏

- 水平排列，gap `space/3`
- 输入框遵循 antd 默认，圆角 override 为 `radius/sm`
- 主按钮 `primary`，次按钮 default

### 5. 反馈

| 类型 | 组件 |
|------|------|
| 成功 | antd message，色 `success` |
| 错误 | antd message，色 `error` |
| 确认删除 | antd Popconfirm |

## 与 antd 的关系

- 通用组件**不重写**，用 `ConfigProvider` 注入 token：
  - `colorPrimary` ← `color/primary`
  - `borderRadius` ← 8（`radius/sm`）
- 只有 shell 和 card 用自定义 CSS module。

## 跨平台映射

| 模式 | CLI | 桌面客户端 |
|------|-----|------------|
| 表格 | 固定列宽 TUI table | DataGrid / antd Table |
| 顶栏 | 标题 bar + 快捷键提示 | 同 Web |
| 卡片 | 边框 box | 同 Web |
| 筛选 | 命令 flag | 同 Web toolbar |

## 新颖感调节旋钮（Admin 专用）

1. 顶栏色 `admin-header` 换 slate 深浅
2. Card shadow 轻重（0.04 → 0.08 opacity）
3. 表格行高（antd `size` middle → small）
4. 内容区 max-width 1600 → 1280（更紧凑）
5. 图标统一 16px vs 18px

Admin 的新颖感应体现在 **密度和利落感**，不是动效。

## 已知技术债（L1 要还）

`AdminDashboard.module.css` 存在硬编码色（`#1e293b`、`#f5f7fa` 等）。  
Phase 4 迁移到 `var(--color-*)` 或新增 `--color-admin-*`。
