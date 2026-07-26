# 前端架构治理阶段二：Chat Controller 拆分（PR4–PR6）

> 状态：Completed / Validated（2026-07-16）
>
> 前置阶段：[基础边界（PR1–PR3）](01-foundation-boundaries-plan.md)（已完成）
>
> 停手点：PR6 与阶段二完成门已通过，本轮结构治理在此结束

## 1. 目标与执行顺序

阶段二只拆分改造前 945 行 `useChatController` 的变化轴，保留 facade 和既有产品行为；唯一明确接受的行为调整是 PR4 将入库超时从“120 次查询尝试”改为“120 秒墙钟 deadline”。目标不是重写聊天，而是让知识入库、会话状态和 SSE/retry 可以独立维护与测试。

执行顺序固定为：

```text
阶段一完成门
  -> PR4 useKbIngestion
  -> PR5 useChatSessionState
  -> PR6 useChatStream + 收薄 facade
  -> 阶段二完成门
  -> 停手
```

PR5 必须在 PR6 前完成：stream hook 只依赖稳定的 session commands，不直接接管或泄漏 session state setter。

## 2. 全阶段约束

- PR4–PR6 是结构 PR；除已明确接受的“入库 120 秒墙钟 deadline”外，不改变聊天、知识入库或 RepoCheck 的产品语义。
- `UseChatControllerReturn`、Chat 页面调用方式和组件 props 保持不变。
- 不修改后端 API、schema、SSE event 或 `[DONE]` 语义。
- SSE 解析继续留在 `streams/chat-stream.ts`，不迁入 TanStack Query。
- Knowledge task status 是服务端状态，轮询必须进入 Query 层。
- 每抽取一个 hook，先保证原 facade 测试和新增 focused tests 通过，再开始下一 PR。
- PR4–PR6 期间冻结其他针对 `use-chat-controller.ts` 的行为性修改。

参考约束：

- [Frontend Architecture](../../architecture.md)
- [State Standard](../../standards/state.md)
- [Streaming Standard](../../standards/streaming.md)
- [Testing Standard](../../standards/testing.md)
- [Chat / RAG / Worker reliability plan](../../../../docs/assessments/2026-07-15-chat-rag-worker-reliability-plan.md)
- [Knowledge ingestion consistency plan](../../../../docs/assessments/2026-07-15-knowledge-ingestion-data-consistency-plan.md)

## 3. 目标结构与公开边界

最终结构：

```text
useChatController()                   # 只组合 mode、trace 与子 hook
  ├─ useKbIngestion()                # upload、task query、ingestion UI state
  ├─ useChatSessionState()           # active session、messages、history hydration
  └─ useChatStream()                 # send、abort、retry、SSE callbacks

streams/chat-stream.ts               # fetch、SSE parse、event validation，保持不变
```

行数完成条件：

- `use-chat-controller.ts` 不超过 250 行。
- `use-kb-ingestion.ts`、`use-chat-session-state.ts`、`use-chat-stream.ts` 各不超过 400 行。
- 不为满足行数机械拆分无业务边界的 helper；纯映射函数可以放到同 feature 的小模块。

对外继续只暴露现有 `UseChatControllerReturn`。三个新 hook 是 `features/*` 内部接口，不从应用公共 barrel 导出。

## 4. PR4 — 抽取 `useKbIngestion`

### 4.1 目标

把文件校验、上传、task polling、ingestion steps 和相关 UI runtime 从 Chat Controller 移到 Knowledge feature，并让 task status 通过 TanStack Query 轮询。

### 4.2 Query 接口

在阶段一的 Knowledge hooks 基础上新增：

```ts
useUploadKBFileMutation()
useKBTaskStatusQuery(taskId, { enabled })
```

固定行为：

1. `useUploadKBFileMutation()`：
   - 调用现有 `uploadKBFileAPI`；
   - 显式 `retry: false`，不改变当前上传重试语义；
   - 继续由 API helper 生成或接收 idempotency key；
   - 不在 Query hook 中生成用户可见 toast。
