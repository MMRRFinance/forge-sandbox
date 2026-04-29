# CoreServices Pattern Library

Recurring code patterns discovered during CoreServices exploration. Each entry covers: name, file paths, how it works, when to use/avoid, and a canonical example.

## Patterns (use these)

| Pattern | File | Summary |
|---|---|---|
| `handleLambda` wrapper | [`handle-lambda-wrapper.md`](./handle-lambda-wrapper.md) | Auto error monitoring for EventBridge/SQS handlers via eventable codegen |
| `captureError` + re-throw | [`captureError-rethrow.md`](./captureError-rethrow.md) | Manual error monitoring for services without `.eventable/` |
| 4-tier funding account waterfall | [`four-tier-funding-account-waterfall.md`](./four-tier-funding-account-waterfall.md) | Ordered bank account selection: primary → secondary → previous loan → any checking |
| `createEventHandler` CDK registration | [`cdk-eventhandler-registration.md`](./cdk-eventhandler-registration.md) | Standard way to wire EventBridge-triggered Lambdas in CDK stacks via `EventHandler[]` config array |
| `addToRolePolicy` GSI grant | [`cdk-inline-policy-gsi-grant.md`](./cdk-inline-policy-gsi-grant.md) | Required workaround when `grantReadData` on imported DynamoDB tables omits `/index/*` from IAM policy |
| EventBridge `source` + `detail-type` matching | [`eventbridge-event-source-matching.md`](./eventbridge-event-source-matching.md) | Exact-string routing contract between event emitters and consumers — copy-paste, never retype |
| Fargate CPU/memory valid combinations | [`fargate-cpu-memory-ratio.md`](./fargate-cpu-memory-ratio.md) | AWS-enforced CPU/memory pairing matrix; CDK doesn't validate at synth time — invalid combos fail at deploy |

## Anti-Patterns (avoid these)

| Anti-Pattern | File | Summary |
|---|---|---|
| `return { statusCode: 500 }` | [`return-statuscode-500-antipattern.md`](./return-statuscode-500-antipattern.md) | Swallows errors silently — Lambda marked SUCCESS, monitoring never fires |
| EventBridge rule disabled by default | [`eventbridge-disabled-cdk-antipattern.md`](./eventbridge-disabled-cdk-antipattern.md) | CDK rule deployed with `enabled: false` — silences entire monitoring pipeline |
| `Table.fromTableName` IAM gap | [`dynamodb-imported-table-iam-gap.md`](./dynamodb-imported-table-iam-gap.md) | Imported tables miss `/index/*` in `grantReadData` — GSI queries hit AccessDenied at runtime |

## Reference

| Reference | File | Summary |
|---|---|---|
| OKR tool quirks | [`okr-tool-quirks.md`](./okr-tool-quirks.md) | 5 confirmed API gotchas: filtered list_entities, search_entities response path, partial UUIDs, spill file re-spill, ownerId filter asymmetry |

## How to add a pattern

1. Create a new `.md` file in this directory.
2. Include all 5 required sections: **Name**, **File Paths**, **How It Works**, **When to Use/Avoid**, **Canonical Example**.
3. Add a row to the table above.
4. Submit via PR on branch `forge/<descriptor>`.
