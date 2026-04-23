# Anti-Pattern: `return { statusCode: 500 }` — Silent Error Swallow

**Type:** Anti-Pattern (avoid this)  
**Category:** Error Handling / Error Monitoring  
**Status:** Actively harmful — causes silent failures

---

## Name

`return { statusCode: 500 }` — returning an HTTP error response from a Lambda catch block instead of throwing, silently swallowing the error.

---

## File Paths

Where this anti-pattern was historically present (now fixed or flagged):
- `eventable/aws/lambda.ts` — contains the correct pattern (`throw`) for comparison
- `eventable/aws/errorMonitoring.ts` — the monitoring pipeline that never fires when errors are swallowed
- `self-service-api/src/index.ts` — related anti-pattern: `throw "string"` (loses stack trace; see `captureError-rethrow.md`)

Where this pattern is documented as wrong:
- `CoreServices/docs/agents/arch/error-monitoring-system.md` — explains why re-throw is required
- `forge-sandbox/docs/patterns/captureError-rethrow.md` — the correct replacement

---

## What It Looks Like

```typescript
// ❌ ANTI-PATTERN — do not do this
export const handler = async (event: APIGatewayEvent) => {
  try {
    const result = await processPayment(event);
    return { statusCode: 200, body: JSON.stringify(result) };
  } catch (error) {
    console.error('Payment failed:', error);
    return { statusCode: 500, body: JSON.stringify({ error: 'Internal server error' }) };
    // ↑ Error is SWALLOWED. Lambda invocation is marked SUCCESS.
    // EventBridge never fires. CloudWatch alarm never triggers.
    // Slack alert never sends. The error is invisible.
  }
};
```

---

## Why It's Harmful

### 1. Lambda marks the invocation as SUCCESS

When a Lambda handler returns (any value, including `{ statusCode: 500 }`), the Lambda runtime marks the invocation as **SUCCEEDED**. This means:
- **No DLQ delivery** — the event is not sent to the dead-letter queue.
- **No retry** — Lambda does not retry successful invocations.
- **No CloudWatch `Errors` metric increment** — the `AWS/Lambda Errors` metric only counts invocations that throw.
- **No CloudWatch alarm** — alarms on `Errors` metric never fire.

### 2. The error monitoring pipeline never fires

The CoreServices error monitoring pipeline is:
```
captureError / handleLambda → EventBridge → SQS → error-log Lambda → CloudWatch Logs → nightly audit → email report
```

`captureError` and `handleLambda` are only called when an error is **thrown**. If the catch block returns instead of throwing, the entire pipeline is bypassed. The error exists only in `console.error` output — buried in CloudWatch Logs with no alarm, no aggregation, no report.

### 3. Errors accumulate silently

A handler that returns `{ statusCode: 500 }` on every invocation looks healthy to all monitoring systems. The error rate in CloudWatch is 0%. The nightly audit reports 0 errors. The team has no idea the handler is failing on every call.

### 4. Observable symptom

The only way to detect this anti-pattern in production is:
- A human notices the feature is broken (customer complaint, manual test).
- Someone manually searches CloudWatch Logs for `console.error` output.
- The nightly error audit shows 0 errors for a handler that should have errors (absence of signal is the signal).

---

## When It Might Seem Correct (But Isn't)

**"I need to return a 500 to the API caller."**

You can return a 500 to the caller AND throw for monitoring. Use `captureError` before returning:

```typescript
// ✅ CORRECT — notify caller AND fire monitoring
export const handler = async (event: APIGatewayEvent) => {
  try {
    const result = await processPayment(event);
    return { statusCode: 200, body: JSON.stringify(result) };
  } catch (error) {
    // Fire monitoring (async, don't await)
    captureError(
      error instanceof Error ? error : new Error(String(error)),
      { functionName: 'processPayment', event }
    ).catch((monitoringErr) => console.error('captureError failed:', monitoringErr));

    // Return 500 to caller
    return {
      statusCode: 500,
      body: JSON.stringify({ error: 'Internal server error' }),
    };
    // Note: for API Gateway handlers, returning (not throwing) is correct
    // because throwing would cause API Gateway to return a 502 Bad Gateway.
    // captureError handles the monitoring side.
  }
};
```

**"The handler is an API Gateway handler — I can't throw."**

Correct — API Gateway Lambda handlers should return `{ statusCode: 500 }` to the caller. But you must still call `captureError` before returning. The `eventable/src/codeGen/aws/apiGateway/utils.ts` codegen handles this correctly at line 168–172:

```typescript
// eventable/src/codeGen/aws/apiGateway/utils.ts:168-172
console.log("ERROR_MONITORING: About to call captureError");
await captureError(e, event, dependencies);
console.log("ERROR_MONITORING: captureError completed");
// ...
console.error("ERROR_MONITORING: captureError failed:", captureErr);
```

**"I'm in a batch job and I want partial success."**

Batch jobs that process items one-by-one should catch per-item errors and accumulate them in an `errors[]` array. The outer job-level catch should still use `captureError + throw`. See `captureError-rethrow.md` for the batch job pattern.

---

## How to Fix

1. **For EventBridge/SQS handlers:** Replace `return { statusCode: 500 }` with `captureError(...); throw error;`. See `captureError-rethrow.md`.

2. **For API Gateway handlers:** Keep the `return { statusCode: 500 }` for the caller, but add `captureError(...)` before the return. The eventable codegen does this automatically for services with `.eventable/`.

3. **Add ESLint rule to prevent recurrence:**
   ```json
   // .eslintrc
   {
     "rules": {
       "no-restricted-syntax": [
         "error",
         {
           "selector": "CatchClause > BlockStatement > ReturnStatement",
           "message": "Do not return from catch blocks — use captureError + throw instead."
         }
       ]
     }
   }
   ```

---

## Related Patterns

- [`captureError-rethrow.md`](./captureError-rethrow.md) — the correct replacement
- [`handle-lambda-wrapper.md`](./handle-lambda-wrapper.md) — preferred when `.eventable/` codegen is available
