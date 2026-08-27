# Engineering platform roadmap

## Phase 2.5 — MultiEngin portable runtime

- [x] Agent-manifest and runtime-manifest schemas
- [x] Agent dependency resolver and deduplicated plan
- [x] Interactive selection and targeted `start` command
- [x] Kiro/Codex runtime installation adapters
- [x] OpenCode runtime adapter with local Ollama health checks
- [x] Persistent `multiengin` user-PATH installer
- [x] Local-model Builder/Reviewer iteration roles
- [x] Authentication and local health detection
- [x] Multica daemon lifecycle (`start` and `stop`)
- [x] `doctor`, `agents`, and `update` commands
- [x] Version compatibility checks and idempotent reruns
- [x] macOS/Linux-compatible launcher
- [ ] Windows launcher and installer adapter
- [ ] Automated cloud skill-import reconciliation, if Multica exposes a
      stable skill-sync operation beyond daemon-managed skill injection
- [ ] Capacity-aware placement and failover across multiple Multica daemon
      machines
- [ ] Shared Ollama model-serving topology with authenticated transport,
      health-aware routing, and per-host concurrency limits

## Subsequent agent work

The shared-skills implementation order remains in
[`.ai/skills/roadmap.md`](../.ai/skills/roadmap.md). Add more agents after
their local runtime requirements have a corresponding manifest and health
checks.
