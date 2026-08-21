# Multica worktree coordination

## Purpose and scope

This policy governs concurrent engineering work performed through Multica in
this repository. It supplements the agent role contracts and does not grant
branch, merge, repository, secret, or deployment permissions.

Multica's `repo checkout` command creates a Git worktree from the runtime
daemon's bare-clone cache. Treat every such checkout as an isolated execution
space. A worktree is not a collaboration surface: task branches, reviewed
commits, declared interfaces, and explicitly reserved external resources are.

## Rules at a glance

| Area | Required rule |
| --- | --- |
| Decomposition | Split only into independently verifiable child tasks with explicit interfaces and ownership. |
| Worktrees | One active task owner per worktree; no agent uses or edits another agent's checkout. |
| Branches | One task branch per task, based on a recorded base commit; its owner is the only writer. |
| Integration | An authorized integrator merges verified commits from a clean integration checkout. |
| Cleanup | The owner cleans its disposable artifacts; only Multica or an authorized maintainer retires worktrees and branches. |
| Shared resources | Reserve exclusive resources before work starts; use task-scoped names for all others. |

## 1. Decompose work before creating checkouts

The coordinator must create a parent task and, for every child task, record:

- a unique task ID and a single owner;
- the exact base branch and starting commit;
- its allowed files or components, public interface, and acceptance criteria;
- dependencies on other tasks, including the commit or pull request that
  satisfies each dependency;
- exclusive shared resources and the intended integration order.

Create parallel child tasks only when each child can be built and verified
without another child's uncommitted files. Prefer vertical slices with a
small, stable interface over splitting one feature by layer. Do not assign two
writers to the same file, generated output, migration sequence, lockfile, or
public contract unless a single named owner is responsible for reconciling it.

If a task cannot be separated this way, keep it as one task or make the later
work explicitly depend on the earlier committed result. An agent must not use
another worktree's uncommitted changes as an input.

## 2. Worktree rules

Each builder, verifier, reviewer, or integrator checks out the stated ref into
its own Multica-created worktree. Before changing files, the task owner records
the worktree path, branch, and `HEAD` commit in its task evidence.

- Never edit, test from, clean, or delete a worktree owned by another task or
  agent.
- Never manually alter Git's worktree metadata, the daemon bare-clone cache,
  or another checkout's `.git` indirection. Do not run broad `git worktree
  prune` operations in an active Multica environment.
- Do not rely on untracked files, generated artifacts, dependency directories,
  or environment changes in any other worktree. Reproduce required setup in
  the current worktree or through a declared shared service.
- A worktree remains task-private until the owner has committed the intended
  changes and reported the commit SHA. A commit, not a live checkout, is the
  handoff unit.

## 3. Branch ownership and lifecycle

The Engineering Task's `repository.base_branch` and `working_branch` are
authoritative. When `working_branch` is absent, the coordinator assigns a
unique, task-ID-bearing name such as `task/TASK-API-42`; the name must be
recorded before the first commit.

- Start a task branch from the recorded base commit, not merely from whatever
  branch happens to be checked out. Record both the base branch and SHA.
- A task branch has exactly one writing owner. Other agents may inspect its
  pushed commit in their own worktrees but must not commit, rebase, reset,
  force-push, or delete the branch.
- Do not work directly on the protected default branch. Do not reuse a branch
  with unrelated work; stop and ask the coordinator to allocate a new branch.
- Builders make focused commits and push only when the task authorizes it.
  The reported candidate SHA is immutable verification input. Follow-up repair
  work uses a new commit and reports a new SHA.
- Never rewrite shared history or force-push. If the base changes, the task
  owner or coordinator decides whether to rebase before verification or to
  integrate in the declared order.

## 4. Integration and conflict handling

Only an authorized integrator or human may merge. The builder must not merge
or approve its own change.

1. The verifier checks the exact candidate SHA in a separate worktree and
   reports evidence against that SHA.
2. The integrator uses a clean, separate worktree at the current target branch
   and confirms the candidate is still the reviewed commit.
3. Integrate child tasks in their declared dependency order. Re-run the checks
   affected by the combined change and record the resulting target SHA.
4. If a merge conflict or interface conflict occurs, return it to the owner of
   the conflicting task as a bounded repair task. Do not silently resolve it
   while integrating or combine unrelated task changes in one commit.

A later task may start only after its declared dependency commit is available.
It must update its base through normal Git history and be independently
verified again when that update can affect its acceptance criteria.

## 5. Cleanup and retention

Cleanup begins only after the task has a recorded terminal outcome: merged,
closed, superseded, or escalated. The coordinator retains the task ID, branch,
candidate SHA, verification evidence, and final disposition before cleanup.

- The task owner may remove only disposable files it created in its own
  worktree, after preserving required evidence. It must never clean another
  task's checkout or shared cache.
- Multica's runtime, or an authorized repository maintainer, retires stale
  worktrees. Agents must not remove worktrees merely because they appear idle.
- Delete a local or remote task branch only after its change is merged or
  formally closed, no active task depends on it, and an authorized maintainer
  has confirmed the final commit is retained elsewhere. Never delete another
  task's branch.
- A blocked or failed task keeps its branch and evidence until a coordinator
  records whether it will be repaired, superseded, or closed.

## 6. Shared-resource rules

Reserve the following before the task begins. The coordinator records the
owner and release condition in the parent task; an unreserved resource is not
available just because it is currently unused.

| Resource | Rule |
| --- | --- |
| Protected branches, release tags, and merge queue | Read-only to task agents; controlled by the authorized integrator or human. |
| Task branch and worktree | Exclusive to the named task owner. |
| Source files, public interfaces, migrations, generated code, and lockfiles | One named owner at a time; dependent tasks consume the owner's committed result. |
| Evidence files | Store task-specific evidence under `.ai/evidence/<task-id>/`; do not write a shared, unscoped report. |
| Ports, databases, queues, buckets, fixtures, and test accounts | Use names derived from the task ID and clean up only those names. Serialize tests that cannot be isolated. |
| Credentials, runtime configuration, workspace settings, and repository registration | Managed by the authorized workspace or repository administrator; agents neither expose nor mutate them without authorization. |
| Multica daemon cache and Git object/worktree metadata | Managed by Multica; never use as a task artifact store or clean it from an agent task. |

When a resource cannot be namespaced or reserved safely, the coordinator must
serialize the affected tasks. If ownership is unclear, agents stop before
writing and request a decision rather than resolving the contention by timing
or by modifying another task's branch.

## 7. Handoff record

Every task handoff includes the task ID, worktree path, base branch and SHA,
working branch, candidate commit SHA, changed resources, verification status,
dependencies, and cleanup disposition. This record is in addition to the
existing Engineering Task, Execution Result, Verification Result, and evidence
bundle contracts; it does not replace them.
