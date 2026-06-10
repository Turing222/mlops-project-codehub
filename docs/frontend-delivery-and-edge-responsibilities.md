# Frontend 交付与 Edge 职责边界

本文档用于说明 Dewflow 前端从容器内 Nginx 入口迁移到 **Cloudflare Pages + 独立 API origin** 后，各层分别负责什么，避免继续把已删除的 legacy edge nginx 配置当成当前生产入口参考。

## 推荐上线拓扑

- Frontend：`https://app.<domain>`（Cloudflare Pages）
- API：`https://api.<domain>`（AWS / 自托管入口）
- API path：继续保持 `/api/v1/...`
- EC2 本机 API edge：`api-nginx` 绑定 `127.0.0.1:8081`，Cloudflare Tunnel 指向 `http://127.0.0.1:8081`

## 责任划分

### Cloudflare Pages / Cloudflare edge

负责：

- 前端静态资源托管
- TLS / HTTPS
- 域名接入
- SPA fallback（`public/_redirects`）
- 基础安全头（`public/_headers`）
- CSP report-only header（构建后生成到 `dist/_headers`，不在仓库默认 `_headers` 写无效占位符）
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
- CSP report-only sink：`POST /api/v1/csp/reports`
- streaming / SSE 兼容
- 长 timeout、禁止错误缓冲 / 缓存
- API request tracing / 访问日志
- 将 Cloudflare Tunnel 的 `CF-Connecting-IP` 规范化为后端可信的 `X-Real-IP`

### 仓库中的 frontend 容器 nginx

对应文件：

- `frontend/apps/admin/nginx.conf`
- `frontend/apps/admin/Dockerfile`

当前仍保留的用途：

- 本地 Compose 演练
- 生产镜像验证
- Cloudflare Pages 回滚时的 fallback

它不再代表 Cloudflare Pages 正式公网入口的 source of truth，并且在 EC2 Compose 中只通过 `frontend-fallback` profile 启动。

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
- true client IP 规范化

## 当前代码层面的配合约定

- 前端 API endpoint path 常量仍集中在 `frontend/apps/admin/src/api/urls.ts`
- 生产 Pages 构建时必须通过 `VITE_API_BASE_URL` 指向 API origin
- 若 `VITE_API_BASE_URL` 未设置，前端退回当前同源路径行为，便于本地 / Compose fallback
- 正式 EC2 API 入口是 `deploy/nginx/api.conf` 对应的 `api-nginx` 服务；它代理 `/api/` 时不剥离 `/api` 前缀。
- Cloudflare Pages 的 CSP report-only header 不在仓库默认 `_headers` 中启用；`pnpm --dir frontend --filter admin build` 会根据 `VITE_API_BASE_URL` 生成 `dist/_headers`，写入真实 `report-uri https://api.<domain>/api/v1/csp/reports`，并校验产物中不存在占位符。
- Cloudflare Pages 环境下如果缺少 `VITE_API_BASE_URL`，构建会失败，避免生产静默漏启 CSP report-only。
- CSP 当前只使用 `Content-Security-Policy-Report-Only`：违规报告只写 `event=csp_violation` 结构化日志，不阻断页面资源，也不直接触发告警。
- Compose fallback 使用 `frontend/apps/admin/nginx.conf` 中的相对 `report-uri /api/v1/csp/reports`，依赖同一 nginx `/api/` 反代到后端。

## 上线前最少检查项

1. Pages 构建时设置 `VITE_API_BASE_URL=https://api.<domain>`
2. Cloudflare Tunnel public hostname `api.<domain>` 指向 `http://127.0.0.1:8081`
3. 后端设置 `BACKEND_CORS_ORIGINS=https://app.<domain>`
4. 若启用 Google OAuth，后端设置 `GOOGLE_ALLOWED_REDIRECT_URIS=https://app.<domain>/auth/google/callback`
5. 运行 Pages build 后检查 `dist/_headers` 已包含 `Content-Security-Policy-Report-Only`，且 `report-uri` 指向真实 `https://api.<domain>/api/v1/csp/reports`
6. 验证 `POST /api/v1/telemetry/errors` 在 Pages origin 下不返回 403
7. 验证 `POST /api/v1/csp/reports` 在 Pages origin 下返回 204
8. 验证 `/api/v1/chat/query_stream` 在公网 API 路径下保持增量流式输出

除第 4 项（仅启用 Google OAuth 时手动确认）和第 8 项（需要登录会话）外，以上检查已脚本化：

```bash
make verify-pages \
  DEPLOY_FRONTEND_BASE_URL=https://app.<domain> \
  DEPLOY_BASE_URL=https://api.<domain>
```

脚本对 telemetry / CSP report 端点提交故意无效的 `{}` 请求体：返回 422 即证明 origin 守卫放行（403 表示 allowlist 缺失），且不会产生伪造的 telemetry / CSP 日志事件。若返回 204，说明端点接受了空请求体——origin 仍判定为放行，但可能已记录一条空事件，脚本会输出 WARN 提示检查后端校验。
