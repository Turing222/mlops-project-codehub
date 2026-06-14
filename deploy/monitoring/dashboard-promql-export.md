# Dashboard PromQL Export

This file preserves the PromQL and LogQL intent from the retired self-hosted
Grafana dashboard. It is reference material for AWS Managed Grafana / AMP or a
future CloudWatch dashboard migration.

## HTTP Request Rate

```promql
sum(rate(http_server_request_duration_seconds_count[1m])) by (http_request_method, http_route)
```

## HTTP Status Rate

```promql
sum(rate(http_server_request_duration_seconds_count[1m])) by (http_response_status_code)
```

## API P99 Latency

```promql
histogram_quantile(0.99, sum(rate(http_server_request_duration_seconds_bucket[5m])) by (le, http_route))
```

## API Average Latency

```promql
sum(rate(http_server_request_duration_seconds_sum[5m])) by (http_route) / sum(rate(http_server_request_duration_seconds_count[5m])) by (http_route)
```

## Postgres Connections

```promql
pg_stat_activity_count
```

## Redis Memory

```promql
redis_memory_used_bytes
```

## Service Logs

```logql
{service=~"$service"} | json | line_format "[{{.service}}] {{.message}}"
```

## Warning And Error Logs

```logql
{level=~"error|warn"} | json | line_format "[{{.service}}] {{.message}}"
```
