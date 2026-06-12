# Monitoring Assets

This directory now keeps AWS observability migration assets for the EC2 deploy
stack. The old self-hosted Prometheus / Grafana / Loki / Vector compose profile
has been retired from `deploy/docker-compose.yml`.

## Current Production Path

Production logs use Docker `awslogs` and go directly to CloudWatch Logs:

```text
backend/worker JSON logs -> CloudWatch Logs -> metric filters -> CloudWatch alarms -> SNS
```

The application-level contract remains stable: structured JSON logs should keep
using fields such as `level`, `event`, `error_code`, `request_id`, `trace_id`,
and `span_id`.

## Files

- `alarms-cloudwatch.md` documents the first CloudWatch metric filters, alarm
  intent, SNS target shape, and verification commands.
- `dashboard-promql-export.md` preserves the PromQL / LogQL expressions from
  the retired Grafana dashboard as reference material for AWS Managed Grafana,
  AMP, or a future CloudWatch dashboard.

## Local And Smoke Boundaries

- `docker-compose.db.yml` remains the local / CI smoke stack and does not depend
  on CloudWatch Logs.
- `local/observability/` keeps the optional self-hosted Prometheus / Grafana /
  Loki / Tempo / Vector assets for local debugging.
- `deploy/docker-compose.local-logging.yml` is the non-EC2 rehearsal override
  that changes deploy-stack logging back to `json-file`.
- `deploy/docker-compose.local-s3.yml` is the non-EC2 rehearsal override that
  replaces AWS S3 with MinIO.
