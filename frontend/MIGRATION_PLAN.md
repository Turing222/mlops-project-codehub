# Frontend Migration Plan

这份计划围绕目标栈逐步改造现有 `apps/admin`，优先保证：

- 每一步都可验证
- 每一步都能回滚
- 不要求一次性重写现有页面

## 当前基线

已完成：

- 只保留 `apps/admin`
- `lint`、`test`、`build` 已通过
- 前端基础 smoke test 已建立
- API 前缀问题已修正
- `zod` schema 已接入关键 API 边界
- 统一 HTTP client / trace id / 错误归一化已接入
- 聊天 `client_request_id` 已迁到公共幂等 helper

当前待改造点：

- 仍然使用 `AuthContext`
- `zustand` / `persist` 还未接入
- `TanStack Query` 还未接入
- 上传等 mutation 还未统一接入幂等策略
- 缺少服务端状态缓存层

## 阶段 1：网络基建与 Schema 基建

目标：

- 建立统一 HTTP client
- 引入 `zod`
- 建立请求/响应 schema 约定

范围：

- 安装 `zod`
- 新增 `src/lib/http/`
- 新增 `src/schemas/`
- 将现有 `src/api/auth.ts`、`src/api/users.ts`、`src/api/chat.ts` 改为基于 schema 的薄封装

建议先做：

1. `schemas/auth.ts`
2. `schemas/user.ts`
3. `lib/http/client.ts`
4. `lib/http/errors.ts`
5. `lib/http/trace.ts`

当前状态：已完成

本阶段结果：

- 所有普通 axios 请求已经走统一 client
- `auth / user / chat` 关键链路已经接入 Zod parse
- 组件不再依赖旧的请求实现细节
- 聊天流请求已经复用统一 token / trace id / idempotency helper

验收标准：

- 所有普通 axios 请求走统一 client
- 登录、用户信息、用户更新、会话列表至少一条链路已经接入 Zod
- 组件中不再直接依赖 `request.ts`

## 阶段 2：认证改造

目标：

- 用 `zustand + persist` 替换 `AuthContext` 作为认证状态来源
- 明确 token bootstrap 规则

范围：

- 安装 `zustand`
- 新增 `src/stores/auth-store.ts`
- 将 `AuthContext` 迁移为 provider 包装层，逐步变薄
- 登录成功后统一走：
  - 存 token
  - 拉 `/users/me`
  - 写用户态

建议先做：

1. `auth store`
2. `bootstrap auth` helper
3. 统一 logout/unauthorized 清理逻辑

验收标准：

- token 来源唯一
- 启动时 bootstrap 逻辑统一
- 401/403 清理逻辑统一

## 阶段 3：引入 TanStack Query

目标：

- 把服务端状态从页面里拿出来
- 统一缓存、失效、轮询策略

范围：

- 安装 `@tanstack/react-query`
- 新增 `src/queries/query-client.ts`
- 新增 `src/queries/auth.ts`
- 新增 `src/queries/users.ts`
- 新增 `src/queries/chat.ts`

优先接入：

1. `/users/me`
2. 用户查询
3. 聊天会话列表
4. 会话详情

先不要接入：

- SSE 主聊天流

验收标准：

- 页面中不再手写 `loading + axios + setState` 组合查询逻辑
- query key 集中定义
- mutation 后统一 invalidation

## 阶段 4：幂等与网络抖动策略落地

目标：

- 形成统一 mutation 规则
- 给后端长耗时或可重复提交接口统一幂等入口

范围：

- 新增 `lib/http/idempotency.ts`
- 为关键 mutation 定义：
  - 是否幂等
  - 是否允许 retry
  - 是否需要 request id

优先处理：

1. 聊天流式请求
2. 文件上传 / 批量导入
3. 后续任务触发接口

建议约定：

- 普通 GET：可 retry
- POST：默认不 retry
- 带幂等 key 的 POST：可按策略 retry

验收标准：

- 至少聊天和上传两条链路有明确幂等策略
- 没有页面层自己生成临时 request id

## 阶段 5：流式聊天重构

目标：

- 把当前页面里的 stream 细节从 UI 中剥离出来

范围：

- 新增 `src/streams/chat-stream.ts`
- 将 `pages/Chat/index.tsx` 中的：
  - SSE 请求
  - chunk 解析
  - abort
  - retry cache
  - meta 事件处理
 逐步迁出

验收标准：

- 聊天页面只保留 UI 与状态编排
- 流式实现集中在单独模块

## 阶段 6：日期与展示层收口

目标：

- 把日期处理从零散 `new Date()` 收敛

范围：

- 需要真实复杂度时再引入 `dayjs`
- 先从相对时间、统一展示格式入手

适用场景：

- 相对时间
- 统一格式
- 时区需求
- 日期比较

验收标准：

- 日期格式化从零散逻辑收敛到工具函数

## 阶段 7：CI 与模板化

目标：

- 让这套范式变成可重复执行的工程约定

范围：

- 前端独立 CI
- 文档链接到 README
- 新页面、新 API、新 query、新 schema 的模板沉淀

建议输出：

- `frontend/ARCHITECTURE.md`
- `frontend/MIGRATION_PLAN.md`
- `frontend/templates/` 或内部样例文件

## 推荐执行顺序

推荐严格按这个顺序推进：

1. 阶段 1：HTTP client + Zod
2. 阶段 2：Auth store
3. 阶段 3：TanStack Query
4. 阶段 4：幂等与 retry
5. 阶段 5：聊天流重构
6. 阶段 6：Dayjs 按需引入
7. 阶段 7：CI 与模板化

## 每阶段通用验收

每做完一阶段，至少执行：

```bash
make frontend-test
make frontend-build
pnpm --dir frontend --filter admin lint
```

如果阶段中涉及到真实请求行为，补充对应的：

- schema parse test
- request helper test
- store test
- query hook test

## 当前不建议做的事

- 一次性重写所有页面
- 为了“统一”先把 SSE 也改进 Query
- 在没有日期复杂度前先全量铺 `dayjs`
- 在没有幂等约定前给所有 mutation 加自动 retry
