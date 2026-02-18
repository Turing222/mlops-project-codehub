# ==========================================
# Stage 1: Builder (构建阶段)
# ==========================================
FROM python:3.11-slim AS builder

# 安装 uv (利用官方镜像中的二进制文件)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/

WORKDIR /app

# 环境变量：禁止字节码生成干扰缓存，设置虚拟环境位置
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
#指定虚拟环境路径
ENV UV_PROJECT_ENVIRONMENT=/app/.venv

# 1. 复制依赖描述文件
COPY pyproject.toml uv.lock ./

# 2. 安装依赖（利用 Docker 缓存挂载提升速度）
# --frozen 确保严格执行 uv.lock
# --no-dev 排除开发依赖，只保留生产环境必需包
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

#验证安装结果（可选）
RUN uv run --no-dev python -c "import openai; print('✅ Verified')"
# 3. 复制源码并完成安装
# Copy the rest of the code
# 1. 复制 Alembic 配置文件
COPY alembic.ini .

# 2. 复制包含 env.py 和 versions 的文件夹
# 确保文件夹名字对应：宿主机的 alembic/ 复制到容器的 alembic/
COPY alembic/ ./alembic/

# 3. 复制后端源码
COPY backend/ ./backend/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev 

RUN uv run --no-dev python -c "import openai; print('✅ OpenAI is ready')"


# ==========================================
# Stage 2: Final (运行阶段)
# ==========================================
FROM python:3.11-slim

WORKDIR /app

# 关键：从 builder 阶段只拷贝最终的虚拟环境
# 这样镜像里就不会包含 uv 及其缓存，也不会包含 build-essential 等编译工具
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app /app

# 将虚拟环境的 bin 目录加入 PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
#迁移代码
COPY alembic/ ./alembic/
COPY alembic.ini .
COPY backend/ ./backend/
#验证安装 (构建时报错能提早发现问题)
RUN /app/.venv/bin/python -c "import openai; print('Stage 2 OpenAI package found')"

# 启动 (建议先跑迁移，再起服务)
# 3. --proxy-headers 如果你前面有 Nginx 或负载均衡器，必须开启
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
#CMD ["/app/.venv/bin/uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
# Expose the port
EXPOSE 8000
#启动



