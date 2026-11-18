# V4 durable operations verification

Status: 4.0.0.dev1, development upgrade stacked on framework-depth PR #14. Not a production release.

Implemented persistent batch acceptance, leased workers with fencing and bounded retries, atomic settlement/receipt/outbox commits, a separately delivered observer with inbox deduplication, reviewed dead-letter recovery, and the `/operations` console. See [the operational guide](DURABLE_OPERATIONS.md) and [architecture decision](decisions/004-durable-settlement.md).

Local verification on 2026-11-18:

- 130 deterministic cases passed, including actual subprocess exits at six crash checkpoints.
- Combined line/branch coverage: 88.77% (2,121/2,299 statements and 685/862 branches).
- Ruff lint/format, strict mypy on 15 files, and whitespace checks passed.
- Original financial browser journey and new durable desktop/mobile browser journey passed.
- The 4.0.0.dev1 wheel installed into a fresh environment outside the checkout; bundled console assets, processing, delivery, and duplicate rejection worked.
- Portable recovery demo verified four settled trades, 16 settlement journal lines, five receipts, five delivered outbox events, five inbox records, and matching reconciliation.

Generated local evidence is under `artifacts/durable-showcase/` and `artifacts/durable-browser/`; CI reproduces and uploads evidence. These are synthetic demonstrations, not external institution or production claims. No paid service is required. The public website and unrelated original-checkout work were not changed.

Limits: one shared SQLite database, demo identities rather than production authentication, an in-database observer, and explicit clock coordination. Deduplication is scoped to this transaction/receipt/inbox design; arbitrary external side effects require their own idempotency contract. Review schema 5 backup and downgrade limits before using a pre-existing database.
