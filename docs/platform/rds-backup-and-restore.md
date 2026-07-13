# RDS 备份与恢复

生产数据库使用 Amazon RDS for PostgreSQL 时，备份责任在 RDS 控制面，不在仓库的 Compose `postgres` 容器脚本中。

- 本地、smoke 和演练环境仍可使用 Compose `postgres`。
- 生产备份不依赖容器内 `pg_dump` 定时脚本或 EBS volume snapshot。
- 生产侧使用 RDS automated backups、DB snapshots 和 restore 流程。

## 当前状态

- 仓库中的 `postgres` 服务只属于 [deploy/docker-compose.local-postgres.yml](../../deploy/docker-compose.local-postgres.yml) 的本地或自管 fallback 形态。
- 生产库迁到 RDS 后，不需要恢复已删除的容器内数据库备份脚本。

## 最低能力

生产数据库是 RDS 时，至少启用：

1. **Automated Backups**：开启自动备份并设置合适的 retention period。
2. **Point-in-Time Recovery (PITR)**：确保可以恢复到误操作前的时间点。
3. **Manual DB Snapshot**：在大版本升级、schema migration、大批量数据修复或不可逆发布前创建快照。
4. **Restore drill**：定期验证能否从 automated backup 或 snapshot 恢复出可用实例。

## 推荐与禁用做法

- 日常依赖 RDS automated backups + PITR。
- 高风险变更前创建 manual DB snapshot 作为静态锚点。
- 有跨 Region 或合规保留要求时，再评估 AWS Backup 或跨 Region backup。
- 不要把 Compose `postgres` 的备份方式等同于生产 RDS 备份。
- 不要只确认“有自动备份”而不做恢复演练。
- 除非生产重新切回 self-managed PostgreSQL on EC2，否则不要恢复容器内备份脚本。

## 发布前 Checklist

在 schema migration、大版本升级、批量数据修复、backfill 或不可逆发布前，默认执行一次 manual DB snapshot：

1. 确认目标生产 RDS 实例，记录 DB instance identifier、Region 和变更单号。
2. 确认 automated backups 已开启，且 retention period 不是 0。
3. 确认最近一次自动备份状态正常，实例没有执行其他高风险维护操作。
4. 创建 manual DB snapshot，名称包含环境、日期和变更标识，例如 `prod-2026-06-07-before-migration-<ticket>`。
5. 等待 snapshot 进入 `available` 状态，再执行 migration 或发布。
6. 在发布记录中写明 snapshot 名称、开始变更时间和执行人。
7. 发布完成后确认应用 smoke、核心查询和连接池状态正常。

## 故障恢复选择

- 误删或数据写坏，希望回到某个时间点：优先 PITR。
- 高风险变更刚完成，希望回到固定状态：优先 manual snapshot restore。
- 只恢复单库、单表或少量数据：从 snapshot 或 PITR 恢复到新实例，再导出需要的数据回灌。

默认先恢复到新实例验证，再决定是否切换生产流量，不直接覆盖生产实例。

## Restore Drill Checklist

建议至少每月或每个大版本前做一次恢复演练：

1. 选择最近的 automated backup 或 manual snapshot。
2. 恢复到新的临时 RDS 实例，不覆盖生产实例。
3. 配置最小必要网络访问，避免直接暴露公网。
4. 验证数据库连接、关键 schema、extension、role、最小 smoke query 和关键表数据量。
5. 记录恢复耗时（RTO）、可接受的数据回退窗口（RPO）及额外参数组、白名单或切换步骤。
6. 演练完成后删除临时实例，避免持续计费。

运行手册还应记录生产实例名或 ARN、snapshot 命名、创建与恢复权限，以及恢复后的应用切换和回切条件。

部署顺序与发布命令见 [deploy-ec2.md](deploy-ec2.md)。
