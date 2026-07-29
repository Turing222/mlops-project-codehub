# 首次生产部署 Checklist

面向 **已开好 EC2/RDS/S3**、采用 **Cloudflare Pages + Tunnel + EC2 API** 的 split-origin 形态。

配套文件：

- 域名三根线模板：[domains.env.example](domains.env.example)
- Tunnel 配置：[cloudflare/README.md](cloudflare/README.md)
- EC2 应用栈详解：[docs/platform/deploy-ec2.md](../docs/platform/deploy-ec2.md)
- 编排脚本：`bash scripts/deploy/bootstrap-prod.sh`（或 `make deploy-bootstrap-prod`）

**里程碑验收**：Phase 5 的 `make verify-pages` 全部通过。

---

## Phase 0 — 机器与 AWS 前置（EC2）

| # | 检查项 | 命令 / 操作 | 通过标准 |
|---|--------|-------------|----------|
| 0.1 | Docker | `docker --version` | 有输出 |
| 0.2 | Compose 插件 | `docker compose version` | 有输出 |
| 0.3 | 拉镜像 | `docker pull <WEB 镜像>` | 成功 |
| 0.4 | RDS 连通 | 安全组 EC2 → RDS `5432` | 规则存在 |
| 0.5 | S3 | `aws s3 ls s3://<bucket>` | 成功 |
| 0.6 | AWS 身份 | `aws sts get-caller-identity` | 有 ARN |
| 0.7 | 8081 不暴露公网 | 安全组 / `ss -lntp` | 无 `0.0.0.0:8081` |

---

## Phase 1 — EC2 配置文件（不进 Git）

| # | 检查项 | 操作 | 通过标准 |
|---|--------|------|----------|
| 1.1 | env 文件 | `cp deploy/.env.ec2.template deploy/.env.ec2` | 文件存在 |
| 1.2 | 镜像 tag | `make release-image-env IMAGE_TAG="$(git describe --tags --always --abbrev=12)"` | 写入 `DOCKER_IMAGE_NAME_*` |
| 1.3 | RDS | `POSTGRES_SERVER` 为主机名，`POSTGRES_SSL_MODE=verify-full` | 非 IP、非 `change-me` |
| 1.4 | S3 | `STORAGE_BACKEND=s3`、bucket/region | 非占位符 |
| 1.5 | 本机 API URL | `DEPLOY_BASE_URL=http://127.0.0.1:8081` | 先本机验证 |
| 1.6 | Secrets | files: `make deploy-ec2-secrets-prepare`; aws: `make deploy-secrets-materialize` | 必填 secret 非空 |
| 1.7 | RDS 密码 | `$DEPLOY_SECRET_DIR/postgres_password.txt` | 与 RDS 一致且不输出值 |
| 1.8 | api-nginx | `API_NGINX_BIND=127.0.0.1` | 与模板一致 |

Pages 域名确定前**先不要**填 `BACKEND_CORS_ORIGINS`。

---

## Phase 2 — 启动应用栈（EC2）

```bash
make deploy-bootstrap-prod ARGS="ec2-stack"
# 或分步：
# make deploy-ec2-secrets-prepare deploy-cloudwatch-setup deploy-ec2-check deploy-ec2-up deploy-ec2-wait
```

| # | 检查项 | 命令 | 通过标准 |
|---|--------|------|----------|
| 2.1 | 预检 | `make deploy-ec2-check` | exit 0 |
| 2.2 | 容器 | `docker compose --env-file deploy/.env.ec2 -f deploy/docker-compose.yml ps` | 核心服务 running |
| 2.3 | live | `curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8081/api/v1/health_check/live` | `200` |
| 2.4 | db_ready | 同上路径 `/api/v1/health_check/db_ready` | `200` |
| 2.5 | smoke（可选） | `make deploy-bootstrap-prod ARGS="ec2-stack --verify"` | exit 0（需 `uv`） |

失败：`make deploy-ec2-logs`

---

## Phase 3 — Cloudflare Tunnel

按 [cloudflare/README.md](cloudflare/README.md) 配置。摘要：

| # | 检查项 | 通过标准 |
|---|--------|----------|
| 3.1 | Tunnel 存在 | `cloudflared tunnel list` 或 Dashboard 可见 |
| 3.2 | Ingress | `api.<domain>` → `http://127.0.0.1:8081` |
| 3.3 | DNS | `api.<domain>` 解析到 Cloudflare |
| 3.4 | 公网 live | `curl https://api.<domain>/api/v1/health_check/live` → `200` |
| 3.5 | 公网 db_ready | 同上 `/api/v1/health_check/db_ready` → `200` |

通过后更新 `deploy/.env.ec2`：

```dotenv
DEPLOY_BASE_URL=https://api.<domain>
```

再执行 `make deploy-ec2-wait`。

---

## Phase 4 — Cloudflare Pages + 三根线

对照 [domains.env.example](domains.env.example) 传播变量。

后端 **只放行 `BACKEND_CORS_ORIGINS` 里显式列出的 origin**。Pages Preview 若配置了与 Production 相同的 `VITE_API_BASE_URL`，却未把 Preview 域名加入 CORS，浏览器请求会被拦截。

