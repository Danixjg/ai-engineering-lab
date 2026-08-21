# Repair request output contract

Produce JSON that validates against `.ai/schemas/repair-request.schema.json`.

- Set `attempt` to the current repair attempt and calculate `max_additional_attempts` from the supplied policy.
- Use the closest schema-supported `reason`; explain more detailed classifications in the failure evidence or required action.
- Include only a bounded corrective action that preserves the task and acceptance criteria.
- Copy every mandatory constraint from the skill into `constraints`.
- Use the repair request only for retryable failures. Return `needs_human` as the outcome instead when the stop conditions apply.

See [the validated example](repair-request.example.json) for the required shape.
