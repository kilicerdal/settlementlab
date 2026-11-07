# V2.2 showcase: approval to balanced settlement

As Alex · Maker, create and match independent submissions. Request instruction approval and demonstrate that Alex cannot approve it. Switch to Sam · Checker, inspect and approve the current matched version. Attempt settlement with insufficient shared capacity; it fails without journal changes. Fund the buyer's shared cash and seller's securities, retry and inspect the four balanced cash/security lines. Reconcile the settled trade. Switch to Casey · Auditor to show read-only shared controls.

A second trade using the same buyer and seller cannot spend the depleted capacity again. Concurrency tests exercise that race for both cash and securities. Manager corrections cancel pending approvals; the maker must request review again. Rejection preserves a reason. Reserve funding is synthetic and idempotent.

Run `PYTHONPATH=src python3 scripts/capture_ledger.py` for recorded approval, recovery and competing-trade evidence. The browser journey tests the console, demo roles, mobile submissions and local AI (when explicitly enabled). Default CI requires no model runtime or paid API.

Demo personas are openly switchable and are not production identity proof. The public website presents recorded synthetic evidence; the actual workflow and local inference run on the developer's computer.

---

# V2.1 showcase walkthrough

## The narrative

A fictional broker submits 10,000 NOVA shares at $42.75. The manager independently submits $42.80 and fund allocations of 6,000 and 3,900 against a declared trade quantity of 10,000. The exact-match policy exposes PRICE_MISMATCH and ALLOCATION_TOTAL_MISMATCH separately.

Inspect the side-by-side terms and ask the local AI investigator to explain the supplied breaks. Revise the manager submission to $42.75 and allocations of 6,000 and 4,000. The trade becomes MATCHED; broker terms remain unchanged and revision one remains visible. Affirm, attempt settlement without capacity, provision fictional balances, retry and reconcile a generated matching statement.

Then demonstrate a manually entered broker trade and a separately entered manager submission through the responsive forms. Search and filter the blotter to find the result.

## Reproduction and evidence

`PYTHONPATH=src python3 scripts/capture_matching.py` records the deterministic two-sided scenario and correction. Add `--ai` for one real local inference; model output and citation checks are recorded separately. Live examples are not a model-quality benchmark. The browser journey writes `two-sided-exception.png`, `desktop.png`, `mobile.png`, `mobile-submission.png` and `journey.zip`. With `SETTLEMENTLAB_TEST_LOCAL_AI=1`, it also captures local AI in the console.

Use matching records, screenshots, and CI results in the website case study. Explain the concurrency, replay and migration checks alongside the interface. Do not invent throughput, coverage, accuracy or production-readiness claims. Historical V1 evidence remains clearly separate.

## Deployment boundary

The existing website presents recorded synthetic evidence. The local application performs the actual workflow and inference. Its unauthenticated loopback API must not be presented as a public multi-participant service. Identity, participant isolation, approvals, resource limits and deployment-specific security controls are future work.
