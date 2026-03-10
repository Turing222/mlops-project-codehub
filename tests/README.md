# Test Layout

`tests/` 目录按测试目标拆分：

- `unit/`: 纯单元测试，默认必须通过。
- `integration/`: 集成测试（API/仓储协同等）。
- `smoke/`: 冒烟测试，覆盖核心链路可用性。
- `performance/`: 并发/性能测试，默认不跑。

## 推荐命令

- 全量默认测试（排除 performance）：

```bash
uv run pytest
```

- 只跑 smoke：

```bash
uv run pytest -m smoke
```

- 跑 performance：

```bash
uv run pytest -m performance
```

- 跑 unit + integration：

```bash
uv run pytest tests/unit tests/integration
```

## 其他说明

- `evals/` 已迁移到项目根目录，不再属于 `pytest` 测试集。
- 诊断脚本放在 `tools/diagnostics/`。
- Locust 脚本位置：`tests/performance/locustfile.py`。
