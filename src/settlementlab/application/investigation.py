"""One consistent, read-only investigation graph built through repository ports."""

from datetime import datetime, timezone

from ..core.durable import identifier
from ..core.validation import DomainError


def instant(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc).isoformat()
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def timeline(trade, records):
    nodes = []
    edges = []
    root = "trade:" + trade["id"]

    def add(key, kind, at, title, details, parent=root):
        nodes.append(dict(id=key, kind=kind, at=instant(at), title=title, details=details))
        if parent and key != parent:
            edges.append(dict(source=parent, target=key, relation="evidence"))
        return key

    first = records["audit"][0]["timestamp"] if records["audit"] else "1970-01-01T00:00:00+00:00"
    add(
        root,
        "trade",
        first,
        trade["id"] + " / " + trade["symbol"],
        dict(state=trade["state"], version=trade["version"], revision=trade["lifecycle_revision"]),
        None,
    )
    for r in records["revisions"]:
        add(
            "revision:" + str(r["revision"]),
            "revision",
            r["created_at"],
            "Accepted terms revision " + str(r["revision"]),
            r,
        )
    for r in records["managers"]:
        add(
            "manager:" + str(r["id"]),
            "matching",
            r["timestamp"],
            "Manager submission " + str(r["revision"]),
            r,
        )
    for r in records["approvals"]:
        key = add(
            "approval:" + r["id"],
            "approval",
            r["created_at"],
            "Approval requested",
            r,
            "revision:" + str(r["lifecycle_revision"]),
        )
        if r["decided_at"]:
            add(
                key + ":decision",
                "approval",
                r["decided_at"],
                "Approval " + r["status"],
                dict(status=r["status"], checker=r["decided_by"]),
                key,
            )
    for r in records["jobs"]:
        add(
            "job:" + r["id"],
            "job",
            r["created_at"],
            "Accepted durable work",
            r,
        )
    for r in records["operations"]:
        add("operation:" + str(r["seq"]), "worker", r["at"], r["kind"], r, "job:" + r["job_id"])
    for r in records["attempts"]:
        key = add(
            "attempt:" + str(r["id"]),
            "attempt",
            r["started_at"],
            "Worker attempt " + str(r["number"]),
            {k: v for k, v in r.items() if k != "token"},
            "job:" + r["job_id"],
        )
        if r["finished_at"]:
            add(
                key + ":finished",
                "attempt",
                r["finished_at"],
                r["status"],
                dict(status=r["status"], detail=r["detail"]),
                key,
            )
    for r in records["receipts"]:
        add(
            "receipt:" + r["job_id"] + ":" + str(r["generation"]),
            "receipt",
            r["created_at"],
            "Committed processing receipt",
            r,
            "job:" + r["job_id"],
        )
    for r in records["batches"]:
        add("journal:" + r["id"], "journal", r["timestamp"], r["kind"], r)
    for r in records["outbox"]:
        add(
            "event:" + r["event_id"],
            "outbox",
            r["created_at"],
            r["event_type"],
            {k: v for k, v in r.items() if k != "lease_token"},
            "job:" + r["job_id"],
        )
    for r in records["reversals"]:
        key = add(
            "correction:" + r["id"],
            "correction",
            r["created_at"],
            "Reversal requested",
            r,
            "journal:" + r["original_batch"],
        )
        if r["decided_at"]:
            decision = add(
                key + ":decision",
                "correction",
                r["decided_at"],
                "Reversal " + r["status"],
                dict(checker=r["checker_id"], reason=r["decision_reason"]),
                key,
            )
            if r["compensation_batch"]:
                edges.append(
                    dict(
                        source=decision,
                        target="journal:" + r["compensation_batch"],
                        relation="compensates",
                    )
                )
    for r in records["statements"]:
        add("statement:" + r["id"], "statement", r["created_at"], "Imported statement", r)
    statement_times = {r["id"]: r["created_at"] for r in records["statements"]}
    for r in records["cases"]:
        key = add(
            "case:" + r["id"],
            "case",
            statement_times[r["statement_id"]],
            r["kind"],
            r,
            "statement:" + r["statement_id"],
        )
        if r["resolved_at"]:
            decision = add(
                key + ":resolved",
                "case",
                r["resolved_at"],
                "Case resolved",
                dict(reason=r["reason"], actor=r["resolved_by"]),
                key,
            )
            edges.append(
                dict(
                    source="statement:" + r["evidence_statement_id"],
                    target=decision,
                    relation="resolution-evidence",
                )
            )
    for r in records["audit"]:
        add("audit:" + str(r["seq"]), "audit", r["timestamp"], r["action"], r)
    if len(nodes) > 5000:
        raise DomainError("Investigation exceeds 5,000 events; export a smaller local dataset", 413)
    ids = {n["id"] for n in nodes}
    if len(ids) != len(nodes) or any(
        e["source"] not in ids or e["target"] not in ids for e in edges
    ):
        raise DomainError("Investigation evidence contains broken correlations", 409)
    return sorted(nodes, key=lambda n: (n["at"], n["id"])), edges


class Investigation:
    def __init__(self, service):
        self.service = service

    def snapshot(self, trade_id):
        identifier(trade_id)
        with self.service.store.transaction() as repository:
            trade = self.service.get(repository, trade_id)
            records = repository.investigation_records(trade_id)
            # Lease capabilities are not investigation evidence. Strip them before
            # either graph construction or portable export, without mutating storage.
            for record in records["jobs"] + records["outbox"]:
                record.pop("lease_token", None)
            for record in records["attempts"]:
                record.pop("token", None)
            nodes, edges = timeline(trade, records)
            return dict(
                version=1,
                trade=trade,
                records=records,
                timeline=nodes,
                correlations=edges,
                business_time=self.service.clock.describe(),
                generated_at=datetime.now(timezone.utc).isoformat(),
                financial_controls=repository.treasury_snapshot()["controls"],
                scope="Single transaction; actual evidence timestamps are separate from simulated business time. Gross receipts stay immutable; corrections produce compensating entries.",
            )
