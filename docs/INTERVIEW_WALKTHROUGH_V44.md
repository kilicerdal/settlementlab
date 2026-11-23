# SettlementLab: five-minute interview walkthrough

Speaking notes for Erdal Kilic. This is an independent, AI-assisted portfolio framework using synthetic financial data. Describe it as personal engineering work; do not imply it represents an employer's system or production deployment. Timing is approximate and should be rehearsed aloud.

## 0:00–0:45 — The problem

“My background is in SDET and automation framework development. With SettlementLab, I wanted to demonstrate how I test financial workflows beyond checking an API status code.

The question I focused on was: if a worker stops during processing, how do we recover the obligation and prove what happened financially? Then, if that execution needs a correction, how do we preserve the original history and show the correct current position?

The framework uses synthetic equity obligations and simulated balances. It does not connect to a market or move real funds.”

## 0:45–1:40 — The architecture

“There are two reference applications. The first is the financial operations workbench. The second is a separate collateral reservation service. I can install the HTTP assurance engine as its own wheel and run declarative scenarios against that second service. That demonstrates actual framework reuse.

In the financial application, the HTTP layer calls application services. Matching and workflow policies are separate from the SQLite adapters. Settlement workers claim work with leases and fencing checks. Financial posting, the execution receipt and outgoing events commit in one transaction.

There are two observer meanings. One records that settlement happened. The other represents the current financial position after corrections. Keeping them separate prevents a historical delivery receipt from being mistaken for today's net position.”

## 1:40–2:40 — The live example

“In this example, the obligation is 100 shares at $42.75. I queue a partial execution for 40 shares. I deliberately stop a real child worker after it commits its claim and before it posts the financial entries. The injected checkpoint exits with code 73.

After the lease expires, another worker completes the execution. The investigation retains the expired attempt, and the trade has one execution slice.

Next, the maker requests a correction and a different checker identity approves it. The application appends inverse cash and security entries. It does not delete the original execution.

At that point, gross quantity is 40, reversed quantity is 40 and authoritative net quantity is zero. The observer still shows 40 until its worker consumes the compensation event. After delivery, it shows zero too. The original settlement delivery remains in history.”

## 2:40–3:40 — A failure the controls catch

“One deliberately defective fixture is financially balanced but economically wrong. That is a useful failure because a simple zero-sum check would pass it.

The separate economic oracle checks the expected participants, asset names, signs, quantities and cents against the accepted execution plan. It rejects the wrong compensation even though the journal balances. The fixture is intentionally injected; it is not a production incident.

For portable evidence, I download an incident ZIP and run the verifier in another process. Checksums alone only establish content integrity. With the separately retained scenario plan, the verifier also checks scoped economics. That separation makes the assurance claim much more precise.”

## 3:40–4:25 — Why these choices

“I chose Python's standard library and SQLite to make the project easy to run without a cloud account or paid services. WAL snapshots give investigations a consistent read while another connection can write. The tradeoff is a local single-writer system, and some financial controls still scan history. I do not claim market-scale performance.

Maker and checker are different demo principals, but a user can switch them in the console. That tests the workflow rules; it does not demonstrate production authentication.

AI is optional and local. It can explain bounded evidence, but it has no financial mutation tools. This recording does not call a live model. Deterministic controls decide whether the financial result is acceptable.”

## 4:25–5:00 — Evidence and close

“For V4.4, the release evidence records 210 unit, API and integration tests, four assurance scenarios and all ten CI jobs passing. Those are release-specific results, not a claim about an unverified current run. There are also real browser journeys, targeted mutation checks and the second-service replay demonstration.

The part I would highlight is the connection between the workflow, failure injection, recovery and inspectable financial evidence. I can explain both what passed and what the framework does not prove.”

## Follow-up pointers

- [Architecture and boundaries](ARCHITECTURE.md)
- [V4.4 controls, measured results and limits](V4_4.md)
- [Balanced-but-wrong correction fixture](V4_3.md)
- [Standalone second-service reuse](STANDALONE_ASSURANCE.md)
- [Recording and reproduction instructions](SHOWCASE_V44.md)

Avoid claiming production readiness, independent human approval, live AI accuracy, tamper-proof evidence or distributed exactly-once processing. All intentionally defective fixtures must be identified as such.
