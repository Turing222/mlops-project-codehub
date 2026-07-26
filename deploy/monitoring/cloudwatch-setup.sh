#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/../.." && pwd)/scripts/lib/common.sh"

cd "$PROJECT_ROOT"

require_cmd aws
require_deploy_env_file
load_deploy_env

region="$(deploy_control_env_value "DEPLOY_AWS_REGION" "us-east-1")"
log_group="$(deploy_control_env_value "DEPLOY_CW_LOG_GROUP" "/dewflow/prod")"
metric_namespace="$(deploy_control_env_value "DEPLOY_CW_METRIC_NAMESPACE" "Dewflow/Logs")"
topic_name="$(deploy_control_env_value "DEPLOY_ALERTS_SNS_TOPIC_NAME" "dewflow-prod-alerts")"
topic_arn="$(deploy_control_env_value "DEPLOY_ALERTS_SNS_TOPIC_ARN" "")"
alarm_period="$(deploy_control_env_value "DEPLOY_CW_ALARM_PERIOD_SECONDS" "300")"
api_latency_threshold="$(deploy_control_env_value "DEPLOY_CW_API_LATENCY_THRESHOLD_MS" "2000")"
queue_depth_threshold="$(deploy_control_env_value "DEPLOY_CW_QUEUE_DEPTH_THRESHOLD" "100")"
oldest_pending_threshold="$(deploy_control_env_value "DEPLOY_CW_OLDEST_PENDING_THRESHOLD_SECONDS" "300")"
queue_evaluation_periods="$(deploy_control_env_value "DEPLOY_CW_QUEUE_EVALUATION_PERIODS" "2")"
receiver_email="$(deploy_control_env_value "DEPLOY_ALERTS_SNS_EMAIL" "")"

log_section "Configuring CloudWatch Logs alerts"

if ! aws logs describe-log-groups \
    --region "$region" \
    --log-group-name-prefix "$log_group" \
    --query "logGroups[?logGroupName=='${log_group}'].logGroupName" \
    --output text | grep -qx "$log_group"; then
    aws logs create-log-group \
        --region "$region" \
        --log-group-name "$log_group"
    log_info "Created log group: $log_group"
else
    log_info "Log group already exists: $log_group"
fi

if [[ -z "$topic_arn" ]]; then
    topic_arn="$(aws sns create-topic \
        --region "$region" \
        --name "$topic_name" \
        --query TopicArn \
        --output text)"
    log_info "Using SNS topic: $topic_arn"
else
    log_info "Using existing SNS topic: $topic_arn"
fi

if [[ -n "$receiver_email" ]]; then
    subscription_arn="$(aws sns list-subscriptions-by-topic \
        --region "$region" \
        --topic-arn "$topic_arn" \
        --query "Subscriptions[?Protocol=='email' && Endpoint=='${receiver_email}'].SubscriptionArn | [0]" \
        --output text)"
    if [[ -z "$subscription_arn" || "$subscription_arn" == "None" ]]; then
        aws sns subscribe \
            --region "$region" \
            --topic-arn "$topic_arn" \
            --protocol email \
            --notification-endpoint "$receiver_email" >/dev/null
        log_info "Requested confirmation for the configured SNS email receiver."
    elif [[ "$subscription_arn" == "PendingConfirmation" ]]; then
        log_info "The configured SNS email receiver is still pending confirmation."
    else
        log_info "The configured SNS email receiver is confirmed."
    fi
fi

put_metric_filter() {
    local filter_name="$1"
    local pattern="$2"
    local metric_name="$3"
    local metric_value="$4"
    local default_value="${5:-}"

    local transformation
    transformation="metricName=${metric_name},metricNamespace=${metric_namespace},metricValue=${metric_value}"
    if [[ -n "$default_value" ]]; then
        transformation+=",defaultValue=${default_value}"
    fi

    aws logs put-metric-filter \
        --region "$region" \
        --log-group-name "$log_group" \
        --filter-name "$filter_name" \
        --filter-pattern "$pattern" \
        --metric-transformations "$transformation"
}

put_alarm() {
    local alarm_name="$1"
    local metric_name="$2"
    local statistic="$3"
    local threshold="$4"
    local comparison_operator="$5"
    local period="$6"
    local evaluation_periods="$7"
    local treat_missing_data="$8"
    local description="$9"

    aws cloudwatch put-metric-alarm \
        --region "$region" \
        --alarm-name "$alarm_name" \
        --alarm-description "$description" \
        --namespace "$metric_namespace" \
        --metric-name "$metric_name" \
        --statistic "$statistic" \
        --period "$period" \
        --evaluation-periods "$evaluation_periods" \
        --datapoints-to-alarm "$evaluation_periods" \
        --threshold "$threshold" \
        --comparison-operator "$comparison_operator" \
        --treat-missing-data "$treat_missing_data" \
        --alarm-actions "$topic_arn" \
        --ok-actions "$topic_arn"
}

put_metric_filter "dewflow-api-5xx" '{ $.event = "api_request_completed" && $.status_code >= 500 }' "Api5xxCount" "1" "0"
put_alarm "dewflow-api-5xx" "Api5xxCount" "Sum" "1" "GreaterThanOrEqualToThreshold" "$alarm_period" "1" "notBreaching" "At least one Dewflow API 5xx response occurred."

put_metric_filter "dewflow-api-latency" '{ $.event = "api_request_completed" && $.duration_ms = * }' "ApiLatencyMs" '$.duration_ms'
put_alarm "dewflow-api-latency" "ApiLatencyMs" "Maximum" "$api_latency_threshold" "GreaterThanOrEqualToThreshold" "$alarm_period" "1" "notBreaching" "Dewflow API response-start latency exceeded the T1-Lite threshold."

