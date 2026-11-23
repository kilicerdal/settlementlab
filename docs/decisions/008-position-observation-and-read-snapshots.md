# 008 — financial-position events, read snapshots and external expectations

V4.4 adds a financial-position stream rather than rewriting the historical settlement observer. Executions and compensations publish absolute gross/reversed/net totals atomically with their financial transactions. A separate fenced worker applies events through an inbox and monotonic source-version/sequence comparison. Duplicate or late events cannot regress the observed position. Migration baselines are labeled snapshots, not invented historical deliveries.

Read-only snapshots use SQLite WAL, read-only connections and deferred transactions. They retain a consistent view while writers commit. Write commands keep their immediate transaction boundary. Statement membership and trade-history indexes remove whole-statement scans; early row/payload limits reject oversized investigations rather than silently dropping evidence. Global journal-control reads remain an explicit cost and WAL-aware online backup remains required.

Gross and net reconciliation are separate named contracts. Legacy clients retain gross semantics and receive a migration target; newer investigation uses net after approved compensations. The UI identifies the basis, and authoritative versus observed position values remain separately visible during delivery lag.

Content integrity is distinct from economic correctness. The combined reviewer command requires an external accepted plan and verifies scoped original/compensating legs and receipts against it. It does not infer expectations from suspect data or claim global funding, market truth or human identity authentication.

Broader repeated local AI samples measure grounded claims, citations, unnecessary abstention and repeat consistency independently. Small synthetic samples remain development evidence. Outside human review is not requested and no review is claimed or sent.
