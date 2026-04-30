# TODO: 将 `storage_key` 和 `file_path` 列类型改为 `Text`

## 背景

`knowledge_files` 表中以下两列当前使用 `String(1024)`，存在边界风险：

| 列名 | 当前类型 | 风险 |
|------|----------|------|
| `file_path` | `String(1024)` | 存储 S3 URI（`s3://bucket/key`），URI 总长可能超 1024 |
| `storage_key` | `String(1024)` | S3 object key 最大 1024 字节（UTF-8），`String(1024)` 恰好卡边 |

PostgreSQL 的 `String(n)` 对应 `VARCHAR(n)`，限制的是**字符**数而非字节数。
当 prefix + kb_id + uuid + filename 拼接后接近或超过 1024 字符时，数据库写入会失败。

## 建议改动

### ORM (`backend/models/orm/knowledge.py`)

```python
# 改前
file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)

# 改后
file_path: Mapped[str] = mapped_column(Text, nullable=False)
storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
```

### Alembic Migration（需新增一个 revision）

```python
def upgrade() -> None:
    op.alter_column(
        "knowledge_files", "file_path",
        existing_type=sa.String(length=1024),
        type_=sa.Text(),
        existing_nullable=False,
    )
    op.alter_column(
        "knowledge_files", "storage_key",
        existing_type=sa.String(length=1024),
        type_=sa.Text(),
        existing_nullable=True,
    )

def downgrade() -> None:
    op.alter_column(
        "knowledge_files", "storage_key",
        existing_type=sa.Text(),
        type_=sa.String(length=1024),
        existing_nullable=True,
    )
    op.alter_column(
        "knowledge_files", "file_path",
        existing_type=sa.Text(),
        type_=sa.String(length=1024),
        existing_nullable=False,
    )
```

## 注意事项

- PostgreSQL 中 `TEXT` 和 `VARCHAR` 底层存储性能完全相同，不会有性能损耗。
- 此改动需要 `ALTER COLUMN`，生产环境执行时对大表需评估锁时间（通常极快，因为只是类型元数据变更）。
- 迁移完成后，删除本文件。

## 优先级

低（当前文件名长度在正常使用范围内不会触发边界，但生产上最好尽快处理）。
