# Frontend Architecture

这份文档定义 `frontend/apps/admin` 的目标前端范式，重点解决下面几类问题：

- 前后端接口联动如何统一
- Token 获取、保存、校验、失效处理如何统一
- 幂等、网络抖动、重复提交如何统一
- AI 生成代码时应该遵守什么结构和边界

## 目标

- 保持通用，但不要过重
- 让前端边界清晰，减少“页面里直接写请求和状态”的混乱
- 让 AI 能按固定模式生成代码，而不是每个页面都发明一套写法
- 以后接入 Nginx、Docker、CI 时，不需要再回头重构前端基础层

## 目标技术栈

| 领域 | 选择 | 角色 |
| --- | --- | --- |
| UI | `antd` | 页面组件与表单 |
| 路由 | `react-router-dom` | 路由管理 |
| 校验 | `zod` | 前端 runtime schema 与 DTO 边界 |
| 本地状态 | `zustand` | 客户端状态 |
| 持久化 | `zustand/middleware/persist` | Token 与 UI 偏好持久化 |
| 网络 | `axios` + interceptors | 统一请求入口 |
| 服务端状态 | `@tanstack/react-query` | 查询、缓存、轮询、失效刷新 |
| 日期 | `dayjs` | 日期处理，按需使用 |
| 流式请求 | 原生 `fetch` / 自定义 stream client | SSE/分块流式响应 |

## 当前结论

- `Zod`、`Zustand`、`TanStack Query` 是目标栈
- `Dayjs` 作为标准日期库保留，但不要求第一阶段就引入
- 聊天 SSE 不强行塞进 `TanStack Query`
- `axios` 继续保留，但必须升级成统一 HTTP client

当前已落地：

- `src/lib/http/client.ts`: 统一 axios client、`Authorization`、`X-Request-ID`、错误归一化
- `src/lib/http/idempotency.ts`: 幂等 key 生成与复用
- `src/schemas/*.ts`: `auth / user / chat` 的 runtime schema
- `src/api/*.ts`: 基于 schema parse 的薄 API 封装

## 核心原则

### 1. 后端是业务真相

- 前端可以做输入校验和响应 parse
- 最终权限、Token 是否有效、用户是否存在、余额是否足够，都以后端返回为准
- 前端不要“猜”业务状态

### 2. 运行时校验和类型推导都要有

- `TypeScript type` 解决编辑期约束
- `Zod schema` 解决运行时边界
- 所有关键 API payload 和 response 都应该有 schema

推荐模式：

```ts
export const loginResponseSchema = z.object({
  access_token: z.string(),
  token_type: z.string(),
})

export type LoginResponse = z.infer<typeof loginResponseSchema>
```

### 3. 客户端状态和服务端状态必须分层

放进 `Zustand` 的：

- token
- 当前登录态元信息
- UI 偏好
- 本地草稿
- 最近选择的筛选条件

放进 `TanStack Query` 的：

- 当前用户资料
- 用户列表
- 会话列表
- 会话详情
- 任务状态
- 任意来自后端、可重新获取的数据

### 4. 页面组件不直接发裸请求

- 页面组件不直接 `axios.get(...)`
- 页面组件不直接在内部拼 Header
- 页面组件不直接生成 request id
- 页面组件最多调用：
  - `useXxxQuery`
  - `useXxxMutation`
  - `stream client`
  - `store action`

### 5. 非幂等 POST 默认不自动重试

- 查询类请求可以 retry
- 创建类请求只有带幂等 key 时才允许 retry
- 没有幂等 key 的 POST，不做静默自动重试

## 推荐目录结构

以 `frontend/apps/admin/src` 为根：

```text
src/
  app/
    router/
    providers/
  lib/
    http/
      client.ts
      errors.ts
      interceptors.ts
      trace.ts
      idempotency.ts
    dayjs/
      index.ts
  schemas/
    auth.ts
    user.ts
    chat.ts
  stores/
    auth-store.ts
    ui-store.ts
  queries/
    query-client.ts
    auth.ts
    users.ts
    chat.ts
  api/
    auth.ts
    users.ts
    chat.ts
  streams/
    chat-stream.ts
  features/
    auth/
    admin/
    chat/
  pages/
    ...
```

目录职责：

- `schemas/`: Zod schema 与 `z.infer`
- `lib/http/`: 请求基建与公共网络规则
- `stores/`: 客户端状态
- `queries/`: Query key、query function、mutation function、轮询策略
- `api/`: 薄封装 endpoint，不做页面逻辑
- `streams/`: SSE/流式请求
- `features/`: 业务能力组合

## 网络层规范

### HTTP Client

所有普通 HTTP 请求统一走 axios client。

必须统一处理：

- `baseURL`
- timeout
- `Authorization`
- `X-Request-ID` 或 `X-Trace-ID`
- 错误格式归一化
- 401/403 清理逻辑
- retry 入口

建议 Header：

- `Authorization: Bearer <token>`
- `X-Request-ID: <uuid>`

### Trace ID

目标：

