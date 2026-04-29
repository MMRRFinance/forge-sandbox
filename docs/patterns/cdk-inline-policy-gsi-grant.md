# Pattern: `addToRolePolicy` for DynamoDB GSI Access on Imported Tables

**Type:** Pattern (use this — required workaround)  
**Category:** Infrastructure / CDK / IAM  
**Status:** Canonical workaround — required whenever `dynamo: { read: true }` is used with an imported table

---

## Name

`addToRolePolicy` inline GSI grant — explicitly granting `dynamodb:Query` and `dynamodb:Scan` on `tableArn/index/*` when `grantReadData` on an imported table fails to include GSI resources in the generated IAM policy.

---

## File Paths

Where the pattern is implemented:
- `eventable/aws/api.ts` — `createApi` function, inside the `endpoint.dynamo?.read` branch

Where the root cause was discovered:
- `collections/lib/collections.ts` — `CollectionsMcpApiStack` uses `Table.fromTableName` to import `CollectionsRepo`, then passes it to `createApi` with `dynamo: { read: true }`

Where the failure was observed:
- `collections/src/modules/collections/tools/queries.ts` — `get_review_queue` tool was hitting `AccessDenied` on `CollectionsRepo/index/status-nextReviewAt-index`

---

## What It Looks Like

```typescript
// eventable/aws/api.ts — inside createApi, endpoint.dynamo?.read branch

if (endpoint.dynamo?.read) {
  dynamoTable?.grantReadData(lambda);
  dynamoCustomerTokenTable?.grantReadData(lambda);
  dynamoRefundRequestTable?.grantReadData(lambda);

  // Explicit GSI grant — grantReadData on imported tables doesn't reliably
  // include the /index/* resource in the generated IAM policy.
  if (dynamoTable) {
    lambda.addToRolePolicy(new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ['dynamodb:Query', 'dynamodb:Scan'],
      resources: [`${dynamoTable.tableArn}/index/*`],
    }));
  }
}
```

---

## Why It's Needed

### The CDK `grantReadData` gap on imported tables

When a DynamoDB table is created in the same CDK stack (`new Table(...)`), `grantReadData` generates an IAM policy that includes both the table ARN and `tableArn/index/*`. This covers GSI queries.

When a table is **imported** via `Table.fromTableName(...)` or `Table.fromTableArn(...)`, CDK constructs an `ITable` reference rather than a full `Table` object. The `grantReadData` call on an `ITable` generates a policy that includes the table ARN — but **does not reliably include `/index/*`**. The exact behavior depends on CDK version and whether the table ARN is fully resolved at synth time.

The result: the Lambda has `dynamodb:GetItem`, `dynamodb:BatchGetItem`, `dynamodb:Scan`, `dynamodb:Query` on the table itself — but **not** on `tableArn/index/*`. Any query that uses a GSI (Global Secondary Index) hits `AccessDenied`.

### Why this is silent until runtime

The CDK stack synthesizes and deploys without error. The IAM policy looks correct in the console (it has `dynamodb:Query`). The missing resource (`/index/*`) is only visible when you expand the policy statement and check the `Resource` array. The failure only surfaces when a Lambda actually executes a GSI query.

### Root cause of PR #544

`CollectionsMcpApiStack` imported `CollectionsRepo` via `Table.fromTableName` and passed it to `createApi` with `dynamo: { read: true }`. The `get_review_queue` tool queries the `status-nextReviewAt-index` GSI. The Lambda had `dynamodb:Query` on the table ARN but not on `CollectionsRepo/index/*`, causing `AccessDenied` on every `get_review_queue` call.

---

## When to Use

**Always add the explicit GSI grant when:**
- The DynamoDB table is imported via `Table.fromTableName` or `Table.fromTableArn` (not created in the same stack).
- The Lambda needs to query any GSI on that table.
- You're using `createApi` with `dynamo: { read: true }` — the fix is already in `eventable/aws/api.ts`, but if you're wiring up a Lambda manually, you must add it yourself.

**You do NOT need this when:**
- The table is created in the same CDK stack (`new Table(...)`). CDK resolves the ARN at synth time and `grantReadData` includes `/index/*` correctly.
- The Lambda only does `GetItem` / `BatchGetItem` (no GSI queries). Those operations target the table ARN directly.

---

## Canonical Example

From `eventable/aws/api.ts` (the fix applied in PR #544):

```typescript
import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";

// After grantReadData (which covers the table ARN):
if (dynamoTable) {
  lambda.addToRolePolicy(new PolicyStatement({
    effect: Effect.ALLOW,
    actions: ['dynamodb:Query', 'dynamodb:Scan'],
    resources: [`${dynamoTable.tableArn}/index/*`],
  }));
}
```

The `tableArn` property is available on both `Table` (created) and `ITable` (imported) — it resolves to the correct ARN in both cases.

---

## Detection

To audit for imported tables that may be missing the GSI grant:

```bash
# Find Table.fromTableName / Table.fromTableArn usages in CDK stacks
grep -rn "Table\.fromTable\(Name\|Arn\)" \
  --include="*.ts" \
  $(find . -path "*/lib/*" -o -path "*/cdk/*" -o -name "*stack*") \
  | grep -v node_modules | grep -v ".d.ts"
```

For each result, check whether the Lambda using that table also queries a GSI. If yes, verify the IAM policy includes `tableArn/index/*`.

---

## Gotchas

1. **`grantReadData` is not wrong — it's incomplete for imported tables.** Don't remove the `grantReadData` call. It grants the table-level permissions. The `addToRolePolicy` call adds the missing GSI resource on top.

2. **The fix in `eventable/aws/api.ts` only covers `createApi` callers.** If you wire up a Lambda manually (not through `createApi`), you must add the `addToRolePolicy` call yourself.

3. **`dynamoTables[]` (plural) does NOT get the GSI fix.** The current `createApi` implementation only adds the explicit GSI grant for `dynamoTable` (singular). If your Lambda uses `dynamoTables: [importedTable]`, you need to add the grant manually. See the `dynamoTables.forEach` block in `eventable/aws/api.ts`.

4. **This is a CDK version-dependent behavior.** Future CDK versions may fix `grantReadData` on imported tables to include `/index/*`. When upgrading CDK, verify whether the explicit grant is still needed by checking the synthesized CloudFormation template.

---

## Related Patterns

- [`eventbridge-disabled-cdk-antipattern.md`](./eventbridge-disabled-cdk-antipattern.md) — another CDK infrastructure pattern that causes silent runtime failures
- [`cdk-eventhandler-registration.md`](./cdk-eventhandler-registration.md) — how EventBridge handlers are registered in CDK stacks
