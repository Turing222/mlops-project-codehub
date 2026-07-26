# 前端架构治理阶段一：基础边界（PR1–PR3）

> 状态：Completed / Validated（2026-07-16）
>
> 执行范围：认证身份生命周期、Knowledge Query、Repo recent-runs
>
> 后续阶段：[Chat Controller 拆分（PR4–PR6）](02-chat-controller-decomposition-plan.md)（已完成）

## 1. 目标与执行顺序

阶段一先修复身份隔离和两个最明显的状态分层缺口，为后续拆分 Chat Controller 建立稳定边界。

执行顺序固定为：

```text
PR1 认证身份生命周期
  -> PR2 Knowledge Query 与 KBFilesModal
  -> PR3 Repo recent-runs
  -> 阶段一完成门
```

三个 PR 严格串行。每个 PR 必须保持独立可测试、可评审和可回滚；前一个 PR 未满足验收标准时，不开始后一个 PR。

## 2. 全阶段约束

- 不修改后端 API、response schema 或 SSE wire contract。
- 不修改 `AuthContext`、`UseChatControllerReturn` 或 Chat 页面 props 的公开形状。
- 不在结构 PR 中夹带登录方式重构、聊天行为变化、上传 UX 重写或 Repo UI 深拆。
- 服务端状态进入 TanStack Query；身份相关本地运行态在身份切换时显式清理。
- 所有身份绑定 Query 的 `enabled` 必须同时依赖有效 token、`/users/me` bootstrap 用户和自身业务条件。
- 页面只做组合，不直接调用 Knowledge API。
- 每个 PR 先跑相关测试，再跑 `make frontend-check`。

参考约束：

- [Frontend Architecture](../../architecture.md)
- [State Standard](../../standards/state.md)
- [Component Standard](../../standards/components.md)
- [Testing Standard](../../standards/testing.md)

## 3. PR1 — 认证身份生命周期与跨账号清理

### 3.1 目标

让 logout、普通 HTTP 401、SSE 401 和登录 bootstrap 失败具有同一身份终止语义，并保证用户 A 的 Query cache、聊天运行态和流式请求不会泄漏给用户 B。

### 3.2 实现范围

主要改动面：

- `frontend/apps/admin/src/context/AuthContext.tsx`
- `/users/me` query options，以及 users/repo-analysis 的身份门控
- `frontend/apps/admin/src/features/chat/use-chat-controller.ts`
- 对应 Auth、stream contract 和 controller 测试

实现决策：

1. 在 auth query 模块导出共享的 `meQueryOptions()`：
   - 固定复用 `authKeys.me()`、`getUserProfileAPI` 和当前 5 分钟 `staleTime`；
   - `useMeQuery()` 与 `AuthProvider.login()` 必须使用同一份 options，避免 bootstrap 出现两套 queryFn 或缓存策略。
2. 在 `AuthProvider` 内新增私有异步函数 `terminateIdentitySession()`，执行顺序固定为：
   - 同步调用 `clearAuth()`，先让依赖 token 的 Query 在下一次 render 进入 disabled；
   - `await queryClient.cancelQueries()`，阻止已在途的身份 Query 再提交 Query state；
   - 调用 `queryClient.clear()` 清除 Query 与 mutation cache；
   - `AuthContext` 对外类型不变，但 value 中 `user` 必须在 token 为空时立即暴露为 `null`，`isAuthenticated` 必须由有效 token 与 `/me` 用户共同决定，不能在异步 clear 完成前继续暴露 A 为已登录。
3. `AUTH_UNAUTHORIZED_EVENT` 监听器必须幂等：
   - 每次事件都读取 `useAuthStore.getState().token`，不得使用可能过期的闭包 token；
   - token 已为空时直接 no-op；
   - 首次事件同步清 token 后，紧随其后的重复 401 不能再次触发 cancel/clear。
