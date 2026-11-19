"""Independent compensation oracle; no posting, correction or balance implementation imports."""

import sqlite3
from collections import Counter, defaultdict
from pathlib import Path


def audit(database, accepted):
    """accepted maps original batch IDs to separately retained economic expectations.

    Each plan includes trade_id, buyer_id, seller_id, symbol, quantity, price_cents.
    Include every approved compensation. Original and compensating postings must
    equal the plan and its exact inverse, not merely balance to zero.
    """
    with sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        requests = [dict(r) for r in db.execute("SELECT * FROM reversal_requests")]
        batches = {r["id"]: dict(r) for r in db.execute("SELECT * FROM journal_batches")}
        lines = defaultdict(list)
        projection = defaultdict(int)
        for row in db.execute("SELECT * FROM journal_lines"):
            lines[row["batch_id"]].append((row["participant_id"], row["asset"], row["delta"]))
            projection[(row["participant_id"], row["asset"])] += row["delta"]
        balances = {
            (r["participant_id"], r["asset"]): r["balance"]
            for r in db.execute("SELECT * FROM balances")
        }
    findings = []
    seen = set()
    originals = set()
    for request in requests:
        if request["status"] != "APPROVED":
            if request["compensation_batch"]:
                findings.append(dict(control="unapproved-compensation", request=request["id"]))
            continue
        original = request["original_batch"]
        compensation = request["compensation_batch"]
        seen.add(compensation)
        plan = accepted.get(original)
        if original in originals:
            findings.append(dict(control="duplicate-original-compensation", batch=original))
        originals.add(original)
        if not plan:
            findings.append(dict(control="unplanned-compensation", batch=original))
            continue
        quantity = plan["quantity"]
        amount = quantity * plan["price_cents"]
        expected = [
            (plan["buyer_id"], "CASH:USD", -amount),
            (plan["seller_id"], "CASH:USD", amount),
            (plan["seller_id"], "SEC:" + plan["symbol"], -quantity),
            (plan["buyer_id"], "SEC:" + plan["symbol"], quantity),
        ]
        if Counter(lines[original]) != Counter(expected):
            findings.append(dict(control="original-economics", batch=original))
        if (
            compensation not in batches
            or batches[compensation]["kind"] != "DVP_REVERSAL"
            or Counter(lines[compensation])
            != Counter((party, asset, -delta) for party, asset, delta in expected)
        ):
            findings.append(dict(control="compensation-economics", batch=compensation))
        if (
            request["trade_id"] != plan["trade_id"]
            or request["quantity"] != quantity
            or request["amount_cents"] != amount
        ):
            findings.append(dict(control="correction-receipt", request=request["id"]))
        if not request["checker_id"] or request["checker_id"] == request["maker_id"]:
            findings.append(dict(control="independent-authorization", request=request["id"]))
    for batch in batches.values():
        if batch["kind"] == "DVP_REVERSAL" and batch["id"] not in seen:
            findings.append(dict(control="orphan-compensation", batch=batch["id"]))
        totals = defaultdict(int)
        for _, asset, delta in lines[batch["id"]]:
            totals[asset] += delta
        if any(totals.values()):
            findings.append(dict(control="asset-conservation", batch=batch["id"]))
    if originals != set(accepted):
        findings.append(dict(control="expected-compensation-set"))
    if any(
        projection.get(key, 0) != balances.get(key, 0)
        for key in projection.keys() | balances.keys()
    ):
        findings.append(dict(control="balance-projection"))
    return dict(
        status="passed" if not findings else "failed",
        findings=findings,
        approved_compensations=len(originals),
        scope="Independent externally supplied accepted economic plans; no production posting imports",
    )
