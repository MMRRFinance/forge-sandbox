# Pattern: IAM Resource Wildcard Constraint for Service-Level Actions

**Type:** Pattern (required — not a choice)
**Category:** Infrastructure / IAM / CDK
**Status:** Canonical — applies to Cost Explorer and other AWS services that do not support resource-level permissions

---

## Name

IAM Resource wildcard constraint — certain AWS service actions (notably Cost Explorer `ce:*`) only support `Resource: "*"` and cannot be scoped to a specific ARN. Attempting to scope them causes a silent IAM policy that never grants access.

---

## File Paths

Where the pattern is implemented:
- `devon-agent/lib/devon-agent-stack.ts` — ECS task role inline policy granting `ce:GetCostAndUsage` with `Resource: "*"`

Where the constraint is documented by AWS:
- [AWS Cost Explorer IAM reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_awscostexplorerservice.html) — all `ce:*` actions list `Resource: "*"` as the only supported resource type

---

## What It Looks Like

```typescript
// devon-agent/lib/devon-agent-stack.ts
import { Effect, PolicyStatement } from 'aws-cdk-lib/aws-iam';

// Cost Explorer actions ONLY support Resource: "*"
// Attempting to scope to a specific ARN (e.g., an account ARN) will
// produce a policy that silently never grants access.
taskRole.addToRolePolicy(new PolicyStatement({
  effect: Effect.ALLOW,
  actions: ['ce:GetCostAndUsage', 'ce:GetCostForecast'],
  resources: ['*'],  // <-- required, not lazy — ce:* has no resource-level support
}));
```

**Wrong (silently broken):**
```typescript
taskRole.addToRolePolicy(new PolicyStatement({
  effect: Effect.ALLOW,
  actions: ['ce:GetCostAndUsage'],
  resources: [`arn:aws:ce:us-east-1:${accountId}:*`],  // ❌ ce:* ignores this
}));
```

---

## Why It Happens

AWS IAM has two tiers of resource support:

1. **Resource-level permissions** — the action can be scoped to a specific ARN (e.g., `s3:GetObject` on `arn:aws:s3:::my-bucket/*`). Scoping reduces blast radius.
2. **Service-level permissions only** — the action operates at the account/service level and AWS does not support ARN scoping. The only valid resource is `"*"`. Examples: `ce:*`, `sts:GetCallerIdentity`, `iam:GenerateCredentialReport`, `support:*`.

When you specify a non-`"*"` resource for a service-level-only action, IAM does **not** error at policy creation time. The policy is created successfully. But the action is never authorized because the resource condition never matches. The failure only surfaces at runtime as `AccessDenied`.

---

## How to Identify Affected Actions

Check the [AWS Service Authorization Reference](https://docs.aws.amazon.com/service-authorization/latest/reference/reference_policies_actions-resources-contextkeys.html) for the service. In the "Actions" table, look at the "Resource types" column. If it shows `*` (asterisk) with no named resource type, the action only supports `Resource: "*"`.

Common services where this applies:
- **Cost Explorer** (`ce:*`) — all actions
- **AWS Support** (`support:*`) — all actions
- **IAM** — `iam:GenerateCredentialReport`, `iam:GetAccountSummary`, `iam:ListAccountAliases`
- **STS** — `sts:GetCallerIdentity`
- **Budgets** (`budgets:*`) — most actions
- **Health** (`health:*`) — all actions

---

## When to Use

**Always use `Resource: "*"` when:**
- The AWS service authorization reference lists only `*` in the resource types column for that action.
- You are granting `ce:*`, `support:*`, `budgets:*`, or `health:*` actions.
- CDK's `grant*` helpers are not available for the service (they don't exist for Cost Explorer).

**Do NOT attempt to scope to a specific ARN when:**
- The action is service-level only. It will appear to work (no CDK/CloudFormation error) but will silently fail at runtime.

---

## Canonical Example

From `devon-agent/lib/devon-agent-stack.ts` (the ECS task role that needs Cost Explorer access for the agent's cost reporting feature):

```typescript
// Correct: Resource: "*" is required for ce:* actions
taskRole.addToRolePolicy(new PolicyStatement({
  effect: Effect.ALLOW,
  actions: [
    'ce:GetCostAndUsage',
    'ce:GetCostForecast',
    'ce:GetDimensionValues',
  ],
  resources: ['*'],
}));
```

---

## Gotchas

1. **CDK does not warn you.** `new PolicyStatement({ actions: ['ce:GetCostAndUsage'], resources: ['arn:aws:ce:...'] })` synthesizes and deploys without error. The broken policy is only visible in the IAM console if you know to look for it.

2. **`Resource: "*"` is not a security failure here.** For service-level-only actions, `"*"` is the only valid value — it does not mean "all resources in all accounts." The action itself is scoped to the calling account by AWS's service implementation. Least-privilege is achieved by being specific about which `ce:*` actions you grant, not by scoping the resource.

3. **Condition keys can still narrow scope.** Even when `Resource: "*"` is required, you can add `Condition` blocks (e.g., `aws:RequestedRegion`, `aws:PrincipalTag`) to limit when the policy applies. This is the correct way to add least-privilege constraints for service-level actions.

4. **This is distinct from the DynamoDB GSI gap.** The DynamoDB GSI gap (`dynamodb-imported-table-iam-gap.md`) is a CDK bug where the correct resource ARN is omitted. The Cost Explorer wildcard constraint is an AWS service design decision — there is no "correct" ARN to use.

---

## Related Patterns

- [`cdk-inline-policy-gsi-grant.md`](./cdk-inline-policy-gsi-grant.md) — inline policy workaround for DynamoDB GSI access (different root cause, same `addToRolePolicy` mechanism)
- [`ecs-task-role-inline-policy.md`](./ecs-task-role-inline-policy.md) — how to add least-privilege inline policies to ECS task roles in CDK
