# Architecture Map: forge-sandbox

**Mapped by:** Forge  
**Date:** 2026-04-28  
**Work item:** WI 1ad37673 (OBJ1 KR1 — repo 2 of 3)  
**Repo:** https://github.com/MMRRFinance/forge-sandbox

---

## Overview

`forge-sandbox` is Forge's **operational home base** within the MMRRFinance GitHub org.
It is explicitly **not a service repo** — it contains no deployable Lambda code, no CDK
stacks, and no infrastructure definitions. Its purpose is institutional memory: tracking
what Forge has investigated, what coverage exists, and how to perform recurring tasks
correctly.

Think of it as Forge's personal wiki + state store, committed to git so findings persist
across sessions and are reviewable by humans.

---

## 1. Main Entry Points

### No Lambda Handlers or CDK Stacks

forge-sandbox has **zero Lambda handlers** and **zero CDK stacks**. There is nothing to
deploy. This is intentional — the repo is a knowledge artifact, not a service.

### CLI Scripts

| Script | Location | Purpose |
|---|---|---|
| `error-summary.py` | `scripts/error-summary.py` | Daily error digest for CoreServices Lambdas |

#### `error-summary.py` — CLI entry point

```
Usage:
    python3 scripts/error-summary.py              # today's errors
    python3 scripts/error-summary.py 2026-04-06   # specific date
```

This is the only executable entry point in the repo. It is a **read-only diagnostic
tool** — it queries CloudWatch Logs and prints a formatted report to stdout. It does not
write to any AWS resource.

**Invocation pattern:** Run manually by Forge during error triage sessions, or scheduled
externally (e.g., a cron job or EventBridge rule invoking it via a Lambda wrapper — not
yet implemented as of 2026-04-28).

### Runbooks (human/agent procedures, not code)

| Runbook | Purpose |
|---|---|
| `runbooks/add-handler-coverage.md` | Step-by-step: wrap a Lambda handler with eventable |
| `runbooks/investigate-error.md` | Step-by-step: RCA a recurring error from CloudWatch |
| `runbooks/update-coverage-map.md` | Step-by-step: update coverage-map.json after a PR merges |

Runbooks are **prose procedures** — they contain code snippets but are not themselves
executable. They are read by Forge at the start of relevant tasks to avoid re-learning
known patterns.

### CLAUDE.md — Agent Initialization Contract

`CLAUDE.md` at the repo root is the **first file Forge reads** at the start of any
session. It defines:
- What each file/directory is for
- How Forge uses the repo (before-task, after-PR, after-RCA, new-pattern)
- Conventions (PR-only pushes, branch naming, commit style)
- Current phase and goal

This file is the closest thing to a "main entry point" for Forge as an agent.

---

## 2. Key Data Flows

### Flow A: Error Monitoring Coverage Tracking

This is the primary operational loop forge-sandbox supports.

```
CoreServices Lambda handler
        │
        │  (errors thrown)
        ▼
  CloudWatch Lambda error metrics
        │
        │  (nightly audit Lambda, 2 AM UTC)
        ▼
  Audit compares: CloudWatch error metrics vs. central error log group
        │
        │  (functions with errors NOT in central log = unmonitored)
        ▼
  Forge reads audit output
        │
        ├─► reads coverage-map.json  ← forge-sandbox (source of truth)
        │         (which handlers are already known/covered?)
        │
        ├─► reads runbooks/add-handler-coverage.md
        │         (how to fix an uncovered handler)
        │
        ├─► opens PR to CoreServices
        │         (adds captureError or handleLambda wrapper)
        │
        └─► updates coverage-map.json in forge-sandbox
                  (marks handler covered, records PR link)
```

**Key invariant:** `coverage-map.json` is the single source of truth for monitoring
coverage state. Forge must read it before starting any coverage task and update it after
any PR merges.

### Flow B: Error Investigation (RCA)

