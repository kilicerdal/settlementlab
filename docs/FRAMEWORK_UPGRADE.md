# Framework-depth upgrade (proposed V3.1)

This branch implements five focused improvements, without changing the public website:

1. External declarative scenario directories for an installed HTTP runner.
2. Real post-commit response loss, bounded timeout, hard process restart and truncated-response regressions.
3. An offline, reviewed AI corpus retaining genuine failed local-model answers and separate synthetic controls.
4. Expanded strict typing for reusable assurance boundaries.
5. Offline failure-first report navigation with control/request/comparison evidence.

[External pack contract](EXTERNAL_SCENARIOS.md) · [Recovery evidence](RECOVERY_ASSURANCE.md) · [AI scoring and limits](AI_EVALUATION.md).

## Static type scope

Strict mypy now includes the pure core and configuration plus six complete assurance modules: catalogs, transport, targets, http_steps, reporting and evaluation. Input/output types and optional request metadata are explicit. JSON/server response boundaries use explicit Any where shape is validated dynamically; no blanket ignore/no-untyped-defs exemption is used.

The workflow service, SQLite implementation, financial client/fixtures and scenario orchestration are not fully typed. This is a measured expansion, not a claim that all application code is statically verified. The exact checked files are in pyproject.toml.

## Compatibility

Existing packaged financial/collateral scenarios, target profiles, JSON/JUnit report shape and exit conventions remain. Human HTML now sorts failed cases first and opens failure evidence. Existing recording scripts account for open details. JSON assertions distinguish booleans/numbers and nested types instead of Python's True == 1 equivalence. New strict validation applies to external packs; packaged financial actions retain their established workflow contracts.

No runtime dependency, paid API, identity provider or cloud infrastructure is added. The website and its recorded V3.0 evidence are not modified by this branch. Historical captures remain dated. CI separately validates installed-package execution; a browser check verifies the financial console and report navigation.
