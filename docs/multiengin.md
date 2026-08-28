# MultiEngin portable runtime

MultiEngin makes the current computer capable of executing selected agents from
this Multica Cloud workspace. It is a local convenience layer, not a second
orchestration system.

```text
Multica Cloud                         Current machine
-------------                         ---------------
agents, squads, skills, policies  ->  multiengin start
workspace state                    ->  OpenCode + local Ollama (iterations)
                                     ->  Codex (control and assurance gates)
                                     ->  Multica daemon and worktrees
```

Multica Cloud remains the source of truth for engineering state. Credentials,
workspace IDs, server URLs, and runtime paths remain in protected local
Multica or agent-CLI configuration and must not be committed here.

## Manifests

Each file in `.ai/agents/` describes an agent's runtime, skills, system
dependencies, required authentication, and health checks. The CLI resolves the
union of those requirements for the selected agents, so OpenCode, Codex, Git, and
authentication are never provisioned twice. Runtime requirements include the
execution mode and protocol capabilities an agent needs. MultiEngin compares
those requirements with the capabilities reported by Multica runtimes; agent
names are used only to identify the selected persistent workspace agents, not
to infer runtime compatibility.

Each runtime requirement also declares a `model_strategy`. `preserve` blocks a
cross-provider move unless the target advertises the current model;
`runtime_default` atomically clears an incompatible workspace model while
rebinding so the target runtime selects its configured default. Model IDs
remain workspace configuration and are never hard-coded into repository
policy.

`.ai/runtime/runtime-manifest.yaml` defines portable-runtime compatibility and
maps provider names to local executable and authentication checks. These files
use JSON-compatible YAML intentionally: it lets a fresh machine run the CLI
with only Python's standard library.

## Commands

Run the repository launcher directly, or install its symlink and persistent
user `PATH` entry once. `install-path` refuses to replace an unrelated existing
`~/.local/bin/multiengin` file and is safe to repeat.

Run `multiengin` without arguments at any time to print the command catalog,
first-time setup sequence, agent-selection examples, readiness commands, and
maintenance usage. Run `multiengin <command> --help` for command-specific
arguments.

```bash
./bin/multiengin install-path
./bin/multiengin start                 # interactively select agents
./bin/multiengin start builder-01      # provision one agent
./bin/multiengin start --all
./bin/multiengin doctor --all
./bin/multiengin agents --all
./bin/multiengin status --all
./bin/multiengin status --all --output json
./bin/multiengin workflow-check
./bin/multiengin squad-check
./bin/multiengin sync-instructions engineering-lead-01 --yes
./bin/multiengin update --all
./bin/multiengin stop
```

Reload the profile printed by `install-path` before invoking `multiengin`
without the `./bin/` prefix. Bash uses `~/.bashrc`, zsh uses `~/.zshrc`, and
other POSIX shells fall back to `~/.profile`.

## OpenCode with a locally hosted model

Builder-01 and Reviewer-01 are the iteration roles. Their manifests require the
Multica `opencode` provider, OpenCode 1.17.7+, and a reachable Ollama service.
The other roles retain Codex so a local iteration is independently integrated,
verified, security-reviewed, and judged.

Install/start Ollama, pull a tool-capable model approved for the machine, and
configure OpenCode. The quickest supported setup is:

```bash
ollama pull <model-id>
multiengin configure-opencode --model <model-id>
opencode run --model ollama/<model-id> "Reply with the current repository name only."
```

`configure-opencode` creates a private user configuration and refuses to replace
an existing one. Alternatively, copy [`config/opencode.ollama.example.json`](../config/opencode.ollama.example.json)
to OpenCode's user configuration, replace both `REPLACE_WITH_MODEL_ID` values,
and adjust `baseURL` when Ollama runs on a trusted model host rather than the
same machine. Do not commit the resulting user configuration, tokens, private
hostnames, or model credentials.

Start or restart Multica only after `opencode` is on `PATH`; its daemon then
auto-detects the built-in OpenCode provider. Configure the persistent workspace
agents' model as `ollama/<model-id>` (or let their OpenCode runtime default select
that configured model), then reconcile and verify:

