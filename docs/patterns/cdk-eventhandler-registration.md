# Pattern: `createEventHandler` — EventBridge Handler Registration in CDK

**Type:** Pattern (use this)  
**Category:** Infrastructure / CDK / EventBridge  
**Status:** Canonical — the standard way to wire EventBridge handlers in CoreServices CDK stacks

---

## Name

`createEventHandler` registration — declaring EventBridge-triggered Lambda handlers in CDK stacks using the `EventHandler[]` config array and `createEventHandler` factory from `@mmrrfinance/eventable/aws/eventbridge`.

---

## File Paths

Where the pattern is defined:
- `eventable/aws/eventbridge.ts` — `createEventHandler` implementation and `EventHandler` interface

Where the pattern is used:
- `collections/lib/collections.ts` — `collectionsEvents: EventHandler[]` array + `createEventHandler` loop
- `payments/lib/payments.ts` — payment event handlers (paymentProcessed, transactionReversed)
- `decisions/lib/decisions.ts` — decision event handlers
- `leads/lib/leads.ts` — lead event handlers

---

## How It Works

EventBridge handlers are declared as a typed `EventHandler[]` array at the top of the CDK stack file, then registered in a `forEach` loop inside the stack constructor. Each entry in the array maps an EventBridge event name to a Lambda handler file.

### Step 1: Declare the handler config array

```typescript
// collections/lib/collections.ts

import { createEventHandler, EventHandler } from '@mmrrfinance/eventable/aws/eventbridge';

const collectionsEvents: EventHandler[] = [
  {
    name: 'paymentFailed',
    handler: 'paymentFailedHandler',
    filePath: __dirname + '/../src/modules/collections/events/paymentFailed.ts',
    events: ['ACH Payment Failed'],
    source: 'Payment Auth Service',
    timeout: cdk.Duration.minutes(1),
    lambda: {
      writeEvents: true,
    },
  },
  {
    name: 'transactionReversed',
    handler: 'transactionReversedHandler',
    filePath: __dirname + '/../src/modules/collections/events/transactionReversed.ts',
    events: ['Transaction Reversed'],
    source: 'PaymentsService',
    timeout: cdk.Duration.minutes(1),
    lambda: {
      writeEvents: true,
    },
  },
];
```

### Step 2: Register handlers in the stack constructor

```typescript
// Inside CollectionsStack constructor

collectionsEvents.forEach((e) => {
  const { vpc, redshift, ...eventHandlerConfig } = e as any;

  createEventHandler(this, {
    eventHandler: {
      ...eventHandlerConfig,
      lambda: {
        ...(e.lambda || {}),
        environment: {
          ...(e.lambda?.environment || {}),
          EVENT_BUS_NAME: 'CashLoansDirect EventBus',
          COLLECTIONS_REPO_TABLE: collectionsTable.tableName,
          PATCH_TABLE_NAME: historyTable.tableName,
        },
      },
    },
    eventBus,
    vpc,
    redshift,
    dynamoTables: [collectionsTable, historyTable],
  });
});
```

### What `createEventHandler` does

`createEventHandler` is a CDK factory that:
1. Creates a `NodejsFunction` Lambda from the `filePath` + `handler` config.
2. Creates an EventBridge `Rule` that matches `events` from `source`.
3. Adds the Lambda as the rule target.
4. Grants the Lambda permission to be invoked by EventBridge.
5. If `lambda.writeEvents: true`, grants the Lambda permission to put events to the EventBus (for handlers that emit downstream events).
6. If `dynamoTables` is provided, grants read/write access to those tables.

---

## The `EventHandler` Interface

Key fields:

| Field | Type | Purpose |
|-------|------|---------|
| `name` | `string` | Logical name — used as the Lambda function name suffix |
| `handler` | `string` | Exported function name in the handler file (e.g., `'paymentFailedHandler'`) |
| `filePath` | `string` | Absolute path to the handler TypeScript file |
| `events` | `string[]` | EventBridge `detail-type` values to match |
| `source` | `string` | EventBridge `source` to match (the emitting service name) |
| `timeout` | `Duration` | Lambda timeout (default: 30s; use `Duration.minutes(1)` for handlers that do DB writes) |
| `lambda.writeEvents` | `boolean` | Grant permission to put events to the EventBus |
| `lambda.environment` | `object` | Additional env vars merged into the Lambda environment |

