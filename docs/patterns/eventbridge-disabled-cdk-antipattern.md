# Anti-Pattern: EventBridge Rule Disabled by Default in CDK

**Type:** Anti-Pattern (avoid this)  
**Category:** Infrastructure / CDK / EventBridge  
**Status:** Actively harmful — silences the error monitoring pipeline at the infrastructure layer

---

## Name

EventBridge rule disabled-by-default in CDK — deploying an EventBridge rule with `enabled: false` (or equivalent) in the CDK stack, causing the rule to be created but never fire.

---

## File Paths

Where this anti-pattern was found (root cause of PR #451):
- `eventable/src/cdk/apiGatewayStack.ts` — CDK stack that builds API Gateway + Lambda integrations
- `eventable/src/cdk/appsync.ts` — AppSync CDK stack (check for similar patterns)

Where the correct pattern is documented:
- `CoreServices/docs/agents/arch/error-monitoring-system.md` — full EventBridge pipeline docs
- `forge-sandbox/docs/phase-0-summary.md` — Phase 0 context (PR #451 root cause)

---

## What It Looks Like

```typescript
// ❌ ANTI-PATTERN — EventBridge rule deployed but disabled
import { Rule, Schedule } from 'aws-cdk-lib/aws-events';
import { LambdaFunction } from 'aws-cdk-lib/aws-events-targets';

const errorMonitoringRule = new Rule(scope, 'ErrorMonitoringRule', {
  schedule: Schedule.cron({ minute: '0', hour: '2' }), // 2 AM UTC
  targets: [new LambdaFunction(errorAuditLambda)],
  enabled: false, // ← THE ANTI-PATTERN
});
```

Or equivalently, using `CfnRule`:

```typescript
// ❌ Also wrong — CfnRule with State: DISABLED
new CfnRule(scope, 'ErrorMonitoringRule', {
  scheduleExpression: 'cron(0 2 * * ? *)',
  state: 'DISABLED', // ← THE ANTI-PATTERN
  targets: [{ arn: errorAuditLambda.functionArn, id: 'ErrorAudit' }],
});
```

---

## Why It's Harmful

### 1. The rule is created but never fires

An EventBridge rule with `enabled: false` (CDK `Rule`) or `State: DISABLED` (CloudFormation `CfnRule`) is deployed to AWS but never triggers. The Lambda target is never invoked. The rule appears in the AWS console, giving a false sense of security — "the rule is there" — but it does nothing.

### 2. It silences the entire error monitoring pipeline at the infrastructure layer

The CoreServices error monitoring pipeline depends on EventBridge rules firing:
```
captureError → EventBridge PUT event → Rule matches → SQS → error-log Lambda → CloudWatch Logs
```

If the EventBridge rule is disabled, `captureError` still puts events to EventBridge, but no rule matches them. The events are silently dropped. The SQS queue never receives messages. The error-log Lambda never runs. CloudWatch Logs never get the error entries. The nightly audit sees 0 errors.

This is the worst kind of failure: the monitoring code runs correctly, but the infrastructure silently discards its output.

### 3. It's invisible in application code

Application developers writing `captureError` calls have no way to know the EventBridge rule is disabled. The `captureError` call succeeds (EventBridge accepts the PUT), the Lambda returns, and everything looks fine. The failure is entirely at the infrastructure layer.

### 4. Root cause of PR #451

This anti-pattern was the root cause of the error monitoring outage investigated in PR #451. An EventBridge rule was deployed with `enabled: false` — likely as a "deploy but don't activate yet" pattern during development — and was never re-enabled. The monitoring pipeline was silently broken for the entire period between deployment and discovery.

---

## How It Gets Introduced

Common scenarios where this anti-pattern appears:

1. **"Deploy but don't activate yet"** — Developer deploys the rule disabled to test the CDK stack without triggering the Lambda. Forgets to re-enable before merging.

2. **"Temporarily disable for debugging"** — Developer disables the rule to stop noise during an incident. Forgets to re-enable after the incident.

3. **Copy-paste from a disabled example** — Developer copies a CDK snippet that had `enabled: false` as a placeholder and doesn't notice.

4. **CDK default confusion** — Some CDK constructs default to disabled. Developer assumes the default is enabled.

---

## The Correct Pattern

```typescript
// ✅ CORRECT — EventBridge rule enabled by default
import { Rule, Schedule } from 'aws-cdk-lib/aws-events';
import { LambdaFunction } from 'aws-cdk-lib/aws-events-targets';

const errorMonitoringRule = new Rule(scope, 'ErrorMonitoringRule', {
  schedule: Schedule.cron({ minute: '0', hour: '2' }), // 2 AM UTC
  targets: [new LambdaFunction(errorAuditLambda)],
  // enabled: true is the default — do not set enabled: false
});
```

If you need to deploy a rule that should NOT fire in a specific environment (e.g., dev):

```typescript
// ✅ CORRECT — environment-aware enable/disable
const errorMonitoringRule = new Rule(scope, 'ErrorMonitoringRule', {
  schedule: Schedule.cron({ minute: '0', hour: '2' }),
  targets: [new LambdaFunction(errorAuditLambda)],
  enabled: props.environment === 'production', // explicit, documented, environment-scoped
});
```

---

## Detection

To audit for disabled EventBridge rules in CDK stacks:

```bash
# Search for disabled rules in CDK TypeScript files
grep -rn "enabled.*false\|enabled: false\|State.*DISABLED\|state.*disabled" \
  --include="*.ts" \
  $(find . -path "*/cdk/*" -o -path "*/infra/*" -o -name "*stack*") \
  | grep -v node_modules | grep -v ".d.ts"
```

To check deployed rules in AWS:

```bash
aws events list-rules --query "Rules[?State=='DISABLED'].[Name,State,ScheduleExpression]" --output table
```

---

## Gotchas

1. **The CDK `Rule` construct defaults to `enabled: true`.** You have to explicitly set `enabled: false` to disable. If you see `enabled: false` in a CDK stack, it was put there intentionally — ask why.

2. **`acquisition-analytics/src/snapshot/scheduler.service.ts:392`** has an `enabled: false` in application code (not CDK) — this is a different pattern (snapshot-level disable flag) but has similar silent-skip behavior. See tech debt WorkItem `54dd4ac8`.

3. **Disabled rules survive CloudFormation updates.** If you deploy a stack with `enabled: false`, then change to `enabled: true` and redeploy, the rule will be re-enabled. But if someone manually disables the rule in the AWS console, a CDK deploy with `enabled: true` will re-enable it — which may surprise the person who manually disabled it.

---

## Related Patterns

- [`handle-lambda-wrapper.md`](./handle-lambda-wrapper.md) — the application-layer pattern that feeds EventBridge
- [`captureError-rethrow.md`](./captureError-rethrow.md) — the manual alternative that also feeds EventBridge
