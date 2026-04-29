# Pattern: EventBridge `source` + `detail-type` Matching — Exact String Contract

**Type:** Pattern (use this — and verify strings carefully)  
**Category:** Event-Driven Architecture / EventBridge  
**Status:** Canonical — the event routing contract across all CoreServices services

---

## Name

EventBridge `source` + `detail-type` matching — the two-field contract that routes events from emitting services to consuming handlers. Both fields must match exactly (case-sensitive, space-sensitive) for an EventBridge rule to fire.

---

## File Paths

Where events are emitted (source side):
- `payments/src/transactionService/loan_transactions/reverse.ts` — emits `"Transaction Reversed"` with `source: 'PaymentsService'`
- `payments/src/payment_account_cleanup.ts` — emits `"ACH Payment Failed"` with `source: 'Payment Auth Service'`
- `eventable/src/eventBridge/emitEvent.ts` — the `emitEvent` utility used by all services

Where events are consumed (handler side):
- `collections/lib/collections.ts` — `collectionsEvents` array declares `events: ['Transaction Reversed']`, `source: 'PaymentsService'`
- `collections/src/modules/collections/events/transactionReversed.ts` — the handler implementation
- `collections/src/modules/collections/events/paymentFailed.ts` — listens for `'ACH Payment Failed'` from `'Payment Auth Service'`

Where the EventBridge rule is created:
- `eventable/aws/eventbridge.ts` — `createEventHandler` builds the `Rule` with `eventPattern: { source: [source], detailType: [events] }`

---

## How It Works

Every event in CoreServices flows through two fields:

| Field | EventBridge term | Set by | Matched by |
|-------|-----------------|--------|------------|
| `source` | `source` | Emitting service's `emitEvent` call | `EventHandler.source` in CDK config |
| `detail-type` | `detailType` | Emitting service's `emitEvent` call | `EventHandler.events[]` in CDK config |

### Emitting side

```typescript
// payments/src/transactionService/loan_transactions/reverse.ts
import { emitEvent } from '@mmrrfinance/eventable/src/eventBridge/emitEvent';

await emitEvent({
  source: 'PaymentsService',          // ← must match handler's `source`
  detailType: 'Transaction Reversed', // ← must match handler's `events[0]`
  detail: {
    loanId: loan.id,
    amount: transaction.amount,
    returnCode: nacha.returnCode,
  },
});
```

### Consuming side (CDK config)

```typescript
// collections/lib/collections.ts
const collectionsEvents: EventHandler[] = [
  {
    name: 'transactionReversed',
    handler: 'transactionReversedHandler',
    filePath: __dirname + '/../src/modules/collections/events/transactionReversed.ts',
    events: ['Transaction Reversed'],   // ← must match emitter's detailType
    source: 'PaymentsService',          // ← must match emitter's source
    timeout: cdk.Duration.minutes(1),
    lambda: { writeEvents: true },
  },
];
```

### Consuming side (handler implementation)

```typescript
// collections/src/modules/collections/events/transactionReversed.ts
import { EventBridgeEvent } from 'aws-lambda';

interface TransactionReversedDetail {
  loanId: string;
  amount: number;
  returnCode: string;
}

export const transactionReversedHandler = async (
  event: EventBridgeEvent<'Transaction Reversed', TransactionReversedDetail>
): Promise<void> => {
  const { loanId, amount, returnCode } = event.detail;

  // Filter to R-code payment returns (NACHA return codes start with 'R')
  if (!returnCode?.startsWith('R')) return;

  // ... open/update collections case
};
```

---

## The Exact-Match Contract

EventBridge rule matching is **exact string equality** — case-sensitive, space-sensitive, no wildcards (unless you use prefix matching, which CoreServices does not use).

Common mismatches that cause silent rule failures:

