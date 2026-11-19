# 007 — linked investigations and compensating financial events

V4.3 assembles a trade-scoped investigation from one transaction through repository ports. Evidence IDs remain stable within the retained database and correlations join accepted terms, approval, attempts, execution, statements and corrections. Actual event timestamps are distinct from the simulated business clock. Exports fail on oversized investigations rather than silently presenting partial history.

A reversal is a new linked financial batch, never an edit to the original execution. One maker requests compensation of one full original batch, invalidating active work; a different checker authorizes its exact inverse. Financial posting, decision and audit evidence commit atomically. Replay is independent of expected-version protection. Insufficient capacity leaves the decision pending and adds no journal effects.

Gross receipts remain the historical executed obligation. Net quantities subtract approved compensations; newer reconciliation compares against that net view while retaining old statement snapshots and decisions. Existing gross-receipt reconciliation remains a documented legacy contract. Corrected obligations close ordinary execution rather than silently reopening capacity or approval. Settlement delivery projection remains historical; it is not represented as a current correction feed.

A deliberately defective reviewer fixture is isolated from the original database. It preserves conservation and projection while changing compensating cash by one cent. An independent oracle uses externally retained economic plans and detects the error. Content checksums still pass because integrity of an exported file is distinct from correctness of its contents.

AI receives only fixed observations and references. Unknown causes require uncertainty, unsupported structured claims fail and missing evidence requires abstention. Offline fixtures and actual small local-model samples are reported separately. These checks do not establish general factual accuracy or replace independent human review.

Tradeoffs: one serialized SQLite writer; complete related synthetic statement data in exports; full-batch reversals only; no correction event-delivery feed, trade reopening or verified production identity. These limits are explicit in the UI/runbooks rather than hidden by a broader production claim.
