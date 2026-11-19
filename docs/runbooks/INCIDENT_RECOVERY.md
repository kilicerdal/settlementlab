# Incident investigation and correction recovery

1. Capture the trade ID/version, business-clock policy and incident export before intervention. Preserve the unresolved export; do not overwrite it with a later result.
2. Inspect the correlated worker, execution, receipt and outbox records. A missing worker acknowledgement does not imply missing financial execution. Reclaim an expired lease through the worker, then verify a single execution/receipt and observer deduplication.
3. Import full independent statement evidence. Retain delayed and erroneous statements; obtain a separate corrected statement before resolving numeric discrepancies. Resolutions are historical decisions, not permanent claims that all future statements agree.
4. If posted execution requires correction, a maker requests reversal of the specific original execution batch with current version, unique key and reason. Confirm active work is fenced and `CORRECTION_PENDING` blocks further execution.
5. A different checker inspects the original four legs and proposed exact inverse. Confirm financial capacity, then approve or reject with a reason. A reason alone cannot bypass an integrity or capacity failure.
6. On failed approval, refresh the investigation. A rolled-back transaction leaves the correction pending and adds no compensating batch. Do not modify journal rows manually or change a request's payload under its original key.
7. On success, verify the linked compensating batch, original unchanged entries, gross/reversed/net quantities, decision identities and balanced asset totals. Use independently retained expected terms; conservation alone is insufficient.
8. Import a new statement of net executed obligations and export the final evidence. Preserve the earlier snapshot and any open discrepancies. A fully compensated obligation is closed; replacement/reopening requires future explicitly designed workflow.

Correction request rejection restores the prior trade state but does not resurrect invalidated jobs. Requeue only after checker review against the current version. Partial approval of a batch is not supported: compensation always reverses one complete original execution batch.

The dedicated incident export is read-only. Verification checks checksums and graph integrity, not authenticity or financial correctness. Treat AI commentary as optional and versioned, never as an approval or root-cause proof.

Before upgrading to schema 7, create and verify a backup. Old releases refuse the new schema; restore a separate pre-upgrade backup for rollback, preserving any post-upgrade work for reconciliation. Never lower `user_version` manually.
