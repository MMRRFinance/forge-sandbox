# Anti-Pattern: `Table.fromTableName` IAM Gap — Imported Tables Miss GSI Permissions

**Type:** Anti-Pattern (be aware — requires explicit workaround)  
**Category:** Infrastructure / CDK / DynamoDB / IAM  
**Status:** Known CDK limitation — requires `addToRolePolicy` workaround (see `cdk-inline-policy-gsi-grant.md`)

---

## Name

`Table.fromTableName` IAM gap — importing a DynamoDB table by name in a CDK stack and relying on `grantReadData` to cover GSI queries, when in fact the generated IAM policy omits the `/index/*` resource.

---

## File Paths

Where this pattern appears (cross-stack table references):
- `collections/lib/collections.ts` — `CollectionsMcpApiStack` imports `CollectionsRepo` via `Table.fromTableName`
- `eventable/aws/api.ts` — `createApi` receives `dynamoTable: ITable` (may be imported or created)
- Any CDK stack that references a table created in a different stack

Where the workaround is implemented:
- `eventable/aws/api.ts` — explicit `addToRolePolicy` for `/index/*` after `grantReadData`

---

## What It Looks Like

```typescript
// ⚠️ INCOMPLETE — grantReadData on imported table misses GSI resources

// Stack A creates the table:
// new Table(this, 'CollectionsRepo', { tableName: 'CollectionsRepo', ... })

// Stack B imports it:
const collectionsTable = Table.fromTableName(this, 'CollectionsRepoRef', 'CollectionsRepo');

// Stack B grants read to a Lambda:
collectionsTable.grantReadData(myLambda);
// ↑ Generates IAM policy with:
//   Resource: ["arn:aws:dynamodb:us-east-1:123456789:table/CollectionsRepo"]
//   Actions: [dynamodb:GetItem, dynamodb:BatchGetItem, dynamodb:Scan, dynamodb:Query, ...]
//
// MISSING: "arn:aws:dynamodb:us-east-1:123456789:table/CollectionsRepo/index/*"
// Any GSI query → AccessDenied
```

---

## Why It Happens

### CDK's two table types

CDK has two distinct types for DynamoDB tables:

| Type | How created | `grantReadData` behavior |
|------|-------------|--------------------------|
| `Table` | `new Table(scope, id, props)` | Includes `tableArn/index/*` in policy |
| `ITable` | `Table.fromTableName(...)` or `Table.fromTableArn(...)` | **May omit** `tableArn/index/*` |

When you create a table with `new Table(...)`, CDK knows the full table definition at synth time and generates a complete IAM policy. When you import a table by name, CDK constructs a minimal `ITable` reference. The `grantReadData` implementation on `ITable` generates a policy based on the ARN alone — and in some CDK versions, it does not append `/index/*` to the resource list.

### Why cross-stack references require imports

In a multi-stack CDK app (e.g., `CollectionsStack` creates the table, `CollectionsMcpApiStack` uses it), the second stack cannot reference the first stack's `Table` construct directly — that would create a circular dependency. Instead, it imports the table by name or ARN. This is the correct CDK pattern for cross-stack resource sharing, but it triggers the IAM gap.

### The failure is silent until runtime

The CDK synth succeeds. The CloudFormation deploy succeeds. The Lambda deploys. The IAM policy in the AWS console shows `dynamodb:Query` — but only on the table ARN, not on `tableArn/index/*`. The failure only surfaces when the Lambda executes a query that uses a GSI.

---

## How to Detect

### At synth time

Inspect the synthesized CloudFormation template for the Lambda's execution role:

```bash
# After cdk synth
cat cdk.out/CollectionsMcpApiStack.template.json \
  | python3 -c "
import json, sys
t = json.load(sys.stdin)
for name, resource in t.get('Resources', {}).items():
    if resource.get('Type') == 'AWS::IAM::Policy':
        stmts = resource.get('Properties', {}).get('PolicyDocument', {}).get('Statement', [])
        for s in stmts:
            if 'dynamodb' in str(s.get('Action', '')):
                print(name, json.dumps(s.get('Resource'), indent=2))
"
```

If you see only `table/CollectionsRepo` and not `table/CollectionsRepo/index/*`, the GSI grant is missing.

### At runtime

```
AccessDeniedException: User: arn:aws:sts::123456789:assumed-role/... is not authorized to perform:
dynamodb:Query on resource: arn:aws:dynamodb:us-east-1:123456789:table/CollectionsRepo/index/status-nextReviewAt-index
```

The error message will name the specific GSI index that was denied.

---

## The Fix

Add an explicit `addToRolePolicy` call after `grantReadData`:

```typescript
import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";

// Step 1: Standard grant (covers table-level operations)
collectionsTable.grantReadData(myLambda);

// Step 2: Explicit GSI grant (covers index queries)
myLambda.addToRolePolicy(new PolicyStatement({
  effect: Effect.ALLOW,
  actions: ['dynamodb:Query', 'dynamodb:Scan'],
  resources: [`${collectionsTable.tableArn}/index/*`],
}));
```

See `cdk-inline-policy-gsi-grant.md` for the full pattern and the fix applied in `eventable/aws/api.ts`.

---

## Scope of Impact

Any Lambda that:
1. Receives a DynamoDB table via cross-stack import (`Table.fromTableName` / `Table.fromTableArn`)
2. AND queries a GSI on that table

is affected. In CoreServices, this includes:
- `CollectionsMcpApiStack` → `CollectionsRepo` (fixed in PR #544)
- Any future MCP API stack that imports a table from another stack

---

## Gotchas

1. **`Table.fromTableArn` has the same gap.** The issue is not specific to `fromTableName` — any import method that returns `ITable` rather than `Table` may exhibit this behavior.

2. **The gap is CDK version-dependent.** Some CDK versions include `/index/*` in `grantReadData` on imported tables; others don't. Do not rely on CDK version behavior — always add the explicit grant when using imported tables with GSI queries.

3. **`grantWriteData` has the same gap.** If a Lambda needs to write to a GSI (rare, but possible with `BatchWriteItem` on tables with GSIs), the same explicit grant is needed for write operations.

4. **The fix is already in `createApi`.** If you're using `createApi` from `eventable/aws/api.ts` with `dynamo: { read: true }`, the fix is already applied. You only need to add it manually if you're wiring up a Lambda outside of `createApi`.

---

## Related Patterns

- [`cdk-inline-policy-gsi-grant.md`](./cdk-inline-policy-gsi-grant.md) — the explicit workaround pattern
- [`cdk-eventhandler-registration.md`](./cdk-eventhandler-registration.md) — how EventBridge handlers are registered (separate from API Gateway handlers)