```bash
multica daemon restart
multiengin start builder-01 reviewer-01
multiengin status builder-01 reviewer-01
```

OpenCode can reach an Ollama server on another trusted machine by changing the
example's `baseURL`. Protect that network path with the organization's normal
access controls; the repository intentionally supplies no shared secret.

## Multiple execution machines

Each worker checks out this repository, runs `multiengin install-path`, installs
only the runtimes needed for its assigned roles, connects the same Multica
workspace, and starts its own daemon with a distinct device name. Multica
runtime bindings determine placement; repository files do not contain host IDs.

A practical first split is:

| Machine | Workload | Required runtime |
| --- | --- | --- |
| GPU iteration worker | Builder-01 and Reviewer-01 | OpenCode + Ollama |
| Control worker | Engineering Lead, Integrator, Verifier, Security, Judge | Codex |

Use `MULTICA_DAEMON_DEVICE_NAME` to make workers distinguishable and cap each
host with `MULTICA_DAEMON_MAX_CONCURRENT_TASKS`. Run `multiengin start` only for
the agents assigned to that machine; do not use `--all` across heterogeneous
workers. A later scheduler can add capacity-aware placement, shared model
serving, and failover without changing agent identity or committing machine
addresses.

`start` runs four stages:

1. **Bootstrap** installs missing language runtimes and runtime CLIs, completes
   required login flows, connects the workspace, and starts the local daemon.
2. **Discover** reads the active workspace's agents and runtimes plus the
   current daemon's registered runtime IDs.
3. **Reconcile** chooses an online local runtime whose provider, mode, version,
   and reported capabilities satisfy each selected manifest, then updates the
   persistent workspace agent's runtime binding when required.
4. **Verify** reads the workspace again and confirms that each selected agent
   is bound to an online runtime on this machine, then checks its runtime CLI,
   authentication, GitHub, repository access, and dependencies.

If this daemon has not published a compatible local runtime yet, `start`
restarts it once and repeats discovery. Repeated starts are idempotent: an
agent already bound to a compatible runtime on this machine is not updated.
The old runtime remains a Multica workspace runtime record; MultiEngin also
records each successful transition in
`${XDG_STATE_HOME:-~/.local/state}/multiengin/runtime-history.json`. That local
history is operational state and must not be committed.

Built-in runtime providers, including OpenCode, are detected and registered by
the Multica daemon;
no custom runtime profile is created for them. `stop` stops only the local
daemon; it never stops cloud agents or changes cloud workspace state.

`doctor` and `agents` are read-only and include current workspace-binding
health when Multica is available. `update` first runs `git pull --ff-only` to
obtain the current manifests, then applies the same four-stage reconciliation
as `start`.

`status` combines host, daemon, workflow-contract, squad-topology, local tool,
authentication, and workspace-binding checks under stable check IDs. Its JSON
form conforms to `.ai/schemas/workflow-status.schema.json`. `workflow-check`
validates transitions, reachability, agent contracts, review barriers, and
terminal outcomes without contacting Multica. `squad-check` verifies that the
live Engineering Squad has the repository-declared leader, seven role
assignments, and member count.

`sync-instructions` persists a selected repository-owned instruction file on
its matching workspace agent. The Engineering Lead runbook uses Multica parent
issues, monotonically increasing child stages, stage barriers, and squad
activity records so orchestration resumes after each worker becomes idle. The
operation is explicit and idempotent; MultiEngin does not overwrite agent
instructions during ordinary runtime reconciliation.

## Scope boundary

MultiEngin establishes the **agent runtime environment** only. It does not
install application dependencies or globally run project package managers.
Repositories remain responsible for reproducible application environments
(for example, dev containers, mise, uv, pnpm, or Poetry). Missing required
system tools are reported with their owning agent; their OS-specific baseline
installation remains available through `.infrastructure/bootstrap/`.

Installing an agent CLI does not install model weights. Codex remains a hosted
provider client; the OpenCode iteration roles use the separately managed local
Ollama model configured by the operator.
