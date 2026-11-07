# Architecture and decisions — V2.2

```mermaid
flowchart LR
    UI[Operations console] --> HTTP[HTTP adapter]
    Client[Python assurance client] --> HTTP
    HTTP --> Domain[Transactional lifecycle service]
    Domain --> Matching[Versioned pure matching policy]
    Domain --> DB[(Trades / submissions / audit / settlements)]
    HTTP --> AI[Read-only local AI adapter]
    AI --> Ollama[Loopback model runtime]
```

## Transaction boundaries

The lifecycle service owns SQLite transactions and has no HTTP/UI dependency. Shared validators define exact monetary constraints. The matching module normalizes independent terms and compares them without storage or network access. Each new manager revision atomically stores the submission, matching result, lifecycle update, audit event and replay response. Failed commands roll back. BEGIN IMMEDIATE serializes local writers; version guards reject stale independent submissions. Unique trade/key and trade/revision constraints protect history.

Manager revisions never change broker economics. The matching report is stored with the trade and carries a policy ID plus all discrepancy records. Replaying a manager key returns its stored response snapshot, even if the trade later advanced. A successful new command increments the version; replay does not.

## State machine

A broker submission creates RECEIVED. Manager submission produces MATCHED or EXCEPTION. Further pre-affirmation manager revisions rerun matching and preserve history. MATCHED may be affirmed with a synthetic instruction. AFFIRMED may settle or become FAILED. FAILED may be funded and retried. SETTLED is terminal. Manager amendments lock after affirmation. Legacy allocation-only trades retain their V1 state transitions; the allocate command cannot bypass two-sided matching.

## Migration and persistence

Startup adds side, currency, mode and matching-report columns and a manager-submissions table. Existing trades default to allocation-only. The migration is repeatable and tested against a V1-shaped database, including its original broker fingerprint format. Back up an existing database before upgrading. Records are not cryptographically immutable: direct database access can change them.

## AI boundary

The server constructs a stage-specific envelope from the same trade version it checked. Matching evidence includes project policy definitions and explicit expected/observed break values. Free-form accounts and audit detail are excluded. The model returns schema-constrained advisory text and references. It has no mutation tools. Analysis runs outside the database transaction; concurrent changes can make its result stale, so its version is visible. Schema and citation identity checks cannot establish semantic correctness.

## Assurance

Domain tests use independent expected amounts and findings. They cover every matching field, separate allocation semantics, normalization, replay, stale writers, rollback, concurrent submissions, state guards, settlement once-only behavior, and migration. HTTP tests use a real ephemeral TCP server. The browser journey tests two-sided correction and recovery, then manual mobile submissions and filters. Optional live local inference is separate from deterministic CI.

## Scope

SQLite and the standard library keep the local demonstration reproducible. Verified identity, participant isolation, durable workers, market calendars and production serving remain later increments. V2.2 adds shared multi-asset posting and demo maker/checker controls as described below. Broker trades are USD; no currency conversion or settlement date eligibility is claimed. Prices use a fixed two-decimal simulation policy.


## Shared-ledger transaction boundary

`journal.py` validates per-asset zero sums, bounded integer deltas, known participants and nonnegative trading balances. Synthetic reserve offsets may be negative. One write transaction posts four cash/security lines, updates balance projections, inserts the settlement record, updates lifecycle state, and writes audit evidence. Failed funding or settlement rolls back the whole transaction. A unique settlement journal per trade plus lifecycle/version guards prevent repeat spending. SQLite writer serialization also protects balances shared by different trades.

Before posting, stored projections are compared with Python-integer reconstruction from journal lines and batches are checked for per-asset balance. Breaks stop new postings. This full scan favors inspectability over scale; it is not a production journal architecture. Direct database access can alter records; no tamper-proof audit claim is made.

## Approval and session boundaries

Instruction requests store maker, current terms version, instruction and idempotency key. A different checker can approve or reject against the current version. New manager revisions cancel pending requests. Approval and the AFFIRMED transition commit together. Funding does not advance trade version because it changes participant capacity, not approved economics.

`identity.py` stores opaque, expiring demo session tokens in memory. The HTTP adapter supplies the resolved Principal to the domain; JSON role/actor fields are not trusted. Anyone at the local console may select a demo persona. This demonstrates role enforcement and different-identity approval, not distinct-person authentication. Participant reads are not isolated. Older trade-scoped contracts remain explicitly outside shared-ledger governance for compatibility.

Startup adds participants, projections, journal batches/lines, instruction approvals and settlement-model columns. Old trades default to trade-scoped behavior; their economics are not silently moved into the shared journal.
