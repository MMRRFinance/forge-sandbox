# Pattern: Fargate Task CPU/Memory Ratio — Valid CDK Combinations

**Type:** Pattern (use this — invalid combinations fail at deploy time)  
**Category:** Infrastructure / CDK / ECS Fargate  
**Status:** Canonical — AWS enforces strict CPU/memory pairing; CDK does not validate at synth time

---

## Name

Fargate CPU/memory ratio — the AWS-enforced constraint that Fargate task definitions must use specific CPU/memory combinations. Invalid combinations are accepted by CDK at synth time but rejected by CloudFormation at deploy time.

---

## File Paths

Where this pattern was applied:
- `devon-agent/infra/ecs-task.ts` — Fargate task definition for the Devon agent fleet (PR #3: bumped CPU 1024→2048, memory 4096→8192)

Where similar patterns appear:
- Any CDK stack with `FargateTaskDefinition` or `TaskDefinition` with `compatibility: Compatibility.FARGATE`

---

## The Valid Combinations

AWS Fargate enforces a strict matrix of valid CPU/memory pairs. These are the only combinations that will deploy successfully:

| CPU (units) | Valid Memory (MiB) |
|-------------|-------------------|
| 256 (0.25 vCPU) | 512, 1024, 2048 |
| 512 (0.5 vCPU) | 1024, 2048, 3072, 4096 |
| 1024 (1 vCPU) | 2048, 3072, 4096, 5120, 6144, 7168, 8192 |
| 2048 (2 vCPU) | 4096–16384 (in 1024 increments) |
| 4096 (4 vCPU) | 8192–30720 (in 1024 increments) |
| 8192 (8 vCPU) | 16384–61440 (in 4096 increments) |
| 16384 (16 vCPU) | 32768–122880 (in 8192 increments) |

---

## What It Looks Like

```typescript
// devon-agent/infra/ecs-task.ts (after PR #3 bump)

import { FargateTaskDefinition } from 'aws-cdk-lib/aws-ecs';

const taskDefinition = new FargateTaskDefinition(this, 'DevonAgentTask', {
  cpu: 2048,           // 2 vCPU
  memoryLimitMiB: 8192, // 8 GB — valid for 2048 CPU
});
```

```typescript
// ❌ INVALID — will fail at CloudFormation deploy
const taskDefinition = new FargateTaskDefinition(this, 'DevonAgentTask', {
  cpu: 2048,
  memoryLimitMiB: 3000, // Not a valid increment for 2048 CPU
});

// ❌ ALSO INVALID — memory too low for this CPU tier
const taskDefinition = new FargateTaskDefinition(this, 'DevonAgentTask', {
  cpu: 2048,
  memoryLimitMiB: 2048, // Minimum for 2048 CPU is 4096
});
```

---

## Why CDK Doesn't Catch This

CDK's `FargateTaskDefinition` construct accepts `cpu` and `memoryLimitMiB` as plain numbers. It does not validate the combination at synth time — it passes the values directly to the CloudFormation `AWS::ECS::TaskDefinition` resource. CloudFormation validates the combination when the stack is deployed and rejects invalid pairs with:

```
Resource handler returned message: "Invalid request provided: CPU value '2048' is not compatible with memory value '3000'"
```

This means:
- `cdk synth` succeeds with an invalid combination.
- `cdk deploy` fails with a CloudFormation error.
- The error message is clear, but the failure happens late in the deploy pipeline.

---

## When to Use

**Always verify the CPU/memory pair when:**
- Creating a new Fargate task definition.
- Bumping CPU or memory on an existing task definition — changing one requires checking the other.
- Copying a task definition from another service — the source may have been tuned for different workloads.

**The Devon agent bump (PR #3):**
- Before: `cpu: 1024, memoryLimitMiB: 4096` — valid (1 vCPU, 4 GB)
- After: `cpu: 2048, memoryLimitMiB: 8192` — valid (2 vCPU, 8 GB)
- Reason: agents were hitting CPU throttle during peak usage; doubling CPU required doubling memory to stay within the valid ratio range

---

## Canonical Example

From `devon-agent/infra/ecs-task.ts` (PR #3):

```typescript
import * as cdk from 'aws-cdk-lib';
import * as ecs from 'aws-cdk-lib/aws-ecs';

export class DevonAgentTaskStack extends cdk.Stack {
  constructor(scope: cdk.App, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const taskDefinition = new ecs.FargateTaskDefinition(this, 'DevonAgentTask', {
      // 2 vCPU — valid memory range: 4096–16384 MiB (1024 increments)
      cpu: 2048,
      memoryLimitMiB: 8192, // 8 GB — within valid range, maintains ~4:1 memory:CPU ratio
    });

    taskDefinition.addContainer('DevonAgentContainer', {
      image: ecs.ContainerImage.fromRegistry('your-ecr-image'),
      memoryLimitMiB: 8192,
      // ... other container config
    });
  }
}
```

---

## Sizing Guidance

For agent workloads (LLM inference, tool execution, concurrent sessions):

| Workload | Recommended | Rationale |
|----------|-------------|-----------|
| Light agent (single session, simple tools) | 512 CPU / 2048 MiB | Minimal cost, adequate for sequential tool calls |
| Standard agent (multi-tool, moderate concurrency) | 1024 CPU / 4096 MiB | Baseline for most CoreServices agents |
| Heavy agent (parallel tool calls, large context) | 2048 CPU / 8192 MiB | Devon agent post-PR #3; handles peak LLM + tool concurrency |
| High-throughput agent (many concurrent sessions) | 4096 CPU / 16384 MiB | Reserved for batch processing agents |

The Devon agent was bumped from 1024/4096 to 2048/8192 because CPU throttling was observed during peak usage (multiple concurrent tool calls + LLM inference). Memory was doubled to maintain the valid ratio and provide headroom for large context windows.

---

## Gotchas

1. **CDK does not validate at synth time.** Always cross-check the combination against the valid matrix before deploying. A quick lookup in the AWS docs or this table is faster than a failed deploy.

2. **Container memory limit ≤ task memory limit.** If you set `memoryLimitMiB` on the container, it must be ≤ the task's `memoryLimitMiB`. Setting them equal (as in the example above) is common and correct — it gives the container all available task memory.

3. **Fleet-wide impact.** Changing the task definition affects all tasks using that definition on the next deploy. For the Devon agent, this means all agent instances get the new CPU/memory allocation simultaneously. Plan deploys during low-traffic windows if the change is significant.

4. **Fargate Spot pricing changes with CPU tier.** Bumping from 1024 to 2048 CPU roughly doubles the Fargate cost per task-hour. Verify the cost impact before bumping production fleets.

5. **ARM64 (Graviton) has the same valid combinations.** If using `runtimePlatform: { cpuArchitecture: CpuArchitecture.ARM64 }`, the same CPU/memory matrix applies.

---

## Related Patterns

- [`cdk-inline-policy-gsi-grant.md`](./cdk-inline-policy-gsi-grant.md) — another CDK pattern where the framework doesn't validate at synth time
- [`eventbridge-disabled-cdk-antipattern.md`](./eventbridge-disabled-cdk-antipattern.md) — CDK anti-pattern with silent runtime failure
