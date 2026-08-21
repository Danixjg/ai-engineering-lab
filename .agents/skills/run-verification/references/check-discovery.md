# Check discovery

Inspect task-relevant repository documentation and configuration before running checks. Prefer, in order:

1. commands named in the Engineering Task or verification policy;
2. documented contributor or CI commands;
3. package-manager scripts and build configuration;
4. checked-in automation under conventional script or workflow directories.

Determine applicability from the candidate changes and repository structure. Record a check as `skipped` only with a reason; record it as `not_run` when it was applicable but not executed. Treat unavailable prerequisites as `blocked` in the human report and use the enclosing verification result's `blocked` status when no valid execution is possible.
