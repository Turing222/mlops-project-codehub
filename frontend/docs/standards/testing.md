# Frontend Testing Standard

## 目标

- 用小成本覆盖架构边界。
- 优先测试容易回归的请求、schema、状态和路由行为。
- 不为了覆盖率数字写脆弱测试。

## 测试分层

Unit / smoke：

- schema parse。
- request helper。
- route smoke。
- store action。
- 纯工具函数。

Integration：

- query hook。
- mutation invalidation。
- token bootstrap。
- unauthorized cleanup。
- stream parser。

Build verification：

- TypeScript build。
- Vite build。
- lint。

## 常用命令

```bash
make frontend-lint
make frontend-typecheck
make frontend-test
make frontend-build
make frontend-e2e-mock
make frontend-check
```

真实后端 smoke e2e 不作为 PR 默认阻塞项。需要先启动后端并提供账号：

```bash
E2E_SMOKE_USER=... E2E_SMOKE_PASS=... make frontend-e2e-smoke
```

## 新增功能的最低测试建议

- 新 API：schema parse 或 API helper test。
- 新 query：query key、enabled 条件、invalidation。
- 新表单：关键校验和 submit payload。
- 新流式逻辑：chunk parser、error event、done event、abort。

## Mock 数据

- Vitest/MSW 和 Playwright mock e2e 共享 `src/test/mock-data.ts` 中的基础响应数据。
- Playwright 仍使用 `page.route`，不强制迁移到浏览器侧 MSW。

## 覆盖率

覆盖率用于**度量回归保护强度**，不是写测试的目标 —— 仍遵循上文"不为覆盖率数字写脆弱测试"。

```bash
make frontend-test-coverage   # = vitest run --coverage，产物在 apps/admin/coverage/
```

- provider `v8`，阈值定义在 `apps/admin/vitest.config.ts` 的 `coverage.thresholds`。
- 阈值是**防回归下限（floor）**，设在当前实测值下方、留波动余量；覆盖率明显下滑才触发，不要求逐步抬高。
- CI（`static-ci.yml` 的 `frontend-static`）跑覆盖率并上传 `frontend-coverage` artifact；`make frontend-test` 与 `make frontend-test-coverage` 均为阻塞门禁。React 19 scheduler 在 jsdom teardown 的竞态已在 `src/test/setup.ts` 通过 `act(cleanup)` + setImmediate flush 修复（见评估文档 §9.1）。
