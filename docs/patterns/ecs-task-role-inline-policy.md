# Pattern: Least-Privilege Inline Policies on ECS Task Roles in CDK

**Type:** Pattern (use this)
**Category:** Infrastructure / CDK / IAM / ECS
**Status:** Canonical — preferred over managed policies for ECS task roles

---

## Name

ECS task role inline policy — adding least-privilege `addToRolePolicy` statements directly to the ECS task role rather than attaching AWS-managed policies. Keeps permissions scoped to exactly what the task needs, avoids over-broad managed policies, and keeps the policy co-located with the CDK stack that defines the task.

---

## File Paths

Where the pattern is implemented:
- `devon-agent/lib/devon-agent-stack.ts` — `FargateTaskDefinition` task role with inline `PolicyStatement` blocks for Cost Explorer, CloudWatch, and SSM access

Where the anti-pattern (managed policy attachment) appears:
- `devon-agent/lib/devon-agent-stack.ts` (earlier version) — `AmazonSSMReadOnlyAccess` managed policy attached to task role; replaced with scoped inline policy

---

## What It Looks Like

```typescript
// devon-agent/lib/devon-agent-stack.ts
import {
  FargateTaskDefinition,
  ContainerImage,
} from 'aws-cdk-lib/aws-ecs';
import {
  Effect,
  ManagedPolicy,
  PolicyStatement,
  Role,
} from 'aws-cdk-lib/aws-iam';

const taskDefinition = new FargateTaskDefinition(this, 'DevonTaskDef', {
  memoryLimitMiB: 2048,
  cpu: 1024,
});

// ✅ Inline policy — scoped to exactly what the task needs
// Cost Explorer: service-level only, must use Resource: "*"
taskDefinition.taskRole.addToRolePolicy(new PolicyStatement({
  effect: Effect.ALLOW,
  actions: [
    'ce:GetCostAndUsage',
    'ce:GetCostForecast',
  ],
  resources: ['*'],  // required — ce:* has no resource-level support
}));

// CloudWatch Logs: scoped to this task's log group
taskDefinition.taskRole.addToRolePolicy(new PolicyStatement({
  effect: Effect.ALLOW,
  actions: [
    'logs:CreateLogStream',
    'logs:PutLogEvents',
  ],
  resources: [
    `arn:aws:logs:${this.region}:${this.account}:log-group:/devon-agent/*`,
  ],
}));

// SSM Parameter Store: scoped to /devon-agent/ prefix only
taskDefinition.taskRole.addToRolePolicy(new PolicyStatement({
  effect: Effect.ALLOW,
  actions: [
    'ssm:GetParameter',
    'ssm:GetParameters',
    'ssm:GetParametersByPath',
  ],
  resources: [
    `arn:aws:ssm:${this.region}:${this.account}:parameter/devon-agent/*`,
  ],
}));

// ❌ Anti-pattern: managed policy is too broad
// taskDefinition.taskRole.addManagedPolicy(
//   ManagedPolicy.fromAwsManagedPolicyName('AmazonSSMReadOnlyAccess')
// );
// AmazonSSMReadOnlyAccess grants ssm:Get* on ALL parameters in the account.
// The inline policy above grants only /devon-agent/* — correct least-privilege.
```

---

## Why Inline Policies Over Managed Policies

### Managed policies are convenient but over-broad

AWS managed policies like `AmazonSSMReadOnlyAccess`, `CloudWatchLogsFullAccess`, or `AmazonECS_FullAccess` are designed to cover all use cases for a service. They grant far more permissions than any single task needs. For ECS task roles, this violates least-privilege and creates unnecessary blast radius if the task is compromised.

### Inline policies are co-located with the task definition

When the policy is defined in the same CDK construct as the task, it's immediately visible to reviewers. There's no need to navigate to IAM in the console to understand what the task can do. The CDK stack is the single source of truth.

### `addToRolePolicy` vs `attachInlinePolicy`

CDK offers two ways to add inline policies to a role:

| Method | Use when |
|--------|----------|
| `role.addToRolePolicy(new PolicyStatement(...))` | Adding individual statements — preferred for ECS task roles. Statements are merged into a single inline policy named `CDKDefaultPolicy`. |
| `role.attachInlinePolicy(new Policy(...))` | Adding a named policy with multiple statements that you want to reference by name. Useful when the same policy needs to be attached to multiple roles. |

For ECS task roles, `addToRolePolicy` is almost always the right choice. The task role is unique to the task definition — there's no reason to name the policy or reuse it.

---

## When to Use

**Use `addToRolePolicy` inline statements when:**
- The ECS task needs access to AWS services (Cost Explorer, SSM, CloudWatch, S3, DynamoDB, etc.).
- You want least-privilege: scope to specific ARNs, prefixes, or actions.
- The task role is defined in the same CDK stack as the task definition.

**Use managed policies only when:**
- You are prototyping and need to move fast — replace with inline policies before production.
- The managed policy is a CDK-generated grant (e.g., `bucket.grantRead(taskRole)`) — these are already scoped correctly and are preferred over manual `addToRolePolicy` for S3, DynamoDB, SQS, etc.

**Never use `AdministratorAccess` or `PowerUserAccess` on a task role.** These are appropriate for CI/CD pipelines deploying infrastructure, not for application task roles.

---

## Canonical Example

From `devon-agent/lib/devon-agent-stack.ts` (the full inline policy block for the devon-agent ECS task):

```typescript
// Three separate addToRolePolicy calls, each scoped to minimum required access:

// 1. Cost Explorer — service-level only (Resource: "*" required)
taskDefinition.taskRole.addToRolePolicy(new PolicyStatement({
  effect: Effect.ALLOW,
  actions: ['ce:GetCostAndUsage', 'ce:GetCostForecast'],
  resources: ['*'],
}));

// 2. CloudWatch Logs — scoped to this task's log group prefix
taskDefinition.taskRole.addToRolePolicy(new PolicyStatement({
  effect: Effect.ALLOW,
  actions: ['logs:CreateLogStream', 'logs:PutLogEvents'],
  resources: [`arn:aws:logs:${this.region}:${this.account}:log-group:/devon-agent/*`],
}));

// 3. SSM — scoped to /devon-agent/ parameter prefix only
taskDefinition.taskRole.addToRolePolicy(new PolicyStatement({
  effect: Effect.ALLOW,
  actions: ['ssm:GetParameter', 'ssm:GetParameters', 'ssm:GetParametersByPath'],
  resources: [`arn:aws:ssm:${this.region}:${this.account}:parameter/devon-agent/*`],
}));
```

---

## Gotchas

1. **`taskRole` vs `executionRole` — they are different.** The `taskRole` is what the running container uses to call AWS APIs. The `executionRole` is what ECS uses to pull the container image from ECR and write logs to CloudWatch. Add application permissions to `taskRole`. The `executionRole` should only have `AmazonECSTaskExecutionRolePolicy` (or equivalent scoped permissions).

2. **CDK merges `addToRolePolicy` calls into one inline policy.** Multiple `addToRolePolicy` calls on the same role produce a single inline policy named `CDKDefaultPolicy` with all statements merged. This is fine — it's just how CDK works. Don't be surprised when you see one policy in the console instead of three.

3. **`this.region` and `this.account` resolve at deploy time, not synth time.** If you're building a cross-account or cross-region stack, these tokens may not resolve as expected. Use explicit strings or `Stack.of(this).region` / `Stack.of(this).account` for clarity.

4. **Cost Explorer actions require `Resource: "*"` — see `iam-resource-wildcard-constraint.md`.** This is not a mistake or a lazy shortcut. It is the only valid value for `ce:*` actions. See the related pattern for the full explanation.

5. **CDK `grant*` helpers are preferred when available.** For S3 (`bucket.grantRead`), DynamoDB (`table.grantReadData`), SQS (`queue.grantConsumeMessages`), etc., use the CDK grant helpers instead of manual `addToRolePolicy`. They are already scoped correctly and are maintained by the CDK team. Use `addToRolePolicy` for services that don't have CDK grant helpers (Cost Explorer, SSM path-scoped access, etc.).

---

## Related Patterns

- [`iam-resource-wildcard-constraint.md`](./iam-resource-wildcard-constraint.md) — why `Resource: "*"` is required for Cost Explorer and other service-level actions
- [`cdk-inline-policy-gsi-grant.md`](./cdk-inline-policy-gsi-grant.md) — `addToRolePolicy` for DynamoDB GSI access on imported tables (same mechanism, different use case)
- [`fargate-cpu-memory-ratio.md`](./fargate-cpu-memory-ratio.md) — valid Fargate CPU/memory combinations for the task definition
