# Pattern: `captureError` + Re-throw

**Type:** Pattern (use this)  
**Category:** Error Monitoring / Manual Coverage  
**Status:** Canonical — use when `handleLambda` is not available

---

## Name

`captureError` + re-throw — manual error monitoring for handlers that cannot use the `handleLambda` codegen wrapper.

---

## File Paths

Where the pattern is defined:
- `eventable/src/errorMonitoring/index.ts` — `captureError` implementation
- `eventable/src/codeGen/aws/apiGateway/utils.ts:61` — `captureError` usage in API Gateway context

Where the pattern is used (hand-written, not generated):
- `fraud-graph/src/handler.ts:148` — outer catch in the backfill handler
- `commitment-service/src/jobs/reminderSender.ts:139` — outer catch in the reminder job
- `commitment-service/src/jobs/overdueChecker.ts:97` — outer catch in the overdue checker job

---

## How It Works

`captureError` emits an EventBridge error event and logs the error to the central error log group. It does NOT re-throw — the caller is responsible for re-throwing after calling it.

The canonical pattern is a try/catch in the handler's outermost scope:

```typescript
import { captureError } from '@mmrrfinance/eventable/src/errorMonitoring';

export const handler = async (event: SomeEvent): Promise<void> => {
  try {
    await doWork(event);
  } catch (error) {
    captureError(
      error instanceof Error ? error : new Error(String(error)),
      {
        functionName: 'myHandlerName',
        event,
      }
    ).catch((monitoringErr) => {
      // captureError itself failed — log but don't mask the original error
      console.error('captureError failed:', monitoringErr);
    });
    throw error; // re-throw — Lambda marks invocation FAILED
  }
};
```

Key details:
1. **`error instanceof Error ? error : new Error(String(error))`** — always pass an `Error` object. String literals thrown with `throw "message"` are not `Error` instances and lose stack traces. This guard converts them.
2. **`.catch(monitoringErr => console.error(...))`** — `captureError` is async (it calls EventBridge). If EventBridge is down, we don't want the monitoring failure to mask the original error. Fire-and-forget with a fallback log.
3. **`throw error`** — always re-throw after `captureError`. This is what makes Lambda mark the invocation as FAILED, enabling DLQ, retry, and CloudWatch alarms.

---

## When to Use

**Use `captureError + re-throw` when:**
- The service does NOT have a `.eventable/` directory (no codegen).
- The handler has structured JSON logging that `handleLambda`'s log lines would interfere with.
- You need fine-grained control over which errors are captured (e.g., inner per-item errors in a batch job should NOT be captured — only the outer failure should be).

**Do NOT use `captureError + re-throw` when:**
- The service already has `.eventable/` — use `handleLambda` via codegen instead. Adding manual `captureError` in a service that already has `handleLambda` wrapping will double-fire error events.
- You want to swallow the error — `captureError` is only meaningful if you re-throw. If you're catching and continuing, you don't need `captureError` (and you should think carefully about whether swallowing is correct).

---

## Canonical Example

From `fraud-graph/src/handler.ts:148` (the reference implementation):

```typescript
} catch (error) {
  captureError(error instanceof Error ? error : new Error(String(error)), {
    functionName: 'fraudGraphHandler',
    event,
  }).catch((monitoringErr) => {
    console.error('captureError failed:', monitoringErr);
  });
  throw error;
}
```

From `commitment-service/src/jobs/overdueChecker.ts:97` (batch job — outer catch only):

```typescript
// Outer catch — captures the job-level failure
} catch (error) {
  captureError(error instanceof Error ? error : new Error(String(error)), {
    functionName: 'overdueChecker',
    event,
  }).catch((monitoringErr) => {
    console.error('captureError failed:', monitoringErr);
  });
  throw error;
}
// Note: inner per-item catches are intentionally NOT wrapped with captureError.
// They collect errors[] for partial-success reporting — correct batch job behavior.
```

---

## Gotchas

1. **Don't await `captureError` in the catch block.** If you `await captureError(...)` and EventBridge is slow or down, your Lambda timeout clock is ticking. Use `.catch()` for the monitoring failure and let the re-throw happen immediately.

2. **The `instanceof Error` guard is mandatory.** `self-service-api` has 20+ `throw "string"` sites that would pass a raw string to `captureError` — the guard converts them to `Error` objects with proper stack traces. See tech debt WorkItem `cdf7f355`.

3. **Inner catches in batch jobs should NOT use `captureError`.** `commitment-service` jobs intentionally catch per-item errors and accumulate them in an `errors[]` array for partial-success reporting. Only the outer job-level failure should be captured. Wrapping inner catches would flood EventBridge with per-item noise.

4. **`captureError` is async — it calls EventBridge.** In local development, EventBridge is not available. The `.catch()` fallback prevents local test failures from masking the original error.

---

## Related Patterns

- [`handle-lambda-wrapper.md`](./handle-lambda-wrapper.md) — preferred alternative when `.eventable/` codegen is available
- [`return-statuscode-500-antipattern.md`](./return-statuscode-500-antipattern.md) — anti-pattern this replaces