- 每个请求都有唯一标识
- 前端日志、Nginx、后端日志可以串起来

建议：

- 普通请求在 request interceptor 中自动生成 `X-Request-ID`
- 关键业务流在 action 层保留并复用该 ID
- 幂等 mutation 可复用同一份 `client_request_id`，并同步写入 `X-Idempotency-Key`

### 错误归一化

HTTP client 应统一把各种错误转换成前端可消费格式，例如：

```ts
type AppHttpError = {
  status?: number
  code: 'network' | 'unauthorized' | 'forbidden' | 'validation' | 'server' | 'unknown'
  message: string
  requestId?: string
}
```

这样页面层只需要处理统一错误结构。

## Token 生命周期规范

### 登录

登录流程固定为：

1. 调用 `/api/v1/auth/login`
2. 收到 `access_token`
3. 写入 `auth store`
4. 立即请求 `/api/v1/users/me`
5. `/me` 成功后，前端才认为“登录完成”

### 启动时恢复

应用启动时：

1. 从 `persist` 中读 token
2. 如果没有 token，进入匿名态
3. 如果有 token，调用 `/users/me` 做 bootstrap
4. `/me` 失败则清 token，回到匿名态

### 失效处理

- 401/403 是唯一权威信号
- 前端可以解析 JWT `exp` 作为优化，但不能代替后端校验
- 一旦收到认证失败：
  - 清 token
  - 清用户信息
  - 清需要绑定身份的 query cache
  - 跳回登录/匿名态

### Token 存储规则

可以 persist 的：

- access token
- 最小登录态信息

不 persist 的：

- 大型业务对象
- 会话详情列表缓存
- 敏感的临时业务结果

## 幂等规范

### 什么时候要幂等 key

必须带幂等 key 的请求：

- 创建任务
- 发起流式聊天
- 可能被用户连续点击的长耗时 POST
- 任何可能因网络抖动而重复提交的“有副作用”请求

通常不需要幂等 key 的请求：

- `GET`
- 只读查询
- 明确幂等的 `PATCH/PUT/DELETE`

### 前端生成方式

统一使用：

```ts
crypto.randomUUID()
```

### 传递方式

优先顺序：

1. `X-Idempotency-Key`
2. 如果后端当前约定为 body 字段，则使用 `client_request_id`

当前项目聊天接口已使用 `client_request_id`，后端在 Redis 中做幂等锁。

## 网络抖动与重试规范

### 查询请求

适用于：

- 列表
- 详情
- profile
- 任务状态

策略：

- 允许自动 retry
- 指数退避
- 带随机抖动
- 最大次数有限制

### 变更请求

适用于：

- 创建
- 注册
- 提交任务
- 发消息

策略：

- 默认不自动 retry
- 只有携带幂等 key 的 mutation 才允许 retry

### 不应重试的情况

- 401 / 403
- 400 / 422
- 明确业务拒绝

### 可以考虑重试的情况

- 网络断开
- 超时
- 429
- 5xx

## Query 规范

`TanStack Query` 负责：

- `useMeQuery`
- `useUsersQuery`
- `useSessionsQuery`
- `useSessionDetailQuery`
- `useTaskStatusQuery`

推荐规则：

- query key 集中定义
- mutation 后通过 invalidation 更新缓存
- 轮询统一使用 `refetchInterval`
- 不在页面中手写 `setInterval + axios`

## SSE / 流式请求规范

聊天流式请求不放入 `TanStack Query`。

原因：

- 它不是标准查询缓存模型
- 它需要逐 chunk 消费
- 它需要中断、失败恢复、重发与 retry cache

流式请求应放到 `streams/` 或 `features/chat/` 中，职责包括：

- token/header 注入
- request id / idempotency key 注入
- `AbortController`
- chunk 解析
- 错误事件解析
- retry 入口

## 表单规范

### Antd Form 与 Zod 的分工

`Form.Item rules` 负责：

- 即时交互反馈
- 基本必填校验
- 简单格式提示

`Zod` 负责：

- 提交前统一 parse
- payload 组装后的最终校验
- API response parse

不要只依赖 `Form.Item rules`。

## 测试规范

前端至少保持三层验证：

### 1. Unit / smoke test

- 路由渲染
- schema parse
- request helper
- store action

### 2. Integration test

- query/mutation hook
- token bootstrap
- idempotency helper

### 3. Build verification

- `make frontend-build`

## AI 生成代码约定

如果主要由 AI 编写前端，默认要求：

- 不在页面组件里直接写裸 axios 请求
- 不手写重复 DTO，优先从 Zod 推导类型
- 不把服务端列表缓存放进 Zustand
- 不为每个页面各写一套错误处理
- 不为 POST 自动加 retry，除非它明确幂等
- 流式请求继续走 stream client，不强塞进 Query

## 非目标

当前阶段不追求：

- 一次性把所有旧代码重写
- 先上最复杂的全局状态方案
- 为了“统一”而把 SSE 也改成 Query
- 在没有真实日期复杂度之前提前铺满 `dayjs`
