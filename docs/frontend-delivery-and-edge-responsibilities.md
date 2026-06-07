# Frontend 交付与 Edge 职责边界

本文档用于说明 Dewflow 前端从容器内 Nginx 入口迁移到 **Cloudflare Pages + 独立 API origin** 后，各层分别负责什么，避免继续把已删除的 legacy edge nginx 配置当成当前生产入口参考。

## 推荐上线拓扑

- Frontend：`https://app.<domain>`（Cloudflare Pages）
- API：`https://api.<domain>`（AWS / 自托管入口）
- API path：继续保持 `/api/v1/...`

## 责任划分

### Cloudflare Pages / Cloudflare edge

负责：

- 前端静态资源托管
- TLS / HTTPS
- 域名接入
- SPA fallback（`public/_redirects`）
- 基础安全头（`public/_headers`）
- 静态资源缓存策略（`public/_headers`）
- 静态 `healthz` 探活文件（如启用）

不负责：

- API `/api/v1/...` 反代主路径
- LLM / SSE 流式代理优化
- API timeout / anti-buffering 策略
- API request tracing / 访问日志

### AWS / 自托管 API 入口

负责：

- `https://api.<domain>/api/v1/...` 暴露
- CORS allowlist（`BACKEND_CORS_ORIGINS`）
- Google OAuth callback allowlist（`GOOGLE_ALLOWED_REDIRECT_URIS`）
- telemetry origin 校验依赖的同源 / allowlist 规则
- streaming / SSE 兼容
- 长 timeout、禁止错误缓冲 / 缓存
- API request tracing / 访问日志

### 仓库中的 frontend 容器 nginx

对应文件：

- `frontend/apps/admin/nginx.conf`
- `frontend/apps/admin/Dockerfile`

当前仍保留的用途：

- 本地 Compose 演练
- 生产镜像验证
- Cloudflare Pages 回滚时的 fallback

它不再代表 Cloudflare Pages 正式公网入口的 source of truth。

## 已从旧 edge nginx 迁移出去的职责

适合迁移到 Pages 的：

- 静态资源托管
- SPA fallback
- 基础安全头
- 静态缓存
- TLS / HTTPS / HSTS（由 Cloudflare edge 负责）

适合迁移到 API 入口层的：

- `/api` 对后端的公网暴露
- LLM / SSE 流式代理优化
- 长 timeout
- anti-buffering / anti-cache
- request tracing / access logs

## 当前代码层面的配合约定

- 前端 API endpoint path 常量仍集中在 `frontend/apps/admin/src/api/urls.ts`
- 生产 Pages 构建时必须通过 `VITE_API_BASE_URL` 指向 API origin
- 若 `VITE_API_BASE_URL` 未设置，前端退回当前同源路径行为，便于本地 / Compose fallback

## 上线前最少检查项

1. Pages 构建时设置 `VITE_API_BASE_URL=https://api.<domain>`
2. 后端设置 `BACKEND_CORS_ORIGINS=https://app.<domain>`
3. 若启用 Google OAuth，后端设置 `GOOGLE_ALLOWED_REDIRECT_URIS=https://app.<domain>/auth/google/callback`
4. 验证 `POST /api/v1/telemetry/errors` 在 Pages origin 下不返回 403
5. 验证 `/api/v1/chat/query_stream` 在公网 API 路径下保持增量流式输出