2. `useKBTaskStatusQuery(taskId, { enabled })`：
   - key 使用 `knowledgeKeys.task(taskId)`；
   - `enabled` 同时要求外部允许且 task ID 非空；
   - active task 每 1000ms refetch；
   - status 为 `completed` 或 `failed` 时 `refetchInterval` 返回 false；
   - 显式 `retry: false`，单次查询失败由下一次 interval 重试，避免 Query retry 与 polling 叠加；
   - 不在 hook 中猜测尚未进入当前后端契约的新终态。

### 4.3 `useKbIngestion` 内部接口

新增 `features/knowledge/use-kb-ingestion.ts`。返回字段固定为：

```ts
{
  activeTraceTab,
  setActiveTraceTab,
  ingestionSteps,
  uploadKBFile,
  isIngesting,
  isIngestionSidebarOpen,
  setIsIngestionSidebarOpen,
  resetIngestion,
}
```

其中除 `resetIngestion` 外，其余字段继续由 controller facade 映射到现有公开返回值；`resetIngestion` 只供身份 teardown 和 controller cleanup 使用。

### 4.4 实现决策

1. 文件前置校验保持不变：
   - 只接受 `.md` 和 `.markdown`；
   - 最大 20MB；
   - 沿用现有成功、失败和校验文案。
2. 上传开始时：
   - 清理上一任务的 deadline timer 和 tab-switch timer；
   - 递增单调的 ingestion generation，并让本次上传、task ID 和后续 response 捕获同一 generation；
   - `isIngesting = true`；
   - `activeTraceTab = ingestion`；
   - 打开 ingestion sidebar；
   - 使用现有五个步骤初始化 progress。
3. 秒传或上传响应已为 `completed` 时：
   - 将剩余步骤标为完成；
   - 停止查询；
   - 显示现有秒传成功提示；
   - 4 秒后切回 rag tab。
4. 普通异步入库时：
   - 保存 `activeTaskId`；
   - 启用 `useKBTaskStatusQuery`；
   - 从保存 `activeTaskId` 并启用 polling 的时刻开始设置单个 120 秒 wall-clock deadline timer，不再递归创建 polling timer；
   - 该 deadline 明确替代当前“每次请求完成后再等待 1 秒、累计最多 120 次尝试”的限制，因此慢请求下会比现实现更早超时，这是本阶段接受的唯一语义微调；
   - 将 task response 映射到现有 content-audit、semantic-chunk、vector-index、ingestion-complete 状态。
5. progress 映射抽成纯函数，输入为当前 steps、task response 和当前时间，输出新 steps；不得在映射函数里产生 toast、timer 或 Query 副作用。
6. 单次 task 查询错误：
   - 保留现有 steps；
   - 只记录现有诊断日志；
   - 在 120 秒 deadline 内由下一 polling tick 继续查询。
7. terminal 处理：
   - `completed`：全部步骤完成、清 task ID/deadline、提示成功、4 秒后切回 rag；
   - `failed`：活动/等待步骤进入 error、使用 `error_log` 或现有 fallback、清 task ID/deadline；
   - deadline：先标记本次 ingestion generation 已终止、清 active task ID，并 cancel 对应 `knowledgeKeys.task(taskId)` Query，再将活动/等待步骤置为 error，提示前往后台查看任务状态；
   - deadline、reset 或新上传都会使旧 generation 失效；之后到达的旧 task response 必须因 generation/task ID 不再匹配而被忽略，不能把 error 或新任务恢复为旧任务 success。
8. `resetIngestion()` 和 unmount cleanup 必须：
   - 清 active task ID；
   - 清 deadline 与 tab-switch timer；
   - 关闭 sidebar；
   - 恢复非 ingesting 状态和初始 steps；
   - 防止旧 Query data 或 timer 更新新身份状态。
9. Controller 删除 Knowledge 上传/task API imports、polling refs 和 ingestion 原始状态，只组合 hook 返回值。

### 4.5 测试要求

- Knowledge query hook：
  - task ID/disabled 时不查询；
  - active 状态保持 1 秒 interval；
  - completed/failed 停止 interval；
  - 查询错误不触发 Query 内额外 retry。