4. 以下入口调用统一终止函数：
   - `logout()`；
   - `AUTH_UNAUTHORIZED_EVENT` 监听器；
   - `login(newToken)` 中 `/users/me` bootstrap 失败的分支；
   - unauthorized handler 的 token no-op 不适用于显式 logout；logout 即使在 token 已空时也执行强制清理。
5. `login(newToken)` 被定义为身份替换事务：
   - 如果调用时已有 token 或已确认用户，先 `await terminateIdentitySession()` 清除 A 的身份数据；
   - 写入新 token 后，使用 `queryClient.fetchQuery(meQueryOptions())` 完成 B 的 `/users/me` bootstrap，不再调用已被 clear 的旧 observer `refetch()`；
   - bootstrap 成功后才关闭登录弹窗；失败时再次执行统一终止并向调用方抛出原错误；
   - 该规则同时覆盖密码、短信和 Google callback，不能假设已登录状态下 `login()` 永远不可达。
6. 补齐当前两个身份绑定 Query 的门控：
   - `useUserSearchQuery` 只有在 token、bootstrap 用户和搜索参数均存在时 enabled；
   - `useRepoAnalysisRunQuery` 只有在 token、bootstrap 用户和 `runId` 均存在时 enabled；
   - Repo run 详情后端依赖当前用户，本计划不保留匿名查询分支。
7. 不在 401 处理器内强制打开登录弹窗或导航；沿用现有匿名态和页面 guard 行为。
8. Chat Controller 保存上一次已确认的 `user.id`：
   - 初始匿名态切到首次登录用户不触发多余 reset；
   - 已登录用户从 A 变为 `null` 或变为 B 时执行身份级 reset。
9. 身份级 reset 必须一次性完成：
   - abort 当前 `AbortController`；
   - 清空 active session、messages、streaming text 和 history 状态；
   - 清空 retry cache 和默认 KB ID 缓存；
   - 清空 trace steps、citations 和 ingestion steps；
   - 停止知识入库 polling timer 与 tab-switch timer；
   - 恢复 `chatMode = normal`、`activeTraceTab = rag`；
   - 关闭 ingestion sidebar，并将 streaming/ingesting 标志恢复为 false。
10. 将 reset 逻辑收敛为 controller 内部命令，供身份变化和 `startNewChat` 复用共同部分；不得通过页面 remount 偶然完成清理。

`cancelQueries()` 在本 PR 的承诺是阻止旧 Query 结果提交，不等同于取消所有底层 Axios 传输；主聊天 SSE 仍通过它自己的 `AbortController` 显式终止。

### 3.3 测试要求

- `AuthContext.test.tsx`：
  - logout 清 token 并清除 auth/chat 等全部 Query 数据；
  - HTTP/SSE 共用的 unauthorized event 清除全部 Query 数据；
  - 连续派发多次 unauthorized event 只执行一次 cancel/clear，不形成重复请求；
  - 延迟返回的 A Query 在身份终止后不能重新写回 cache；
  - token 一旦清空，Context 立即暴露 `user = null`、`isAuthenticated = false`，不等待异步 Query clear；
  - login bootstrap 失败执行同样清理；
  - 初次成功登录的公开行为不变；
  - A 状态下直接 `login(B)` 会先清 A cache，再以共享 `/me` options bootstrap B。
- users/repo-analysis query hook 测试：
  - token 缺失或 `/me` 用户缺失时，即使搜索参数或 `runId` 存在也不请求；
  - token、用户和业务参数同时满足时才请求；
  - token 清空后的 rerender 不产生匿名重请求。
- `use-chat-controller.test.tsx`：
  - A 的用户 ID 变为匿名时清空本地消息、session、trace 和缓存；
  - A 直接变为 B 时同样清空；
  - 身份变化会 abort 活跃 stream；
  - 首次从匿名态加载用户不会误清新会话。
- 保留现有 streaming contract 对 SSE 401 派发统一 unauthorized event 的覆盖。

### 3.4 验收标准