```
Nightly audit / human report: "function X has high error count"
        │
        ▼
  Forge reads known-errors.json  ← forge-sandbox
        │  (is this already investigated?)
        │
        ├─ YES, status=fixed → check PR link, may already be deployed
        │
        └─ NO → investigate
                │
                ├─► reads runbooks/investigate-error.md
                │
                ├─► queries CloudWatch Logs Insights
                │     log group: /aws/monitoring/central-lambda-errors
                │
                ├─► forms hypotheses, reproduces locally
                │
                └─► adds entry to known-errors.json
                      then enters Build mode if fix is clear
```

### Flow C: Daily Error Digest (error-summary.py)

```
Operator runs: python3 scripts/error-summary.py [date]
        │
        ▼
  aws logs describe-log-streams
    --log-group-name /aws/monitoring/central-lambda-errors
    --log-stream-name-prefix YYYY-MM-DD
        │
        ▼
  aws logs get-log-events (paginated via nextForwardToken)
        │
        ▼
  Parse each event: JSON → { functionName, error.name, error.message }
        │
        ▼
  Normalise messages: strip UUIDs, request IDs, timestamps, hex strings
    (so identical errors collapse into one counter bucket)
        │
        ▼
  Aggregate: { functionName → Counter(error_type: message → count) }
        │
        ▼
  Format ranked report (sorted by total error count desc) → stdout
```

**Pagination:** Uses `nextForwardToken` loop; detects end-of-stream when token repeats.
**Normalisation patterns:** 7 regex substitutions (UUIDs, request IDs, hex strings,
ISO timestamps, large integers, quoted values, request_id JSON keys).

### Flow D: OKR Tooling Pattern Reference

```
Forge starts OKR-heavy session
        │
        ▼
  reads docs/patterns/okr-tooling.md  ← forge-sandbox
        │
        ▼
  Applies known workarounds before hitting API:
    - search_entities not list_entities
    - category as array
    - parse data['hits']['items'] not data['items']
    - handle spill files via bash + python3
    - correct status enums per entity type
```

This flow prevents re-discovering the same API quirks across sessions.

---

## 3. External Dependencies

forge-sandbox itself has **no runtime dependencies** — it is a static repo. However, the
tools it documents and the script it contains interact with the following external systems:

### AWS CloudWatch Logs

| Detail | Value |
|---|---|
| Log group | `/aws/monitoring/central-lambda-errors` |
| Stream naming | `YYYY-MM-DD` (one stream per day) |
| Access method | AWS CLI (`aws logs get-log-events`, `aws logs describe-log-streams`) |
| Used by | `scripts/error-summary.py` |
| Auth | AWS CLI credentials / IAM role of the executing environment |

**Note:** The `--log-group-name-pattern` flag does NOT exist in the AWS CLI. Use
`--log-group-name` for exact match or `--log-group-name-prefix` for prefix search.
(Confirmed gotcha — see Section 5.)

### GitHub API (CoreServices repo)

| Detail | Value |
|---|---|
| Repo | `MMRRFinance/CoreServices` |
| Used for | Opening PRs that add error monitoring coverage |
| Access method | `gh pr create` CLI or GitHub API via Forge tooling |
| Auth | GitHub token (rotates hourly in Forge execution environment) |

forge-sandbox itself does not call the GitHub API — it only stores PR links in
`coverage-map.json` and `known-errors.json` as references.

### EventBridge (CoreServices infrastructure)

| Detail | Value |
|---|---|
| Bus | Central EventBridge bus (name injected via `EVENT_BUS_NAME` env var) |
| Used by | `@mmrrfinance/eventable` — `captureError` / `handleLambda` |
| Flow | Lambda error → EventBridge → SQS → CloudWatch Logs central group |

forge-sandbox documents this pipeline but does not interact with EventBridge directly.

### OKR Tooling API (agent tool layer)

| Detail | Value |
|---|---|
| Tools | `search_entities`, `get_entity`, `update_entity`, `create_entity` |
| Used by | Forge agent during OKR tracking sessions |
| Quirks | Documented in `docs/patterns/okr-tooling.md` (5 confirmed quirks) |

### `@mmrrfinance/eventable` (npm package, CoreServices)

