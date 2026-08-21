# Evidence bundle output contract

Produce JSON that validates against `.ai/schemas/evidence-bundle.schema.json` and a human summary containing every heading required by the skill.

- Verify `task_id` and `implementation.commit_sha` against the final Verification Result before deriving a decision.
- Use only `pass`, `fail`, or `needs_human` for `decision`.
- Include all verification checks, findings, and acceptance-criterion mappings available for the final commit.
- Treat missing mandatory evidence, unrun required checks, unverified required criteria, unresolved blocking findings, and contradictory commits as `needs_human`.

See [the validated example](evidence-bundle.example.json) for the JSON shape.
