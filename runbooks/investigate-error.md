# Runbook: Investigate a Recurring Error

Use this when the nightly audit reports a function with high error counts,
or when asked to RCA a specific error pattern.

## Step 1: Check known-errors.json first

Before investigating, check if this error is already documented:

```bash
cat known-errors.json | jq '.errors[] | select(.service == "my-service")'
```

If it's there with `status: "fixed"` or `status: "pr-merged"`, the fix may
already be deployed. Check the PR link.

## Step 2: Locate the error in CloudWatch Logs Insights

Query the central error log group:

```
fields @timestamp, functionName, errorMessage, severity, rcaHint
| filter functionName = "my-function-name"
| sort @timestamp desc
| limit 50
```

Log group: `/aws/monitoring/central-lambda-errors`

## Step 3: Form hypotheses

Common patterns (from `eventable/src/errorMonitoring/index.ts`):

| rcaHint | Likely cause |
|---|---|
| `iam-permission-denied` | Lambda execution role missing a permission |
| `downstream-lambda-error` | Dependency Lambda failing |
| `database-schema-error` | DynamoDB attribute mismatch or missing GSI |
| `timeout` | Lambda timeout too short, or downstream slow |
| `null-reference` | Missing required field in event payload |

## Step 4: Reproduce locally

```bash
cd ~/source/CoreServices/<service>
# Run the handler test with a crafted failing event
npx jest test/handler --no-coverage
```

## Step 5: Document findings

Add an entry to `known-errors.json`:

```json
{
  "id": "ERR-NNN",
  "title": "Short description",
  "service": "service-name",
  "handler": "path/to/handler.ts",
  "symptom": "What was observed",
  "rootCause": "What actually caused it",
  "fix": "What needs to change",
  "status": "investigating | pr-open | pr-merged | fixed | wont-fix",
  "pr": null,
  "discoveredDate": "YYYY-MM-DD",
  "fixedDate": null
}
```

## Step 6: Fix it

If the fix is clear, enter Build mode:
1. Create branch `forge/fix-<service>-<descriptor>`
2. Make the change
3. Add/update tests
4. Open PR
5. Update `known-errors.json` with `status: "pr-open"` and PR link