先选一种 Preview 策略，再填表：

| 策略 | Pages Preview `VITE_API_BASE_URL` | `BACKEND_CORS_ORIGINS`（生产 EC2） | 适用场景 |
|------|-----------------------------------|-------------------------------------|----------|
| **A — Preview 联调生产 API** | `https://api.<domain>`（与 Production 相同） | `https://app.<domain>,https://<branch>.<project>.pages.dev`（列出实际会用到的 Preview origin） | PR 预览要在生产 API 上测登录/聊天 |
| **B — Preview 不连生产 API** | 独立 staging API，例如 `https://api.staging.<domain>`；或仅 Production 设生产 API、Preview 不设（**Preview 构建会因缺少 `VITE_API_BASE_URL` 失败**，故通常 Preview 也要设 staging URL） | 仅 `https://app.<domain>`（生产 API 不放 `pages.dev`） | Preview 只看 UI，或 Preview 指向独立 staging 栈 |

> Cloudflare Pages 在 `CF_PAGES=1` 下构建时 **缺少 `VITE_API_BASE_URL` 会直接失败**（CSP `_headers` 生成）。因此「Preview 环境变量留空」不是可行选项；若不想 Preview 打生产 API，应给 Preview 单独的 API origin（策略 B），而不是省略变量。

| # | 位置 | 变量 | 值 |
|---|------|------|-----|
| 4.1 | Pages **Production** | `VITE_API_BASE_URL` | `https://api.<domain>` |
| 4.1b | Pages **Preview** | `VITE_API_BASE_URL` | 按上表策略 A 或 B |
| 4.2 | Pages | 自定义域名 | `app.<domain>`（Production） |
| 4.3 | `deploy/.env.ec2` | `DEPLOY_FRONTEND_BASE_URL` | `https://app.<domain>` |
| 4.4 | `deploy/.env.ec2` | `BACKEND_CORS_ORIGINS` | 策略 A：生产 + 用到的 Preview origin；策略 B：仅 `https://app.<domain>` |
| 4.5 | EC2 | `make deploy-ec2-up` | CORS 生效 |
| 4.6 | Git | merge `main` 或触发 Pages 部署 | Production（及需验证的 Preview）成功 |

策略 A 可选自测（将 `PREVIEW_ORIGIN` 换成实际 Preview URL）：

```bash
curl -sSI -X OPTIONS \
  -H "Origin: ${PREVIEW_ORIGIN}" \
  -H "Access-Control-Request-Method: POST" \
  "https://api.<domain>/api/v1/telemetry/errors" \
  | grep -i access-control-allow-origin
```

应返回 Preview 的 origin，而不是空或 403。

Pages 构建配置（source of truth 仍见 `deploy-ec2.md`）：

```text
Root directory: frontend
Build command: pnpm install --frozen-lockfile && pnpm --filter admin build
Build output: apps/admin/dist
```

---

## Phase 5 — 全链路验收（任意能 curl 的机器）

```bash
make verify-pages \
  DEPLOY_FRONTEND_BASE_URL=https://app.<domain> \
  DEPLOY_BASE_URL=https://api.<domain>
```

| # | 检查项 | 通过标准 |
|---|--------|----------|
| 5.1 | Frontend `/healthz` | 200 |
| 5.2 | Frontend `/` | 200 |
| 5.3 | CSP + 安全头 | report-uri 指向 API `/api/v1/csp/reports` |
| 5.4 | API liveness | 200 |
| 5.5 | CORS preflight | `Access-Control-Allow-Origin` = 前端 origin |
| 5.6 | Telemetry origin | POST → `422`（或 `204` 带 WARN） |
| 5.7 | CSP report sink | POST → `422`（或 `204` 带 WARN） |

**7/7 通过 = split-origin 部署完成。**

---

## Phase 6 — GitHub 门禁（本机，需 `gh`）

```bash
BOOTSTRAP_DEPLOY_FRONTEND_BASE_URL=https://app.<domain> \
BOOTSTRAP_DEPLOY_BASE_URL=https://api.<domain> \
make deploy-bootstrap-prod ARGS=github-gate

APPLY_BRANCH_PROTECTION=true make deploy-bootstrap-prod ARGS=github-gate
```

| # | 检查项 | 通过标准 |
|---|--------|----------|
| 6.1 | Variables | `DEPLOY_*` 已设置 |
| 6.2 | Branch protection | `main` required checks 与 `scripts/ci/required_status_checks.txt` 一致 |
| 6.3 | PAT（一次性 Web） | `BRANCH_PROTECTION_READ_TOKEN` 已创建 |

---

## Phase 7 — 仅人工

| # | 项 |
|---|-----|
| 7.1 | 登录 / 注册真实走一遍 |
| 7.2 | SSE 流式聊天（需登录态） |
| 7.3 | Google OAuth（仅启用时） |

---

## 推荐顺序

```text
Phase 0 → 1 → 2（本机 API 200）
    → 3（公网 API 200）
    → 4（Pages + CORS）
    → 5 verify-pages 全绿  ← 里程碑
    → 6 GitHub gate
    → 7 人工冒烟
```
