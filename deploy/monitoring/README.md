# Monitoring Assets

这个目录保存 Dewflow 的**本地 observability 栈资产**，用于本地调试、演示和对照验证；它不是 AWS 生产监控的 source of truth。

## 状态说明

- **当前生产路径**：单台 EC2 以 [deploy/docker-compose.yml](../docker-compose.yml) + 云端托管监控服务为准。
- **当前本地路径**：需要本地自托管可观测性时，可启用 `DEPLOY_ENABLE_OBSERVABILITY=true`，使用 Prometheus / Grafana / Loki 这组 profile 做本地观察和排障。
- **共享合同**：无论本地自托管还是云端托管，真正应保持一致的是 `event` / `error_code` / `request_id` / `trace_id` / health endpoint 等应用层语义，而不是这里的 compose host、datasource URL 或 container wiring。

## 文件边界

### 当前 EC2 observability profile 实际挂载

`deploy/docker-compose.yml` 当前 observability profile 直接挂载的是：

- `prometheus.yml`
- `alert_rules.yml`
- `grafana_datasources.yaml`
- `grafana_dashboards_provisioning.yaml`
- `loki-config.yaml`
- `../logging/vector.yaml`

这些文件描述的是**当前 compose / EC2 本地自托管观测入口**，用于本地或自托管排障，不等价于 AWS 生产监控实现。

### richer local-db / tracing 资产

以下文件属于 **local-db / richer tracing** 方案，不是当前 EC2 observability profile 的默认挂载对象：

- `prometheus-db.yml`
- `grafana_datasources_db.yaml`
- `tempo-db.yml`
- `otel-collector-db.yml`

它们表达的是更完整的本地 traces + metrics + logs 联调路径，适合本地实验、演示或后续增强；不要把它们误读为当前默认生产方案。

## 告警与监控范围说明

- `alert_rules.yml` 表示本地自托管栈的规则定义，不自动意味着已经具备生产告警投递链路。
- AWS 生产环境如果走云端托管监控，建议复用这里沉淀的**事件名、错误码和告警意图**，而不是强行复用 Prometheus/Grafana/Vector 的本地接线细节。
- 如果后续要统一本地与云端 observability contract，应优先统一应用层信号命名，再决定 transport / collector / dashboard 的实现。
