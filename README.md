# AI Engineering Lab

This repository is the version-controlled control plane for autonomous
engineering work in other GitHub repositories. A Project Blueprint can describe
a new or existing target repository, and the Engineering Squad can turn that
brief into bounded, staged child issues while this repository supplies the role
instructions, routing rules, contracts, skills, and governance. It intentionally
does not contain a Multica workspace ID, server URL, runtime path, model
credential, or other instance secret.

## Repository layout

| Path | Purpose |
| --- | --- |
| `.ai/prompts/` | Provider-neutral instructions for every engineering role. |
| `.ai/schemas/` | Contracts for tasks, results, findings, and workflow state. |
| `.ai/workflows/` | The engineering-task lifecycle. |
| `.ai/blueprints/` | Portable project-intent examples for new or existing repositories. |
| `.ai/agents/` | Stable runtime-bound agent instances, role eligibility, skills, dependencies, and health requirements. |
| `.ai/runtime/` | OpenCode/Ollama adapters plus the weighted local-model portfolio and independence policy. |
| `.agents/skills/` | Canonical sources for reusable agent skills. |
| `docs/multica/` | Multica skill bindings and [worktree coordination rules](docs/multica/worktree-coordination.md). |
| `bin/multiengin` | Portable local-runtime launcher for the current machine. |
| `.infrastructure/` | Low-level macOS/Linux baseline bootstrap and full-host verification. |
| `scripts/package-skill.py` | Packages a canonical skill for import into Multica. |
| `bin/project-blueprint` | Validates, plans, renders, and submits a governed project brief. |

## Start a project through the squad

Copy and edit the example Project Blueprint. The brief makes repository
creation, issue creation, branch/push/PR authority, recursion limits, and human
gates explicit.

```bash
cp .ai/blueprints/project.example.json project.json
./bin/project-blueprint validate project.json
./bin/project-blueprint plan project.json
./bin/project-blueprint preflight project.json
```

Preview creation of a dedicated Multica project and parent issue without
changing the workspace:

```bash
./bin/project-blueprint submit project.json \
  --create-project \
  --start
```

After reviewing the plan, add `--apply` to create the Multica project, retain
this repository as its control resource, assign the parent issue to the
configured squad, and start the leader. Omit `--start` to create the issue in
`backlog` without enqueueing work. The apply path first checks the live daemon,
squad leader and membership, agents, OpenCode runtime bindings, pinned Ollama
models, and required skill bindings; drift blocks submission before any write.

```bash
./bin/project-blueprint submit project.json \
  --create-project \
  --start \
  --apply
```

The Engineering Lead applies the `project-orchestration` skill. It may create
the target GitHub repository only when the blueprint authorizes that action,
then recursively decomposes implementation into independently verifiable child
issues. Repository bootstrap, implementation, integration, independent checks,
and judgment run as ordered Multica stages. See [Project Blueprints](docs/project-blueprints.md).

A parent issue created directly in the Multica UI follows the same route when
it contains equivalent blueprint fields. The checked-in helper is preferable
when you want validation and a reproducible routing preview before assignment.

## Multica instance setup

The following is the reproducible setup procedure for a workspace using this
repository. Values in angle brackets are operator-specific and must not be
committed. Run `multica --help` if a command differs from the installed CLI
version.

### 1. Connect the CLI and select a workspace

Choose the Multica deployment that the organization operates. For Multica
Cloud, authenticate and configure the local CLI:

```bash
multica setup cloud
```

For an organization-hosted instance, provide its endpoints instead:

```bash
multica setup self-host \
  --server-url <https://multica-api.example> \
  --app-url <https://multica.example>
```

Create a workspace once, then make it the default for this CLI profile:

```bash
multica workspace create \
  --name "AI Engineering Lab" \
  --slug ai-engineering-lab \
  --issue-prefix AIEL
multica workspace switch ai-engineering-lab
```

If the workspace already exists, omit creation and switch to its existing slug
or ID. The workspace owner adds the relevant members and grants only the
permissions required for their roles.

### 2. Run the local model stack

