# Local Observability

This directory keeps the optional self-hosted observability stack for
`docker-compose.db.yml`. It is for local debugging and smoke investigation only.
Production EC2 deploy observability lives under `deploy/monitoring/` and uses
CloudWatch Logs / CloudWatch alarms.

Start the local stack with:

```bash
docker compose --env-file .env.smoke -f docker-compose.db.yml --profile observability up -d
```

The stack includes:

- OpenTelemetry Collector for local OTLP intake
- Prometheus for metrics and local alert-rule evaluation
- Grafana for local dashboards
- Loki and Vector for container log exploration
- Tempo for local traces

Default ports:

- Grafana: `http://localhost:3000`
- Prometheus: `http://localhost:9090`
- Loki: `http://localhost:3100`
- Tempo: `http://localhost:3200`

This stack is intentionally not wired into `make env-smoke-up`; enable it
explicitly only when you need local observability.
