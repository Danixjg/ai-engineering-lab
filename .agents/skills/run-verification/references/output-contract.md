# Verification result output contract

Produce JSON that validates against `.ai/schemas/verification-result.schema.json`.

- Use the exact candidate SHA in `commit.sha` and identify the repository and branch when known.
- Include an entry for every discovered applicable check. The schema permits `passed`, `failed`, `skipped`, and `not_run`; represent a blocked execution by setting the top-level `status` to `blocked` and documenting the blocked prerequisite in `summary` or `blocking_failures`.
- Include command, exit code, duration, output reference, and blocking flag whenever available.
- Map every required acceptance criterion to `passed`, `failed`, or `not_verified`, with an evidence reference.
- Set top-level status to `passed`, `failed`, `blocked`, or `not_verified` only from executed evidence and policy.

See [the validated example](verification-result.example.json) for field shape; replace its illustrative IDs, commit, and evidence with actual values.
