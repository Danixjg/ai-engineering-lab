---
name: run-verification
description: Independently execute deterministic checks for an exact candidate commit when a verifier, or a builder performing pre-submission checks, needs machine-readable verification evidence.
---

# Run verification

Independently execute deterministic verification against the exact candidate commit. The Verifier is the authoritative independent user; a Builder may use this only for pre-submission checks. This skill does not grant repository, dependency-installation, credential, or external-system permissions.

## Inputs

Require the Engineering Task, repository, exact candidate commit SHA, acceptance criteria, and verification policy.

## Procedure

1. Confirm the repository and exact commit. Inspect or check out that commit without changing implementation.
2. Read repository instructions and discover applicable repository-defined commands using [check discovery](references/check-discovery.md). Prefer those commands to invented ones and install dependencies only when permitted.
3. Run applicable build, unit, integration, end-to-end, type-check, lint, formatting, dependency, security, and contract checks.
4. For every check, record its command, exit code, duration, status, and relevant output reference. Use only `passed`, `failed`, `skipped`, `not_run`, or `blocked` in human reporting; map schema output to its permitted status vocabulary.
5. Map deterministic evidence to every acceptance criterion, classify any failures with [failure classification](references/failure-classification.md), and produce a result that conforms to `.ai/schemas/verification-result.schema.json` using [the output contract](references/output-contract.md).

## Evidence boundaries

Never accept another agent's assertion as proof, report an unexecuted check as executed, or modify implementation or tests to obtain a passing result. Preserve the distinction between passed, failed, skipped, not run, and blocked.

Return `blocked` when credentials, execution environment, required services, or the exact commit are unavailable; when verification would make a destructive external change; or when the verification policy is missing or contradictory.
