# Frontend API Standard

## 目标

- 页面不直接发裸请求。
- API payload 和 response 都有稳定边界。
- 请求 trace、错误归一化和幂等策略由公共层统一处理。

## 目录约定

```text
src/
  api/
    auth.ts
    users.ts
    chat.ts
  schemas/
    auth.ts
    user.ts
    chat.ts
  lib/http/
    client.ts
    errors.ts
    trace.ts
    idempotency.ts
```

## 新增 API 的默认步骤

1. 在 `src/schemas/*` 定义 request / response schema。
2. 从 schema 推导 TypeScript 类型，避免重复 DTO。
3. 在 `src/api/*` 新增薄封装，只负责 endpoint、payload parse、response parse。
4. 页面或 feature 只调用 `api`、`query`、`mutation`、`stream client`，不直接调用 `axios`。
5. 为关键边界补 schema parse 或 request helper 测试。

## HTTP 请求

- 普通 HTTP 请求统一走 `src/lib/http/client.ts`。
- 请求必须自动带 `X-Request-ID`。
- 有 token 时必须自动带 `Authorization: Bearer <token>`。
- 401 / 403 由公共层触发认证清理。

## 错误处理

- 公共层输出统一错误形状。
- 页面只消费稳定字段，例如 `code`、`message`、`status`、`requestId`。
- 页面不解析后端原始错误结构，除非该结构已经被 schema 固化。

## 幂等策略

必须考虑幂等 key 的请求：

- 流式聊天。
- 创建任务。
- 文件上传 / 批量导入。
- 用户可能重复点击的长耗时 mutation。

默认规则：

- `GET` 可自动 retry。
- 普通 `POST` 默认不自动 retry。
- 带 `X-Idempotency-Key` 或 `client_request_id` 的 mutation 才允许按策略 retry。

## TODO

- 明确上传接口是否统一写入 `X-Idempotency-Key`。
- 明确 429 / 5xx 的前端 retry 次数和退避参数。
- 补充 API 文件模板。
