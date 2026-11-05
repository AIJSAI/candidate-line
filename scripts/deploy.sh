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
OPERATOR_EMAIL="${OPERATOR_EMAIL:?set OPERATOR_EMAIL in the environment, never in a file}"
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
  *) echo "unknown step"; exit 2 ;;
esac
