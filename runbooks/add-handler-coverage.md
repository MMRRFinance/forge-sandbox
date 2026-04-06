# Runbook: Add Error Monitoring Coverage to a Lambda Handler

Use this when the nightly audit reports a function as unmonitored, or when
adding a new Lambda handler to any service.

## Decision: handleLambda vs captureError directly

| Use `handleLambda` | Use `captureError` directly |
|---|---|
| Handler is a simple async function with no custom error logic | Handler has per-item error collection (batch jobs) |
| Handler is in a service that already uses eventable | Handler needs to distinguish item-level vs job-level failures |
| Fastest path — one wrapper, done | Need fine-grained control over what gets reported |

## Option A: Wrap with handleLambda (preferred for simple handlers)

```typescript
import { handleLambda } from "@mmrrfinance/eventable";

// BEFORE
export const handler = async (event: MyEvent) => {
  // ... handler logic
};

// AFTER
export const handler = handleLambda(async (event: MyEvent) => {
  // ... handler logic (unchanged)
});
```

`handleLambda` automatically:
- Logs structured start/success/error JSON
- Calls `captureError` on failure
- Re-throws so CloudWatch error metrics fire

Also ensure the CDK Lambda definition has `errorMonitoring: true` (it defaults to true
if using `createLambda` from eventable).

## Option B: captureError + re-throw (for batch jobs with inner error collection)

```typescript
import { captureError } from "@mmrrfinance/eventable";

export const handler = async (): Promise<JobResult> => {
  const errors: string[] = [];

  try {
    // ... job logic with inner try/catch that pushes to errors[]
    return { success: errors.length === 0, errors };

  } catch (error) {
    // Job-level failure (infrastructure down, etc.)
    console.error("Job failed:", error);

    captureError(error instanceof Error ? error : new Error(String(error)), {
      functionName: "my-service-job-name",
    }).catch((monitoringErr) =>
      console.error("captureError failed:", monitoringErr)
    );

    throw error; // ← CRITICAL: must throw for CloudWatch metrics to fire
  }
};
```

## After making the change

1. Run the handler's test suite. Add a test that verifies the handler throws on failure.
2. Open a PR to CoreServices.
3. After PR is merged, update `coverage-map.json` in this repo:
   - Set `covered: true`
   - Set `coverageMethod` to `"handleLambda"` or `"captureError + re-throw"`
   - Set `pr` to the merged PR URL
   - Set `prStatus` to `"merged"`
4. Update `_meta.coveredCount` and `_meta.uncoveredCount`.

## Common mistakes

- **Forgetting to re-throw** — `captureError` alone is not enough. CloudWatch Lambda
  error metrics only fire when the handler throws. Always `throw error` after `captureError`.
- **Wrapping the inner catch** — For batch jobs, only the outer (job-level) catch should
  throw. Inner per-item catches should continue collecting errors[].
- **Missing EVENT_BUS_NAME env var** — `captureError` needs `EVENT_BUS_NAME` set on the
  Lambda. If using `createLambda` with `errorMonitoring: true`, this is set automatically.
  For manually-defined Lambdas, add it to the CDK definition.
