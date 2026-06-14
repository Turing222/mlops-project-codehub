# Dewflow Design System (L1)

跨平台设计基础层。Web 是当前第一个消费者；CLI、移动端、小程序、客户端以后从同一份 token 导出。

## 目录

| 文件 | 用途 |
|------|------|
| [L1-checklist.md](./L1-checklist.md) | **主清单**：分阶段任务、耗时、验收标准 |
| [principles.md](./principles.md) | 品牌气质与动效原则（全平台复用） |
| [figma-setup.md](./figma-setup.md) | Figma Variables 逐步录入对照表 |
| [patterns/chat.md](./patterns/chat.md) | 对话产品交互模式 |
| [patterns/admin.md](./patterns/admin.md) | 管理后台交互模式 |
| [tokens/](./tokens/) | 平台无关设计 token（JSON，W3C DTCG 格式） |

## 快速开始

1. 读 [principles.md](./principles.md)（3 分钟）
2. 按 [L1-checklist.md](./L1-checklist.md) Phase 0–1 建 Figma + 录入 token
3. 画 Chat / Admin 标杆帧（Phase 2–3）
4. 回代码：先 `index.css`，再标杆页 CSS module
5. 截图放入 `design/showcase/`（见清单 Phase 5）

## 与前端代码的关系

```
design/tokens/*.json     ← 单一真相（Source of Truth）
        ↓
frontend/.../index.css   ← Web 运行时（当前手写同步，L2 可自动化）
        ↓
pages/*/*.module.css     ← 页面局部样式，引用 var(--*)
```

`theme-store` 的 `brandColor` 会运行时覆盖 `--color-primary`；token 中的 primary 是默认值。

## 展示用法

个人作品集 / 项目 README 可引用：

- `design/principles.md` — 设计决策
- `design/showcase/` — 亮暗色标杆截图
- `design/tokens/` — 跨平台规范能力证明
