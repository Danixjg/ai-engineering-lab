# Shared skill bindings

Skills provide reusable procedures; agent instructions retain role authority and boundaries. Bind the following skills additively after importing the relevant package into the workspace.

All agents also follow the repository's [worktree coordination policy](worktree-coordination.md). It defines task decomposition, branch ownership, integration, cleanup, and shared-resource boundaries; skills do not override it.

| Agent | Skills |
| --- | --- |
| Engineering Lead | `project-orchestration`, `repository-analysis`, `analyze-test-failure`, `evidence-reporting` |
| Builder-01 | `repository-analysis`, `git-workflow`, `analyze-test-failure` |
| Integrator-01 | `repository-analysis`, `git-workflow` |
| Verifier-01 | `repository-analysis`, `run-verification`, `analyze-test-failure` |
| Reviewer-01 | `repository-analysis` |
| Security-Adversary-01 | `repository-analysis` |
| Judge-01 | `evidence-reporting` |

Do not bind `git-workflow` to read-only review agents. `run-verification`
supports the Verifier's independent work; it does not replace the Verifier's
independent authority. Do not change a shared agent's bindings around one task;
the project router selects among stable role bindings.

After importing each `skill.zip`, use the returned IDs with `multica agent skills add <agent-id> --skill-ids <skill-id> --output json`, then verify with `multica agent skills list <agent-id> --output json`. Re-import updated packages because a workspace import is a snapshot of repository content.