- `useKbIngestion`：
  - 文件格式和大小拒绝；
  - 秒传完成；
  - active progress 映射；
  - completed、failed、临时查询错误和 120 秒 wall-clock 超时；
  - 慢请求导致 120 秒内不足 120 次尝试时仍按 deadline 超时；
  - deadline 后到达的旧 completed response 不再提交状态；
  - 新上传取消旧 deadline；
  - reset/unmount 不再提交旧任务状态；
  - 4 秒 tab 切换及其清理。
- 原 controller facade 与 knowledge upload mock e2e 保持通过。

### 4.6 验收标准

- [x] Controller 不再 import `uploadKBFileAPI` 或 `getKBTaskStatusAPI`。
- [x] Controller 不再持有 knowledge polling/deadline/tab-switch timer。
- [x] task status 由 `useKBTaskStatusQuery` 每秒查询，terminal 和 cleanup 后停止。
- [x] 秒传、普通成功、失败和临时错误语义保持不变；超时明确按 120 秒 wall-clock deadline 执行，提示文案保持不变。
- [x] 身份 reset 能终止旧用户的 ingestion runtime。
- [x] `UseChatControllerReturn` 不变。
- [x] focused tests、`make frontend-e2e-mock` 和 `make frontend-check` 通过。

### 4.7 明确不做

- 不消费知识一致性计划将来可能新增的 canceled/retry/reindex 语义。
- 不调整上传大小限制或允许的扩展名。
- 不重新设计 ingestion sidebar、steps 或文案。

## 5. PR5 — 抽取 `useChatSessionState`

### 5.1 目标

把 active session、messages、历史会话选择和 detail hydration 封装成稳定命令接口，为 PR6 的 stream hook 提供唯一的会话状态入口。

### 5.2 内部接口

新增 `features/chat/use-chat-session-state.ts`，返回状态：

```ts
{
  activeSessionId,
  activeSession,
  messages,
  displayedMessages,
  isSessionFromHistory,
  isLoadingHistory,
  sessionDetailData,
}
```

返回命令：

```ts
selectSession(session)
enterLiveMode()
appendMessage(message)
updateMessages(updater)
commitSession(session)
resetSession()
```

这些命令是 feature 内部契约，不加入 `UseChatControllerReturn`。

### 5.3 实现决策

1. Hook 接管：
   - `activeSessionId`、`activeSession`、`messages`；
   - `isSessionFromHistory`；
   - `useSessionDetailQuery`；
   - 当前 history/detail 与 live state 的 displayed 选择逻辑。
2. `selectSession(session)`：
   - 进入 history 状态；
   - 设置 session ID 和 metadata；
   - 清空本地 live messages，等待 detail Query；
   - 不直接修改 chat mode、trace、citations 或 retry cache。
3. `enterLiveMode()` 只退出 history 展示模式，供新 send 开始前调用。
4. `appendMessage` 和 `updateMessages` 是 stream 写入消息的唯一入口；PR6 不获得 React state setter。
5. `commitSession(session)` 更新当前 live session ID 和 metadata，用于 stream meta/done callback。
6. `resetSession()` 清空 ID、session、messages 和 history 标志；身份 reset 与 `startNewChat` 均调用它。
7. 历史 detail 到达后：
   - displayed session/messages 保持与当前 facade 相同；
   - 将 detail messages hydration 到本地 messages，保证从 history 继续提问时可以切换到 live state；
   - 不在 hook 内解析 RAG metrics、citation 或 trace。
8. Controller 保留一层协调：
   - select 后按现有规则设置 chat mode 并清 retry/trace/citation；
   - detail 到达后按最后一条 assistant message 更新 mode/trace/citation；
   - start new 时组合 session reset、stream abort、mode/trace reset。

### 5.4 测试要求

- 选择 session 时使用 detail Query 并显示 loading。
- detail 到达后 active session/messages 与现有行为一致。
- history 进入 live mode 后使用 hydration 后的 messages。
- `appendMessage`、`updateMessages`、`commitSession` 正确更新 live state。
- `resetSession` 清空全部身份相关会话状态。
- Controller facade 测试继续覆盖 select session、start new 和 history 后发送新问题。

### 5.5 验收标准

