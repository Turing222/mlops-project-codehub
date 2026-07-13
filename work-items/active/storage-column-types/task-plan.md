# 工作项计划：存储路径列迁移为 Text

> 机读状态（`status`、`workstreams`、`current_checkpoint`、`next_choices`、
> `open_decisions`）只保存在 `manifest.yaml`，并以它为准。
> 本文件只记录稳定叙事：为什么做、范围是什么、取舍是什么。
> 不要在这里复制状态字段。

## 目标

`knowledge_files.file_path` 和 `knowledge_files.storage_key` 当前使用 `String(1024)`。目标是将两列迁移为 PostgreSQL `Text`，避免长 S3 URI 或 object key 在边界处写入失败，同时保留清晰、可逆的数据库迁移路径。

## 对话结论

- 当前 ORM 定义仍为 `String(1024)`，原待办尚未实施。
- PostgreSQL `VARCHAR(n)` 限制字符数，而 S3 object key 的限制按 UTF-8 字节计算，二者边界并不等价。
- `Text` 与无索引用途下的 `VARCHAR` 具有相同的常规存储特征，本次不改变业务字段语义。
- 改动必须同时覆盖 ORM、Alembic upgrade/downgrade、聚焦测试和生产 rollout 注意事项。
- 这是实现工作，不再作为稳定项目文档维护。

## Workstream 拆分理由

### WS1 — Confirm the migration scope and operational constraints

- Scope：确认当前列定义、目标类型、兼容性和生产锁风险。
- Reason：数据库类型迁移必须先明确 schema 与运行边界。
- Expected effect：实现范围稳定，不把存储 key 生成逻辑带入本工作项。

### WS2 — Implement the ORM and Alembic type changes

- Scope：修改 `backend/models/orm/knowledge.py` 并创建 Alembic revision。
- Reason：ORM 与数据库 schema 必须同步演进。
- Expected effect：upgrade 后两列均为 `Text`，downgrade 可恢复原类型。

### WS3 — Add focused tests and validate upgrade and downgrade behavior

- Scope：补充最低层测试并执行 migration chain 校验。
- Reason：保护 nullable 属性、类型声明和双向迁移合同。
- Expected effect：变更可重复验证，不依赖人工观察 schema。

### WS4 — Prepare rollout guidance and complete the handoff

- Scope：记录生产执行窗口、锁影响和兼容性检查结果。
- Reason：即使 PostgreSQL 通常只做元数据变更，也应显式评估实际表规模和发布顺序。
- Expected effect：迁移具备可执行的上线与回退说明。

## 暂缓 / 不纳入范围

- 修改 S3 object key 或文件路径生成规则。
- 清理历史数据或重写现有 key。
- 在本次文档整理中直接执行数据库迁移。

## Open Decisions 说明

- 当前没有阻塞实现的 open decision；生产执行窗口在 WS4 中结合实际环境确认。
