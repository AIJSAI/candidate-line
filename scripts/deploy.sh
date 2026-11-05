#!/bin/sh
# Block 2, step by step, with the break-glass admin profile for the stack and the builder profile for reads.
# Each step prints what it did and stops on the first failure; nothing here prints an account id, a secret or a
# full ARN. Usage: deploy.sh <step>   steps: ecr | push | stack | url | status | probe-url
set -eu
ADMIN=candidate-line-admin; BUILD=candidate-line; REGION=us-east-1
REPO="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE=$ROOT/infra/aws/candidate-line-stack.yaml
STACK=candidate-line
# The operator's address is a stack parameter and is read from the environment only by the stack step, never from a file.
OPERATOR_EMAIL="${OPERATOR_EMAIL:-}"
mask() { sed -E 's/[0-9]{12}/<account>/g'; }
registry() { aws sts get-caller-identity --profile "$ADMIN" --query Account --output text | sed 's/$/.dkr.ecr.'"$REGION"'.amazonaws.com/'; }
sha() { git -C "$REPO" rev-parse --short HEAD; }
case "${1:?step}" in
  ecr)
    # the repository alone first (the stack also declares it; an existing one is adopted by a retain policy only
    # if names match, so it is created by the stack: this step only logs the docker client in)
    aws ecr get-login-password --profile "$ADMIN" --region "$REGION" | docker login --username AWS --password-stdin "$(registry)" 2>&1 | mask | tail -1 ;;
  push)
    tag="$(registry)/candidate-line:$(sha)"
    docker buildx build --platform linux/arm64 --load -t "candidate-line:$(sha)" "$REPO" 2>&1 | tail -3
    docker tag "candidate-line:$(sha)" "$tag"
    docker push "$tag" 2>&1 | mask | tail -2
    echo "pushed candidate-line:$(sha)" ;;
  stack)
    [ -n "$OPERATOR_EMAIL" ] || { echo "set OPERATOR_EMAIL in the environment for the stack step"; exit 2; }
    pl="$(aws ec2 describe-managed-prefix-lists --profile "$ADMIN" --region "$REGION" --filters Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing --query 'PrefixLists[0].PrefixListId' --output text)"
    echo "cloudfront prefix list: $pl"
    aws cloudformation deploy --profile "$ADMIN" --region "$REGION" --stack-name "$STACK" --template-file "$TEMPLATE" \
      --capabilities CAPABILITY_NAMED_IAM --no-fail-on-empty-changeset \
      --parameter-overrides ImageUri="$(registry)/candidate-line:$(sha)" OperatorEmail="$OPERATOR_EMAIL" CloudFrontPrefixListId="$pl" \
        PublicBaseUrl="${PUBLIC_BASE_URL:-}" 2>&1 | mask | tail -5 ;;
  url)
    aws cloudformation describe-stacks --profile "$ADMIN" --region "$REGION" --stack-name "$STACK" --query "Stacks[0].Outputs[?OutputKey=='CloudFrontDomain'].OutputValue" --output text ;;
  status)
    aws cloudformation describe-stacks --profile "$ADMIN" --region "$REGION" --stack-name "$STACK" --query 'Stacks[0].StackStatus' --output text
    aws ecs describe-services --profile "$ADMIN" --region "$REGION" --cluster candidate-line --services candidate-line --query 'services[0].{running:runningCount,desired:desiredCount,deployments:length(deployments)}' --output json 2>/dev/null | tr -d '\n '; echo
    aws cloudformation describe-stack-events --profile "$ADMIN" --region "$REGION" --stack-name "$STACK" --max-items 12 --query 'StackEvents[].[Timestamp,ResourceStatus,LogicalResourceId,ResourceStatusReason]' --output text 2>/dev/null | mask | cut -c1-200 ;;
  probe-url)
    host="$(aws cloudformation describe-stacks --profile "$ADMIN" --region "$REGION" --stack-name "$STACK" --query "Stacks[0].Outputs[?OutputKey=='CloudFrontDomain'].OutputValue" --output text)"
    echo "health through CloudFront: $(curl -s -m 15 -o /dev/null -w '%{http_code}' "https://$host/health") at https://$host/health" ;;
  cockpit-forward)
    # The recruiter's cockpit, reached through the task's SSM channel on a local port; Ctrl-C ends it.
    task="$(aws ecs list-tasks --profile "$ADMIN" --region "$REGION" --cluster candidate-line --service-name candidate-line --query 'taskArns[0]' --output text | sed 's#.*/##')"
    rid="$(aws ecs describe-tasks --profile "$ADMIN" --region "$REGION" --cluster candidate-line --tasks "$task" --query 'tasks[0].containers[?name==`line`].runtimeId' --output text)"
    echo "cockpit at http://127.0.0.1:8011/ while this runs"
    aws ssm start-session --profile "$ADMIN" --region "$REGION" --target "ecs:candidate-line_${task}_${rid}" --document-name AWS-StartPortForwardingSession --parameters '{"portNumber":["8001"],"localPortNumber":["8011"]}' ;;
  line-off|line-on)
    # The kill switch (DR-021): with the file present every call hears the closing line and ends; removing it
    # reopens the line on the next call. The file lives on the task's volume, so it outlives a restart.
    task="$(aws ecs list-tasks --profile "$ADMIN" --region "$REGION" --cluster candidate-line --service-name candidate-line --query 'taskArns[0]' --output text | sed 's#.*/##')"
    if [ "$1" = "line-off" ]; then cmd="touch /app/var/kill && echo 'line off: every call now hears the closing line'"; else cmd="rm -f /app/var/kill && echo 'line on'"; fi
    aws ecs execute-command --profile "$ADMIN" --region "$REGION" --cluster candidate-line --task "$task" --container line --interactive --command "sh -c \"$cmd\"" 2>&1 | grep -v -E 'Session Manager plugin|Starting session|Exiting session|Cannot perform start session' ;;
  *) echo "unknown step"; exit 2 ;;
esac
