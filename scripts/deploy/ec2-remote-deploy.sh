#!/usr/bin/env bash
# Remote deploy entrypoint executed on the EC2 host through SSM Run Command.
# Expects /opt/dewflow/repo checked out at the release ref and deploy/.env.ec2
# populated with host-specific values (see docs/platform/deploy-ec2.md).

set -euo pipefail

image_tag="${1:?usage: ec2-remote-deploy.sh <image-tag>}"
ecr_registry="${ECR_REGISTRY:?ECR_REGISTRY is required}"
aws_region="${AWS_REGION:-us-west-2}"
last_good_file="/opt/dewflow/last-good-tag"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$script_dir/../lib/common.sh"
cd "$PROJECT_ROOT"

deploy_env_file="deploy/.env.ec2"
test -f "$deploy_env_file" || { echo "missing $deploy_env_file on host" >&2; exit 1; }

secret_source="$(deploy_control_env_value "DEPLOY_SECRET_SOURCE" "files")"
case "$secret_source" in
    files)
        ;;
    aws)
        make deploy-secrets-materialize
        ;;
    *)
        echo "unsupported DEPLOY_SECRET_SOURCE: $secret_source" >&2
        exit 1
        ;;
esac

aws ecr get-login-password --region "$aws_region" \
    | docker login --username AWS --password-stdin "$ecr_registry" >/dev/null

web_image="${ecr_registry}/dewflow-backend:${image_tag}-web"
ai_image="${ecr_registry}/dewflow-backend:${image_tag}-ai"
sed -i \
    -e "s|^DOCKER_IMAGE_NAME_WEB=.*|DOCKER_IMAGE_NAME_WEB=${web_image}|" \
    -e "s|^DOCKER_IMAGE_NAME_AI=.*|DOCKER_IMAGE_NAME_AI=${ai_image}|" \
    "$deploy_env_file"

make deploy-ec2-check
DEPLOY_PULL_IMAGES=true make deploy-ec2-up
make deploy-ec2-wait
make deploy-ec2-verify

printf '%s\n' "$image_tag" > "$last_good_file"
echo "deploy succeeded: ${image_tag}"
