#!/bin/sh
# Block 2, step by step, with the break-glass admin profile for the stack and the builder profile for reads.
# Each step prints what it did and stops on the first failure; nothing here prints an account id, a secret, a
# phone number or a full ARN. Usage: deploy.sh <step>   steps: ecr | push | secrets | stack | url | status |
# probe-url | cockpit-forward | line-off | line-on | dial-off | dial-on | forget ACME-dddd | apply
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
keychain() { security find-generic-password -s candidate-line -a "$1" -w 2>/dev/null; }
E164='^\+1[2-9][0-9]{2}[2-9][0-9]{6}$'
task_id() { aws ecs list-tasks --profile "$ADMIN" --region "$REGION" --cluster candidate-line --service-name candidate-line --query 'taskArns[0]' --output text | sed 's#.*/##'; }
# One command on the running task. The volume's access point acts as the container's own user for every file, so
# a file the command writes is the line's to read and write.
on_task() {
  aws ecs execute-command --profile "$ADMIN" --region "$REGION" --cluster candidate-line --task "$(task_id)" --container line --interactive --command "sh -c \"$1\"" 2>&1 | grep -v -E 'Session Manager plugin|Starting session|Exiting session|Cannot perform start session'
}
# A secret from the login keychain into Secrets Manager under candidate-line/, through stdin so the value is never
# on a command line, and with only its length printed.
store_secret() {
  value="$(keychain "$1")" || { echo "$1 is not in the login keychain (make secret NAME=$1); nothing stored"; exit 2; }
  if aws secretsmanager describe-secret --profile "$ADMIN" --region "$REGION" --secret-id "candidate-line/$1" >/dev/null 2>&1; then
    printf '%s' "$value" | aws secretsmanager put-secret-value --profile "$ADMIN" --region "$REGION" --secret-id "candidate-line/$1" --secret-string file:///dev/stdin >/dev/null
  else
    printf '%s' "$value" | aws secretsmanager create-secret --profile "$ADMIN" --region "$REGION" --name "candidate-line/$1" --secret-string file:///dev/stdin >/dev/null
  fi
  echo "stored candidate-line/$1 (${#value} characters)"
}
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
  secrets)
    # The outbound call's three secrets (DR-025 section 19). Each is checked for its shape first, without being
    # printed, so the task never starts on a malformed allow-list or a short key.
    key="$(keychain INTAKE_SIGNING_KEY)" || key=""
    [ "${#key}" -ge 32 ] || { echo "INTAKE_SIGNING_KEY must be at least 32 characters (make secret NAME=INTAKE_SIGNING_KEY); nothing stored"; exit 2; }
    allowed="$(keychain OUTBOUND_ALLOWED_NUMBERS)" || allowed=""
    printf '%s' "$allowed" | tr ',' '\n' | grep -Eqv "$E164" && { echo "OUTBOUND_ALLOWED_NUMBERS must be comma-separated E.164 US numbers; nothing stored"; exit 2; }
    [ -n "$allowed" ] || { echo "OUTBOUND_ALLOWED_NUMBERS is empty; nothing stored"; exit 2; }
    line="$(keychain TWILIO_LINE_NUMBER)" || line=""
    printf '%s' "$line" | grep -Eq "$E164" || { echo "TWILIO_LINE_NUMBER must be one E.164 US number; nothing stored"; exit 2; }
    unset key allowed line
    for name in INTAKE_SIGNING_KEY OUTBOUND_ALLOWED_NUMBERS TWILIO_LINE_NUMBER; do store_secret "$name"; done ;;
  stack)
    [ -n "$OPERATOR_EMAIL" ] || { echo "set OPERATOR_EMAIL in the environment for the stack step"; exit 2; }
    # The task references the outbound call's three secrets whatever OutboundEnabled says, and ECS cannot start a task
    # whose secret reference is missing: with MinimumHealthyPercent 0 the old task stops first, so a stack deployed
    # before `deploy.sh secrets` would take the inbound line down too.
    for name in INTAKE_SIGNING_KEY OUTBOUND_ALLOWED_NUMBERS TWILIO_LINE_NUMBER; do aws secretsmanager describe-secret --profile "$ADMIN" --region "$REGION" --secret-id "candidate-line/$name" >/dev/null 2>&1 || { echo "candidate-line/$name is not in Secrets Manager: run deploy.sh secrets first, or the task cannot start"; exit 2; }; done
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
    if [ "$1" = "line-off" ]; then on_task "touch /app/var/kill && echo 'line off: every call now hears the closing line'"; else on_task "rm -f /app/var/kill && echo 'line on'"; fi ;;
  dial-off|dial-on)
    # The dialler's own stop (DR-025, Security): with var/no-dial present it places no call, while calls in and the
    # retention sweep go on. OUTBOUND_ENABLED and the kill switch still decide when it is absent.
    if [ "$1" = "dial-off" ]; then on_task "touch /app/var/no-dial && echo 'dialling off: no call is placed; calls in and the retention sweep go on'"; else on_task "rm -f /app/var/no-dial && echo 'dialling on, if OUTBOUND_ENABLED is 1 and the line is not killed'"; fi ;;
  forget)
    # A deletion request (spec 9.13): the application, its answers, its dials, its calls' traces and its raw number, on the task or,
    # with local as the third word, in this Mac's var/. The code is matched in full before it reaches any shell,
    # so nothing else can ride along with it.
    code="${2:-}"
    printf '%s' "$code" | grep -Eq '^ACME-[0-9]{4}$' || { echo "usage: deploy.sh forget ACME-dddd [local]"; exit 2; }
    # Through -c rather than -m, because the tools package imports the ledger first and -m would run a second copy.
    forget_py="import sys; from candidate_line.tools.ledger import main; sys.exit(main())"
    if [ "${3:-}" = "local" ]; then
      (cd "$ROOT" && uv run python -c "$forget_py" forget "$code")
    else
      on_task "STATE_PATH=/app/var/state.json CONTACTS_PATH=/app/var/contacts.json TRACE_STORE_PATH=/app/var/traces.sqlite python -c '$forget_py' forget $code"
    fi ;;
  apply)
    # A signed synthetic application for a walk (DR-025 section 10), posted to URL (the line on this Mac by
    # default). PHONE is a fictional 555-01xx number by default, which is on no allow-list, so the line stores the
    # application as not dialled; PHONE=probe uses the probe's number from the keychain. The key and the number go
    # to the signer on stdin, never on a command line, and the reply carries the code and the status only.
    url="${URL:-http://127.0.0.1:8000}"
    pin="${PIN:-}"
    printf '%s' "$pin" | grep -Eq '^[0-9]{4}$' || { echo "set PIN to the four digits the walk will say on the call"; exit 2; }
    key="$(keychain INTAKE_SIGNING_KEY)" || { echo "INTAKE_SIGNING_KEY is not in the login keychain (make secret NAME=INTAKE_SIGNING_KEY)"; exit 2; }
    phone="${PHONE:-+15555550100}"
    if [ "$phone" = "probe" ]; then phone="$(keychain TWILIO_PROBE_NUMBER)" || { echo "TWILIO_PROBE_NUMBER is not in the login keychain"; exit 2; }; fi
    printf '%s' "$phone" | grep -Eq "$E164" || { echo "PHONE must be an E.164 US number or probe"; exit 2; }
    printf '%s\n%s\n' "$key" "$phone" | python3 -c '
