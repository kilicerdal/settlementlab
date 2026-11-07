# SettlementLab

**Confidence starts with the match.**

[![Settlement assurance](https://github.com/kilicerdal/settlementlab/actions/workflows/assurance.yml/badge.svg)](https://github.com/kilicerdal/settlementlab/actions/workflows/assurance.yml)

SettlementLab is an independent post-trade simulator and Python assurance framework. V2.1 introduces separate broker and investment-manager submissions, a versioned matching policy, field-level exception investigation, preserved revisions, and free local AI triage. Follow a synthetic trade through correction, affirmation, settlement failure, recovery, and reconciliation.

![V2.1 two-sided matching workspace](docs/images/matching-v21.png)

## Run the workbench

Python 3.9+; the application and core tests have **zero third-party dependencies**.

```sh
PYTHONPATH=src python3 -m settlementlab.server
```

Open http://127.0.0.1:8080. Select **Run showcase scenario** for independently submitted terms with a price mismatch and an allocation-total mismatch. Use **Revise manager submission**, change the price to `42.75`, and make the fund allocations sum to `10000`. Submit the revision, affirm, attempt settlement, provision synthetic balances, retry, and reconcile.

Alternatively, use **Submit broker trade** and enter your own fictional terms, then **Submit manager terms** separately. Manager fields are not silently filled from the broker record. The explicit **Load broker terms for review** action copies them for review without committing a submission.

Data persists in `settlementlab.db`. Use `--db /tmp/demo.db` for a separate environment and `--port 8082` for another port. Install with `python3 -m pip install .` to use the `settlementlab` command; console assets are bundled in the package.

## What V2.1 adds

- Seven independently compared trade fields: security, economic side, quantity, price, currency, trade date, and settlement date.
- A separate check that fund allocations sum to the manager's declared quantity.
- Versioned, inspectable `equity-exact-v1` policy with exact equality and zero price tolerance.
- Structured discrepancy records: expected/observed values, field, code, and rule identity.
- Immutable-through-the-application manager revision history; corrections never overwrite broker terms.
- Idempotent manager submissions, conflicting-payload rejection, and stale-write protection.
- A matching console with search, status filters, submission forms, side-by-side comparison, and scoped audit history.
- Stage-specific local AI evidence with matching rules and discrepancy references.
- Additive migration for V1 databases, which retain their allocation-only workflow.

## Free local AI

Run Ollama locally with `qwen2.5:3b` installed, then select **Analyze exception with AI**. No API key, paid service, cloud account, or automatic model download is required. The adapter calls only the loopback Ollama endpoint. Set `SETTLEMENTLAB_MODEL` to another installed model or an empty string to disable AI.

AI explains supplied evidence, cites fact/break IDs, and suggests investigation. It has no tools to approve, fund, or settle trades. Structured output and reference validation do not establish factual accuracy; review the explanation. See [AI setup and evaluation scope](docs/AI.md).

## Verify the framework

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Core controls cover arithmetic, all matching fields, malformed submissions, migration, replay after correction, concurrent submissions, stale updates, lifecycle guards, rollback, settlement once-only behavior, and reconciliation. HTTP tests run against a real temporary TCP server and database. AI contract tests use injected responses and make no model calls.

Browser assurance (start the application separately):

```sh
python3 -m venv .venv
.venv/bin/pip install 'playwright>=1.48,<2'
.venv/bin/python -m playwright install chromium
.venv/bin/python tests/browser_smoke.py
```

The browser journey corrects two matching breaks, completes settlement recovery and reconciliation, then creates independent broker/manager submissions through mobile forms and checks filters. It captures desktop/mobile screenshots and a trace under `artifacts/`. Set `SETTLEMENTLAB_URL` for another environment. Opt into a real local-model browser check with `SETTLEMENTLAB_TEST_LOCAL_AI=1`; CI never requires Ollama.

CI runs Python 3.9/3.13 controls, verifies the installed package and CLI, and executes Chromium with uploaded failure evidence.

## Inspect the contract

```sh
curl http://127.0.0.1:8080/api/trades \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: broker-example' \
  -d '{"matching_mode":"two-sided","symbol":"NOVA","side":"BUY","currency":"USD","quantity":100,"price":"42.75","trade_date":"2026-11-06","settlement_date":"2026-11-09"}'
```

See [API contract](docs/API.md), [matching policy](docs/MATCHING.md), [architecture](docs/ARCHITECTURE.md), and [showcase guide](docs/SHOWCASE.md). The `SettlementClient` assurance adapter supports independent submissions without browser interaction.

## Reproduce recorded evidence

```sh
PYTHONPATH=src python3 scripts/capture_matching.py
PYTHONPATH=src python3 scripts/capture_matching.py --ai
```

The first command is deterministic and makes zero model calls. The second adds one real local inference. Captures distinguish their origin and source state. V1 lifecycle and model captures remain in `docs/evidence/` as historical examples.

## Current boundaries and upgrade

V2.1 is the first V2 increment, not the complete V2 roadmap. Broker trades use USD and fixed prices with two decimal places. Other recognized manager currencies are accepted for discrepancy detection, not FX settlement. Both sides use the investment manager economic BUY/SELL perspective. Settlement dates are compared as submitted; market holidays, eligibility, cutoffs, and date-gated settlement are not simulated. Legacy trades derive the next weekday; new two-sided submissions provide explicit dates.

Balances remain trade-scoped, not a participant-level double-entry ledger. Instructions are synthetic references. Workflow participant labels are not authenticated roles: login, participant isolation, and maker/checker controls are not implemented. Audit and revision records are transactional but not tamper-proof. The loopback server is for synthetic local demonstrations, not public API hosting. AI inference is local; the website presents recorded evidence.

Existing databases migrate additively on startup; back up the database first. Existing V1 records retain `allocation-only` mode. API requests that omit `matching_mode` also use that legacy contract for compatibility; the new console always creates `two-sided` trades. Two-sided trades cannot bypass matching through the legacy allocation endpoint. Manager terms lock after affirmation.

Next: shared participant ledger, identity and approval controls, controlled business calendars, durable processing, and broader AI evaluation.
