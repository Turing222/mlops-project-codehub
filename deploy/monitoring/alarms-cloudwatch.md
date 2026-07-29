# CloudWatch Alarm Migration

Production deploy logs are delivered directly from Docker to CloudWatch Logs
through the `awslogs` driver. The deploy stack uses these defaults:

```text
log group: ${DEPLOY_CW_LOG_GROUP:-/dewflow/prod}
region: ${DEPLOY_AWS_REGION:-us-west-2}
stream prefix: ${DEPLOY_CW_LOG_STREAM_PREFIX:-dewflow}
metric namespace: ${DEPLOY_CW_METRIC_NAMESPACE:-Dewflow/Logs}
SNS topic: ${DEPLOY_ALERTS_SNS_TOPIC_NAME:-dewflow-prod-alerts}
```

Create or update the log group, SNS topic, log metric filters, and alarms:

```bash
make deploy-cloudwatch-setup
```

The EC2 instance role needs CloudWatch Logs write access for this group,
including `logs:CreateLogStream`, `logs:DescribeLogStreams`, and
`logs:PutLogEvents`.

The human or CI role that runs `make deploy-cloudwatch-setup` also needs:

- `logs:CreateLogGroup`
- `logs:DescribeLogGroups`
- `logs:PutMetricFilter`
- `cloudwatch:PutMetricAlarm`
- `sns:CreateTopic`

## T1-Lite 最低告警合同

首版只消费下表列出的稳定 JSON 顶层字段。所有 alarm action 指向
`DEPLOY_ALERTS_SNS_TOPIC_ARN`，或脚本创建的
`DEPLOY_ALERTS_SNS_TOPIC_NAME`；若设置 `DEPLOY_ALERTS_SNS_EMAIL`，脚本会创建
email subscription，但收件人仍须在邮箱中完成确认。

| Signal | Producer / filter | Metric | 默认 threshold / window | 首要处置 |
| --- | --- | --- | --- | --- |
| API 5xx | `event=api_request_completed` 且 `status_code >= 500` | `Api5xxCount` (`Sum`) | `>= 1` / 5 min | 按 `http_request_id`、`route` 与 `error_code` 定位 endpoint 和异常。 |
| API latency | `event=api_request_completed`，value=`duration_ms` | `ApiLatencyMs` (`Maximum`) | `>= 2000 ms` / 5 min | 区分 endpoint、DB 与外部 provider；SSE 只测 response-start latency。 |
| Queue depth | `event=t1_lite_heartbeat_completed`，value=`queue_depth` | `TaskiqQueueDepth` (`Maximum`) | `>= 100` / 2 consecutive 5 min windows | 检查 Scheduler、TaskIQ Redis 与 Worker 消费速率，不从 Redis 盲目重放。 |
| Oldest pending | 同一 heartbeat，value=`oldest_pending_age_seconds` | `OldestPendingAgeSeconds` (`Maximum`) | `>= 300 s` / 5 min | 根据 `oldest_pending_source` 回到 PostgreSQL generation / TaskJob / outbox 事实。 |
| E2E heartbeat + log dead-man | `event=t1_lite_heartbeat_completed` | `T1LiteHeartbeatCount` (`Sum`) | `< 1` / 5 min；missing=`breaching` | 先检查 CloudWatch 日志采集，再沿 Scheduler -> Redis -> Worker 排查。 |
| Terminal task / outbox failure | `chat_generation_terminal_failed`、`chat_generation_recovery_failed` 或 `knowledge_outbox_dead` | `TerminalTaskFailureCount` (`Sum`) | `>= 1` / 5 min | 按 request / task / outbox ID 查 PostgreSQL；只走受控 retry / replay。 |
| Redis eviction / restart | `redis_eviction_detected` 或 `redis_restart_detected` | `RedisRiskCount` (`Sum`) | `>= 1` / 5 min | 区分 `app` 与 `taskiq` Redis；核对 uptime、eviction delta 和 durable DB 状态。 |
| Probe failure | `operability_probe_failed` 或 `redis_probe_failed` | `OperabilityProbeFailureCount` (`Sum`) | `>= 1` / 5 min | 按 `probe_component` 检查 DB / Redis；该信号不代替 heartbeat dead-man。 |
| Delivery validation | `event=t1_lite_synthetic_alarm` | `T1LiteSyntheticAlarmCount` (`Sum`) | `>= 1` / 1 min | 仅用于非恢复型受控送达验证；记录 Alarm 时间和 receiver 人工确认。 |

可调默认值来自 `deploy/.env.ec2`：

