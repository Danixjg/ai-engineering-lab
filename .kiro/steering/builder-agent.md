# Builder Engineering Standards

These rules apply whenever the Builder Agent modifies this repository.

## Before Coding

Always inspect:

1. repository structure;
2. relevant source files;
3. relevant tests;
4. project configuration;
5. existing implementation patterns.

Do not assume the architecture.

## Code Changes

Prefer:

- small focused changes;
- existing abstractions;
- existing libraries;
- explicit error handling;
- readable code;
- testable design.

Avoid:

- unnecessary abstractions;
- speculative features;
- duplicated functionality;
- unrelated refactoring.

## Tests

Every behavioral change should have appropriate automated tests.

Tests should verify behavior rather than implementation details where practical.

Do not weaken existing tests to accommodate an implementation.

## Dependencies

Do not add a dependency when existing project capabilities are sufficient.

When a dependency is necessary, document why it is required.

## Git

Use a dedicated task branch.

Keep commits focused.

Never commit secrets, credentials, tokens, or generated sensitive data.

## Verification

Run the strongest applicable deterministic checks before completion.

Report actual results.

Never claim a command was executed when it was not.

## Scope

Do not expand the task without authorization.

If requirements conflict with repository architecture or existing behavior, stop and report the conflict.