# Phase 0: Error Monitoring Coverage Baseline

**Started:** 2026-04-06
**Goal:** Get all 21 uncovered Lambda handlers flowing through eventable error monitoring.

## Background

The CoreServices monorepo has a mature error monitoring pipeline:
`handleLambda` / `captureError` → EventBridge → SQS → CloudWatch Logs → nightly audit → email report.

A nightly audit Lambda (runs 2 AM UTC) compares CloudWatch Lambda error metrics against
the central error log group to identify functions that have errors but are NOT flowing
through eventable. As of Phase 0 start, 21 handlers were unmonitored.

See: `CoreServices/docs/agents/arch/error-monitoring-system.md` for full pipeline docs.

## Phase 0 PRs

| PR | Service | Files | Status |
|---|---|---|---|
| [#481](https://github.com/MMRRFinance/CoreServices/pull/481) | fraud-graph | `handler.ts` | Open — awaiting review |
| [#482](https://github.com/MMRRFinance/CoreServices/pull/482) | commitment-service | `overdueChecker.ts`, `reminderSender.ts` | Open — awaiting review |

## Coverage progress

| Metric | Value |
|---|---|
| Total handlers | 21 |
| Covered (PRs merged) | 0 |
| Covered (PRs open) | 3 |
| Uncovered | 18 |
| Coverage % (merged) | 0% |
| Coverage % (including open PRs) | 14.3% |

## Remaining handlers (18 uncovered)

Grouped by service for efficient batching:

### cdp-comms (4 handlers)
- `delinquencyDetection.ts`
- `dailyReport.ts`
- `five9Transcription.ts`
- `workQueueGraphql.ts`

### okr-tracking (2 handlers)
- `measure-okrs-handler.ts`
- `graphql-handler.ts`

### ms-graph-integration (3 handlers) — no .eventable/ in this service
- `webhookHandler.ts`
- `subscriptionRenewal.ts`
- `backfill.ts`

### leads (2 handlers)
- `analyticsJob.ts`
- `enrichmentJob.ts` (needs verification)

### payroll-loans (2 handlers)
- `gradingJob.ts`
- `applicationProcessor.ts` (needs verification)

### acquisition-analytics (3 handlers)
- `snapshotHandler.ts`
- `searchIndexer.ts`
- `metricsQuery.ts` (needs verification)

### onboarding (1 handler)
- `handler.ts` (location needs verification)

## Key decisions made in Phase 0

1. **fraud-graph**: Used `captureError + re-throw` (not `handleLambda`) because the handler
   has structured JSON logging that we want to preserve. `handleLambda` would add its own
   log lines; `captureError` is additive.

2. **commitment-service jobs**: Used `captureError + re-throw` on the **outer** catch only.
   Inner per-item catches intentionally left unchanged — they collect `errors[]` for partial
   success reporting, which is correct batch job behavior.

3. **Separate PRs per service**: Each service gets its own PR so reviewers can approve
   independently and failures don't block unrelated services.

## Next phase

Phase 1: Wrap the remaining 18 handlers. Batch by service (one PR per service).
Priority order: cdp-comms → okr-tracking → ms-graph-integration → leads/payroll-loans/acquisition-analytics → onboarding.
