# Project orchestration output contract

## Initial routing result

Produce a routing plan containing:

- schema version, project ID, and a digest of the normalized blueprint;
- `ready` or `needs_human` status;
- mandatory governance sources;
- effective recursion and parallelism limits;
- execution harness, local model backend, model concentration, stage diversity, and separation evidence;
- the leader task, ordered stages, conditional repair route, and routing gaps;
- for each task, its role, selected agent, selected skills, scores, and reasons.

When the repository schema is available, conform to
`.ai/schemas/routing-plan.schema.json`.

## Parent issue updates

At every stage boundary report the stage outcome, completed child issue IDs,
candidate commit SHAs, blocked or failed children, consumed descendant budget,
and next action. Do not paste secrets or unbounded logs.

## Terminal result

Return one of:

- `ready_for_human`: required evidence is present and the next configured human
  gate is identified;
- `needs_human`: scope, authority, policy, evidence, environment, or recursion
  limits prevent safe autonomous progress;
- `cancelled`: the parent issue was explicitly cancelled.

Include the target repository, branch or pull request, final candidate commit,
verification result, review/security findings, repair history, routing gaps,
and remaining human gates. Child completion alone is never a terminal success
criterion for the parent.