- [x] Controller 不再直接调用 `useSessionDetailQuery`。
- [x] Controller 不再声明 session/messages/history 原始 state。
- [x] stream/controller 通过命令写 session state，不直接获得 setter。
- [x] 选择历史、loading、hydration、历史转 live 和新建聊天行为不变。
- [x] 身份 reset 清空 session hook 状态。
- [x] `UseChatControllerReturn` 不变。
- [x] focused tests 和 `make frontend-check` 通过。

### 5.6 明确不做

- 不把 chat mode、trace 或 citation 塞进 session hook。
- 不改变 session detail Query key、分页或后端 DTO。
- 不引入 Zustand、状态机或新的全局 Chat store。

## 6. PR6 — 抽取 `useChatStream` 并收薄 facade

### 6.1 目标

把 send、abort、retry cache 和 SSE callback 从 Controller 移到独立 hook，让 facade 只组合各领域状态，同时保持四种 chat mode 和现有可靠性语义不变。

### 6.2 内部接口

新增 `features/chat/use-chat-stream.ts`，输入固定为：

```ts
{
  userId,
  refreshUser,
  chatMode,
  activeSessionId,
  displayedMessages,
  sessionActions,
  traceActions,
  resolveDefaultKbId,
}
```

其中：

- `sessionActions` 只使用 PR5 的命令接口。
- `traceActions` 由 facade 提供 reset、step、complete、error 和 citation 更新 callback。
- `resolveDefaultKbId` 直接复用 PR2 已建立并被 Controller 消费的 resolver：先读 `useDefaultKBQuery({ enabled: false })` 的缓存 data，缺失时才显式 `refetch()`；PR6 只负责注入该函数，stream hook 不得直接调用 Knowledge API、调用 `queryClient.fetchQuery` 或另建默认 KB 缓存。

返回固定为：

```ts
{
  streamingText,
  isStreaming,
  sendQuery,
  retryFailedMessage,
  abort,
  resetStream,
}
```

### 6.3 实现决策

1. Hook 接管：
   - `streamingText`、`isStreaming`；
   - 当前 `AbortController`；
   - retry cache、5 分钟 TTL 和 prune；
   - `sendQuery`、`retryFailedMessage`；
   - `streamChatQuery` 的 meta/chunk/step/done/error/abort callbacks。
2. 新查询开始前必须 abort 旧 controller，再创建新 controller。
3. `startNewChat`、身份终止和 unmount 通过 `resetStream()`：
   - abort 当前流；
   - 清 retry cache；
   - 清 streaming text；
   - 恢复 `isStreaming = false`。
4. normal、rag、web_rag：
   - 保持当前 payload、idempotency key、默认 KB 解析和 callback 顺序；
   - 保持当前 Query invalidation、session detail refresh 与 user refresh 行为。
5. repo_check：
   - 继续作为 `sendQuery` 的 early return；
   - 沿用当前 API、临时消息和错误文案；
   - 不与独立 RepoCheck 页合并。
6. retry：
   - 继续以失败 message ID 查 retry cache；
   - cache miss 时仍回退到前一条 user message；
   - cache hit 时继续复用原 `clientRequestId`；
   - 删除失败消息后以 `addUserMessage: false` 重发；
   - 不提前实施 reliability WS1 的 attempt/request identity 新语义。
7. stream terminal：
   - 继续沿用当前 `[DONE]` 与 `onDone` 行为；
   - 继续沿用当前 idle trace completion；
   - 不提前实施 reliability WS3 的 versioned terminal/recovery 语义。
8. abort 后所有 callback 必须检查旧 signal，不能写入 session、message、trace 或 streaming state。
9. Controller 最终只保留：
   - chat mode；
   - trace/citation 状态与 callback；
   - default KB resolver；
   - 三个子 hook 的组合；
   - select/start-new/identity-reset 的跨 hook 协调。

### 6.4 测试要求

将 transport-focused 场景放入 `use-chat-stream.test.tsx`，同时保留 facade 回归测试：

- 新 send abort 上一个 signal；
- abort 后 done/error callback 不提交状态；
- meta、chunk、step、done、error 正确调用 session/trace actions；
- normal、rag、web_rag 使用正确 KB 参数；
- repo_check early return 行为保持；
- retry cache hit 复用 ID；
- cache miss 从消息历史恢复 query；
- TTL 过期后不错误复用；
- start new、身份 reset 和 unmount 清理流与 cache。

