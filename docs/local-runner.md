# EngLab local Codex runner

EngLab runs the repository's engineering roles locally without relying on a
Multica queue. It uses `codex exec` for non-interactive agent turns and Git
worktrees for isolated branches. The target can be this repository or any other
local Git repository.

## Quick start

Authenticate Codex and check the target repository:

```bash
codex login
./bin/englab doctor --repo /path/to/project
```

Write the desired change in a Markdown or text file, then inspect the proposed
local run without starting agents:

```bash
./bin/englab run issue.md --repo /path/to/project --dry-run
```

Start the workflow:

```bash
./bin/englab run issue.md --repo /path/to/project --max-builders 2
```

The target checkout must be clean when the default `HEAD` base is used. This
prevents uncommitted local work from being silently omitted from new worktrees.
To use another committed base explicitly, pass `--base <ref-or-sha>`.

## Workflow

One run performs these stages:

```text
Lead plan
  -> independent Builders (parallel, workspace-write)
  -> Integrator (workspace-write)
  -> Verifier + Reviewer + Security Adversary (parallel)
  -> Judge
  -> explicit human review
```

The Lead creates at most `--max-builders` independently committable tasks from
one base SHA. Each Builder receives its own branch and worktree. The Integrator
combines only their reported commits and produces one candidate SHA. All three
assurance roles inspect that exact SHA. The Judge aggregates their evidence but
cannot merge.

EngLab grants `workspace-write` only to Builder, Integrator, and Verifier. The
Lead, Reviewer, Security Adversary, and Judge run read-only. It never uses
`danger-full-access`, never pushes, and never merges the candidate into the
user's branch.

## Durable state

Run state, result artifacts, JSONL Codex events, and stderr logs live under:

```text
.englab/projects/<project-key>/runs/<run-id>/
```

Worktrees live beside the run records under `.englab/projects/<project-key>/worktrees/`.
The directory is ignored by this repository. Worktree branches use the prefix
`englab/<run-id>/`; they remain available for inspection even when a run fails.

Inspect the newest run for a target repository:

```bash
./bin/englab status --repo /path/to/project
```

Or inspect a specific run:

```bash
./bin/englab status <run-id> --repo /path/to/project --output json
```

EngLab deliberately does not delete worktrees or branches automatically. That
keeps failures recoverable and avoids destroying an agent's committed work.

## Codex configuration

By default, each invocation uses the current Codex configuration and saved CLI
authentication. Optional overrides apply consistently to every role:

```bash
./bin/englab run issue.md \
  --repo /path/to/project \
  --model <model-id> \
  --profile <profile-name>
```

The runner records the complete JSONL event stream for each role and requests a
schema-constrained final result. Prompts are passed as process arguments and
must not contain credentials or other secrets.

## Failure behavior

The run state changes to `failed` when planning, implementation, integration,
or Codex execution cannot complete. Review failures still proceed to Judge so
the human receives a combined evidence decision. A non-passing judgment ends in
`needs_human`; a passing judgment ends in `ready_for_human`.

EngLab retains every worktree, branch, artifact, and log after failure. Inspect
the state file and relevant stderr/JSONL log before deciding whether to resume
manually or start a new run.
