# Financial-position and verification recovery

## Position is lagging after compensation

Inspect authoritative and observed amounts, pending events, source versions and the linked compensation journal. Keep historical settlement delivery separate. Run the financial-position worker against the same database; it requires no business-date override because it observes already committed financial events rather than making new settlement decisions.

A crash after projection commit but before acknowledgment leaves an inbox receipt. Redelivery deduplicates it and acknowledges the publisher without applying financial effects again. An expired worker must not acknowledge with its former lease token. Old delivered events remain retained and cannot regress newer observed totals.

A blocked event indicates exhausted delivery attempts or an invalid envelope. Preserve the incident bundle and inspect the event and source journal. Do not edit payloads, fabricate delivery receipts or delete inbox rows to make the UI green. This candidate has no automatic administrative unblock command. Repairing a corrupted event stream requires an explicit future repair workflow.

## Investigation bound exceeded

The endpoint rejects oversized retrieval rather than dropping history. Use a smaller isolated synthetic demonstration dataset or an appropriately scoped database copy. This candidate does not implement date-range pagination. Do not delete financial history from the source database to bypass the limit. Global financial controls can still be expensive even though statement retrieval is indexed.

## Bundle passes checksums but fails economic verification

Preserve both the bundle and external accepted-plan file, including their hashes. Read the named failed control and compare original/compensating participants, assets, signs, quantities and cents against the independently retained plan. Conservation and matching checksums alone cannot prove correct economics. A plan copied from the suspect output is not independent evidence.

A positive combined result is scoped to the supplied obligation and plan. It does not authenticate counterparties, operator identities or global funding. Integrity-only output explicitly says economic verification was not run.

## Choosing a reconciliation contract

Legacy `/api/reconcile` compares gross receipts. Use `/api/reconciliation/statements` for net-after-compensation investigation and retain its imported snapshots and case resolutions. Do not interpret results across these bases as interchangeable. Empty or zero-net positions must follow the documented full-statement convention.

## WAL-aware backup

Use the shipped online SQLite backup/verification tool. Do not copy only the main `.db` file while its WAL is active. An established read transaction sees a consistent historical snapshot; release it promptly so checkpointing can progress. Keep pre-upgrade backups and reconcile any work accepted after their recovery point before rollback.
