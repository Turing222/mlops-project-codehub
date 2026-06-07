# Admin Frontend

当前前端只保留 `apps/admin` 这一个应用，负责聊天主页和管理员入口。

## 文档

- [前端文档索引](../../docs/README.md)
- [架构约定](../../docs/architecture.md)
- [逐步改造计划](../../docs/migration-plan.md)

## 常用命令

在仓库根目录执行：

```bash
make frontend-lint
make frontend-typecheck
make frontend-test
make frontend-build
make frontend-e2e-mock
make frontend-check
```

如果只想在前端目录里跑：

```bash
pnpm --dir frontend --filter admin lint
pnpm --dir frontend --filter admin typecheck
pnpm --dir frontend --filter admin test
pnpm --dir frontend --filter admin build
pnpm --dir frontend --filter admin test:e2e:mock
pnpm --dir frontend --filter admin dev
```

真实后端 smoke e2e 需要先启动后端，并提供测试账号：

```bash
E2E_SMOKE_USER=... E2E_SMOKE_PASS=... make frontend-e2e-smoke
```

## 测试范围

- `Vitest + jsdom + Testing Library`
- 路由级 smoke test
- Playwright mock e2e
- 真实后端 smoke e2e（手动触发）
- API 路径和流式请求的基础测试

这一步先保证最基础的前端验证链路可跑，再继续做镜像和 CI 拆分。

## 生产构建、Pages 部署与容器 fallback

### 1. 本地开发
本地开发及热更新请使用 Vite dev server：
```bash
pnpm --dir frontend --filter admin dev
```

默认情况下，本地开发仍通过 Vite dev server 的 `/api` proxy 对接 `http://127.0.0.1:8000`。
如果你想提前模拟 Cloudflare Pages 的 split-origin 生产形态，可以显式设置：

```bash
VITE_API_BASE_URL=http://127.0.0.1:8000 pnpm --dir frontend --filter admin dev
```

### 2. Cloudflare Pages 生产路径
当前推荐的正式前端上线形态是：

- Frontend：Cloudflare Pages（例如 `https://app.<domain>`）
- API：独立 AWS / 自托管入口（例如 `https://api.<domain>`）
- 前端通过 `VITE_API_BASE_URL` 指向 API origin，API path 保持 `/api/v1/...`

Pages 生产部署前至少确认：

1. 构建时设置 `VITE_API_BASE_URL=https://api.<domain>`
2. `public/_redirects` 已提供 SPA fallback
3. `public/_headers` 已提供基础安全头与静态缓存策略
4. `pnpm --dir frontend --filter admin build` 会在 `dist/_headers` 生成真实 `Content-Security-Policy-Report-Only` header；Cloudflare Pages 环境下缺少 `VITE_API_BASE_URL` 会直接失败
5. 后端已设置 `BACKEND_CORS_ORIGINS=https://app.<domain>`
6. 若启用 Google OAuth，后端已设置 `GOOGLE_ALLOWED_REDIRECT_URIS=https://app.<domain>/auth/google/callback`

### 3. 前端生产镜像构建（fallback / 演练）
使用根目录的 `Makefile` 构建前端生产 Docker 镜像（支持多阶段构建和 pnpm store 缓存）：
```bash
# 仅构建前端生产镜像
make frontend-image-build

# 构建所有镜像（后端 + 前端）
make image-build-all
```

`frontend/apps/admin/nginx.conf` 仍然用于：

- 本地 Compose 演练
- 生产镜像验证
- Cloudflare Pages 回滚时的容器前端 fallback

它不再代表 Cloudflare Pages 正式公网入口的 source of truth。

### 4. Docker Compose 生产环境验证
在本地以生产近似环境拉起并验证前端镜像。`deploy/docker-compose.yml` 使用已构建镜像，不会自动 build，因此启动 `frontend` 前必须先执行镜像构建：
```bash
# 1. 构建前端镜像
make frontend-image-build

# 2. 启动 Compose 堆栈中的 frontend 和 api 服务
docker compose --env-file .env -f deploy/docker-compose.yml up -d frontend api

# 3. 验证前端容器健康检查
curl -fsS http://127.0.0.1:80/healthz

# 4. 验证前端静态页面可访问
curl -fsSI http://127.0.0.1:80/

# 5. 验证 API 代理接口联通性
curl -fsS http://127.0.0.1:80/api/v1/health_check/live
```
当使用生产镜像时，前端页面已完全内置于容器中，不再需要依赖本地 `dist` 目录挂载。
