# Failure classification

Classify evidence conservatively:

| Classification | Use when |
| --- | --- |
| implementation failure | Candidate behavior or code causes the check to fail. |
| test failure | The test is invalid, stale, or fails independently of the candidate. |
| build/type-check/lint failure | The named deterministic tool reports that category. |
| dependency failure | Required resolved packages or lockfile inputs are unavailable or inconsistent. |
| environment failure | Local execution prerequisites, credentials, or services are unavailable. |
| infrastructure failure | CI, network, runner, or managed service fails independently of the candidate. |
| security failure | A security policy or scan reports a security issue. |
| acceptance-criterion failure | Evidence shows a required criterion is unmet despite checks completing. |
| unknown | Evidence cannot support a more specific classification. |

Separate the observed failure from the suspected cause. Do not assign blame without reproducible evidence.
