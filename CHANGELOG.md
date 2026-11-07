# Changelog

## 2.2.0 — Shared ledger and governed instruction approval

- Shared participant cash/security balances and balanced four-line DvP settlement, with atomic projections, lifecycle and audit writes.
- Checker-only idempotent synthetic reserve funding; no trade-scoped funding bypass for shared trades.
- Maker instruction requests, different-checker approval/rejection, reason history, stale guards and cancellation after revised terms.
- Opaque server-resolved demo sessions and role checks; personas are freely switchable, not production authentication.
- Participant balances, approval controls and journal inspection in the responsive console.
- Integrity checks, contention tests, injected-failure rollback tests and session-spoofing HTTP tests.

Legacy records retain trade-scoped settlement. Verified identity, participant isolation and market calendars remain future increments.

## 2.1.0 — Independent matching, first V2 increment

- Independent broker/manager terms with exact matching across seven fields and a separate manager allocation-total rule.
- Versioned policy, structured findings, preserved manager revisions, and idempotent submission replay.
- Additive V1 database migration and backward-compatible allocation-only mode; no bypass into two-sided matching.
- Operator forms, side-by-side comparison, discrepancy cards, scoped audit timeline, revision history, search and filters.
- Local AI receives policy definitions and explicit break facts; no paid API requirement.
- Matching/concurrency/migration/HTTP controls plus mobile manual-submission browser coverage.

Shared participant balances, authentication and approval roles remain later V2 increments.

## 1.0.0 — Initial local showcase

- Optional read-only AI triage with structured output, evidence references, and explicit provider configuration.
- Post-trade lifecycle with allocation exceptions, affirmation, simulated settlement, failure recovery, and statement reconciliation.
- Responsive operations console with a synthetic demonstration and persisted audit timeline.
- Exact integer-cent accounting within documented bounds, request idempotency, optimistic versions, and transactional updates.
- Reusable Python API assurance client and real HTTP integration tests.
- Concurrency controls verified for duplicate submissions and competing settlement attempts.
- Automated browser journey with desktop/mobile screenshots and a Playwright trace.
- GitHub Actions workflow for Python controls and Chromium evidence.

This release uses SQLite, a weekday-only calendar, trade-scoped demo balances, and simplified allocation matching. See the README for all version-one boundaries.
