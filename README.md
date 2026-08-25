# AI Engineering Lab

This repository is the version-controlled source for an autonomous engineering
workflow running in Multica. It contains role instructions, machine-readable
task and evidence contracts, shared skills, and the policies that govern
concurrent work. It intentionally does not contain a Multica workspace ID,
server URL, runtime path, model credential, or other instance secret.

## Repository layout

| Path | Purpose |
| --- | --- |
| `.kiro/agents/` | Builder and verifier role instructions. |
| `.ai/schemas/` | Contracts for tasks, results, findings, and workflow state. |
| `.ai/workflows/` | The engineering-task lifecycle. |
| `.ai/agents/` | Canonical runtime, skill, dependency, and health requirements for each agent. |
| `.ai/runtime/` | Portable-runtime compatibility and provider adapters. |
| `.agents/skills/` | Canonical sources for reusable agent skills. |
| `docs/multica/` | Multica skill bindings and [worktree coordination rules](docs/multica/worktree-coordination.md). |
| `bin/multiengin` | Portable local-runtime launcher for the current machine. |
| `.infrastructure/` | Low-level macOS/Linux baseline bootstrap and full-host verification. |
| `scripts/package-skill.py` | Packages a canonical skill for import into Multica. |

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

### 2. Run the team's own model runtime

This setup deliberately uses models selected and funded by the workspace rather
than hard-coding a provider model or storing a provider key in this repository.
The runtime operator installs and authenticates the compatible local agent CLI
on each execution machine, then starts the Multica daemon that invokes it:

```bash
multica daemon start --workspaces-root <task-workspaces-directory>
```

For a non-default or internally hosted agent CLI, create a runtime profile and
pin its executable path on each runner as needed:

```bash
multica runtime profile create \
  --display-name "<team runtime>" \
  --command-name <agent-cli-command> \
  --protocol-family <supported-protocol> \
  --output json
multica runtime profile set-path <runtime-profile-id> \
  --path <absolute-path-to-agent-cli>
```

The profile's protocol family and command must be supported by the installed
Multica version. Keep provider credentials in the runtime's approved secret
store or local protected configuration; never place them in Git, agent
instructions, shell history, or task evidence.

### 3. Make the model choice explicit per agent

List the runtimes available to the workspace, choose a model ID from the
selected runtime's catalog, and create each agent with that explicit model. A
model choice is therefore auditable and can vary by role without changing this
repository.

```bash
multica runtime list --output json
multica agent create \
  --name "Builder-01" \
  --runtime-id <runtime-id> \
  --model <workspace-owned-model-id> \
  --instructions "<contents of .kiro/agents/builder.md>" \
  --output json
```

Use the same pattern for the verifier and any lead, reviewer, security, or
judge agents. Select model and reasoning settings appropriate to each role;
they are workspace/runtime configuration, not a repository policy. Do not pass
secrets through `--custom-env` on a command line: it can expose them through
shell history or process listings. Use the CLI's stdin or protected-file option
when custom environment values are unavoidable.

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
```

MultiEngin installs agent **CLIs/runtimes**, not hosted frontier models. It
leaves application dependencies to each repository's own reproducible project
environment. On `start`, it discovers the current daemon's runtime IDs, matches
them to manifest-declared capabilities, and rebinds the selected persistent
workspace agents when they still point at another machine. The lower-level
`.infrastructure/verify-worker.sh` remains useful when validating a full host
against the shared Python/Node compatibility line.

The canonical delivery path is Engineering Lead planning, independently owned
Builder tasks, clean-SHA integration, parallel Verifier/Reviewer/Security
review of one integrated commit, Judge evidence aggregation, an explicit human
approval gate, and authorized integration. Run the combined readiness report
before routing work:

```bash
./bin/multiengin status --all
```
