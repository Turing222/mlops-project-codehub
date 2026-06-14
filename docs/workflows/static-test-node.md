# 静态测试节点

本文档说明本项目静态检查节点的职责、推荐执行顺序，以及 Ruff 和 ty 的处理标准。

## 目标

静态测试节点用于在运行较重的集成、烟测或性能验证前，先拦截确定性问题：

- 代码风格和格式漂移
- Web / Worker 边界破坏
- pytest marker 配置错误
- 类型契约不清晰
- 依赖层级和迁移链问题
- 基础配置错误
- 单元和组件级回归

本节点不应该依赖外部 LLM、真实对象存储或完整运行时环境。

## 本地入口

推荐按范围选择命令。

只检查 Ruff：

```bash
make qa-lint
make qa-format-check
```

自动修复 Ruff 可安全处理的问题：

```bash
make qa-lint-fix
make qa-format
```

运行完整静态节点：

```bash
make check
```

`make check` 当前等价于 `flow-static`，会依次执行：

```bash
make qa-lint
make qa-format-check
make qa-boundaries
make qa-test-markers
make qa-typecheck
make qa-layer-deps
make qa-alembic-check
make qa-config-check
make qa-test-unit
make qa-test-component
```

## Ruff 标准

Ruff 是当前项目的强阻断项。只要 `qa-lint` 或 `qa-format-check` 失败，就应该先修复再提交。

本地开发可以使用：

```bash
make qa-lint-fix
make qa-format
```

CI 和静态节点必须使用检查模式：

```bash
make qa-lint
make qa-format-check
```

新增 Ruff 规则时，必须先在本地清零，再加入 `select`。新增例外时按以下优先级处理：

1. 直接修代码。
2. 合理误报使用精确 `# noqa: RULE - reason`。
3. 目录性质不同才使用 `per-file-ignores`。
4. 避免新增宽泛全局 `ignore`。

安全规则 `S` 的 `noqa` 必须写清楚原因，例如纯文本 prompt 模板不需要 HTML autoescape。

## ty 标准

ty 当前作为类型雷达使用：

```toml
[tool.ty.rules]
all = "warn"
```

这表示类型问题会暴露出来，但不会像 Ruff 一样作为硬阻断。这个策略适合当前阶段，因为部分告警来自第三方库类型定义、eval 脚本和动态运行边界。

处理 ty 告警时不要把输出当成平铺列表逐条修。先按文件和规则类型归类，找根因。

常见模式：

- `possibly-unresolved-reference`：变量只在某个分支定义，后续路径也在使用。
- `unresolved-attribute`：值可能为 `None`，但代码直接访问属性。
- `invalid-argument-type`：传入值类型过宽，常见于 `object`、`dict[str, object]` 或第三方 SDK 边界。
- `invalid-return-type`：临时结构丢失了精确类型。
- `call-non-callable`：运行时鸭子类型可行，但静态类型仍看到 `object`。
- `no-matching-overload`：第三方库 overload 需要更精确的入参类型。

优先使用低风险修复：

1. 提前初始化可选变量。
2. 添加明确的 `None` guard。
3. 用 `TypedDict`、`Protocol` 或更具体的模型替代 `object`。
4. 在第三方库边界做局部 `cast`。
5. 最后才考虑重构 DTO、接口或调用链。

不要为了消除 ty 告警改变运行时语义。类型修复应该让已有业务意图更明确，而不是让代码绕着检查器走。

## 提交前建议

轻量提交前检查：

```bash
make qa-lint
make qa-format-check
make qa-typecheck
make qa-test-unit
```

合并前静态全量：

```bash
make check
```

如果变更涉及运行时环境、Docker、迁移或 smoke 链路，再运行：

```bash
make flow-dev-check
```