put_metric_filter "dewflow-taskiq-queue-depth" '{ $.event = "t1_lite_heartbeat_completed" && $.queue_depth = * }' "TaskiqQueueDepth" '$.queue_depth'
put_alarm "dewflow-taskiq-queue-depth" "TaskiqQueueDepth" "Maximum" "$queue_depth_threshold" "GreaterThanOrEqualToThreshold" "$alarm_period" "$queue_evaluation_periods" "notBreaching" "TaskIQ queue depth stayed above the T1-Lite threshold."

put_metric_filter "dewflow-oldest-pending" '{ $.event = "t1_lite_heartbeat_completed" && $.oldest_pending_age_seconds = * }' "OldestPendingAgeSeconds" '$.oldest_pending_age_seconds'
put_alarm "dewflow-oldest-pending" "OldestPendingAgeSeconds" "Maximum" "$oldest_pending_threshold" "GreaterThanOrEqualToThreshold" "$alarm_period" "1" "notBreaching" "Durable pending work exceeded the T1-Lite age threshold."

put_metric_filter "dewflow-t1-lite-heartbeat" '{ $.event = "t1_lite_heartbeat_completed" }' "T1LiteHeartbeatCount" "1" "0"
put_alarm "dewflow-t1-lite-heartbeat-missing" "T1LiteHeartbeatCount" "Sum" "1" "LessThanThreshold" "$alarm_period" "1" "breaching" "Scheduler to Redis to Worker to log heartbeat is missing."

put_metric_filter "dewflow-terminal-task-failure" '{ ($.event = "chat_generation_terminal_failed") || ($.event = "chat_generation_recovery_failed") || ($.event = "knowledge_outbox_dead") }' "TerminalTaskFailureCount" "1" "0"
put_alarm "dewflow-terminal-task-failure" "TerminalTaskFailureCount" "Sum" "1" "GreaterThanOrEqualToThreshold" "$alarm_period" "1" "notBreaching" "A Chat generation or Knowledge outbox reached terminal failure."

put_metric_filter "dewflow-redis-risk" '{ ($.event = "redis_eviction_detected") || ($.event = "redis_restart_detected") }' "RedisRiskCount" "1" "0"
put_alarm "dewflow-redis-risk" "RedisRiskCount" "Sum" "1" "GreaterThanOrEqualToThreshold" "$alarm_period" "1" "notBreaching" "A Redis role reported eviction or restart risk."

put_metric_filter "dewflow-operability-probe-failure" '{ ($.event = "operability_probe_failed") || ($.event = "redis_probe_failed") }' "OperabilityProbeFailureCount" "1" "0"
put_alarm "dewflow-operability-probe-failure" "OperabilityProbeFailureCount" "Sum" "1" "GreaterThanOrEqualToThreshold" "$alarm_period" "1" "notBreaching" "The T1-Lite operability probe was degraded."

put_metric_filter "dewflow-t1-lite-synthetic-delivery" '{ $.event = "t1_lite_synthetic_alarm" }' "T1LiteSyntheticAlarmCount" "1" "0"
put_alarm "dewflow-t1-lite-synthetic-delivery" "T1LiteSyntheticAlarmCount" "Sum" "1" "GreaterThanOrEqualToThreshold" "60" "1" "notBreaching" "Controlled non-recovery T1-Lite SNS delivery validation."

put_metric_filter "dewflow-critical-log" '{ $.level = "CRITICAL" }' "CriticalLogCount" "1" "0"
put_alarm "dewflow-critical-log" "CriticalLogCount" "Sum" "1" "GreaterThanOrEqualToThreshold" "$alarm_period" "1" "notBreaching" "Dewflow emitted at least one CRITICAL log event."

put_metric_filter "dewflow-llm-routing-failed" '{ $.error_code = "LLM_ROUTING_FAILED" }' "LlmRoutingFailedCount" "1" "0"
put_alarm "dewflow-llm-routing-failed" "LlmRoutingFailedCount" "Sum" "1" "GreaterThanOrEqualToThreshold" "$alarm_period" "1" "notBreaching" "Dewflow LLM routing failed."

put_metric_filter "dewflow-knowledge-ingest-failed" '{ $.error_code = "KNOWLEDGE_FILE_INGEST_FAILED" }' "KnowledgeIngestFailedCount" "1" "0"
put_alarm "dewflow-knowledge-ingest-failed" "KnowledgeIngestFailedCount" "Sum" "1" "GreaterThanOrEqualToThreshold" "$alarm_period" "1" "notBreaching" "Dewflow knowledge ingestion failed."

put_metric_filter "dewflow-circuit-breaker-opened" '{ $.event = "circuit_breaker_opened" }' "CircuitBreakerOpenedCount" "1" "0"
put_alarm "dewflow-circuit-breaker-opened" "CircuitBreakerOpenedCount" "Sum" "1" "GreaterThanOrEqualToThreshold" "$alarm_period" "1" "notBreaching" "Dewflow circuit breaker opened."

put_metric_filter "dewflow-worker-rerank-degraded" '{ $.event = "worker_rerank_init_degraded" }' "WorkerRerankDegradedCount" "1" "0"
put_alarm "dewflow-worker-rerank-degraded" "WorkerRerankDegradedCount" "Sum" "1" "GreaterThanOrEqualToThreshold" "$alarm_period" "1" "notBreaching" "Dewflow worker rerank initialization degraded."

log_info "CloudWatch metric filters and alarms are configured."
log_info "Subscribe recipients to SNS topic: $topic_arn"
