#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/../.." && pwd)/scripts/lib/common.sh"

cd "$PROJECT_ROOT"

require_cmd aws
require_deploy_env_file
load_deploy_env

region="$(deploy_env_value "DEPLOY_AWS_REGION" "us-east-1")"
log_group="$(deploy_env_value "DEPLOY_CW_LOG_GROUP" "/dewflow/prod")"
metric_namespace="$(deploy_env_value "DEPLOY_CW_METRIC_NAMESPACE" "Dewflow/Logs")"
topic_name="$(deploy_env_value "DEPLOY_ALERTS_SNS_TOPIC_NAME" "dewflow-prod-alerts")"
topic_arn="$(deploy_env_value "DEPLOY_ALERTS_SNS_TOPIC_ARN" "")"
alarm_period="$(deploy_env_value "DEPLOY_CW_ALARM_PERIOD_SECONDS" "300")"

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

put_metric_filter() {
    local filter_name="$1"
    local pattern="$2"
    local metric_name="$3"

    aws logs put-metric-filter \
        --region "$region" \
        --log-group-name "$log_group" \
        --filter-name "$filter_name" \
        --filter-pattern "$pattern" \
        --metric-transformations \
            metricName="$metric_name",metricNamespace="$metric_namespace",metricValue=1,defaultValue=0
}

put_alarm() {
    local alarm_name="$1"
    local metric_name="$2"
    local description="$3"

    aws cloudwatch put-metric-alarm \
        --region "$region" \
        --alarm-name "$alarm_name" \
        --alarm-description "$description" \
        --namespace "$metric_namespace" \
        --metric-name "$metric_name" \
        --statistic Sum \
        --period "$alarm_period" \
        --evaluation-periods 1 \
        --datapoints-to-alarm 1 \
        --threshold 1 \
        --comparison-operator GreaterThanOrEqualToThreshold \
        --treat-missing-data notBreaching \
        --alarm-actions "$topic_arn" \
        --ok-actions "$topic_arn"
}

put_metric_filter "dewflow-critical-log" '{ $.level = "CRITICAL" }' "CriticalLogCount"
put_alarm "dewflow-critical-log" "CriticalLogCount" "Dewflow emitted at least one CRITICAL log event."

put_metric_filter "dewflow-llm-routing-failed" '{ $.error_code = "LLM_ROUTING_FAILED" }' "LlmRoutingFailedCount"
put_alarm "dewflow-llm-routing-failed" "LlmRoutingFailedCount" "Dewflow LLM routing failed."

put_metric_filter "dewflow-knowledge-ingest-failed" '{ $.error_code = "KNOWLEDGE_FILE_INGEST_FAILED" }' "KnowledgeIngestFailedCount"
put_alarm "dewflow-knowledge-ingest-failed" "KnowledgeIngestFailedCount" "Dewflow knowledge ingestion failed."

put_metric_filter "dewflow-circuit-breaker-opened" '{ $.event = "circuit_breaker_opened" }' "CircuitBreakerOpenedCount"
put_alarm "dewflow-circuit-breaker-opened" "CircuitBreakerOpenedCount" "Dewflow circuit breaker opened."

put_metric_filter "dewflow-worker-rerank-degraded" '{ $.event = "worker_rerank_init_degraded" }' "WorkerRerankDegradedCount"
put_alarm "dewflow-worker-rerank-degraded" "WorkerRerankDegradedCount" "Dewflow worker rerank initialization degraded."

log_info "CloudWatch metric filters and alarms are configured."
log_info "Subscribe recipients to SNS topic: $topic_arn"