- [x] logout、HTTP 401、SSE 401、`/users/me` bootstrap 失败最终都清 token 和整个 Query cache。
- [x] 重复 unauthorized event 在 token 已空后 no-op，只执行一次身份清理且不形成 401 请求循环。
- [x] users/repo-analysis 身份 Query 在 token 或 bootstrap 用户缺失时保持 disabled。
- [x] token 清空后 `AuthContext` 立即进入匿名态，不在 cancel/clear 窗口继续暴露旧用户。
- [x] 用户 A 退出或失效后登录 B，B 看不到 A 的消息、会话详情、trace、citation 或知识入库状态。
- [x] 已登录 A 时直接调用 `login(B)`，A 的 chat、credits、repo 等 cache 被清除，`/users/me` 最终只包含 B。
- [x] 身份终止后，原 SSE signal 的 `aborted` 为 true，后续 callback 不能提交状态。
- [x] 身份终止前已经发出的普通 Query 即使延迟完成，也不能重新填充已清理 cache。
- [x] `AuthContext` 与 `UseChatControllerReturn` 的公开类型没有变化。
- [x] 未引入 Cookie、refresh token、认证路由或登录方式调整。
- [x] 相关测试和 `make frontend-check` 通过。

### 3.5 明确不做

- 不把 Auth 短信或 Google 登录迁入新的 feature hook。
- 不实现 refresh token、跨标签页同步或服务端 logout。
- 不为 Query key 增加 user ID；本阶段以完整身份 teardown 保证隔离。
- 不在本 PR 为所有 Axios API helper 全量增加 `AbortSignal`；Query cancellation 与 SSE transport abort 分别按上述边界验收。

## 4. PR2 — Knowledge Query 层与 KBFilesModal 边界

### 4.1 目标

消除 KBFilesModal 中手写的服务端状态管理，让 Knowledge 列表和删除遵守集中 query key、enabled 和 invalidation 规则。

### 4.2 实现范围

新增内部接口：

```ts
knowledgeKeys.all()
knowledgeKeys.default()
knowledgeKeys.files()
knowledgeKeys.task(taskId)

useDefaultKBQuery({ enabled })
useKBFilesQuery({ enabled })
useDeleteKBFileMutation()
```

实现决策：

1. 新增 `query/keys/knowledge.ts`：
   - 所有 key 由 `knowledgeKeys.all()` 派生；
   - `task(taskId)` 将 task ID 放在 key 末尾；
   - 即使 PR2 尚未消费 task key，也在本 PR 固定形状供 PR4 使用。
2. 新增 `query/hooks/knowledge.ts`：
   - query function 只调用现有 `api/knowledge.ts` helper；
   - `useDefaultKBQuery` 接收 `{ enabled: boolean }`，使用 `staleTime: Infinity`，匹配当前 `defaultKbIdRef` 在身份生命周期内只解析一次的语义；
   - `useKBFilesQuery` 接收 `{ enabled: boolean }`，使用 `staleTime: 0`；
   - `useDeleteKBFileMutation` 成功后 invalidate `knowledgeKeys.files()`；
   - mutation 的本地化成功/失败提示仍由 feature component 决定。
3. 将 `KBFilesModal.tsx` 与 CSS module 移到 `features/knowledge/`：
   - props 继续使用 `visible` 和 `onClose`；
   - `pages/Chat/index.tsx` 只更新 import 和组件组合；
   - 不修改表格列、分页、确认框和现有文案。
4. Modal 改为：
   - `useKBFilesQuery({ enabled: visible })` 提供 `data`、`isFetching`、`isError` 和 `errorUpdatedAt`；
   - `useDeleteKBFileMutation().mutateAsync(fileId)` 执行删除；
   - 删除 `fetchVersionRef`、`fetchFiles()`、本地 `loading/files` 和相关 effect；
   - 使用独立 ref 记录最后一次已提示的 `errorUpdatedAt`，每次新的列表加载失败只显示一次 `chat.load_kb_files_failed` 本地化 toast；普通 rerender、StrictMode 和同一错误状态不得重复提示；
   - 保留现有 HTTP client 全局错误通知策略；本 PR 的 ref 只负责避免领域级列表错误 toast 自身重复，不顺带调整全局与领域提示的组合策略；
   - 列表加载失败时保留已有 Query data，不因错误主动清空表格；
   - 关闭弹窗时不发请求，重新打开时因数据 stale 而刷新。