现有 `streams/chat-stream.test.ts` 继续负责协议 parser、truncated stream、parse error 和 abort 事件，不把相同 parser 测试复制到 hook。

### 6.5 验收标准

- [x] `useChatController` 不再持有 AbortController、retry cache、streaming state 或 send/retry 主路径。
- [x] 新查询、新建聊天、身份失效和 unmount 都能 abort 对应流。
- [x] abort 后旧 callback 不修改任何新状态。
- [x] retry ID、TTL、消息删除和 fallback 行为保持不变。
- [x] normal、rag、web_rag、repo_check 四种模式通过回归测试。
- [x] `use-chat-controller.ts` 不超过 250 行，三个新 hook 均不超过 400 行。
- [x] `UseChatControllerReturn` 和 Chat 页面调用不变。
- [x] focused tests、`make frontend-e2e-mock` 和 `make frontend-check` 通过。

### 6.6 明确不做

- 不抽取 `useChatTrace`；trace 保留在 facade 是本轮停手选择。
- 不修改 SSE parser 或引入 async iterator。
- 不实现新 retry attempt、terminal event、断线恢复或取消协议。
- 不进行 mode 策略模式、消息状态机或 Chat store 重写。

## 7. 阶段二完成门

PR4–PR6 全部满足各自验收标准后，从仓库根目录运行：

```bash
make frontend-test-coverage
make frontend-check-full
```

完成条件：

- [x] Knowledge task polling、session state、SSE/retry 分属独立 hook。
- [x] Controller facade 不直接承担上传轮询、session Query 或 stream 生命周期。
- [x] 页面不新增 API、Query 或 stream 编排逻辑。
- [x] `UseChatControllerReturn` 与现有 UI 行为兼容，只有计划已声明的 120 秒超时边界例外。
- [x] line budget 达标且没有为压行数制造无语义碎片。
- [x] coverage floor、lint、typecheck、unit、build、bundle 和 mock e2e 全部通过。

完成记录（2026-07-16）：

- `make frontend-test-coverage` 通过：38 个测试文件、310 个测试；Statements 59.2%，Lines 60.14%。
- `make frontend-check-full` 通过：lint、typecheck、unit、build、bundle check 与 11 个 mock e2e 全部通过。
- 行数完成门通过：controller 234/250、stream 355/400、session 115/400、ingestion 368/400。

Checkpoint（closed）：`frontend-chat-controller-decomposition-validated`。

## 8. 与其他计划的依赖

### Chat / RAG / Worker reliability

- 后端 WS1/WS2 的 schema、repository 和 worker 工作可独立推进。
- 涉及前端 retry identity 的 WS1 修改必须在 PR6 后落到 `useChatStream`。
- 涉及 versioned terminal、断线恢复和 step 终态的 WS3 修改必须在 PR6 后实施。
- 如果可靠性修复必须紧急先行，暂停 PR4–PR6，在行为修复合并后重新建立 characterization baseline，不能同时改行为和搬代码。

### Knowledge ingestion consistency

- 后端 P0/P1 可与阶段一并行。
- PR4 只消费当前 `completed/failed` contract；新增 canceled、lease、retry 或 reindex 状态另开行为 PR。
- 后端若在 PR4 前改变 task response schema，先完成兼容适配和 contract tests，再开始 hook 抽取。

## 9. 回滚与最终停手点

- 每个 PR 只移动一个变化轴；回滚时恢复 facade 内对应逻辑，不跨 PR 回滚其他 hook。
- PR4 回滚不能删除阶段一 Knowledge keys/hooks；它们已被 KBFilesModal 使用，并且回滚 polling 时要同时恢复原 120 次尝试的超时语义。
- PR5 是 PR6 的依赖；若回滚 PR5，必须同时回滚尚未合并的 PR6 分支。
- PR6 和阶段二完成门通过后，本轮结构治理结束。
- 后续 i18n、Auth feature 对齐、RepoAnalysisCard UI 深拆、MessageList/Credits 拆分和聊天状态机均另行评估，不作为本计划“顺手收尾”。
