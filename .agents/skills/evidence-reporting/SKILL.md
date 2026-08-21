---
name: evidence-reporting
description: Aggregate task, implementation, verification, review, security, and repair evidence into a consistent final decision package when an engineering lead or judge needs a traceable handoff.
---

# Evidence reporting

Aggregate final task evidence into a consistent decision package. This skill does not grant approval, merge, deployment, or policy-override authority.

## Inputs

Require the Engineering Task, Execution Result, Verification Result, findings, repair history, branch/commit/pull-request information, and applicable policy.

## Procedure

1. Confirm that all artifacts identify the same task and that they refer to the final candidate commit.
2. Detect missing or contradictory artifacts before deciding the result.
3. Summarize implementation changes and deterministic verification. Map every required acceptance criterion to evidence.
4. Include open findings by severity, repair attempts and outcomes, and unresolved limitations.
5. Apply only the policy-defined decisions `pass`, `fail`, and `needs_human`. Do not use model confidence as evidence or convert missing evidence into a pass.
6. Produce an artifact conforming to `.ai/schemas/evidence-bundle.schema.json` using [the output contract](references/output-contract.md).

## Required human summary

```text
Task
Risk
Candidate commit
Pull request
Acceptance criteria passed
Verification status
Blocking findings
Non-blocking findings
Repair attempts
Known limitations
Recommended human action
```

Return `needs_human` when mandatory evidence is missing, artifacts refer to different commits, required checks were not run, blocking findings remain, required acceptance criteria are unverified, or policy interpretation is ambiguous.
