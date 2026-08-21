---
name: repository-analysis
description: Inspect a repository before planning, implementation, review, verification, or security analysis when a task needs a factual map of relevant components, conventions, commands, risks, and unknowns.
---

# Repository analysis

Inspect the supplied repository before acting on the task. This skill is a read-only procedure; it does not grant access, change a checkout, or modify implementation files.

## Inputs

Use the repository root and engineering task or issue. Accept an optional candidate branch or commit and area of focus. State any missing input that prevents a reliable analysis.

## Procedure

1. Confirm the repository root, current branch or commit, remotes, and working-tree state.
2. Inspect the top-level layout, then identify languages, frameworks, package managers, build tools, and locations for source, tests, configuration, migrations, infrastructure, and documentation.
3. Read repository guidance, including `AGENTS.md`, steering files, contribution rules, architecture records, and task-relevant policies or schemas.
4. Trace only task-relevant implementation and test patterns. Identify applicable build, test, lint, type-check, and formatting commands from repository-owned configuration and documentation.
5. Identify likely risks and unknowns. Label observations as facts or assumptions; do not infer facts from names alone.
6. Produce the concise report defined in [the output contract](references/output-contract.md).

## Boundaries

Stop and report a blocker if the repository cannot be located, the requested ref cannot be inspected, required files are inaccessible, unrelated uncommitted work could be damaged, or the task is too ambiguous to identify relevant components. Do not perform a deep repository-wide audit when the task has a bounded focus.