import hashlib, hmac, json, secrets, sys, time, urllib.error, urllib.request
from datetime import datetime, timezone
key, phone = sys.stdin.read().split("\n")[:2]
url, first, role, zone, pin, version = sys.argv[1:7]
consent = {"version": version, "accepted": True, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": "operator"}
body = json.dumps({"first_name": first, "role": role, "phone": phone, "zone": zone, "pin": pin, "consent": consent}).encode()
stamp, nonce = str(int(time.time())), secrets.token_urlsafe(24)
signature = hmac.new(key.encode(), f"{stamp}.{nonce}.".encode() + body, hashlib.sha256).hexdigest()
headers = {"Content-Type": "application/json", "X-Intake-Timestamp": stamp, "X-Intake-Nonce": nonce, "X-Intake-Signature": signature}
request = urllib.request.Request(url.rstrip("/") + "/applications", data=body, method="POST", headers=headers)
try:
    with urllib.request.urlopen(request, timeout=15) as reply:
        print(reply.status, reply.read().decode()[:200])
except urllib.error.HTTPError as refused:
    print(refused.code, refused.read().decode()[:200])
    sys.exit(1)
' "$url" "${FIRST:-Ama}" "${ROLE:-care-aide}" "${ZONE:-America/Chicago}" "$pin" "${CONSENT_VERSION:-consent-2026-11-05}" ;;
  *) echo "unknown step"; exit 2 ;;
esac