5. PR2 立即让现有 Chat Controller 消费 `useDefaultKBQuery({ enabled: false })`，不保留未使用 hook：
   - resolver 先返回 hook 已缓存的 `data.id`；
   - cache 为空时显式调用 `refetch()`，`enabled: false` 只禁止自动请求，不禁止这次命令式首次解析；
   - `refetch()` 失败或没有 data 时沿用当前行为返回 `null`；
   - 删除 `getDefaultKBAPI` 直接调用和 `defaultKbIdRef`；
   - PR6 只把这份 resolver 原样传给 `useChatStream`，不得重新选择直接 API 或另一套 Query 口径。
6. 本 PR 不新增 upload mutation 或 task polling；它们属于 PR4。

### 4.3 测试要求

- 在 query key 测试中覆盖四种 Knowledge key 的稳定形状。
- 新增 Knowledge hook 测试：
  - `useDefaultKBQuery({ enabled: false })` 不自动请求，但显式 `refetch()` 可以获取并缓存默认 KB；
  - `useKBFilesQuery({ enabled: false })` 不请求；
  - `useKBFilesQuery({ enabled: true })` 获取并返回文件列表；
  - 删除成功 invalidate files key；
  - 删除失败不伪造成功数据。
- Modal 测试或等价集成测试覆盖：
  - 关闭状态不加载；
  - 打开时显示 loading 和数据；
  - 列表加载失败显示一次 `chat.load_kb_files_failed`，同一 `errorUpdatedAt` rerender 不重复提示；
  - 加载失败时保留上一次成功数据；
  - 删除成功沿用成功提示；
  - 删除失败保留列表并显示失败提示。
- Controller 既有 RAG 测试补充：首次 send 解析默认 KB 一次，后续 send 复用 Query data，身份 teardown 清 cache 后下次 send 重新解析。

### 4.4 验收标准

- [x] `pages/Chat` 和 `KBFilesModal` 不再 import `api/knowledge`。
- [x] Modal 不再持有文件列表、请求版本号或手写加载状态。
- [x] `visible = false` 时不请求；每次重新打开 stale 列表都会刷新。
- [x] 每次新的文件列表加载失败保留旧数据并显示一次本地化提示，同一失败不会因 rerender 重复 toast。
- [x] 删除成功通过 Query invalidation 更新列表，不再调用 `void fetchFiles()`。
- [x] Chat Controller 不再直接调用 `getDefaultKBAPI` 或维护 `defaultKbIdRef`；默认 KB 由 `useDefaultKBQuery` 缓存并在首次 RAG send 时显式解析。
- [x] 表格 UI、props 和本地化提示保持兼容。
- [x] key、enabled、invalidation 测试和 `make frontend-check` 通过。

### 4.5 明确不做

- 不改变文件上传、入库 progress 或 task status UI。
- 不改变后端 Knowledge response schema。
- 不为了本次迁移重写 KBFilesModal 展示组件。

## 5. PR3 — Repo recent-runs 单一持久化模块

### 5.1 目标

把 RepoCheck 页面读取历史和 RepoAnalysisCard 写入历史的重复 localStorage 逻辑收敛到一个可校验、可测试的 feature 模块。

### 5.2 实现范围

新增 `features/repo-check/recent-runs.ts`，固定导出：

```ts
type RecentRepoRun = z.infer<typeof recentRepoRunSchema>

listRecentRepoRuns(): RecentRepoRun[]
upsertRecentRepoRun(run: RecentRepoRun): RecentRepoRun[]
clearRecentRepoRuns(): void
```

实现决策：

