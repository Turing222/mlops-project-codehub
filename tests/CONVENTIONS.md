# Test Conventions

这份文档定义新增和迁移测试时的第一版标准。目标是让测试分层清楚、运行稳定、失败信息容易定位。

## 基本原则

- 测试先按层级归类，再按被测模块归档。
- 单元测试默认快速、确定、无真实外部依赖。
- 组件测试运行在同一进程内，可以覆盖 router/middleware/dependency override 的协作边界。
- 集成测试可以慢一些，但必须明确依赖和跳过条件。
- 一个测试只验证一个主要行为；准备数据可以多，断言目标要清楚。
- 优先测试公开行为，不为私有实现细节写脆弱测试，除非是在保护复杂边界。

## 放置规则

- API endpoint 直接调用：放到 `tests/unit/api/`。
- FastAPI router、ASGI client、dependency override、fake service 的请求/响应协作测试：放到 `tests/component/api/`。
- Middleware、exception handler、HTTP infra 的进程内协作测试：放到 `tests/component/http/`。
- Service 业务规则：放到 `tests/unit/services/`。
- Repository 查询构造和数据访问契约：放到 `tests/unit/repositories/`；需要真实数据库时放到 `tests/integration/`。
- Workflow、orchestrator、跨服务编排：放到 `tests/unit/workflows/`。
- Redis、TaskIQ dispatcher、storage、database session 等基础设施封装：放到 `tests/unit/infra/`。
- AI、RAG、prompt、token、embedding 等逻辑：放到 `tests/unit/ai/`。
- Worker 任务和 worker 依赖：放到 `tests/unit/worker/`；真实 broker/worker 协作放到 `tests/integration/`。
- 通用工具函数：放到 `tests/unit/utils/`。

## 命名规则

- 测试文件使用 `test_<module_or_behavior>.py`。
- 目录已经表达 `unit` 时，文件名通常不再追加 `_unit`。
- 测试函数使用 `test_<行为>_<预期结果>`，例如 `test_create_user_returns_400_when_service_returns_none`。
- fixture 使用描述性名称，例如 `fake_user_repo`、`mock_task_dispatcher`、`sample_generation_payload`。
- fake/mock 类使用清楚前缀，例如 `FakeRedis`、`StubLLMService`。

## Fixture 规则

- `tests/conftest.py` 只放全局、轻量、无应用启动的 fixture。
- 根 `conftest.py` 不 import `backend.main`，不创建 FastAPI app，不连接外部服务。
- 需要 app lifespan、真实 client、DB/Redis 的 fixture 放到对应子目录的 `conftest.py`。
- fixture 默认保持局部；只有两个以上文件复用时再上移。
- 对环境变量、时间、UUID、token 计数等不稳定来源做显式固定。

## Unit 测试写法

- 每个文件围绕一个模块或一组紧密相关行为组织，不混入跨层级集成验证。
- 文件顶部优先写模块职责 header，说明职责、边界和副作用。
- 先覆盖行为边界，再统一格式；至少考虑成功、拒绝/失败、边界值、跳过/旁路、依赖异常或空结果。
- 测试名使用 `test_<行为>_<预期结果>`，避免只写 `test_success`、`test_error`。
- `asyncio_mode = "auto"`（见 `pyproject.toml`）下，async 测试直接写 `async def` 即可，不要再加 `pytest.mark.asyncio`（逐函数或文件级 `pytestmark` 都不需要）；多余的 asyncio 标记会误标同文件的同步测试并触发警告。
- fixture 名称表达被测上下文或能力，例如 `payload_client`、`fake_user_repo`；避免泛泛的 `client`、`mock`。
- fixture 和测试函数补返回类型；异步生成器 fixture 使用 `AsyncIterator[...]`。
- mock 只断言关键协作参数，不把无关调用顺序和内部实现全部钉死。
- 注释只解释风险、边界或非显然约束，不解释代码正在做什么。

## Marker 规则

- `component`: 进程内组件测试，通常使用 ASGI client、dependency override 和 fake/mock 依赖。
- `integration`: 依赖真实基础设施、完整应用生命周期或真实跨进程协作的测试。
- `smoke`: 针对运行中环境的真实 HTTP stack 冒烟测试，通常访问 `SMOKE_BASE_URL`。
- `performance`: 并发、负载、耗时或资源敏感测试，默认排除。
- `requires_db`: 需要 `TEST_DATABASE_URL`。
- `requires_redis`: 需要 `TEST_REDIS_URL`。
- `requires_taskiq`: 需要 `TEST_TASKIQ_REDIS_URL`。
- `requires_s3`: 需要 `TEST_S3_ENDPOINT_URL`。
- `requires_llm`: 需要 `TEST_LLM_API_KEY`。
- `local_only`: 只在本地 profile 下运行。
- `ci_only`: 只在 CI profile 下运行。
- 新增 marker 必须同步注册到 `pyproject.toml`。

## Marker 审计

