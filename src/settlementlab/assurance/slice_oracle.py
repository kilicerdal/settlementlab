"""Read-only partial-execution oracle driven by independently retained plans.

No production settlement, balance, or reconciliation implementation is imported.
"""

import sqlite3
from collections import Counter, defaultdict

from ..infrastructure.sqlite_snapshot import readonly_connection


def audit_slices(database, plans):
    """plans maps trade IDs to accepted terms and expected executed_quantity.

    Supply every trade with partial execution; omitted/orphan slice batches fail.
    This checks slice economics and cumulative receipts, not market authenticity.
    """
    findings = []
    with readonly_connection(database) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        slices = [dict(r) for r in db.execute("SELECT * FROM settlement_slices")]
        batches = {r["id"]: dict(r) for r in db.execute("SELECT * FROM journal_batches")}
        lines = defaultdict(list)
        for row in db.execute("SELECT * FROM journal_lines"):
            lines[row["batch_id"]].append((row["participant_id"], row["asset"], row["delta"]))
        receipts = {r["trade_id"]: dict(r) for r in db.execute("SELECT * FROM settlements")}
        revisions = {
            (r["trade_id"], r["revision"]) for r in db.execute("SELECT * FROM trade_revisions")
        }
    seen = set()
    totals = defaultdict(int)
    for item in slices:
        plan = plans.get(item["trade_id"])
        batch = batches.get(item["batch_id"])
        seen.add(item["batch_id"])
        if not plan:
            findings.append(dict(control="unplanned-execution", trade_id=item["trade_id"]))
            continue
        quantity = item["quantity"]
        amount = quantity * plan["price_cents"]
        expected = Counter(
            [
                (plan["buyer_id"], "CASH:USD", -amount),
                (plan["seller_id"], "CASH:USD", amount),
                (plan["seller_id"], "SEC:" + plan["symbol"], -quantity),
                (plan["buyer_id"], "SEC:" + plan["symbol"], quantity),
            ]
        )
        if (
            not batch
            or batch["kind"] != "DVP_PARTIAL"
            or Counter(lines[item["batch_id"]]) != expected
            or item["price_cents"] != plan["price_cents"]
        ):
            findings.append(
                dict(control="slice-economics", trade_id=item["trade_id"], batch=item["batch_id"])
            )
        if (
            item["revision"] != plan["revision"]
            or (item["trade_id"], item["revision"]) not in revisions
        ):
            findings.append(dict(control="slice-revision", trade_id=item["trade_id"]))
        totals[item["trade_id"]] += quantity
    for key, batch in batches.items():
        if batch["kind"] == "DVP_PARTIAL" and key not in seen:
            findings.append(dict(control="orphan-slice-batch", batch=key))
    for trade, plan in plans.items():
        receipt = receipts.get(trade)
        expected_quantity = plan["executed_quantity"]
        if (
            totals[trade] != expected_quantity
            or not 0 <= totals[trade] <= plan["quantity"]
            or not receipt
            or receipt["quantity"] != expected_quantity
            or receipt["amount_cents"] != expected_quantity * plan["price_cents"]
        ):
            findings.append(dict(control="cumulative-execution", trade_id=trade))
    return dict(
        status="passed" if not findings else "failed",
        findings=findings,
        slices=len(slices),
        scope="Independent accepted terms and execution totals; no production posting imports",
    )
