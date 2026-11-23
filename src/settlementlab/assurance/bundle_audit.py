"""Independent scoped bundle economics against a separately supplied accepted plan."""

import hashlib
import json
from collections import Counter
from pathlib import Path


def unique(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise ValueError("Duplicate expectation field")
        result[k] = v
    return result


def load_plan(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError("Expectations exceed 64 KiB")
    plan = json.loads(raw, object_pairs_hook=unique)
    if (
        not isinstance(plan, dict)
        or set(plan) != {"format_version", "trade_id", "terms", "executions", "compensations"}
        or type(plan["format_version"]) is not int
        or plan["format_version"] != 1
    ):
        raise ValueError("Invalid expectation contract")

    def identifier(value):
        if (
            not isinstance(value, str)
            or not 1 <= len(value) <= 120
            or any(ord(c) < 32 for c in value)
        ):
            raise ValueError("Invalid expected identifier")

    identifier(plan["trade_id"])
    terms = plan["terms"]
    if not isinstance(terms, dict) or set(terms) != {
        "buyer_id",
        "seller_id",
        "symbol",
        "price_cents",
        "quantity",
    }:
        raise ValueError("Invalid expected economic terms")
    for key in ("buyer_id", "seller_id", "symbol"):
        identifier(terms[key])
    if (
        terms["buyer_id"] == terms["seller_id"]
        or any(
            type(terms[k]) is not int or not 1 <= terms[k] <= 10**15
            for k in ("price_cents", "quantity")
        )
        or terms["price_cents"] * terms["quantity"] > 10**15
    ):
        raise ValueError("Invalid expected notional")
    if (
        not isinstance(plan["executions"], list)
        or len(plan["executions"]) > 1000
        or not isinstance(plan["compensations"], list)
        or len(plan["compensations"]) > 1000
    ):
        raise ValueError("Invalid expected execution list")
    seen = set()
    for execution in plan["executions"]:
        if not isinstance(execution, dict) or set(execution) != {"batch_id", "quantity"}:
            raise ValueError("Invalid expected execution")
        identifier(execution["batch_id"])
        if (
            execution["batch_id"] in seen
            or type(execution["quantity"]) is not int
            or not 1 <= execution["quantity"] <= terms["quantity"]
        ):
            raise ValueError("Duplicate or invalid expected execution")
        seen.add(execution["batch_id"])
    if sum(e["quantity"] for e in plan["executions"]) > terms["quantity"]:
        raise ValueError("Expected overfill")
    for batch in plan["compensations"]:
        identifier(batch)
    if (
        len(set(plan["compensations"])) != len(plan["compensations"])
        or not set(plan["compensations"]) <= seen
    ):
        raise ValueError("Unknown or duplicate expected compensation")
    return plan, hashlib.sha256(raw).hexdigest()


def audit(snapshot, plan):
    findings = []

    def issue(control, identity=None):
        findings.append(dict(control=control, evidence_id=identity))

    trade = snapshot["trade"]
    records = snapshot["records"]
    terms = plan["terms"]
    if trade.get("currency") != "USD" or trade.get("settlement_model") != "shared-ledger":
        issue("supported-financial-model")
    if trade["id"] != plan["trade_id"]:
        issue("expected-trade")
    if any(
        trade.get(k) != terms[k]
        for k in ("buyer_id", "seller_id", "symbol", "price_cents", "quantity")
    ):
        issue("accepted-terms")
    batches = {b["id"]: b for b in records["batches"]}
    if len(batches) != len(records["batches"]):
        issue("duplicate-batch")
    actual_originals = {
        b["id"] for b in batches.values() if b["kind"] in ("DVP_PARTIAL", "DVP_SETTLEMENT")
    }
    expected_originals = {e["batch_id"] for e in plan["executions"]}
    if actual_originals != expected_originals:
        issue("execution-set")

    def expected(quantity):
        amount = quantity * terms["price_cents"]
        return [
            (terms["buyer_id"], "CASH:USD", -amount),
            (terms["seller_id"], "CASH:USD", amount),
            (terms["seller_id"], "SEC:" + terms["symbol"], -quantity),
            (terms["buyer_id"], "SEC:" + terms["symbol"], quantity),
        ]

    def actual(batch):
        if not batch:
            return Counter()
        if any(type(line["delta"]) is not int for line in batch["lines"]):
            raise ValueError("Financial line deltas require exact integers")
        return Counter(
            (line["participant_id"], line["asset"], line["delta"]) for line in batch["lines"]
        )

    executed = {e["batch_id"]: e["quantity"] for e in plan["executions"]}
    for batch_id, quantity in executed.items():
        if actual(batches.get(batch_id)) != Counter(expected(quantity)):
            issue("execution-economics", batch_id)
    approved = [r for r in records["reversals"] if r["status"] == "APPROVED"]
    if {r["original_batch"] for r in approved} != set(plan["compensations"]) or len(
        approved
    ) != len(plan["compensations"]):
        issue("compensation-set")
    seen = set()
    for request in records["reversals"]:
        if request["status"] != "APPROVED":
            if request["compensation_batch"]:
                issue("unapproved-compensation", request["id"])
            continue
        original = request["original_batch"]
        batch_id = request["compensation_batch"]
        seen.add(batch_id)
        if not request["checker_id"] or request["checker_id"] == request["maker_id"]:
            issue("independent-checker", request["id"])
        if original not in executed:
            issue("unknown-original", request["id"])
            continue
        quantity = executed[original]
        batch = batches.get(batch_id)
        if (
            not batch
            or batch["kind"] != "DVP_REVERSAL"
            or actual(batch)
            != Counter((party, asset, -delta) for party, asset, delta in expected(quantity))
        ):
            issue("compensation-economics", batch_id)
        if (
            request["trade_id"] != plan["trade_id"]
            or request["quantity"] != quantity
            or request["amount_cents"] != quantity * terms["price_cents"]
        ):
            issue("correction-receipt", request["id"])
    if {b["id"] for b in batches.values() if b["kind"] == "DVP_REVERSAL"} != seen:
        issue("orphan-compensation")
    if any(
        b["kind"] not in ("DVP_PARTIAL", "DVP_SETTLEMENT", "DVP_REVERSAL") for b in batches.values()
    ):
        issue("unexpected-scoped-batch")
    gross = sum(executed.values())
    reversed_quantity = sum(executed[b] for b in plan["compensations"])
    totals = dict(
        settled_quantity=gross,
        settled_amount_cents=gross * terms["price_cents"],
        reversed_quantity=reversed_quantity,
        reversed_amount_cents=reversed_quantity * terms["price_cents"],
        net_settled_quantity=gross - reversed_quantity,
        net_settled_amount_cents=(gross - reversed_quantity) * terms["price_cents"],
    )
    if any(type(trade.get(k)) is not int or trade[k] != v for k, v in totals.items()):
        issue("gross-reversed-net-receipts")
    return dict(
        status="failed" if findings else "passed",
        findings=findings,
        expected=totals,
        scope="Scoped execution/compensation legs, checker separation and receipts against external expectations; no counterparty authenticity, global funding or independent-human-review claim",
    )
