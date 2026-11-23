"""Independent, read-only DVP oracle. No settlement/posting implementation imports.

Expected movements come from externally supplied accepted terms, never journal output.
This oracle is intentionally restricted to shared-ledger USD equity settlement.
"""

import sqlite3
from collections import Counter, defaultdict

from ..infrastructure.sqlite_snapshot import readonly_connection


def expected_lines(terms):
    quantity, cents = terms["quantity"], terms["price_cents"]
    if any(type(v) is not int or v <= 0 for v in (quantity, cents)):
        raise ValueError("Oracle requires positive integer quantity and cents")
    buyer, seller, symbol = (terms[k] for k in ("buyer_id", "seller_id", "symbol"))
    if not all(isinstance(v, str) and v for v in (buyer, seller, symbol)) or buyer == seller:
        raise ValueError("Oracle requires distinct participants and a symbol")
    amount = quantity * cents
    return Counter(
        [
            (buyer, "CASH:USD", -amount),
            (seller, "CASH:USD", amount),
            (seller, "SEC:" + symbol, -quantity),
            (buyer, "SEC:" + symbol, quantity),
        ]
    )


def audit(database, accepted, include_details=False):
    """accepted maps every expected settled trade ID to independently retained terms.

    Full journal is read in one SQLite snapshot; UI history limits do not apply.
    Funding is checked for conservation/projection, not independently authorized here.
    """
    findings = []
    comparisons = []
    with readonly_connection(database) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        trades = {r["id"]: dict(r) for r in db.execute("SELECT * FROM trades")}
        batches = [dict(r) for r in db.execute("SELECT * FROM journal_batches")]
        lines = [dict(r) for r in db.execute("SELECT * FROM journal_lines")]
        settlements = {r["trade_id"]: dict(r) for r in db.execute("SELECT * FROM settlements")}
        approvals = [dict(r) for r in db.execute("SELECT * FROM approval_requests")]
        balances = {
            (r["participant_id"], r["asset"]): r["balance"]
            for r in db.execute("SELECT * FROM balances")
        }
    by_batch = defaultdict(list)
    projection = defaultdict(int)
    for line in lines:
        by_batch[line["batch_id"]].append(line)
        projection[(line["participant_id"], line["asset"])] += line["delta"]
    for batch in batches:
        totals = defaultdict(int)
        for line in by_batch[batch["id"]]:
            totals[line["asset"]] += line["delta"]
        if len(by_batch[batch["id"]]) < 2 or any(totals.values()):
            findings.append(dict(control="asset-conservation", batch=batch["id"]))
    if dict(projection) != {k: v for k, v in balances.items()}:
        # Missing zero-only accounts are equivalent to an explicit zero balance.
        if any(
            projection.get(k, 0) != balances.get(k, 0) for k in projection.keys() | balances.keys()
        ):
            findings.append(dict(control="balance-projection"))
    if any(v < 0 for (party, _), v in balances.items() if party != "SYN-RESERVE"):
        findings.append(dict(control="nonnegative-trading-balances"))
    dvp = defaultdict(list)
    for batch in batches:
        if batch["kind"] == "DVP_SETTLEMENT":
            dvp[batch["trade_id"]].append(batch)
    actual_settled = {k for k, v in trades.items() if v["state"] == "SETTLED"}
    if (
        actual_settled != set(accepted)
        or set(dvp) != set(accepted)
        or set(settlements) != set(accepted)
    ):
        findings.append(
            dict(
                control="settled-trade-completeness",
                expected=sorted(accepted),
                actual=sorted(actual_settled),
            )
        )
    for trade_id, terms in accepted.items():
        expected = expected_lines(terms)
        rows = dvp.get(trade_id, [])
        observed = Counter(
            (line["participant_id"], line["asset"], line["delta"])
            for batch in rows
            for line in by_batch[batch["id"]]
        )
        if include_details:
            comparisons.append(
                dict(
                    trade_id=trade_id,
                    accepted_terms=dict(terms),
                    expected_movements=[
                        dict(participant=party, asset=asset, delta=delta, count=count)
                        for (party, asset, delta), count in sorted(expected.items())
                    ],
                    observed_movements=[
                        dict(participant=party, asset=asset, delta=delta, count=count)
                        for (party, asset, delta), count in sorted(observed.items())
                    ],
                    settlement_batches=len(rows),
                    movements_match=len(rows) == 1 and observed == expected,
                )
            )
        if len(rows) != 1 or observed != expected:
            findings.append(dict(control="independent-dvp-movements", trade_id=trade_id))
        receipt = settlements.get(trade_id, {})
        if (
            receipt.get("quantity") != terms["quantity"]
            or receipt.get("amount_cents") != terms["quantity"] * terms["price_cents"]
        ):
            findings.append(dict(control="independent-settlement-receipt", trade_id=trade_id))
        approved = [a for a in approvals if a["trade_id"] == trade_id and a["status"] == "APPROVED"]
        if (
            not approved
            or any(a["maker_id"] == a["decided_by"] for a in approved)
            or (
                rows
                and not any(
                    a["decided_at"] and a["decided_at"] <= rows[0]["timestamp"] for a in approved
                )
            )
        ):
            findings.append(dict(control="independent-approval", trade_id=trade_id))
    return dict(
        status="passed" if not findings else "failed",
        expected_settlements=len(accepted),
        journal_batches=len(batches),
        journal_lines=len(lines),
        findings=findings,
        comparisons=comparisons,
        scope="Independent expected DVP terms; full read-only SQLite snapshot; funding conservation only",
    )
