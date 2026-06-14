# Frontend State Standard

## 目标

- 区分客户端状态和服务端状态。
- 避免页面重复手写 `loading + api + setState`。
- 让登录态、缓存失效和页面刷新有统一入口。

## 状态分层

放进 `Zustand`：

- access token。
- 当前登录态元信息。
- UI 偏好，例如侧边栏折叠状态。
- 本地草稿。
- 最近选择的筛选条件。

放进 `TanStack Query`：

- `/users/me`。
- 用户列表 / 用户详情。
- 会话列表。
- 会话详情。
- 任务状态。
- 任意可重新从后端获取的数据。

留在组件内部：

- 表单输入中的临时值。
- 当前 modal 是否打开。
- 非共享的 hover、展开、局部 loading。

## Query 规则

- query key 集中定义，不在页面内临时拼数组。
- mutation 成功后通过 invalidation 刷新相关 query。
- 轮询统一使用 query 层能力，不在页面中手写 `setInterval + api`。
- 登录态变化时，身份相关 query 必须清理或失效。

## Auth 规则

- token 来源保持唯一。
- 启动时如有 token，应调用 `/users/me` bootstrap。
- `/users/me` 成功后才认为登录完成。
- 401 / 403 是认证失效的权威信号。

## TODO

- 明确 `AuthContext` 到 `Zustand` 的兼容迁移步骤。
- 明确 query key 命名模板。
- 明确 logout 时需要清理哪些 query cache。
