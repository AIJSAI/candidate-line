# DR-002: AWS sign-in with no long-lived key, and the spend alarm

Status: DRAFT
Built: pre-built (PREBUILT.md row 1)
Commit: (filled when the item lands)

## What it is

How this Mac's AWS CLI gets credentials for the build days and the live session, and what guards the spend. One Identity Center user, two permission sets, two CLI profiles, a short-lived session token instead of a key, and a budget alarm.

## The decision

IAM Identity Center, as an organization instance in us-east-1. The account was standalone, so an Organization was created from the CLI first (`aws organizations create-organization --feature-set ALL`), making it the management account; enabling Identity Center and adding the user are the two console steps, declared here, and they were done on 2026-11-02 from a **federated console session** opened from the existing CLI identity (`aws sts get-federation-token` with the administrator policy, exchanged at the sign-in federation endpoint for a two-hour console session, opened in Chrome by `open`; no root sign-in, no MFA prompt, no credential printed). The instance is a **single-Region organization instance in us-east-1 with the AWS owned key**: the console's default was multi-Region with a customer managed KMS key, which bills monthly and buys nothing for one person in one Region. One user. Two permission sets:

- `CandidateLineBuilder`, the daily profile `candidate-line`, 8-hour session. One inline policy, `infra/aws/candidate-line-builder-policy.json`, plus the AWS managed `IAMReadOnlyAccess`. It can invoke Bedrock models, discover them and request access, manage guardrails, hold the three AWS Marketplace actions the first use of a Claude model needs, stream to Transcribe, synthesize with Polly, view and modify budgets, read cost, quotas, metrics, logs and the CloudTrail trail. It cannot provision capacity, fine-tune, import or deploy a model, create a knowledge base or a marketplace endpoint, or write IAM.
- `CandidateLineAdmin`, the break-glass profile `candidate-line-admin`, AdministratorAccess, 1-hour session, for the moment a command needs a permission the builder lacks. Using it is a visible choice on screen, and the builder policy gains the missing action afterwards by a diff.

`aws sso login --profile candidate-line` opens the browser once and writes a short-lived token under `~/.aws/sso/cache`; the CLI exchanges it for role credentials that expire with the session. No long-lived key exists in any file on this Mac once the old one is gone.

The IAM user's access key in the local credentials file (details removed) is deactivated the moment the new profile passes `aws sts get-caller-identity`, and deleted on Tuesday 2026-11-03 if nothing on this Mac has asked for it. Deactivation is reversible; deletion is not.

The budget alarm: (item 2, pending) an AWS Budgets monthly cost budget with notifications on actual and forecast spend to an email alert channel. The cap is James's money call and is recorded here once set, never the address.

## The alternative rejected, and why

1. **The long-lived key in `~/.aws/credentials`, as found.** A lost laptop, a pasted log or a committed dotfile leaks a permanent admin credential with no MFA behind it. It also makes the on-screen answer to "how does your CLI authenticate" the wrong one.
2. **The same key moved into 1Password, fetched per command by the 1Password shell plugin.** Five minutes, no console step, and the key leaves the file. But a permanent admin key still exists, rotation stays manual, and anyone holding the unlocked vault holds the account.
3. **One AdministratorAccess permission set only.** Never a bottleneck, but every daily command runs as admin, so a mistyped command can buy provisioned throughput or start a fine-tune.
4. **One scoped permission set only.** The most secure shape, but a missing action on a shared screen on Wednesday stops the build cold. The second, short-session admin profile removes that risk at the cost of one more profile name.
5. **An account instance of Identity Center, with no Organization.** Simpler, but it cannot grant AWS account access through permission sets: the instances page (read 2026-11-01) marks multi-account permissions "Yes" only for the instance in the Organizations management account.

## What would change the decision

A second person needs access (Identity Center already has the user model; a shared key never would). A CI runner needs credentials (then an OIDC-assumed role, never a key). The builder set blocks a command more than once in a day (widen it by a diff to the policy file, not by living in the admin profile). AWS stops billing Claude on Bedrock through AWS Marketplace (then the three Marketplace actions leave the policy).

## Evidence

