# 006 — versioned obligations and immutable execution

V4.2 keeps accepted terms, independent approval and financial execution as separate evidence. A trade version protects concurrent commands; a lifecycle revision identifies the economic terms that a manager submission and checker approval authorize. An amendment must change both, invalidate active work and restart matching. Approved historical decisions are retained rather than rewritten to imply that a reviewer approved different terms.

Partial execution uses one balanced four-leg batch per explicit slice and a cumulative settlement receipt. The legacy full-execution journal shape remains supported. An additive slice table maps partial batches to trades without removing the legacy unique full-batch constraint. This avoids destructive migration and preserves old oracle behavior, at the cost of two supported journal representations. The slice oracle therefore verifies the new representation independently against retained expected terms and totals.

Cancellation closes only the unexecuted obligation. Reversal accounting and corrections to posted economics are intentionally absent: quietly editing posted terms would erase the basis of earlier financial effects. Any future reversal must be a new linked financial event with its own authorization and tests.

Reconciliation compares imported full statements with cumulative executed receipts. Original rows, snapshots and discrepancies stay immutable. Closing a case requires a distinct imported statement whose values agree with current records, plus a retained human-readable reason. User-supplied evidence is not authenticated counterparty data; the interface and documentation state that limit.

The deadline policy is pinned on new obligations and interpreted against an explicit clock. Date-only fixtures stay date-only; migrated trades do not acquire a retroactive cutoff. Queue leases continue to use actual elapsed time, independent of the simulated business clock.

Evidence: V4.2 workflow/API tests, independent slice tampering test, six source mutants, real V4.1 migration/recovery drill, standalone second-service wheel and concurrent workload artifacts. External human review remains pending.
