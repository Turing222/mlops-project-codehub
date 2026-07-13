# 本地生产形态演练

smoke 通过后，可以在部署 EC2 前验证 production compose、secret 注入、frontend fallback、worker、migration 和 S3 形态。

## 执行命令

```bash
make deploy-local-prod-secrets-prepare
make deploy-local-prod-check
make deploy-local-prod-up
make deploy-local-prod-wait
make deploy-local-prod-verify
```

## 编排边界

这套命令会：

- 使用 `deploy/.env.local-prod.template`，不要复用带 RDS 占位符的 `deploy/.env.ec2.template`。
- 以 `deploy/docker-compose.yml` 为主体。
- 叠加 `deploy/docker-compose.local-postgres.yml`，提供 PostgreSQL fallback。
- 叠加 `deploy/docker-compose.local-s3.yml`，使用 MinIO 模拟 S3。
- 叠加 `deploy/docker-compose.local-logging.yml`，把 CloudWatch Logs 降级为本机 `json-file`。
- 使用 `secrets/local-prod`，不复用 `secrets/ec2` 的真实部署 secret。
- 启用 `frontend-fallback` profile，并将 frontend 暴露到 `http://localhost:8080`。
- 不拉入 `docker-compose.db.yml` 中的 Tempo 或 smoke-only 组件。

## 日志与清理

```bash
make deploy-local-prod-logs
make deploy-local-prod-logs ARGS="api"
make deploy-local-prod-down
```

正式部署顺序和远端验证见 [deploy-ec2.md](deploy-ec2.md)。
