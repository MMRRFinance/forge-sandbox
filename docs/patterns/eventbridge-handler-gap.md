# Anti-Pattern: `emitEvent` Alone Is Insufficient for Error Monitoring

**Type:** Anti-Pattern (avoid this)
**Category:** Error Monitoring / EventBridge / Lambda
**Status:** Canonical — confirmed gap in ms-graph-integration and other services

---

## Name

EventBridge handler gap — calling `emitEvent(...)` to publish a domain event does NOT provide error monitoring. The Lambda handler must also be wrapped with `handleLambda` (or `captureError` + re-throw) to capture failures. Services that only call `emitEvent` have a silent monitoring blind spot.

---

## File Paths

Where the gap was confirmed:
- `ms-graph-integration/src/modules/graph-webhooks/subscriptionRenewal.ts:106` — comment says "The outer handleLambda wrapper..." but no `handleLambda` call exists; the handler only calls `emitEvent` for the success path
- `ms-graph-integration/src/modules/graph-webhooks/changeNotification.ts` — emits domain events on success; no error wrapper present

Where the correct pattern is implemented (reference):
- `payments/.eventable/aws/services/services.ts` — `handleLambda` wraps every handler, including those that also call `emitEvent`
- `commitment-service/src/jobs/reminderSender.ts:139` — `captureError` + re-throw in outer catch, separate from the `emitEvent` calls inside the try block

---

## What It Looks Like

### The gap (wrong):

```typescript
// ms-graph-integration/src/modules/graph-webhooks/subscriptionRenewal.ts
export const handler = async (event: ScheduledEvent): Promise<void> => {
  const result = await renewSubscriptions();

  // ✅ This emits a domain event on SUCCESS — correct for business logic
  await emitEvent('graph-webhooks.subscription-renewed', { result });

  // ❌ But if renewSubscriptions() throws, nothing captures the error.
  // Lambda marks the invocation FAILED in CloudWatch, but:
  // - No EventBridge error event is emitted
  // - No alert fires
  // - The failure is invisible to the error monitoring system
};
```

### The fix (correct):

```typescript
// Option A: handleLambda wrapper (preferred when .eventable/ is available)
export const handler = handleLambda(
  async (event: ScheduledEvent): Promise<void> => {
    const result = await renewSubscriptions();
    await emitEvent('graph-webhooks.subscription-renewed', { result });
  },
  { functionName: 'subscriptionRenewal' }
);

// Option B: captureError + re-throw (for services without .eventable/)
export const handler = async (event: ScheduledEvent): Promise<void> => {
  try {
    const result = await renewSubscriptions();
    await emitEvent('graph-webhooks.subscription-renewed', { result });
  } catch (error) {
    captureError(error instanceof Error ? error : new Error(String(error)), {
      functionName: 'subscriptionRenewal',
      event,
    }).catch((monitoringErr) => {
      console.error('captureError failed:', monitoringErr);
    });
    throw error; // re-throw — Lambda marks invocation FAILED
  }
};
```

---

## Why It Happens

`emitEvent` and `captureError`/`handleLambda` serve completely different purposes:

| Mechanism | Purpose | Fires when |
|-----------|---------|------------|
| `emitEvent(...)` | Publish a **domain event** (business logic) | Handler **succeeds** |
| `handleLambda` / `captureError` | Publish an **error event** (monitoring) | Handler **throws** |

A handler that only calls `emitEvent` has monitoring coverage for the happy path only. The error path is invisible to the EventBridge-based alerting system. CloudWatch will record the Lambda invocation as FAILED, but no alert fires and no error event appears in the monitoring stream.

The confusion arises because both mechanisms use EventBridge under the hood. Developers see `emitEvent` and assume the handler is "wired up to EventBridge" — which is true for domain events, but irrelevant for error monitoring.

---

## Detection

```bash
# Find Lambda handlers that call emitEvent but lack handleLambda or captureError
# Step 1: Find files with emitEvent
grep -rn "emitEvent" --include="*.ts" . | grep -v node_modules | grep -v ".d.ts" | grep -v ".eventable/"

# Step 2: For each file found, check if handleLambda or captureError is also present
# If a handler file has emitEvent but NOT (handleLambda OR captureError), it has the gap.
grep -rn "emitEvent" --include="*.ts" . | grep -v node_modules \
  | awk -F: '{print $1}' | sort -u \
  | xargs -I{} sh -c 'grep -l "handleLambda\|captureError" {} 2>/dev/null || echo "GAP: {}"'
```

---

## When This Matters

**The gap is critical when:**
- The Lambda is a scheduled job (EventBridge rule triggers it on a cron). Failures are silent until someone notices the job hasn't run.
- The Lambda processes webhook notifications (like `subscriptionRenewal`). A failure means events are dropped with no alert.
- The Lambda is not in `.eventable/` — codegen won't add `handleLambda` automatically.

**The gap is lower risk when:**
- The Lambda is synchronous (API Gateway invocation) — the caller gets the error response directly.
- The Lambda has a DLQ configured — failed invocations are captured for retry even without `captureError`.

---

## Canonical Example

From `ms-graph-integration` (the confirmed gap, tech debt WorkItem `e0a74d72`):

```typescript
// subscriptionRenewal.ts:106 — comment describes intended behavior that was never implemented
// "The outer handleLambda wrapper catches any unhandled errors..."
// Reality: no handleLambda wrapper exists. The comment is aspirational, not descriptive.
```

The fix is to add `handleLambda` wrapping in the `.eventable/` generated output, or add `captureError` + re-throw manually if the service doesn't use codegen.

---

## Gotchas

1. **The misleading comment in `subscriptionRenewal.ts` is a trap.** It says `handleLambda` is present. It is not. Always verify with `grep handleLambda <file>` rather than trusting comments.

2. **`emitEvent` failures don't help either.** If `emitEvent` itself throws (EventBridge is down), and there's no outer error wrapper, that failure is also invisible. The `captureError` wrapper catches errors from the entire handler body, including `emitEvent` calls.

3. **`.eventable/` codegen adds `handleLambda` automatically — but only for handlers registered in the eventable config.** If a handler is wired up manually in CDK (not through the eventable config), codegen won't wrap it. Check the CDK stack to verify the Lambda's `handler` property points to the generated `.eventable/` wrapper, not the raw `src/` function.

4. **DLQ is not a substitute for `captureError`.** A DLQ captures the failed event for retry, but does not emit an error event to the monitoring stream. Alerts that watch for error events won't fire. Both DLQ and `captureError` serve different purposes and should coexist.

---

## Related Patterns

- [`handle-lambda-wrapper.md`](./handle-lambda-wrapper.md) — `handleLambda` implementation and when to use it
- [`captureError-rethrow.md`](./captureError-rethrow.md) — manual alternative for services without `.eventable/`
- [`eventbridge-disabled-cdk-antipattern.md`](./eventbridge-disabled-cdk-antipattern.md) — another EventBridge monitoring gap (disabled rules)
