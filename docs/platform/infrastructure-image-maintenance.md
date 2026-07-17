# 基础设施镜像维护

仓库对生产、fallback 和 CI 使用的基础设施镜像显式钉版。升级时应同步修改所有使用位置，并按普通部署变更验证。

## Nginx

仓库内 nginx 仅用于反向代理和静态 SPA fallback，不使用 `rewrite`、njs 或 HTTP/3 模块。`api-nginx` 与 frontend fallback runtime 共用同一 tag。

| 用途 | 镜像 tag | 定义位置 |
| --- | --- | --- |
| EC2 API edge (`api-nginx`) | `nginx:1.30.1-alpine` | `deploy/docker-compose.yml` |
| frontend fallback runtime | `nginx:1.30.1-alpine` | `frontend/apps/admin/Dockerfile` |
| CI `nginx -t` 校验 | `nginx:1.30.1-alpine` | `.github/workflows/deploy-validate-ci.yml` |

收到 nginx OSS 或 F5 安全公告时，先核对配置是否触发 exploit 条件，再升级到修复版。依次运行 `nginx -t`、frontend image build 和 `make deploy-ec2-check`；只有启用 `frontend-fallback` profile 时才需要更新 `DOCKER_IMAGE_NAME_FRONTEND`。

## Redis、PostgreSQL 与 MinIO

| 组件 | 镜像 tag | 定义位置 |
| --- | --- | --- |
| Redis cache / TaskIQ（生产 / 本地 / CI） | `redis:7.4.9-alpine` | `deploy/docker-compose.yml`, `docker-compose.db.yml`, `deploy/k8s/local-scaling/redis.yaml`, CI workflows |
| pgvector + PostgreSQL 17（本地 / CI） | `pgvector/pgvector:0.8.2-pg17-bookworm` | `docker-compose.db.yml`, `deploy/docker-compose.local-postgres.yml`, CI workflows |
| MinIO（本地 smoke / 演练） | `quay.io/minio/minio:RELEASE.2025-04-22T22-12-26Z` | `docker-compose.db.yml`, `deploy/docker-compose.local-s3.yml` |
| MinIO client | `quay.io/minio/mc:RELEASE.2025-04-16T18-13-26Z` | `docker-compose.db.yml`, `deploy/docker-compose.local-s3.yml` |

生产数据库默认走 RDS；pgvector 镜像只用于本地 fallback 与 CI。升级 Redis、pgvector 或 MinIO 时，保持 compose、CI service 与表格同步。

## 季度核查

Dependabot 的 `docker` ecosystem 主要覆盖 Dockerfile，不会完整跟踪 compose 中的镜像。当前每季度至少检查：

- `deploy/docker-compose.yml`
- `deploy/docker-compose.local-postgres.yml`
- `deploy/docker-compose.local-s3.yml`
- `deploy/docker-compose.local-logging.yml`
- `docker-compose.db.yml`
- `.github/workflows/*.yml` 中的 service image

```bash
rg -n "image:" deploy docker-compose*.yml .github/workflows | sort
```

对每个镜像记录当前 tag、最新兼容 tag、相关 CVE 或 release note，以及是否需要 PR。发现安全修复或兼容 patch 时，运行 `make deploy-ec2-check` 和 [本地生产形态演练](local-production-rehearsal.md)。
