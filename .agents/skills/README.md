# Shared agent skills

This directory is the canonical source for executable repository skills. A skill is a reusable procedure, references, and optional deterministic helpers; an agent is a long-lived role with authority, boundaries, and delivery responsibilities. Skills do not grant permissions.

The Squad routes work to agents. A selected agent executes a relevant skill. The Squad decides the next lifecycle step, risk-based independent review, repair-attempt counting, and human escalation; skills do not contain that routing logic.

## Layout and versioning

Executable content lives only in `.agents/skills/<skill-name>/`. `.ai/skills/manifest.yaml` records compatibility and semantic versions, while `.ai/skills/roadmap.md` records planned work. Do not copy executable instructions to `.ai/skills/`.

Use semantic versions in the manifest: patch for clarifications that preserve the procedure, minor for backward-compatible new capability, and major for incompatible procedure or contract changes. Update the manifest version, references, validation evidence, and package whenever a skill changes.

## Initialize, validate, and package

Initialize a new skill with the installed initializer:

```bash
python3 /home/danny/.codex/skills/.system/skill-creator/scripts/init_skill.py <skill-name> --path .agents/skills --resources scripts,references,assets
```

Validate each skill and package it separately:

```bash
python3 /home/danny/.codex/skills/.system/skill-creator/scripts/quick_validate.py .agents/skills/<skill-name>
python3 scripts/package-skill.py .agents/skills/<skill-name> dist/skills/<skill-name>/skill.zip
```

Keep `SKILL.md` concise, frontmatter limited to `name` and `description`, supporting detail directly linked under `references/`, and only tested deterministic helpers under `scripts/`. Remove unused scaffold directories and example files before committing.

## Updating and using skills

Update the canonical skill, validate it, repackage it, and commit the changed source and package together. Attach skills to agents according to [the binding plan](../../docs/multica/skill-bindings.md); permissions stay in agent configuration, repository controls, and policies rather than skill content.

Import each generated package into Multica, capture the returned skill ID, then add that ID to the intended agent. For example:

```bash
multica skill import --file dist/skills/repository-analysis/skill.zip --output json
multica agent skills add <agent-id> --skill-ids <skill-id> --output json
multica agent skills list <agent-id> --output json
```

An import is a workspace snapshot. Re-import repository changes and verify bindings after every update; editing local files alone does not change the Multica workspace.
