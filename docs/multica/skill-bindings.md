# Shared skill bindings

Skills provide reusable procedures; agent instructions retain role authority and boundaries. Bind the following skills additively after importing the relevant package into the workspace.

| Agent | Skills |
| --- | --- |
| Engineering Lead | `repository-analysis`, `analyze-test-failure`, `evidence-reporting` |
| Builder-01 | `repository-analysis`, `git-workflow`, `analyze-test-failure` |
| Verifier-01 | `repository-analysis`, `run-verification`, `analyze-test-failure` |
| Reviewer-01 | `repository-analysis` |
| Security-Adversary-01 | `repository-analysis` |
| Judge-01 | `evidence-reporting` |

Do not bind `git-workflow` to read-only review agents. `run-verification` supports the Verifier's independent work; it does not replace the Verifier's independent authority.

After importing each `skill.zip`, use the returned IDs with `multica agent skills add <agent-id> --skill-ids <skill-id> --output json`, then verify with `multica agent skills list <agent-id> --output json`. Re-import updated packages because a workspace import is a snapshot of repository content.