| Detail | Value |
|---|---|
| Package | `@mmrrfinance/eventable` |
| Exports | `handleLambda`, `captureError`, `createLambda` |
| Used by | CoreServices Lambda handlers (not forge-sandbox directly) |
| Documented in | `runbooks/add-handler-coverage.md` |

The `EVENT_BUS_NAME` environment variable must be set on any Lambda using `captureError`.
When using `createLambda` with `errorMonitoring: true`, this is set automatically. For
manually-defined Lambdas, it must be added explicitly to the CDK definition.

### No DynamoDB, No S3, No SQS (direct)

forge-sandbox has no direct DynamoDB, S3, or SQS dependencies. All state is stored in
git (JSON files committed to the repo).

---

## 4. Test Coverage Assessment

### Summary: No Automated Tests Exist

forge-sandbox has **zero test files** as of 2026-04-28. There is no `package.json`, no
Jest config, no pytest config, and no CI test step.

This is a deliberate trade-off: the repo is a knowledge artifact, not a service. The
"tests" are human/agent review of the JSON files and runbooks.

### What Is Well-Covered (by design/convention)

| Artifact | Coverage mechanism |
|---|---|
| `coverage-map.json` schema | JSON structure is self-documenting; `_meta` block tracks counts |
| `known-errors.json` schema | Consistent fields: id, title, service, handler, symptom, rootCause, fix, status, pr, dates |
| Runbook correctness | Validated by Forge executing them and updating if they fail |
| `CLAUDE.md` conventions | Enforced by PR review (no direct pushes to main) |

### What Is Fragile

| Risk | Detail |
|---|---|
| `coverage-map.json` drift | If a PR merges in CoreServices and Forge doesn't update the map, counts go stale. No automated sync. |
| `_meta` count fields | `coveredCount` and `uncoveredCount` are manually maintained integers — easy to get out of sync with the actual `handlers[]` array. |
| `error-summary.py` — no unit tests | The normalisation regexes, pagination logic, and JSON parsing are untested. A CloudWatch API change or log format change would silently break the script. |
| `error-summary.py` — AWS credential dependency | The script fails entirely if AWS credentials are not configured. No graceful degradation or mock mode. |
| Runbook staleness | Runbooks reference CoreServices patterns (e.g., `handleLambda` API, `.eventable/` directory structure). If CoreServices refactors these, runbooks become misleading without a sync mechanism. |
| OKR quirks doc | `docs/patterns/okr-tooling.md` documents API behavior that could change with OKR tool updates. No version pinning. |

### Recommended Test Additions (if this repo grows)

1. **JSON schema validation** — a simple Python script that validates `coverage-map.json`
   and `known-errors.json` against expected schemas, run in CI.
2. **Count consistency check** — assert `_meta.coveredCount == len([h for h in handlers if h.covered])`.
3. **`error-summary.py` unit tests** — pytest with mocked `subprocess.run` to test
   normalisation, aggregation, and formatting without AWS credentials.

---

## 5. Known Gotchas

These are issues discovered during actual task work in forge-sandbox sessions. Each one
caused at least one wasted investigation cycle before being documented.

### Gotcha 1: AWS CLI has no `--log-group-name-pattern` flag

**Symptom:** `aws logs ... --log-group-name-pattern` returns a CLI error.  
**Reality:** The flag does not exist. Use:
- `--log-group-name` for exact match
- `--log-group-name-prefix` for prefix search
- `filter-log-events` for pattern-based queries

**Where it matters:** `error-summary.py` and any manual CloudWatch investigation.

---

### Gotcha 2: CloudWatch error metrics only fire when the handler throws

**Symptom:** A Lambda has known failures but never appears in the nightly audit's
"unmonitored" list — and also never appears in the error log.  
**Reality:** CloudWatch Lambda error metrics only increment when the handler **throws**.
Returning `{ statusCode: 500 }` or `{ success: false }` from a catch block does NOT
trigger error metrics. `captureError` alone is also not enough — you must `throw error`
after calling it.

**Canonical examples:** ERR-001 (fraud-graph), ERR-002 (commitment-service).