```text
DEPLOY_CW_ALARM_PERIOD_SECONDS=300
DEPLOY_CW_API_LATENCY_THRESHOLD_MS=2000
DEPLOY_CW_QUEUE_DEPTH_THRESHOLD=100
DEPLOY_CW_OLDEST_PENDING_THRESHOLD_SECONDS=300
DEPLOY_CW_QUEUE_EVALUATION_PERIODS=2
DEPLOY_ALERTS_SNS_EMAIL=
```

不得把 log metric filter 描述为完整 SLO 或 dashboard。`queue_depth` 只表示
传输层积压，replay 决策必须回到 PostgreSQL identity、status 与 expected attempt。

### 最短 runbook

1. 确认 Alarm 的 source metric、首个 breaching datapoint、log group 和 SNS topic。
2. 用结构化 ID 查询上下文，禁止复制 query、history、output 或 provider reasoning 到工单。
3. heartbeat 缺失时先验证日志采集；若采集正常，再逐段检查 Scheduler、TaskIQ Redis、Worker。
4. terminal failure 只使用现有 actor-scoped Chat retry 或受控 Knowledge replay；禁止 SQL / `LPUSH` 重放。
5. Redis restart / eviction 后先核对 durable DB，再决定是否 replay；T1-Lite 不包含恢复实证。
6. 受控验证使用 `make deploy-cloudwatch-verify-delivery`；只有 receiver 明确确认后才记录送达成立。

## Additional Existing Log Metric Filters

`make deploy-cloudwatch-setup` creates metric filters in a dedicated namespace
such as `Dewflow/Logs`, then attaches CloudWatch alarms to an SNS topic:

```text
SNS topic ARN: arn:aws:sns:${DEPLOY_AWS_REGION}:${AWS_ACCOUNT_ID}:dewflow-prod-alerts
```

| Signal | Filter pattern | Metric | Severity |
| --- | --- | --- | --- |
| Critical application log | `{ $.level = "CRITICAL" }` | `CriticalLogCount` | critical |
| LLM routing failure | `{ $.error_code = "LLM_ROUTING_FAILED" }` | `LlmRoutingFailedCount` | critical |
| Knowledge ingest failure | `{ $.error_code = "KNOWLEDGE_FILE_INGEST_FAILED" }` | `KnowledgeIngestFailedCount` | critical |
| LLM circuit breaker opened | `{ $.event = "circuit_breaker_opened" }` | `CircuitBreakerOpenedCount` | warning |
| Worker rerank degraded | `{ $.event = "worker_rerank_init_degraded" }` | `WorkerRerankDegradedCount` | warning |

这些既有应用告警继续保留，但不替代上面的 T1-Lite minimum set。

If the SNS topic is managed elsewhere, set `DEPLOY_ALERTS_SNS_TOPIC_ARN` in
`deploy/.env.ec2`; otherwise the setup script creates
`${DEPLOY_ALERTS_SNS_TOPIC_NAME:-dewflow-prod-alerts}`.

## Phase 2 Metric Alarms

The retired Prometheus rules captured these metric intents:

| Previous alert | Target AWS path | Notes |
| --- | --- | --- |
| `ApiHighLatency` | T1-Lite structured log metric；后续可迁移到 EMF / ADOT / AMP | 当前只对每请求 `duration_ms` 做 `Maximum`，不能称为 P99。 |
| `ApiErrorRateHigh` | T1-Lite structured 5xx count；后续可迁移到 EMF / ADOT / AMP | 当前只有 5xx count，不宣称 error rate 或 SLO。 |
| `RedisMemoryUsageHigh` | CloudWatch custom metric or ElastiCache metric | Current compose Redis has no managed ElastiCache metric. |
| `PostgresConnectionsExhausted` | RDS metric | Main deploy path now uses external Postgres / RDS. |

Do not replace these with plain log metric filters unless the application first
emits explicit structured metrics for the required values.

Recommended first RDS alarms after the RDS instance identifier is known:
`DatabaseConnections`, `FreeStorageSpace`, `CPUUtilization`, `FreeableMemory`,
and `ReadLatency` / `WriteLatency`. EC2 memory and disk alarms require
CloudWatch Agent; default EC2 metrics only cover CPU, network, and status checks.

## Verification

Tail production logs:

```bash
aws logs tail "${DEPLOY_CW_LOG_GROUP:-/dewflow/prod}" \
  --region "${DEPLOY_AWS_REGION:-us-west-2}" \
  --follow
```

运行 `make deploy-cloudwatch-verify-delivery` 发送独立的
`t1_lite_synthetic_alarm`。脚本只证明 log event 已使 Alarm 进入 `ALARM`；必须再由
confirmed receiver 明确确认实际收到通知，才能把送达写入验收证据。
