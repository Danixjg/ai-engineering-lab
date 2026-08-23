# MultiEngin local runtime

MultiEngin makes the current computer capable of executing cloud-managed
Multica agents with local models. It is a portable runtime layer, not a second
orchestration system.

```text
Multica Cloud                       Current machine
-------------                       ---------------
agents, squads, skills, issues  ->  OpenCode ACP harness
                                    -> Ollama local model server
                                    -> governed Git worktrees
```

OpenCode and Ollama are complementary layers. OpenCode implements the coding
agent and ACP protocol Multica invokes. Ollama serves the model weights and API;
it does not replace the agent harness.

Multica Cloud remains the source of truth for issues, squads, skill bindings,
and execution state. Local runtime paths and process state stay outside Git.

## Manifests

Each `.ai/agents/*.yaml` file describes one stable role instance, including its
OpenCode harness, pinned Ollama model, skills, system dependencies, and health
checks. Role instructions in `.ai/prompts/` are provider-neutral.

`.ai/runtime/runtime-manifest.yaml` defines the OpenCode and Ollama adapters.
The repository-root `opencode.json` registers Ollama's OpenAI-compatible local
endpoint and allowlists the evaluated model portfolio for every task checkout.
`.ai/runtime/model-policy.yaml` separately defines:

- the OpenCode/Ollama execution stack;
- resource limits for the current `local-16gb` profile;
- weighted role-to-model affinity;
- required model-family diversity and concentration limits;
- model separation between implementation and independent evaluation.

The default portfolio is:

| Model | Stable roles |
| --- | --- |
| `ollama/multica-qwen3.5:2b` | Engineering Lead, Builder, Integrator |
| `ollama/multica-granite4.1:3b` | Verifier, Security Adversary |
| `ollama/multica-ministral-3:3b` | Reviewer, Judge |

Each `multica-*` model is a lightweight derived manifest that reuses the
downloaded upstream weights. The versioned `.ai/runtime/models/*.Modelfile`
files pin `num_ctx 65536`; the OpenAI-compatible endpoint cannot set context
size per request.

The host loads one model and runs one agent task at a time. Logical stages may
contain several tasks, but the execution-capacity limit queues them. The model
policy caps this small local profile at medium-risk work; high and critical
risk plans stop at `needs_human`.

## Commands

```bash
./bin/multiengin start --all
./bin/multiengin doctor --all
./bin/multiengin agents --all
./bin/multiengin reconcile --all
./bin/multiengin reconcile --all --apply
./bin/multiengin update --all
./bin/multiengin stop
```

`start` is idempotent. It installs OpenCode from its official installer when
missing, exposes it through the user-local executable path that Multica scans,
links the versioned OpenCode provider config into the user's global OpenCode
config location so fresh Multica worktrees can resolve local models immediately,
starts a locally managed Ollama server, pulls each selected model only once,
builds any missing governed aliases, runs authentication/dependency checks,
and starts or safely refreshes the Multica daemon. A refresh is refused while
Multica has an active task.
The Ollama process uses the context, loaded-model, and parallelism limits in the
model policy. Ollama itself must be installed through the approved OS package.

`reconcile` compares live Multica agents with both the desired OpenCode runtime
and desired Ollama model. It previews by default, requires exactly one online
OpenCode runtime when changing harnesses, and refuses to mutate an active
agent. `--apply` changes the runtime ID and model together.

`doctor` and `agents` are read-only. They verify the OpenCode executable, Ollama
server, required model inventory, OpenCode provider exposure, GitHub
authentication, repository access, and system dependencies. `stop` stops the
Multica daemon and only the Ollama server started by MultiEngin; it does not
kill an independently managed Ollama service.

## Reusability and upgrades

Do not bind every model or skill to every task. Add a new model as an evaluated
stable agent variant, assign it role-affinity scores, and preserve the
separation gates. The routing plan scores eligible agent instances by role,
capability, required skills, risk, priority, and model affinity, then rejects a
portfolio that violates concentration or independence constraints.

For a stronger host, add a separately evaluated capacity profile and larger
tool-capable Ollama models. Do not silently raise parallelism, context, or risk
ceilings: those settings affect memory safety and governance.

Application dependencies remain the target repository's responsibility (for
example through dev containers, mise, uv, pnpm, or Poetry).
