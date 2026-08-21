---
name: analyze-test-failure
description: Classify a real verification failure and prepare a bounded, policy-compliant repair request when a verifier, builder, or engineering lead needs evidence-based next steps.
---

# Analyze test failure

Classify a real verification failure, identify the likely root cause without overstating certainty, and create a bounded repair request. This skill does not authorize a repair or change the original task.

## Inputs

Require the Engineering Task, Verification Result, relevant logs, current repair-attempt count, and repair policy.

## Procedure

1. Confirm that a real failure exists and identify the failing check. Extract the smallest useful error evidence.
2. Classify it as implementation, test, build, type-check, lint, dependency, environment, infrastructure, security, acceptance-criterion, or unknown failure.
3. Decide whether it is retryable, identify the likely root cause with a stated confidence boundary, and define the smallest corrective action.
4. Preserve the original task and acceptance criteria. Do not remove or weaken a valid failing test.
5. Apply the maximum-repair-attempt policy. Produce a repair request conforming to `.ai/schemas/repair-request.schema.json` using [the output contract](references/output-contract.md).

Include these constraints in every repair request:

```text
Do not modify the original acceptance criteria.
Do not remove or weaken a valid failing test.
Do not bypass verification.
Do not make unrelated changes.
Re-run the failed check and the broader applicable suite.
```

Return `needs_human` rather than an autonomous repair when attempts are exhausted; production access, destructive action, or human security approval is required; requirements conflict; ownership is unclear; or the failure is non-retryable.
