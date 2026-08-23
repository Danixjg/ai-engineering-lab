# Delegation and recursion

## Hard gates before scoring

Reject an agent candidate before scoring when its role or risk eligibility does
not match, required skills are not bound, its authority is insufficient, its
runtime is unavailable, or using it would violate independent verification.
Do not compensate for a failed hard gate with a high relevance score.

## Skill selection

Select every explicitly required skill. Score other role-compatible skills
using the weights in `routing-policy.json`, subtract the context-cost penalty,
and keep only skills at or above the selected threshold until the per-task
limit is reached. Record the score components and the reason for every selected
skill.

Skills guide work; they do not change the agent's permissions. Do not mutate a
shared agent's bindings around one run. If no agent already covers a required
skill, record a routing gap and stop for configuration rather than racing a
global update against active tasks.

## Child issue contract

Every child issue records:

- parent project and task IDs;
- remaining recursion depth and descendant budget;
- one owner and one working branch;
- repository URL, base branch, and starting commit when available;
- objective, requirements, constraints, and acceptance criteria;
- required and selected skills with score evidence;
- inputs, expected outputs, dependencies, and stage;
- authorizations inherited from the parent and applicable human gates.

A child may use less authority than its parent, never more.

## Stages and wakeups

Use Multica stages as ordered barriers. Create parallel children only when they
can be verified without another child's uncommitted work. The leader evaluates
the stage-completion wakeup, records the result, and creates or releases the
next stage. All independent verification, review, and security children inspect
the same integration commit.

## Recursion accounting

The parent passes each child `remaining_depth = parent.remaining_depth - 1` and
the available descendant budget. Count every created child against the root's
total-descendant limit. Stop decomposition when the next child would exceed a
limit, when work cannot be separated into independently verifiable slices, or
when an unsatisfied human gate is reached.

Recursive decomposition is a planning mechanism, not permission to keep
creating work until an agent feels finished.
