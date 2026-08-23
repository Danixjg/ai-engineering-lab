# Project Blueprints

A Project Blueprint is the portable boundary between a person's project intent
and recursive squad execution. It can target a repository that already exists
or authorize the squad to create a new GitHub repository.

The AI Engineering Lab remains the control repository. Do not copy its whole
contents into every product repository. Each Multica project retains this
repository as a control resource and adds the target repository as delivery
work proceeds. Workspace skills provide reusable procedures, while parent and
child issues carry the project-specific contracts.

## Contract

`.ai/schemas/project-blueprint.schema.json` defines:

- project identity, objective, requirements, and acceptance criteria;
- new or existing target-repository details;
- risk and expected outputs;
- explicit authorizations for repository, issue, branch, push, and pull-request
  creation;
- human gates for ambiguity, permissions, destructive changes, production,
  deployment, and merge;
- maximum recursion depth, child count, and parallel tasks.

Authorizations do not imply completion. They only establish which ordinary
operations the squad may perform while satisfying the brief. Human gates remain
hard stops.

## Local planning

Start from the checked-in example:

```bash
cp .ai/blueprints/project.example.json project.json
./bin/project-blueprint validate project.json
./bin/project-blueprint plan project.json
./bin/project-blueprint render project.json
./bin/project-blueprint preflight project.json
```

The deterministic plan resolves the canonical skill and agent manifests. It
hard-gates role, risk eligibility, and required skill coverage before applying
weights. Required skills are always selected. Optional skills must meet the
configured threshold and the per-task context budget.

The routing policy is packaged with the `project-orchestration` skill at
`.agents/skills/project-orchestration/references/routing-policy.json`. Governance,
permissions, acceptance criteria, and recursion limits are never weighted.

## Submit to Multica

You can also create the parent issue directly in Multica and assign it to the
Engineering Squad. Put the objective, repository mode and identity,
requirements, acceptance criteria, permitted external actions, human gates,
and recursion limits in the issue. The lead must post a normalized Project
Blueprint and routing plan before creating children; material omissions return
`needs_human`. The helper below is the reproducible path that performs this
normalization before submission.

Dry-run by default:

```bash
./bin/project-blueprint submit project.json \
  --create-project \
  --start
```

Apply after reviewing the output:

```bash
./bin/project-blueprint submit project.json \
  --create-project \
  --start \
  --apply
```

Before either write, the helper performs a live preflight: the daemon must be
running; the Engineering Lead must lead the named squad; every routed agent
must be a squad member; and every required workspace skill must already be
bound. A drifted workspace fails closed before project or issue creation.

`--create-project` creates a Multica project with the control repository as a
resource. To use an existing Multica project, replace it with
`--project-id <id>`. Without `--start`, the parent issue is assigned in
`backlog`; with it, the issue is created in `todo` and the squad leader is
enqueued.

The helper deliberately does not create the target GitHub repository itself.
That operation belongs to the repository-bootstrap child issue, where the
Engineering Lead can confirm the blueprint's authorization and preserve its
evidence on the issue. The bootstrap stage then registers the Git URL and adds
it as a Multica project resource before target-repository child work begins.

## Recursive execution

The leader follows `.ai/workflows/project-delivery.yaml`:

1. Normalize and plan the project.
2. Bootstrap and register a new target repository when authorized.
3. Decompose implementation into independently verifiable slices.
4. Integrate committed child results from a clean worktree.
5. Run Verifier, Reviewer, and Security Adversary concurrently against the
   exact integration commit.
6. Route retryable failures through bounded repairs.
7. Ask the Judge to aggregate evidence.
8. Stop at the configured human merge or deployment gate.

Every child receives a smaller recursion budget. The root limit covers all
descendants, not only direct children. A child may narrow authority but may
never expand it.

## Skill growth

Do not attach every new skill to every agent. Add routing metadata to
`.ai/skills/manifest.yaml`, bind the skill only to eligible long-lived roles,
and let the plan score only skills already bound to a compatible agent.

Multica skill bindings are agent-wide. Changing a shared agent's bindings for a
single issue is unsafe when tasks run concurrently. Task-level specialization
therefore comes from delegation to stable specialist agents and native skill
selection, not from global binding mutations around a run.