1. 模块独占常量 `DEWFLOW_RECENT_REPO_RUNS` 和最大条数 `10`。
2. 使用 Zod 定义单条记录和数组 schema；类型只从 schema 推导，不在页面重复定义。
3. `listRecentRepoRuns()`：
   - 捕获 localStorage 和 JSON 异常；
   - 使用数组 schema `safeParse`；
   - 任意解析或 schema 失败均返回 `[]`，不抛出到 UI；
   - 读取失败时不自动删除原始值，避免静默破坏用户数据。
4. `upsertRecentRepoRun()`：
   - 先读取合法列表；
   - 移除 `runId` 相同或 `repoUrl` 相同的旧记录；
   - 新记录放在首位并截断到 10 条；
   - best-effort 写回 localStorage，返回计算后的 canonical 列表。
5. `clearRecentRepoRuns()` 捕获存储异常；页面仍立即清空当前 UI state。
6. RepoCheck 页面：
   - 使用 `RecentRepoRun` 类型和 `listRecentRepoRuns()`；
   - clear handler 调用 adapter，不再知道 storage key。
7. RepoAnalysisCard：
   - 成功且存在 structured report 时构造记录并调用 `upsertRecentRepoRun()`；
   - 不再直接 parse、去重、截断或写 localStorage。

### 5.3 测试要求

新增 `features/repo-check/recent-runs.test.ts`，覆盖：

- 无数据时返回空数组；
- 合法数据读取；
- 非法 JSON 和 schema 不匹配降级为空数组；
- 按 `runId` 去重；
- 按 `repoUrl` 去重；
- 新记录置顶；
- 超过 10 条时截断；
- clear 删除 storage value；
- localStorage get/set/remove 抛错时 API 不向 UI 抛出。

### 5.4 验收标准

- [x] storage key、`JSON.parse/stringify` 和 recent-runs localStorage 调用只存在于 adapter 模块。
- [x] RepoCheck 页面和 RepoAnalysisCard 不再直接访问 localStorage。
- [x] `RecentRepoRun` 类型只有一个定义来源。
- [x] 读取坏数据不会导致 Repo 页面白屏。
- [x] 去重、排序和 10 条上限行为与当前产品语义一致。
- [x] Repo UI、后端提交和轮询行为没有变化。
- [x] adapter 测试和 `make frontend-check` 通过。

### 5.5 明确不做

- 不把 recent-runs 同步到后端。
- 不统一 Chat repo_check 与独立 RepoCheck 页的产品历史。
- 不拆 RepoAnalysisCard 的展示结构或计时器。

## 6. 阶段一完成门

PR1–PR3 全部满足各自验收标准后，从仓库根目录运行：

```bash
make frontend-test-coverage
make frontend-check-full
```

进入阶段二前必须同时满足：

- [x] 身份终止与 A→B 切换不存在缓存和运行态泄漏。
- [x] 重复 unauthorized 不形成清理/请求循环，身份绑定 Query 不在匿名态请求。
- [x] Knowledge 默认库解析、文件列表和删除已进入 Query 层。
- [x] recent-runs 持久化只有一个入口。
- [x] coverage floor、lint、typecheck、unit、build、bundle 和 mock e2e 全部通过。
- [x] PR1–PR3 没有混入后端契约或聊天产品行为变化。

完成记录（2026-07-16）：PR1–PR3 的 focused tests、逐 PR `make frontend-check` 和阶段完成门均已通过；身份隔离、Knowledge Query 边界与 recent-runs 单一持久化入口已按计划落地。

Checkpoint（closed）：`frontend-foundation-boundaries-validated`。

## 7. 回滚与停手点

- PR1 可通过恢复原 Auth cleanup/controller reset 实现独立回滚，不依赖 PR2、PR3。
- PR2 回滚时同时恢复 Modal 文件位置/import，以及 Controller 的 `getDefaultKBAPI + defaultKbIdRef`；不得只删除 Query hooks 留下断裂调用。
- PR3 回滚时保留原 storage key，避免丢失已有浏览器历史。
- 阶段一验收通过后才开始 PR4；如果本阶段失败，停止在失败 PR，不跨阶段绕过完成门。
