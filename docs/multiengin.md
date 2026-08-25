# MultiEngin portable runtime

MultiEngin makes the current computer capable of executing selected agents from
this Multica Cloud workspace. It is a local convenience layer, not a second
orchestration system.

```text
Multica Cloud                         Current machine
-------------                         ---------------
agents, squads, skills, policies  ->  multiengin start
workspace state                    ->  local Kiro/Codex runtimes
                                     ->  Multica daemon and worktrees
```

Multica Cloud remains the source of truth for engineering state. Credentials,
workspace IDs, server URLs, and runtime paths remain in protected local
Multica or agent-CLI configuration and must not be committed here.

## Manifests

Each file in `.ai/agents/` describes an agent's runtime, skills, system
dependencies, required authentication, and health checks. The CLI resolves the
union of those requirements for the selected agents, so Kiro, Codex, Git, and
authentication are never provisioned twice. Runtime requirements include the
execution mode and protocol capabilities an agent needs. MultiEngin compares
those requirements with the capabilities reported by Multica runtimes; agent
names are used only to identify the selected persistent workspace agents, not
to infer runtime compatibility.

`.ai/runtime/runtime-manifest.yaml` defines portable-runtime compatibility and
maps provider names to local executable and authentication checks. These files
use JSON-compatible YAML intentionally: it lets a fresh machine run the CLI
with only Python's standard library.

## Commands

Run the repository launcher directly, or add `bin/` to your `PATH` to use
`multiengin` without a path prefix.

```bash
./bin/multiengin start                 # interactively select agents
./bin/multiengin start builder-01      # provision one agent
./bin/multiengin start --all
./bin/multiengin doctor --all
./bin/multiengin agents --all
./bin/multiengin update --all
./bin/multiengin stop
```

`start` runs four stages:

1. **Bootstrap** installs missing runtime CLIs, completes required login flows,
   connects the workspace, and starts the local daemon.
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

Built-in runtime providers are detected and registered by the Multica daemon;
no custom runtime profile is created for them. `stop` stops only the local
daemon; it never stops cloud agents or changes cloud workspace state.

`doctor` and `agents` are read-only and include current workspace-binding
health when Multica is available. `update` first runs `git pull --ff-only` to
obtain the current manifests, then applies the same four-stage reconciliation
as `start`.

## Scope boundary

MultiEngin establishes the **agent runtime environment** only. It does not
install application dependencies or globally run project package managers.
Repositories remain responsible for reproducible application environments
(for example, dev containers, mise, uv, pnpm, or Poetry). Missing required
system tools are reported with their owning agent; their OS-specific baseline
installation remains available through `.infrastructure/bootstrap/`.

The runtime CLIs are clients for hosted providers. Installing Kiro or Codex
does not download a frontier model onto the machine.
