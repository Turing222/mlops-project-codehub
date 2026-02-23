---
description: 项目环境使用与服务验证规范
---

# 项目环境使用与服务验证规范

为了确保在 MLOps 项目开发过程中环境的一致性以及验证的准确性，请遵循以下规则：

### 1. Python 环境与命令执行
- **强制使用 uv**: 本项目使用 `uv` 管理依赖。在执行任何 Python 脚本、测试或 Python 相关工具（如 alembic）时，必须前缀 `uv run`。
- **虚拟环境**: 不要尝试手动 `source .venv/bin/activate`。`uv run` 会自动处理环境。
- **示例**:
  ```bash
  // turbo
  uv run python main.py
  uv run pytest
  uv run alembic upgrade head
  ```

### 2. 服务可用性验证 (Service Verification)
- **禁止使用浏览器访问 localhost**: 由于网络隔离，Agent 自带的浏览器工具无法直接访问宿主机的 `localhost` 或 `127.0.0.1`。
- **使用 curl 命令**: 验证服务状态时，请使用 `curl`。
- **验证流程**:
  1. 确认容器状态：`docker compose ps`
  2. 执行健康检查：`curl -s -f http://localhost:8000/api/v1/health_check/live` (根据实际端口调整)
  3. 查看错误日志：如果 curl 失败，立即检查相关服务的日志：`docker compose logs --tail=50 [service_name]`

### 3. 配置审查
- **资源限制**: 修改 `docker-compose.yml` 时，确保所有新增或修改的服务都包含 `deploy.resources.limits` 和 `reservations` 配置。
- **安全头**: 确保 Nginx 配置中包含 `X-Content-Type-Options`, `X-Frame-Options` 等安全响应头。
