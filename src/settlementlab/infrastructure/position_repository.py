"""Atomic financial-position publication, fenced delivery and monotonic projection."""

import json
import time
from uuid import uuid4

from ..core.durable import LeaseLost
from ..core.validation import DomainError


class PositionRepository:
    def position_truth(self, trade_id):
        row = self.db.execute(
            """SELECT t.id,t.version,s.quantity,s.amount_cents,
            COALESCE(r.quantity,0) reversed_quantity,COALESCE(r.amount_cents,0) reversed_amount_cents
            FROM trades t JOIN settlements s ON s.trade_id=t.id LEFT JOIN
            (SELECT trade_id,SUM(quantity) quantity,SUM(amount_cents) amount_cents FROM reversal_requests WHERE trade_id=? AND status='APPROVED' GROUP BY trade_id) r ON r.trade_id=t.id WHERE t.id=?""",
            (trade_id, trade_id),
        ).fetchone()
        if not row:
            raise DomainError("No posted financial position for this trade", 404)
        return dict(
            trade_id=trade_id,
            source_version=row["version"],
            basis="NET_AFTER_APPROVED_COMPENSATIONS",
            gross_quantity=row["quantity"],
            gross_amount_cents=row["amount_cents"],
            reversed_quantity=row["reversed_quantity"],
            reversed_amount_cents=row["reversed_amount_cents"],
            net_quantity=row["quantity"] - row["reversed_quantity"],
            net_amount_cents=row["amount_cents"] - row["reversed_amount_cents"],
        )

    def position_emit(self, trade_id, kind, journal_id):
        payload = self.position_truth(trade_id)
        event = "P-" + uuid4().hex
        self.db.execute(
            """INSERT INTO position_outbox(event_id,trade_id,source_version,event_type,payload,journal_id,created_at) VALUES(?,?,?,?,?,?,?)""",
            (
                event,
                trade_id,
                payload["source_version"],
                kind,
                json.dumps(payload),
                journal_id,
                time.time(),
            ),
        )
        return event

    def position_claim(self, worker, now, lease):
        self.db.execute(
            "UPDATE position_outbox SET status=CASE WHEN attempts>=8 THEN 'BLOCKED' ELSE 'PENDING' END,lease_token=NULL,lease_until=NULL,error='Delivery lease expired' WHERE status='LEASED' AND lease_until<=?",
            (now,),
        )
        row = self.db.execute(
            "SELECT * FROM position_outbox WHERE status='PENDING' AND attempts<8 ORDER BY seq LIMIT 1"
        ).fetchone()
        if not row:
            return None
        token = uuid4().hex
        self.db.execute(
            "UPDATE position_outbox SET status='LEASED',attempts=attempts+1,lease_token=?,lease_until=?,worker_id=? WHERE event_id=?",
            (token, now + lease, worker, row["event_id"]),
        )
        return self.position_owned(row["event_id"], token, now)

    def position_owned(self, event_id, token, now):
        row = self.db.execute(
            "SELECT * FROM position_outbox WHERE event_id=?", (event_id,)
        ).fetchone()
        if (
            not row
            or row["status"] != "LEASED"
            or row["lease_token"] != token
            or row["lease_until"] <= now
        ):
            raise LeaseLost()
        return dict(row)

    def position_consume(self, event, now):
        if self.db.execute(
            "SELECT 1 FROM position_inbox WHERE event_id=?", (event["event_id"],)
        ).fetchone():
            return False
        if event["event_type"] not in ("PositionBaseline", "ExecutionPosted", "CompensationPosted"):
            raise DomainError("Unknown financial position event", 409)
        try:
            data = json.loads(event["payload"])
        except (ValueError, TypeError) as error:
            raise DomainError("Invalid financial-position JSON", 409) from error
        if (
            not isinstance(data, dict)
            or type(data.get("source_version")) is not int
            or data["source_version"] < 1
        ):
            raise DomainError("Invalid financial-position identity", 409)
        values = (
            "gross_quantity",
            "gross_amount_cents",
            "reversed_quantity",
            "reversed_amount_cents",
            "net_quantity",
            "net_amount_cents",
        )
        if (
            data.get("trade_id") != event["trade_id"]
            or data.get("source_version") != event["source_version"]
            or data.get("basis") != "NET_AFTER_APPROVED_COMPENSATIONS"
            or any(type(data.get(k)) is not int or not 0 <= data[k] <= 10**15 for k in values)
            or data["net_quantity"] != data["gross_quantity"] - data["reversed_quantity"]
            or data["net_amount_cents"]
            != data["gross_amount_cents"] - data["reversed_amount_cents"]
        ):
            raise DomainError("Invalid financial-position envelope", 409)
        self.db.execute("INSERT INTO position_inbox VALUES(?,?)", (event["event_id"], now))
        cursor = self.db.execute(
            """INSERT INTO position_projection VALUES(?,?,?,?,?,?) ON CONFLICT(trade_id) DO UPDATE SET
            source_version=excluded.source_version,event_seq=excluded.event_seq,event_id=excluded.event_id,payload=excluded.payload,updated_at=excluded.updated_at
            WHERE excluded.source_version>position_projection.source_version OR (excluded.source_version=position_projection.source_version AND excluded.event_seq>position_projection.event_seq)""",
            (
                event["trade_id"],
                event["source_version"],
                event["seq"],
                event["event_id"],
                event["payload"],
                now,
            ),
        )
        return cursor.rowcount == 1

    def position_ack(self, event, now):
        self.position_owned(event["event_id"], event["lease_token"], now)
        self.db.execute(
            "UPDATE position_outbox SET status='DELIVERED',lease_token=NULL,lease_until=NULL,error=NULL WHERE event_id=?",
            (event["event_id"],),
        )

    def position_fail(self, event, now, error):
        try:
            current = self.position_owned(event["event_id"], event["lease_token"], now)
        except LeaseLost:
            return "FENCED"
        status = (
            "BLOCKED" if current["attempts"] >= 8 or isinstance(error, DomainError) else "PENDING"
        )
        self.db.execute(
            "UPDATE position_outbox SET status=?,error=?,lease_token=NULL,lease_until=NULL WHERE event_id=?",
            (status, type(error).__name__, event["event_id"]),
        )
        return status

    def position_view(self, trade_id):
        truth = self.position_truth(trade_id)
        row = self.db.execute(
            "SELECT * FROM position_projection WHERE trade_id=?", (trade_id,)
        ).fetchone()
        events = [
            {k: v for k, v in dict(r).items() if k != "lease_token"}
            for r in self.db.execute(
                "SELECT * FROM position_outbox WHERE trade_id=? ORDER BY seq LIMIT 5001",
                (trade_id,),
            )
        ]
        if len(events) > 5000:
            raise DomainError("Position history exceeds investigation bound", 413)
        observed = json.loads(row["payload"]) if row else None
        pending = sum(e["status"] != "DELIVERED" for e in events)
        synchronized = bool(
            observed
            and all(
                observed[k] == truth[k]
                for k in (
                    "gross_quantity",
                    "gross_amount_cents",
                    "reversed_quantity",
                    "reversed_amount_cents",
                    "net_quantity",
                    "net_amount_cents",
                )
            )
            and not pending
        )
        return dict(
            authoritative=truth,
            observed=observed,
            status="CURRENT" if synchronized else "LAGGING",
            pending_events=pending,
            event_history=events,
            scope="Observed financial position is eventually consistent; historical settlement delivery remains separate. Source version identifies its financial event, not every workflow change.",
        )