- `scripts/qa/check_test_markers.py` 会检查明显真实依赖特征是否有对应 marker。
- 测试文件出现 `create_async_engine(...)` 时，必须标记 `requires_db`。
- 测试文件出现 `redis.from_url(...)` 时，必须标记 `requires_redis`。
- 测试文件出现 `.kiq(...)` 或 `taskiq worker` 时，必须标记 `requires_taskiq`。
- 测试文件出现真实 S3 client 或 `TEST_S3_ENDPOINT_URL` 时，必须标记 `requires_s3`。
- 测试文件出现 `TEST_LLM_API_KEY` 时，必须标记 `requires_llm`。
- `tests/smoke/` 使用 `SMOKE_*` 环境和 `smoke` marker，不强制使用 `requires_*`。
- 纯构造、导入、轻量 wiring 检查放到 `tests/unit/`；文件名或函数名可以使用 `construction`、`minimal` 或 `unit_smoke`，但不要使用 `smoke` marker。
- fake/mock/stub、`api_key="test-key"`、`s3://bucket/key` 这类本地确定性测试不需要 `requires_*`。

## 示例模板

单元测试：不访问真实外部依赖，围绕行为边界组织用例。

```python
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def payload_client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=build_test_app(), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_replays_json_body_when_size_equals_limit(
    payload_client: AsyncClient,
) -> None:
    response = await payload_client.post(
        "/echo-size",
        content=b"hello",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert response.json() == {"size": 5, "body": "hello"}


async def test_rejects_large_json_body_while_streaming(
    payload_client: AsyncClient,
) -> None:
    response = await payload_client.post(
        "/echo-size",
        content=chunked_large_body(),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413
```

需要 Redis 的 integration：声明 `integration` 和 `requires_redis`，通过 `require_env()` 读取测试环境变量。

```python
import pytest
import redis.asyncio as redis

from tests.helpers.env import require_env

pytestmark = [pytest.mark.integration, pytest.mark.requires_redis]


async def test_cache_roundtrip_with_real_redis():
    client = redis.from_url(require_env("TEST_REDIS_URL"), decode_responses=True)
    try:
        await client.set("dewflow:test:key", "value")
        assert await client.get("dewflow:test:key") == "value"
    finally:
        await client.delete("dewflow:test:key")
        await client.aclose()
```

本地或 CI profile skip：只用 profile marker 表达运行范围，不在测试体里手写 profile 判断。

```python
import pytest


@pytest.mark.local_only
def test_local_diagnostic_output_is_available():
    assert True


@pytest.mark.ci_only
def test_ci_contract_is_enabled():
    assert True
```

## Profile + Marker + Fixture Skip

- 测试配置采用 base-first override：默认使用 fake/mock/local deterministic 实现，只有 `requires_*` marker 声明真实依赖时，才允许读取 `TEST_*` 覆盖值。
- `DEWFLOW_TEST_PROFILE` 只允许 `unit`、`local`、`ci`、`external`；未设置时默认为 `local`。
- 缺少 `requires_*` 对应环境变量时，pytest hook 会统一 skip 当前测试。
- 不为 local/ci 复制整套配置；只通过 `TEST_*` 覆盖少量真实依赖。
- 需要在测试或 fixture 中读取环境变量时，优先使用 `tests.helpers.env.require_env()` 或 `optional_env()`。

## Layered Environment Rules

- L1 (`make check` / `flow-static`) 不启动 Docker、不访问 localhost、不读取 `.env.smoke`。
- L2 (`flow-runtime` / smoke pytest) 只通过 `SMOKE_*` 访问运行中的 HTTP stack。
- L3 (`qa-eval-rag` / `qa-perf-chat` / agent flow) 复用 L2 环境，只叠加 `EVAL_*`、`PERF_*`、`AGENT_*`。
- `tests/manual/*.http` 是人工调试入口；长期契约必须在 pytest smoke 中有对应断言。

## Async 规则

- 只有测试体内需要 `await` 时才使用 async test。
- `asyncio_mode = "auto"` 自动识别 async 测试，无需 `pytest.mark.asyncio`；组合 marker（如 `integration`、`requires_redis`）按需保留，但不要再带 asyncio。
- 同步 blocking I/O 不应直接放进 async 测试；必要时通过被测代码的异步封装进入。

## 外部依赖规则

- 单元测试不访问真实 PostgreSQL、Redis、S3、TaskIQ worker 或外部 LLM。
- 集成测试依赖不可用时使用 `pytest.skip(...)`，skip 信息要说明缺少哪个服务。
- 不在测试里偷偷读取开发者本机私有配置；需要配置时使用测试环境变量或 fixture 注入。

## 断言风格

- 优先断言行为结果、错误类型、状态码、关键字段。
- 错误消息断言只匹配稳定片段，不依赖完整堆栈或内部实现文本。
- 对 mock 调用断言关键参数，避免把无关实现细节全部钉死。
- 测试数据尽量小而完整；复杂 payload 可以抽成 fixture 或 builder。

## 迁移检查

移动测试文件后至少运行：

```bash
uv run pytest --collect-only tests/unit tests/integration
uv run pytest --collect-only tests/component
uv run pytest tests/unit
```

涉及集成测试 marker、目录或命令变更时，同时检查：

```bash
uv run python scripts/qa/check_test_markers.py
uv run pytest --collect-only tests/integration
```
