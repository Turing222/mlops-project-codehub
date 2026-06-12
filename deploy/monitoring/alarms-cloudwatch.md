# CloudWatch Alarm Migration

Production deploy logs are delivered directly from Docker to CloudWatch Logs
through the `awslogs` driver. The deploy stack uses these defaults:

```text
log group: ${DEPLOY_CW_LOG_GROUP:-/dewflow/prod}
region: ${DEPLOY_AWS_REGION:-us-east-1}
stream prefix: ${DEPLOY_CW_LOG_STREAM_PREFIX:-dewflow}
```

Create the log group before the first deploy:

```bash
aws logs create-log-group \
  --log-group-name "${DEPLOY_CW_LOG_GROUP:-/dewflow/prod}" \
  --region "${DEPLOY_AWS_REGION:-us-east-1}"
```

The EC2 instance role needs CloudWatch Logs write access for this group,
including `logs:CreateLogStream`, `logs:DescribeLogStreams`, and
`logs:PutLogEvents`.

## Phase 1 Log Metric Filters

Create metric filters in a dedicated namespace such as `Dewflow/Logs`, then
attach CloudWatch alarms to an SNS topic:

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

## Phase 2 Metric Alarms

The retired Prometheus rules captured these metric intents:

| Previous alert | Target AWS path | Notes |
| --- | --- | --- |
| `ApiHighLatency` | EMF, ADOT to CloudWatch, or AMP | Needs request duration distribution before P99 is meaningful. |
| `ApiErrorRateHigh` | EMF, ADOT to CloudWatch, or AMP | Needs request and 5xx counts with route/status dimensions. |
| `RedisMemoryUsageHigh` | CloudWatch custom metric or ElastiCache metric | Current compose Redis has no managed ElastiCache metric. |
| `PostgresConnectionsExhausted` | CloudWatch custom metric or RDS metric | Current compose Postgres has no managed RDS metric. |

Do not replace these with plain log metric filters unless the application first
emits explicit structured metrics for the required values.

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
