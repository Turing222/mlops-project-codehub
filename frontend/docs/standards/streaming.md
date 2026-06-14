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
- retry cache。
- abort controller。
- mutation 完成后的 query invalidation。

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
- 明确失败消息和 retry cache 的过期策略。
