# Exact equity matching policy

Policy ID: `equity-exact-v1`. This is a project-defined simulation policy, not an external market specification.

Both participants independently submit the same economic perspective: BUY means the investment manager buys. The broker side is not automatically inverted. Broker terms remain unchanged through the application. Manager corrections are new revisions.

| Rule suffix | Comparison |
|---|---|
| SECURITY | Uppercased ASCII alphanumeric security identifier |
| SIDE | BUY/SELL equality |
| QUANTITY | Positive integer trade quantity equality |
| PRICE | Exact equality in integer cents; zero tolerance |
| CURRENCY | Currency-code equality; no conversion |
| TRADE_DATE | ISO date equality |
| SETTLEMENT_DATE | ISO date equality |
| ALLOCATION_TOTAL | Allocation sum equals the manager declared quantity |

A trade is MATCHED only when every comparison passes. Otherwise it is EXCEPTION with all discrepancies reported in stable rule order. A quantity mismatch and an allocation-total mismatch are distinct: the first compares broker and manager trade quantities; the second compares the manager's declared quantity to its own fund allocations. Unmatched trades cannot be affirmed.

For example, broker quantity 100 and manager quantity 99 with allocations totaling 99 produce one QUANTITY_MISMATCH, not an allocation-total break. Price 42.75 versus 42.76 produces PRICE_MISMATCH with expected 4275 and observed 4276. Prices are not rounded into agreement.

The manager must provide every term; omitted values are rejected rather than inferred from the broker. Symbol case is normalized and allocation accounts are trimmed and sorted. Duplicate accounts after trimming are rejected. Keys are scoped to a trade. An identical normalized manager replay returns the original response without a new revision or audit event, even after later corrections. A changed payload under that key conflicts. New submissions require the current trade version and an open pre-affirmation state.

The full active rule set is available at `GET /api/matching-policy`. Tolerances, alternative policies, reference-data matching and official market calendar integration require explicit future versions. Shared-ledger date eligibility already uses a separate pinned project calendar; it does not change these matching comparisons.