---

## When to Use

**Use `createEventHandler` when:**
- Adding a new EventBridge-triggered Lambda to a CoreServices service.
- The handler should react to events emitted by another service (e.g., `PaymentsService` emitting `"Transaction Reversed"`).
- You want the standard CDK wiring: Lambda + EventBridge Rule + IAM grants in one call.

**Do NOT use `createEventHandler` when:**
- The Lambda is triggered by SQS, API Gateway, or a schedule — use `createApi` (API Gateway), `createQueueHandler` (SQS), or a CDK `Rule` with `Schedule` (cron) instead.
- You need fine-grained control over the EventBridge rule pattern (e.g., filtering on `detail` fields) — `createEventHandler` only matches on `source` + `detail-type`. For content-based filtering, create the `Rule` manually.

---

## Canonical Example

From `collections/lib/collections.ts` (PR #542 — `transactionReversed` handler added):

```typescript
// Handler declaration (top of file, outside the stack class)
const collectionsEvents: EventHandler[] = [
  {
    name: 'transactionReversed',
    handler: 'transactionReversedHandler',
    filePath: __dirname + '/../src/modules/collections/events/transactionReversed.ts',
    events: ['Transaction Reversed'],
    source: 'PaymentsService',
    timeout: cdk.Duration.minutes(1),
    lambda: { writeEvents: true },
  },
];

// Registration (inside stack constructor)
collectionsEvents.forEach((e) => {
  const { vpc, redshift, ...eventHandlerConfig } = e as any;
  createEventHandler(this, {
    eventHandler: {
      ...eventHandlerConfig,
      lambda: {
        ...(e.lambda || {}),
        environment: {
          ...(e.lambda?.environment || {}),
          EVENT_BUS_NAME: 'CashLoansDirect EventBus',
          COLLECTIONS_REPO_TABLE: collectionsTable.tableName,
        },
      },
    },
    eventBus,
    dynamoTables: [collectionsTable, historyTable],
  });
});
```

---

## Gotchas

1. **`source` must exactly match the emitting service's `source` field.** EventBridge rules match on exact string equality. If the emitting service uses `'PaymentsService'` and the rule declares `source: 'Payments Service'` (with a space), the rule never fires. Always verify the source string against the emitting service's `emitEvent` call.

2. **`writeEvents: true` is required for handlers that emit downstream events.** If a handler calls `emitEvent(...)` but the Lambda role doesn't have `events:PutEvents` permission, the emit silently fails (EventBridge returns an error that the handler may not surface). Always set `lambda: { writeEvents: true }` for handlers that emit.

3. **Environment variables must be injected at CDK time.** The `environment` block in the `createEventHandler` call is the only way to pass table names, bus names, and other config to the Lambda. The handler file cannot read these from CDK constructs at runtime — it must use `process.env.TABLE_NAME`. Always inject `tableName` and `eventBusName` via the environment block.

4. **The handler array is declared outside the stack class.** This is intentional — it keeps the handler list readable and separate from the CDK wiring. Do not inline the handler objects directly in the `forEach` call.

5. **Redshift-connected handlers need `redshift: true` in the config.** The `createEventHandler` factory checks for a `redshift` field and adds the VPC + Redshift security group grants if present. Handlers that query Redshift (e.g., `transactionReversed` which looks up loan context) must include this.

---

## Related Patterns

- [`handle-lambda-wrapper.md`](./handle-lambda-wrapper.md) — the application-layer error monitoring wrapper that wraps handlers registered via `createEventHandler`
- [`cdk-inline-policy-gsi-grant.md`](./cdk-inline-policy-gsi-grant.md) — the IAM GSI fix needed when `dynamoTables` contains imported tables
- [`eventbridge-disabled-cdk-antipattern.md`](./eventbridge-disabled-cdk-antipattern.md) — the anti-pattern that silences the EventBridge rules this pattern creates
