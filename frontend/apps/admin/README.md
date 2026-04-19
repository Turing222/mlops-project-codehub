# Admin Frontend

当前前端只保留 `apps/admin` 这一个应用，负责聊天主页和管理员入口。

## 文档

- [架构约定](../../ARCHITECTURE.md)
- [逐步改造计划](../../MIGRATION_PLAN.md)

## 常用命令

在仓库根目录执行：

```bash
make frontend-test
make frontend-build
```

如果只想在前端目录里跑：

```bash
pnpm --dir frontend --filter admin test
pnpm --dir frontend --filter admin build
pnpm --dir frontend --filter admin dev
```

## 测试范围

- `Vitest + jsdom + Testing Library`
- 路由级 smoke test
- API 路径和流式请求的基础测试

这一步先保证最基础的前端验证链路可跑，再继续做镜像和 CI 拆分。
