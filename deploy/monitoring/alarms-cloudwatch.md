# CloudWatch Alarm Migration

Production deploy logs are delivered directly from Docker to CloudWatch Logs
through the `awslogs` driver. The deploy stack uses these defaults:

```text
log group: ${DEPLOY_CW_LOG_GROUP:-/dewflow/prod}
region: ${DEPLOY_AWS_REGION:-us-east-1}
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

## Phase 1 Log Metric Filters

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

Recommended first alarm threshold: `>= 1` event in 5 minutes, with both alarm
and OK actions pointing to the SNS topic. Tune noisy warning signals after
production baselines are known.

If the SNS topic is managed elsewhere, set `DEPLOY_ALERTS_SNS_TOPIC_ARN` in
`deploy/.env.ec2`; otherwise the setup script creates
`${DEPLOY_ALERTS_SNS_TOPIC_NAME:-dewflow-prod-alerts}`.

## Phase 2 Metric Alarms

The retired Prometheus rules captured these metric intents:

| Previous alert | Target AWS path | Notes |
| --- | --- | --- |
| `ApiHighLatency` | EMF, ADOT to CloudWatch, or AMP | Needs request duration distribution before P99 is meaningful. |
| `ApiErrorRateHigh` | EMF, ADOT to CloudWatch, or AMP | Needs request and 5xx counts with route/status dimensions. |
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
  --region "${DEPLOY_AWS_REGION:-us-east-1}" \
  --follow
```

Trigger one controlled `CRITICAL` JSON log in a non-customer-impacting path,
then confirm the metric filter increments and the SNS email receives both
`ALARM` and recovery notifications.
