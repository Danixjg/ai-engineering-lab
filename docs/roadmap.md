# Engineering platform roadmap

## Phase 2.5 — MultiEngin portable runtime

- [x] Agent-manifest and runtime-manifest schemas
- [x] Agent dependency resolver and deduplicated plan
- [x] Interactive selection and targeted `start` command
- [x] OpenCode ACP harness and Ollama backend adapters and health checks
- [x] Weighted local-model portfolio, concentration cap, and separation gates
- [x] Resource-aware local capacity and risk ceilings
- [x] Dry-run-first live runtime/model reconciliation
- [x] Authentication and local health detection
- [x] Multica daemon lifecycle (`start` and `stop`)
- [x] `doctor`, `agents`, and `update` commands
- [x] Version compatibility checks and idempotent reruns
- [x] macOS/Linux-compatible launcher
- [ ] Windows launcher and installer adapter
- [ ] Automated cloud skill-import reconciliation, if Multica exposes a
      stable skill-sync operation beyond daemon-managed skill injection

## Subsequent agent work

The shared-skills implementation order remains in
[`.ai/skills/roadmap.md`](../.ai/skills/roadmap.md). Add more agents after
their local runtime requirements have a corresponding manifest and health
checks.

## Phase 3 — Project blueprint and recursive delivery

- [x] Portable new/existing repository Project Blueprint contract
- [x] Explicit project authorizations, human gates, and recursion limits
- [x] Weighted skill selection and agent delegation plan
- [x] Engineering Lead and Integrator agent manifests
- [x] Packaged `project-orchestration` skill
- [x] Dry-run-first Multica project/issue submission helper
- [x] Staged recursive project-delivery workflow
- [ ] Desired-state reconciliation for agent creation, instructions, squads,
      and skill bindings in a live Multica workspace (runtime bindings complete)
- [ ] Historical routing utility derived from verified outcomes