| Emitter sends | Handler expects | Result |
|---------------|-----------------|--------|
| `'PaymentsService'` | `'Payments Service'` | ❌ Rule never fires |
| `'ACH Payment Failed'` | `'ACH payment failed'` | ❌ Rule never fires |
| `'Transaction Reversed'` | `'TransactionReversed'` | ❌ Rule never fires |
| `'PaymentsService'` | `'PaymentsService'` | ✅ Rule fires |

**Silent failure:** When the strings don't match, EventBridge accepts the event (no error on the emitter side), the rule simply doesn't match, and the handler Lambda is never invoked. There is no error log, no alarm, no indication that the event was dropped.

---

## When to Use

**Always verify both strings when:**
- Adding a new EventBridge handler — check the emitting service's `emitEvent` call to get the exact `source` and `detailType` strings.
- Renaming an event — update both the emitter and all consumers atomically. A rename that only updates one side silently breaks the pipeline.
- Adding a new emitter for an existing event type — use the exact same `source` and `detailType` strings as the existing emitter.

**Verification checklist:**
1. Find the `emitEvent` call in the emitting service.
2. Copy the `source` and `detailType` strings verbatim.
3. Paste them into the `EventHandler` config's `source` and `events` fields.
4. Do not retype — copy-paste to avoid case/space errors.

---

## Canonical Example

From PR #542 (`transactionReversed` handler added to collections):

**Step 1: Find the emitter**
```typescript
// payments/src/transactionService/loan_transactions/reverse.ts
await emitEvent({
  source: 'PaymentsService',
  detailType: 'Transaction Reversed',
  detail: { loanId, amount, loan_id, returnCode },
});
```

**Step 2: Copy strings exactly into CDK config**
```typescript
// collections/lib/collections.ts
{
  events: ['Transaction Reversed'],  // copied verbatim from detailType
  source: 'PaymentsService',         // copied verbatim from source
}
```

**Step 3: Type the handler with the exact detail-type string**
```typescript
// collections/src/modules/collections/events/transactionReversed.ts
export const transactionReversedHandler = async (
  event: EventBridgeEvent<'Transaction Reversed', TransactionReversedDetail>
  //                       ↑ same string — TypeScript enforces it
): Promise<void> => { ... };
```

---

## Gotchas

1. **There is no compile-time check that emitter and consumer strings match.** TypeScript can enforce the string within a single file (e.g., `EventBridgeEvent<'Transaction Reversed', ...>`), but it cannot verify that the CDK rule's `events` array matches the emitter's `detailType`. This is a runtime contract.

2. **`emitEvent` enriches the payload — the handler receives the full EventBridge envelope.** The handler's `event` parameter is `EventBridgeEvent<DetailType, Detail>`, not just the `detail` object. Access the business payload via `event.detail`.

3. **Multiple handlers can listen to the same event.** EventBridge fan-out is built-in — if both `collections` and `decisions` declare a rule for `'Transaction Reversed'` from `'PaymentsService'`, both Lambdas fire independently. This is intentional and correct.

4. **`source` is the service name, not the AWS account or region.** CoreServices uses human-readable service names (`'PaymentsService'`, `'Payment Auth Service'`) as the `source` field. Do not confuse this with the AWS EventBridge `source` format used in AWS-native events (e.g., `'aws.ec2'`).

5. **PR #542 added `loan_id` and `amount` to the `"Transaction Reversed"` payload** specifically so the Collections handler could open cases without a second lookup. If you're consuming this event, both fields are available in `event.detail`.

---

## Related Patterns

- [`cdk-eventhandler-registration.md`](./cdk-eventhandler-registration.md) — how to register the CDK rule for an EventBridge handler
- [`handle-lambda-wrapper.md`](./handle-lambda-wrapper.md) — error monitoring wrapper for EventBridge handlers
- [`eventbridge-disabled-cdk-antipattern.md`](./eventbridge-disabled-cdk-antipattern.md) — the CDK anti-pattern that silences EventBridge rules
