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
authentication are never provisioned twice.

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

`start` checks the selected manifests, requests confirmation, installs missing
Kiro or Codex CLIs, invokes the required interactive login flows, and starts
the local Multica daemon. Kiro and Codex are built-in Multica runtime
providers, so the daemon detects and registers their normal executables; no
custom runtime profile is created for them. `stop` stops only the local daemon;
it never stops cloud agents or changes cloud workspace state.

`doctor` and `agents` are read-only. `update` first runs `git pull --ff-only`
to obtain the current manifests, then applies the same selected-agent
provisioning checks as `start`.

## Scope boundary

MultiEngin establishes the **agent runtime environment** only. It does not
install application dependencies or globally run project package managers.
Repositories remain responsible for reproducible application environments
(for example, dev containers, mise, uv, pnpm, or Poetry). Missing required
system tools are reported with their owning agent; their OS-specific baseline
installation remains available through `.infrastructure/bootstrap/`.

The runtime CLIs are clients for hosted providers. Installing Kiro or Codex
does not download a frontier model onto the machine.
