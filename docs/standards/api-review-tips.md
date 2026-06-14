# API Review Tips

这些笔记是轻量 review 提醒，不是强制规范。只有当某条提醒反复证明有用时，再考虑沉淀到 `AGENTS.md` 或 review skill。

## Endpoint 输入

- 同一个 endpoint 文件内，输入参数写法尽量保持一致。
- 重复出现的依赖优先用 `Annotated[..., Depends(...)]` 别名。
- 简单的 `Query(...)` 约束可以内联，让读者就近看到范围。
- 普通分页字段如 `skip`、`limit` 不必单独写说明，除非正在系统性维护 API 文档。
- 不保留未使用的业务 service 依赖参数。
- 只为副作用执行的依赖用 `_` 或 `_xxx` 命名，例如限流。
- 如果注入了 `PermissionService`，通常应调用 `require_permission(...)`；否则考虑删除。
- `Depends`、`Query`、`Form` 等 FastAPI 输入逻辑不要放进 schema 模块。

