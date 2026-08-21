# Repository analysis output contract

Return a concise analysis with these headings in this order:

```text
Repository summary
Relevant components
Relevant files
Existing conventions
Applicable commands
Risks
Unknowns
Recommended next step
```

For every material statement, label it `Fact` when observed directly or `Assumption` when inferred. Include the inspected branch or commit and the repository root in the summary. List a file path with each relevant-file entry. Mark a command as discovered from repository configuration, documentation, or an observed script; do not present an invented command as repository-defined.
