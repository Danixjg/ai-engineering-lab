---
name: git-workflow
description: Create safe, traceable task branches, focused commits, pushes, and pull requests when an authorized engineering task requires repository delivery.
---

# Git workflow

Use this procedure for authorized repository delivery. It does not grant Git hosting, branch, push, pull-request, or merge permissions.

## Inputs

Require a task ID, repository, base branch, intended working branch, and required commit or pull-request metadata.

## Procedure

1. Inspect Git status, remotes, and the expected base branch. Detect unrelated local modifications before switching branches or staging files.
2. Create or reuse the approved task branch. Do not work directly on a protected branch.
3. Stage only intended files. Review the staged diff and scan it for credentials, tokens, secrets, and unrelated changes.
4. Create one focused commit with the required message and record its full SHA.
5. Push the working branch only when authorized. Confirm the remote result rather than relying on command intent.
6. Create or update a pull request when requested, using [the reusable PR body template](references/pull-request-template.md). Confirm its number and status.
7. Return the delivery record below.

## Delivery record

```text
Repository
Base branch
Working branch
Commit SHA
Commit message
Push status
Pull request number
Pull request status
Warnings
```

## Safety boundaries

Never merge a pull request, force-push without explicit authorization, rewrite shared history, commit secrets, stage unrelated files, delete another task's branch, bypass branch protection, or claim a push or PR succeeded without confirmation.

Stop when authentication is unavailable, the branch has unrelated changes, the remote branch diverges unexpectedly, a protected operation is required, or the requested operation could destroy work.