---

### Gotcha 3: Inner vs. outer catch in batch jobs

**Symptom:** Wrapping the entire handler with `handleLambda` breaks partial-success
reporting in batch jobs.  
**Reality:** Batch jobs typically have two catch levels:
- **Inner (per-item):** collects `errors[]`, continues processing — do NOT throw here
- **Outer (job-level):** handles infrastructure failures — DO throw here

Only the outer catch should call `captureError` + throw. The inner catch is intentionally
swallowing per-item errors to enable partial success. Wrapping with `handleLambda` at the
outer level would catch the inner errors too and break the batch semantics.

**Canonical examples:** ERR-002 (commitment-service overdueChecker, reminderSender).

---

### Gotcha 4: `EVENT_BUS_NAME` must be set on manually-defined Lambdas

**Symptom:** `captureError` silently fails or throws at runtime on a Lambda that was
defined manually in CDK (not via `createLambda`).  
**Reality:** `createLambda` with `errorMonitoring: true` automatically injects
`EVENT_BUS_NAME`. Manually-defined CDK Lambda constructs do not get this env var. It
must be added explicitly.

**Where it matters:** Services that don't use `createLambda` — notably `ms-graph-integration`,
which has no `.eventable/` directory at all.

---

### Gotcha 5: OKR API — `search_entities` vs `list_entities`

**Symptom:** `list_entities(entityType='Objective', category='personal')` raises MCP
error `-32603`. `list_entities` results parse as empty even when `total > 0`.  
**Reality:** Two separate issues:
1. `list_entities` does not support `category` filter — use `search_entities` with
   `category` as an **array**.
2. Results are at `data['hits']['items']`, not `data['items']`.

**Full reference:** `docs/patterns/okr-tooling.md` (5 confirmed quirks documented).

---

### Gotcha 6: No direct pushes to main

**Symptom:** Attempting `git push origin main` is blocked by branch protection.  
**Reality:** All changes to forge-sandbox go through PRs. Branch naming: `forge/<descriptor>`.
This applies even for small documentation updates.

---

### Gotcha 7: `coverage-map.json` `_meta` counts are manually maintained

**Symptom:** `_meta.coveredCount` shows 2 but the actual `handlers[]` array has 3
entries with `covered: true` (or vice versa).  
**Reality:** The count fields are not computed — they are manually updated. After any
change to handler coverage status, both the handler entry AND the `_meta` block must be
updated. The `update-coverage-map.md` runbook documents this, but it's easy to forget.

---

## Appendix: File Inventory

```
forge-sandbox/
├── CLAUDE.md                          ← agent initialization contract
├── coverage-map.json                  ← handler coverage state (21 handlers tracked)
├── known-errors.json                  ← investigated errors registry (ERR-001, ERR-002)
├── scripts/
│   └── error-summary.py              ← daily error digest CLI (~200 lines, Python 3)
├── runbooks/
│   ├── add-handler-coverage.md       ← how to wrap a handler with eventable
│   ├── investigate-error.md          ← how to RCA a recurring error
│   └── update-coverage-map.md        ← how to update coverage-map after PR merges
└── docs/
    ├── phase-0-summary.md            ← Phase 0 status (21 handlers, 3 covered via open PRs)
    ├── patterns/
    │   └── okr-tooling.md            ← 5 confirmed OKR API quirks with workarounds
    └── architecture/
        └── forge-sandbox.md          ← this file
```

## Appendix: Phase 0 Coverage Status (as of 2026-04-28)

| Metric | Value |
|---|---|
| Total handlers tracked | 21 |
| Covered (PRs merged) | 0 |
| Covered (PRs open) | 3 |
| Uncovered | 18 |
| Coverage % (merged) | 0% |
| Coverage % (incl. open PRs) | 14.3% |

Open PRs: CoreServices #481 (fraud-graph), #482 (commitment-service x2).

Remaining 18 handlers span: cdp-comms (4), okr-tracking (2), ms-graph-integration (3),
leads (2), payroll-loans (2), acquisition-analytics (3), onboarding (1).
