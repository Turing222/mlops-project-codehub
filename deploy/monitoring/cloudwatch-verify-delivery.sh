#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/../.." && pwd)/scripts/lib/common.sh"

cd "$PROJECT_ROOT"

require_cmd aws
require_cmd uv
require_deploy_env_file
load_deploy_env

region="$DEPLOY_AWS_REGION"
log_group="$(deploy_control_env_value "DEPLOY_CW_LOG_GROUP" "/dewflow/prod")"
topic_name="$(deploy_control_env_value "DEPLOY_ALERTS_SNS_TOPIC_NAME" "dewflow-prod-alerts")"
topic_arn="$(deploy_control_env_value "DEPLOY_ALERTS_SNS_TOPIC_ARN" "")"
alarm_name="dewflow-t1-lite-synthetic-delivery"
stream_name="t1-lite-controlled-validation"
poll_attempts="$(deploy_control_env_value "DEPLOY_CW_VERIFY_POLL_ATTEMPTS" "24")"
poll_interval="$(deploy_control_env_value "DEPLOY_CW_VERIFY_POLL_SECONDS" "10")"

log_section "Validating CloudWatch Alarm to SNS delivery"

if [[ -z "$topic_arn" ]]; then
    topic_arn="$(aws sns create-topic \
        --region "$region" \
        --name "$topic_name" \
        --query TopicArn \
        --output text)"
fi

confirmed_subscriptions="$(aws sns list-subscriptions-by-topic \
    --region "$region" \
    --topic-arn "$topic_arn" \
    --query "length(Subscriptions[?SubscriptionArn!='PendingConfirmation' && SubscriptionArn!='Deleted'])" \
    --output text)"
if [[ "$confirmed_subscriptions" == "0" ]]; then
    log_error "SNS topic has no confirmed receiver; configure and confirm one before validation."
    exit 1
fi

alarm_count="$(aws cloudwatch describe-alarms \
    --region "$region" \
    --alarm-names "$alarm_name" \
    --query 'length(MetricAlarms)' \
    --output text)"
if [[ "$alarm_count" != "1" ]]; then
    log_error "Synthetic delivery alarm is missing; run make deploy-cloudwatch-setup first."
    exit 1
fi

state_before="$(aws cloudwatch describe-alarms \
    --region "$region" \
    --alarm-names "$alarm_name" \
    --query 'MetricAlarms[0].StateValue' \
    --output text)"
if [[ "$state_before" == "ALARM" ]]; then
    log_error "Synthetic alarm is already ALARM; wait for it to return to OK before retrying."
    exit 1
fi

stream_exists="$(aws logs describe-log-streams \
    --region "$region" \
    --log-group-name "$log_group" \
    --log-stream-name-prefix "$stream_name" \
    --query "logStreams[?logStreamName=='${stream_name}'].logStreamName" \
    --output text)"
if [[ "$stream_exists" != "$stream_name" ]]; then
    aws logs create-log-stream \
        --region "$region" \
        --log-group-name "$log_group" \
        --log-stream-name "$stream_name"
fi

timestamp_ms="$(uv run python - <<'PY'
import time

print(time.time_ns() // 1_000_000)
PY
)"
marker="t1-lite-$(date -u +%Y%m%dT%H%M%SZ)-$$"
request_file="$(mktemp)"
trap 'rm -f "$request_file"' EXIT

uv run python - "$log_group" "$stream_name" "$timestamp_ms" "$marker" >"$request_file" <<'PY'
import json
import sys

log_group, stream_name, timestamp_ms, marker = sys.argv[1:]
message = json.dumps(
    {
        "timestamp_ms": int(timestamp_ms),
        "level": "WARNING",
        "event": "t1_lite_synthetic_alarm",
        "error_code": "T1_LITE_SYNTHETIC_ALARM",
        "validation_marker": marker,
    },
    separators=(",", ":"),
)
print(
    json.dumps(
        {
            "logGroupName": log_group,
            "logStreamName": stream_name,
            "logEvents": [{"timestamp": int(timestamp_ms), "message": message}],
        }
    )
)
PY

aws logs put-log-events \
    --region "$region" \
    --cli-input-json "file://${request_file}" >/dev/null
log_info "Emitted controlled marker: $marker"

for ((attempt = 1; attempt <= poll_attempts; attempt += 1)); do
    state="$(aws cloudwatch describe-alarms \
        --region "$region" \
        --alarm-names "$alarm_name" \
        --query 'MetricAlarms[0].StateValue' \
        --output text)"
    if [[ "$state" == "ALARM" ]]; then
        changed_at="$(aws cloudwatch describe-alarms \
            --region "$region" \
            --alarm-names "$alarm_name" \
            --query 'MetricAlarms[0].StateUpdatedTimestamp' \
            --output text)"
        log_info "Alarm reached ALARM at $changed_at."
        log_info "Confirm actual receipt out of band; Alarm state alone is not delivery evidence."
        exit 0
    fi
    sleep "$poll_interval"
done

log_error "Alarm did not reach ALARM within the bounded polling window."
exit 1
