# Lifecycle recovery procedures

Record the database path, release, business-clock mode, trade/revision/version, job/generation and relevant request keys before intervention. Preserve evidence and use public commands; do not repair financial rows with SQL.

## Amendment while a worker holds a lease

1. Maker submits complete corrected terms with the displayed version, a new key and a review reason.
2. Confirm `RECEIVED`, a new lifecycle revision, retained original terms and a `LIFECYCLE_INVALIDATED` queue event.
3. Confirm the old claimed worker is fenced; it must not create an execution, receipt or outbox event.
4. Submit a new manager match and request independent checker approval. Queue only the new version.

Evidence: `WorkflowControls.test_amend_fences_claimed_worker_and_invalidates_old_approval` and `test_amended_trade_can_be_matched_and_approved_again`.

## Capacity shortage after a partial execution

1. Inspect executed and remaining quantities, cumulative cents, journal slices and shared participant balances.
2. Confirm the failed request added no financial slice. Do not replay with changed quantity under the same key.
3. Checker adds explicit synthetic funding with its own idempotency key. This is demonstration funding, not a cash transfer.
4. Refresh the version. Submit a new explicit execution key or reviewed durable retry.
5. Confirm cumulative quantity/cents and balanced journal. Use the independent slice oracle with the retained execution plan.

Evidence: `test_partial_failure_then_funding_keeps_original_execution`. A precommit worker failure rolls back posting, receipt and outbox together; retry after its actual queue availability time. Evidence: `test_partial_precommit_failure_rolls_back_financial_and_evidence`.

## Cutoff exceeded

1. Inspect the pinned UTC cutoff and business-clock precision. A date-only simulation does not enforce an intraday cutoff.
2. Timed execution after the original deadline is blocked, including the next morning. Advancing or rewinding the simulation is not an authorized operational remedy.
3. Retain the overdue obligation for investigation or cancel the remainder with checker review. This release has no deadline override. Unposted terms can be corrected only through a valid amendment and fresh approval, preserving the original history.

Evidence: `test_cutoff_uses_explicit_utc_timestamp` and `test_overdue_cutoff_does_not_reopen_next_morning`.

## Statement discrepancy

1. Import a full independently supplied CSV statement; retain its source outside the system if authenticity matters.
2. Inspect the original internal snapshot and imported rows. Identify missing internal, missing external or value mismatch cases.
3. Obtain and import corrected full evidence under a new key. A reason alone cannot close a mismatch.
4. Resolve against the new statement ID. Confirm the original discrepancy remains and resolution includes actor, time, reason and comparison snapshot.
5. Other cases may remain open; resolution of one case is not global reconciliation success.

Evidence: `test_statement_break_requires_distinct_corrected_evidence` and the lifecycle browser smoke.

## Cancel a partially executed obligation

Checker cancels with current version, key and reason. Confirm `CANCELLED`; prior quantities and journal entries remain unchanged. Confirm subsequent execution is rejected. Cancellation is not reversal. Genuine correction/reversal accounting is outside this release.

## SQLite writer contention

A continuous worker reports `STORAGE_BUSY` and backs off when a claim or delivery cannot acquire the writer lock. A one-shot worker exits 75 with a retryable diagnostic; its supervisor may retry. Do not treat this exit as settlement completion. Inspect the persisted job/receipt to determine whether the financial transaction committed. Other storage errors remain visible and are not silently retried. The 1,000-trade campaign records claim timeouts separately from job-attempt retries.