OpenCode is the Multica-compatible coding-agent harness. Ollama is the local
model server behind it; it is not used as a standalone coding agent. The
portable launcher installs OpenCode when needed, starts a managed Ollama
server, builds the governed 65K-context aliases from downloaded weights, and
starts the Multica daemon:

```bash
./bin/multiengin start --all
```

The current `local-16gb` capacity profile loads at most one model and runs one
agent task at a time with a 65,536-token context. A Project Blueprint may ask
for more parallelism, but the deterministic plan safely caps it to local
capacity. High and critical-risk work remains `needs_human` until an evaluated
local profile explicitly raises that ceiling.

### 3. Reconcile the local model portfolio

`.ai/runtime/model-policy.yaml` separates the execution harness, model backend,
capacity, role-to-model affinity, and independence rules. Agent manifests pin
the desired model while live runtime IDs remain machine/workspace state.

| Ollama model | Roles |
| --- | --- |
| `multica-qwen3.5:2b` | Engineering Lead, Builder, Integrator |
| `multica-granite4.1:3b` | Verifier, Security Adversary |
| `multica-ministral-3:3b` | Reviewer, Judge |

These aliases reuse the upstream model weights. Their versioned Modelfiles pin
`num_ctx 65536`, because an OpenAI-compatible request cannot change Ollama's
context size at runtime.

Preview drift between the manifests and the current Multica workspace, then
apply only when every affected agent is idle:

```bash
./bin/multiengin reconcile --all
./bin/multiengin reconcile --all --apply
```

The apply command resolves the online OpenCode runtime, pins each declared
Ollama model, and refuses to rebind an active agent. This avoids task-time
mutation of shared instances:

```bash
multica runtime list --output json
multica agent create \
  --name "Builder-01" \
  --runtime-id <opencode-runtime-id> \
  --model ollama/multica-qwen3.5:2b \
  --instructions "<contents of .ai/prompts/builder.md>" \
  --output json
```

Use the same pattern when initially creating an agent that reconciliation
reports as missing. Model families and independence are repository policy;
runtime IDs and local paths are machine/workspace configuration. Do not put
credentials or private endpoints in the repository, shell history, or task
evidence.

### 4. Register the repository and import shared skills

Register the canonical remote in the workspace:

```bash
multica repo add https://github.com/Danixjg/ai-engineering-lab.git
```

Package every required skill from its source, import the archive, and attach
the returned skill ID to its intended agent. The binding matrix and exact
attachment commands are in [Shared skill bindings](docs/multica/skill-bindings.md).
An import is a workspace snapshot, so package and re-import a skill after each
repository update.

### 5. Use isolated worktrees for task execution

Multica checks repositories out into Git worktrees from its daemon cache. An
agent works only in its assigned worktree and hands off a committed SHA, never
another agent's live files. The full rules for decomposition, branch ownership,
integration, cleanup, and shared test resources are in the [worktree
coordination policy](docs/multica/worktree-coordination.md).

### 6. Confirm the instance

Before routing production work, confirm that the workspace, runtime, agents,
repository registration, and daemon are visible to the authenticated CLI:

```bash
multica workspace get --output json
multica runtime list --output json
multica agent list --output json
multica repo list --output json
multica daemon status
```

Keep the resulting IDs and operational evidence in the Multica workspace or
the organization's approved operations system, not in this repository.

## Portable local runtime

Multica Cloud owns shared agents, squads, skills, policies, and engineering
state. [MultiEngin](docs/multiengin.md) makes the particular laptop or desktop
you are using capable of executing selected cloud agents; it does not create a
separate worker fleet or duplicate cloud state.

Select and provision agents interactively:

```bash
./bin/multiengin start
```

Or target an agent, inspect all configured agents, and diagnose the local
environment:

```bash
./bin/multiengin start builder-01
./bin/multiengin agents --all
./bin/multiengin doctor --all
./bin/multiengin reconcile --all
```

MultiEngin provisions the OpenCode harness and the declared Ollama model
portfolio. It leaves application dependencies to each target repository's own
reproducible project environment. The lower-level
`.infrastructure/verify-worker.sh` remains useful when validating a full host.
