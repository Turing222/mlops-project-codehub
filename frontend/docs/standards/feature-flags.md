# Frontend Feature Flag Standard

Feature flag 由后端控制下发，前端只负责消费，绝不直接连接 GrowthBook。新 flag 的注册、作用域和回退治理见 [Secrets And Feature Flags](../../../.codex/skills/project/references/secrets-and-flags.md)。

## 来源

- 登录用户的 flag 来自 `/api/v1/users/me` 响应的 `features` 字段（`Record<string, boolean>`，见 `src/schemas/user.ts`）。
- 缺失或未配置的 key 一律按 `false` 处理（安全默认）。
- 未登录态没有 `features`，所有 flag 均为 `false`。
- 新功能默认 opt-in：必须由后端 `FeatureFlagService` 显式开启才对用户可见。

## 消费入口

只通过 `src/context/` 提供的这两个入口读取 flag，不要在组件里自己解析 `user.features`：

- `useFeatureFlag(key: string): boolean`：在任意逻辑里动态判断。
- `<FeatureGate flag="..." fallback={...}>...</FeatureGate>`：声明式隐藏或切换 UI，`fallback` 默认 `null`。

`FeatureGate` 内部复用 `useFeatureFlag`，两者行为一致。

## 命名约定

- flag key 使用稳定的 `kebab-case`，与后端注册的 key 保持一致。
- 当前在用的 flag：`enable-credits`、`enable-agent-trace`、`enable-pixel-avatar`、
  `chat-explicit-retry`。

### `chat-explicit-retry` rollout contract

- Owner：当前单人维护者；进度与删除 checkpoint 记录在
  `work-items/active/chat-generation-consistency/manifest.yaml`。
- Scope：只控制显式 retry UI 与命令入口；status、SSE 和 session detail 的
  additive identity 字段始终兼容返回，flag 不承担授权。
- Default / rollback：缺失时为 `false`；发现异常时后端关闭 flag 即可隐藏前端入口，
  status 查询与原有消息读取不受影响。
- Enable / delete：WS6 的 flag-on、flag-off、刷新后重试和身份未知故障矩阵通过后再
  扩大流量；完成全量观察并确认不再需要快速回滚后，删除前后端分支与 flag 注册。

## 约定

- 不在前端硬编码 flag 的业务效果，最终以后端下发为准。
- flag 只控制可见性，不替代权限判断；真正的权限仍以后端返回为准。
