# Reviewer journey

## What this demonstrates
A reusable Python assurance engine checks two independent synthetic local applications. Financial scope is USD equity trades with simplified calendar rules and no exchange connection or real money. Demo personas are not production authentication.

| Component | Role | Entry point |
|---|---|---|
| `src/settlementlab/assurance/` | Reusable HTTP scenario, expectation and reporting engine | `settlementlab-assure --suite scenarios` after package install |
| Operations workbench | Reference matching, maker/checker and settlement application | `settlementlab --config environments/showcase.json` |
| `examples/collateral_service/` | Independent reservation API; no framework imports | Started temporarily by `python -m scripts.showcase` |
| `scripts/showcase.py` | Runs both targets and verifies exact control/fault outcomes | Commands below |

## Run from a clean checkout
Python 3.9+ and Git; no paid key or model required. On Windows use `.venv\Scripts\python.exe`.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m scripts.showcase
.venv/bin/python -m scripts.showcase --verify
```

Open `artifacts/showcase/index.html`. Expect four passing settlement scenarios, two passing collateral controls, and a deliberately failed collateral C02 report: expected HTTP 200, observed 201 on reservation replay. The overall verifier succeeds only for that exact negative result. An arbitrary server failure does not count.

## Explore the operations workflow

```sh
.venv/bin/settlementlab --config environments/showcase.json
```

Open http://127.0.0.1:8085. Correct mismatched terms, obtain separate maker/checker approval, observe capacity rejection, fund and retry, then reconcile balanced postings. The showcase fixes the simulated business date to 2026-11-09. [Exact five-minute steps](SHOWCASE.md).

The temporary showcase closes its services; the interactive console uses persistent local state. Do not delete an existing database for a fresh rehearsal; choose an unused `--db` filename. [Full quality checks](MAINTENANCE.md) · [Evidence provenance](EVIDENCE.md) · [Framework extension](FRAMEWORK.md).

[How this project complements the portfolio](https://github.com/kilicerdal/eai-engineering/blob/main/docs/PROJECTS.md).
