---
name: project-orchestration
description: Turn an authorized software-project brief into a governed, staged Multica squad plan, then coordinate bounded recursive delegation across engineering roles. Use for new repositories, substantial projects in existing repositories, and parent issues whose delivery requires multiple dependent agents. Do not use for a single bounded task that one agent can complete directly.
---

# Project orchestration

Coordinate a project without implementing delegated product work. Preserve the
project brief as the source of product intent while converting it into explicit,
auditable child issues.

## Inputs

Require a Project Blueprint conforming to
`.ai/schemas/project-blueprint.schema.json`, or an issue containing equivalent
fields. Also require the current parent issue, project resources, squad roster,
and routing plan or [routing policy](references/routing-policy.json).

If the target repository, acceptance criteria, required authority, or project
boundary is materially ambiguous, return `needs_human`. Do not invent the
missing product decision.

## Procedure

1. Normalize the request into a Project Blueprint. Preserve requirements,
   constraints, acceptance criteria, authorizations, and human gates.
2. Apply every mandatory governance document in the routing policy. Governance,
   permissions, and human gates are hard constraints; they are never affected
   by skill or agent scores.
3. Produce a routing plan. When the blueprint helper is available, prefer its
   deterministic `plan` output. Otherwise follow [delegation and
   recursion](references/delegation.md) and record equivalent score evidence.
4. Confirm that the Multica project retains the AI Engineering Lab control
   repository. For a new target repository, create it, add it to the workspace
   repository registry, and attach it as a project resource only when the
   blueprint explicitly authorizes those operations. Create later child issues
   only after their target repository is available as project context.
5. Create staged child issues. Give each issue one owner, one repository/ref,
   bounded scope, acceptance criteria, expected outputs, dependencies, selected
   skills, and its remaining recursion budget.
6. Delegate by role and skill coverage. Do not change a shared agent's global
   skill bindings to tailor one task; select an already-compatible agent.
7. Treat each stage as a barrier. Integration consumes committed SHAs, and all
   independent checks inspect the same integration commit.
8. On retryable failure, create only the bounded repair route allowed by policy.
   On any stop condition, update the parent with evidence and return
   `needs_human`.
9. Aggregate child outcomes using [the output contract](references/output-contract.md).
   A completed child run is not proof that the parent project is complete.

## Boundaries

- Never exceed maximum depth, children per issue, total descendants, or
  parallel tasks.
- Never allow a child issue to broaden the parent's authorization.
- Never use another task's live worktree as a handoff.
- Never merge, deploy, access production, expand permissions, or make a
  destructive change through a soft routing decision.
- Never reinterpret missing evidence as success.