- State read on 2026-11-01 before any change: `aws sts get-caller-identity`, `aws iam list-access-keys --user-name james`, `aws iam list-mfa-devices --user-name james`, `aws iam get-access-key-last-used`, `aws cloudtrail lookup-events` on the key, `aws sso-admin list-instances` in us-east-1, us-east-2 and us-west-2 (all empty), `aws organizations describe-organization` (not in an organization).
- `docs/refs/2026-11-01-aws-identity-center-instances.txt`: the capability table (organization instance vs account instance).
- `docs/refs/2026-11-01-aws-cli-configure-sso.txt`: the `sso-session` and `profile` sections of `~/.aws/config`.
- `docs/refs/2026-11-01-aws-bedrock-model-access.txt`: model access is enabled on first invoke when the identity holds `aws-marketplace:Subscribe`, `Unsubscribe` and `ViewSubscriptions`; Anthropic models also need the one-time use-case form (`PutUseCaseForModelAccess`); a valid payment method is required.
- The AWS managed policy `AmazonBedrockFullAccess` v11 (read from the account on 2026-11-01) carries those three Marketplace actions in its statement `MarketplaceOperationsFromBedrockFor3pModels`; the builder policy copies the three actions and leaves the rest of that policy behind.
- `aws accessanalyzer validate-policy` on the builder policy found three actions that do not exist in IAM: `bedrock:Converse`, `bedrock:ConverseStream` and `bedrock:InvokeModelWithBidirectionalStream`. Converse is authorized by `bedrock:InvokeModel` (Bedrock user guide, identity-based policy examples, read 2026-11-01). The bidirectional stream "requires permission for the bedrock:InvokeModel action" (`docs/refs/2026-11-01-aws-bedrock-api-invoke-model-with-bidirectional-stream.txt`, line 12). Final lint: 0 findings.
- **Commands run to build it, 2026-11-02, 13:05 to 13:27 CT** (ids and the account number stay out of this file):
  - `aws sts get-federation-token --name james-console --policy-arns arn=arn:aws:iam::aws:policy/AdministratorAccess --duration-seconds 7200`, the credentials passed to `https://signin.aws.amazon.com/federation?Action=getSigninToken`, the returned token into the `Action=login` URL, opened with `open`. The session ran as "james-console" in the console.
  - Console: IAM Identity Center, Enable, Single-Region instance (AWS owned key), Enable. Result: an organization instance in us-east-1; the access portal URL is the `d-...awsapps.com/start` form, written to `~/.aws/config` and nowhere in this repository.
  - `aws sso-admin create-permission-set --name CandidateLineBuilder --session-duration PT8H`, then `put-inline-policy-to-permission-set` from `infra/aws/candidate-line-builder-policy.json` and `attach-managed-policy-to-permission-set` with `IAMReadOnlyAccess`.
  - `aws sso-admin create-permission-set --name CandidateLineAdmin --session-duration PT1H`, then `attach-managed-policy-to-permission-set` with `AdministratorAccess`.
  - Console: Users, Add user: username `james`, "Send an email to this user with password setup instructions", no group. The invitation link lives seven days.
  - `aws identitystore list-users --filters AttributePath=UserName,AttributeValue=james` for the user id, then `aws sso-admin create-account-assignment` twice (USER, AWS_ACCOUNT, each permission set); both `describe-account-assignment-creation-status` reads returned SUCCEEDED.
  - `~/.aws/config` gained `[sso-session candidate-line]` (start URL, region us-east-1, scope `sso:account:access`) and the profiles `candidate-line` (CandidateLineBuilder) and `candidate-line-admin` (CandidateLineAdmin); the previous file is kept beside it as a dated backup.
  - **Still to run, in this order, once James has set his password from the email and added his MFA:** `aws sso login --profile candidate-line` (opens the browser once), `aws sts get-caller-identity --profile candidate-line`, then `aws iam update-access-key --user-name james --access-key-id <the AKIA id> --status Inactive`, and `make text` on the new profile to prove the line still reaches Bedrock. Deletion of the key waits for Tuesday, as above.

## Say it like this

> (written after the teach-back)

## Teach-back

(not yet)
