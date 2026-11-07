# 001 — Commit settlement and financial evidence together

Status: implemented; documented from the V3.0 code.

## Problem

A settlement moves cash and securities, updates lifecycle state and records evidence. If these operations commit separately, a storage failure could leave money moved without a settlement record, or a SETTLED trade without its journal lines. Two trades sharing participant balances can also compete for the same capacity.

## Decision

Run posting, balance projection, settlement record, trade update and audit insertion inside one SQLiteStore transaction. Validate exact integer deltas, per-asset zero sums and journal/projection consistency before posting. BEGIN IMMEDIATE serializes local writers. State/version guards and settlement uniqueness prevent another command from spending the trade again.

Implementation: [SQLiteStore](../../src/settlementlab/infrastructure/store.py), [workflow service](../../src/settlementlab/application/service.py), [journal](../../src/settlementlab/infrastructure/journal.py), [posting invariants](../../src/settlementlab/core/postings.py).

## Alternatives and tradeoff

Separate commits simplify individual operations but require compensating recovery and introduce partially committed states. An asynchronous event-driven journal could support another deployment model, but requires durable delivery, replay policy and independently verified transaction semantics. A single SQLite transaction makes this synthetic local system easy to inspect, at the cost of serialized writers and a journal scan that does not target production scale.

## Reproducible evidence

[Shared-ledger tests](../../tests/integration/test_shared_ledger.py):

- `test_buy_transfers_four_balanced_lines`: independently checks cash and security transfers.
- `test_journal_and_settlement_rollback_together_on_failure`: installs a SQLite trigger that aborts settlement-record insertion; the complete snapshot must equal its pre-command value.
- `test_two_trades_cannot_spend_same_cash` and `test_two_trades_cannot_spend_same_securities`: competing trades cannot consume the same shared capacity.

```sh
PYTHONPATH=src python -m unittest tests.integration.test_shared_ledger -v
```

## Limits

SQLite locking is local persistence behavior, not evidence of distributed exactly-once processing. Direct database access can tamper with records. Project closure calendars and demo identities do not establish custody, regulatory accounting or production authorization.
