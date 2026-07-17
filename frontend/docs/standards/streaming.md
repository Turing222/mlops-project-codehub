# Frontend Streaming Standard

## 目标

- 聊天 SSE / chunk 流式请求不散落在页面组件中。
- 页面只负责 UI 编排，流式协议解析集中管理。
- retry、abort、trace 和幂等策略可复用。

## 推荐边界

```text
src/
  streams/
    chat-stream.ts
  features/
    chat/
      use-chat-controller.ts
  pages/
    Chat/
      index.tsx
```

`streams/chat-stream.ts` 负责：

- 发起原生 `fetch`。
- 注入 token、request id、idempotency key。
- 读取 `ReadableStream`。
- 解析 SSE `data:` 事件。
- 用 Zod 校验 stream event。
- 把 `meta`、`chunk`、`error`、`done` 事件交给调用方。

`features/chat/use-chat-controller.ts` 负责：

- 当前会话状态。
- 消息列表状态。
- streaming text。
- 服务端 generation request 身份与显式 retry 编排。
- abort controller。
- mutation 完成后的 query invalidation。

失败重试必须使用后端返回的 `generation_request_id`、`attempt` 和
`retryable=true` 发起显式 retry。缺少任一字段时按不可重试处理；不得复用本地
`client_request_id` 猜测服务端状态，也不得在历史缓存缺失时生成新 ID 盲目重发。
pre-meta 传输错误只能先按原 `client_request_id` 解析服务端 request，解析失败时
保持 fail-closed。

`pages/Chat/index.tsx` 负责：

- 页面布局。
- 用户菜单。
- 把 controller 状态传给 `Sidebar` 和 `MessageList`。

## 非目标

- 不把主聊天流强行放进 `TanStack Query`。
- 不在页面组件里直接解析 SSE chunk。
- 不在多个页面里复制 stream parser。

## TODO

- 确定 stream client API 形状：callback、async iterator，或二者都支持。
- 明确 abort 后 UI 如何展示。
- 明确 generation request 状态轮询和 T1-4 自动恢复的交互策略。
