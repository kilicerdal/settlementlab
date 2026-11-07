# V2.5 quality review and gates

This release is an agent self-review, not an independent human security audit. No new product features were added.

## Findings corrected

| Finding | Correction | Regression evidence |
|---|---|---|
| Schema bootstrap used executescript, which commits an existing transaction | All DDL runs under SQLiteStore's transaction; no implicit migration commit | Injected migration failure leaves no partial schema; retry succeeds |
| A database with a future schema version could be silently downgraded | Refuse versions newer than the supported schema before writes | Version 99 and sentinel data remain unchanged |
| A skipped subtest could overwrite an earlier reported failure | Failure status is sticky; subtest skips are recorded separately | Real failing-then-skipped unittest remains failed in exported results |
| Underfunded settlement could fail before checking ledger integrity | Verify shared-ledger controls before attempting settlement | Corrupt projection leaves state, audit and balances unchanged |
| An empty journal batch could be treated as balanced | Require each recorded batch to have at least two balanced lines | Empty batch produces an integrity break |
| Unsupported stored calendar fields or empty hashes were accepted | Validate stored shape, weekend convention and provided fingerprint | Invalid pins fail closed with 409 |

## Repeatable checks

Install the application and pinned development tools in a virtual environment:

```sh
python -m pip install . -r requirements-quality.txt
ruff check src tests scripts
ruff format --check src tests scripts
mypy
coverage run -m settlementlab.assurance.runner --suite all
coverage report
coverage json
coverage xml
coverage html
```

The application retains zero runtime dependencies. These tools are development-only and require no paid API. Tool versions are pinned in requirements-quality.txt.

Ruff checks import order, unused/undefined names and selected Python correctness/style rules across source, tests and scripts. Formatting is checked separately. Mypy uses strict mode for the pure core and configuration; the application, persistence, HTTP, AI transport and assurance modules are not yet fully type-checked. Validated dictionaries still contain explicit Any at external data boundaries.

Coverage includes all settlementlab runtime modules, including compatibility entry points and uncovered failure paths. No module exclusions or artificial no-cover annotations were introduced. It is measured from deterministic controls and acceptance scenarios; browser and live-model checks are separate. The CI minimum is 85% combined statement/branch coverage. Coverage percentage does not establish correctness, security or model accuracy.

The release evidence in docs/evidence/quality-v25.json contains exact measured totals. CI uploads JSON/JUnit/HTML assurance results and JSON/XML/HTML coverage outputs on both supported Python versions. Remaining gaps include actual provider outage variants, CLI/error paths and full static typing outside the core. Production authentication, participant isolation and distributed execution remain outside this local simulator.
