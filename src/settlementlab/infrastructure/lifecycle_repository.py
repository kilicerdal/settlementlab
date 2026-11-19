"""SQL adapter for immutable lifecycle evidence, partial posting and break cases."""

import json
from datetime import datetime, timezone
from uuid import uuid4

from . import journal


class LifecycleRepository:
    def lifecycle_replay(self, trade, action, key):
        row = self.db.execute(
            "SELECT * FROM lifecycle_commands WHERE trade_id=? AND action=? AND request_key=?",
            (trade, action, key),
        ).fetchone()
        return dict(row) if row else None

    def lifecycle_record(self, trade, action, key, digest, response):
        self.db.execute(
            "INSERT INTO lifecycle_commands VALUES(?,?,?,?,?)",
            (trade, action, key, digest, json.dumps(response)),
        )

    def lifecycle_revisions(self, trade):
        return [
            dict(r)
            for r in self.db.execute(
                "SELECT * FROM trade_revisions WHERE trade_id=? ORDER BY revision", (trade,)
            )
        ]

    def lifecycle_revision(self, trade, actor, reason):
        terms = {
            k: trade[k]
            for k in (
                "symbol",
                "side",
                "currency",
                "quantity",
                "price_cents",
                "trade_date",
                "settlement_date",
                "buyer_id",
                "seller_id",
                "cutoff_utc",
            )
        }
        self.db.execute(
            "INSERT OR IGNORE INTO trade_revisions VALUES(?,?,?,?,?,?)",
            (
                trade["id"],
                trade["lifecycle_revision"],
                json.dumps(terms),
                actor,
                reason,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    def current_manager(self, trade):
        row = self.db.execute(
            """SELECT m.payload FROM manager_submissions m JOIN manager_trade_revisions r
             ON r.trade_id=m.trade_id AND r.manager_revision=m.revision
             WHERE m.trade_id=? AND r.revision=? ORDER BY m.revision DESC LIMIT 1""",
            (trade["id"], trade["lifecycle_revision"]),
        ).fetchone()
        return json.loads(row["payload"]) if row else None

    def current_authorized(self, trade):
        return bool(
            self.db.execute(
                """SELECT 1 FROM approval_requests a JOIN approval_revisions r ON r.approval_id=a.id
            WHERE a.trade_id=? AND a.status='APPROVED' AND r.revision=? AND a.maker_id<>a.decided_by""",
                (trade["id"], trade["lifecycle_revision"]),
            ).fetchone()
        )

    def pin_cutoff(self, trade_id, cutoff):
        self.db.execute("UPDATE trades SET cutoff_utc=? WHERE id=?", (cutoff, trade_id))

    def lifecycle_amend(self, trade, terms):
        self.db.execute(
            """UPDATE trades SET symbol=?,side=?,currency=?,quantity=?,price_cents=?,trade_date=?,settlement_date=?,
            buyer_id=?,seller_id=?,state='RECEIVED',reason=NULL,instruction=NULL,allocations='[]',matching_result='{}',
            lifecycle_revision=lifecycle_revision+1,version=version+1 WHERE id=?""",
            tuple(
                terms[k]
                for k in (
                    "symbol",
                    "side",
                    "currency",
                    "quantity",
                    "price_cents",
                    "trade_date",
                    "settlement_date",
                    "buyer_id",
                    "seller_id",
                )
            )
            + (trade["id"],),
        )

    def lifecycle_cancel(self, trade, reason):
        self.db.execute(
            "UPDATE trades SET state='CANCELLED',reason=?,version=version+1 WHERE id=?",
            (reason, trade["id"]),
        )

    def lifecycle_fence(self, trade, reason, actor):
        now = datetime.now(timezone.utc).timestamp()
        jobs = [
            dict(r)
            for r in self.db.execute(
                "SELECT * FROM ops_jobs WHERE trade_id=? AND status IN ('READY','RUNNING','RETRY_WAIT')",
                (trade["id"],),
            )
        ]
        for job in jobs:
            self.db.execute(
                "UPDATE ops_attempts SET status='INVALIDATED',finished_at=?,detail=? WHERE token=? AND finished_at IS NULL",
                (now, reason, job["lease_token"]),
            )
            self.db.execute(
                "UPDATE ops_jobs SET status='DEAD_LETTER',error=?,lease_token=NULL,lease_until=NULL,updated_at=? WHERE id=?",
                (reason, now, job["id"]),
            )
            self.ops_timeline(job, "LIFECYCLE_INVALIDATED", actor, now, reason)
        for pending in self.db.execute(
            "SELECT id FROM approval_requests WHERE trade_id=? AND status='PENDING'", (trade["id"],)
        ).fetchall():
            self.cancel_approval((datetime.now(timezone.utc).isoformat(), reason, pending["id"]))

    def lifecycle_progress(self, trade_id):
        row = self.db.execute(
            "SELECT quantity,amount_cents FROM settlements WHERE trade_id=?", (trade_id,)
        ).fetchone()
        return dict(row) if row else dict(quantity=0, amount_cents=0)

    def lifecycle_slices(self, trade_id):
        return [
            dict(r)
            for r in self.db.execute(
                "SELECT * FROM settlement_slices WHERE trade_id=? ORDER BY created_at,id",
                (trade_id,),
            )
        ]

    def lifecycle_post_slice(self, trade, quantity, key, actor):
        amount = quantity * trade["price_cents"]
        buyer, seller = trade["buyer_id"], trade["seller_id"]
        unit = "SEC:" + trade["symbol"]
        if self.balance(buyer, "CASH:USD") < amount or self.balance(seller, unit) < quantity:
            return None
        batch = journal.post(
            self.db,
            "slice:" + trade["id"] + ":" + key,
            "DVP_PARTIAL",
            [
                (buyer, "CASH:USD", -amount),
                (seller, "CASH:USD", amount),
                (seller, unit, -quantity),
                (buyer, unit, quantity),
            ],
            actor,
        )
        self.db.execute(
            "INSERT INTO settlement_slices VALUES(?,?,?,?,?,?,?, ?,?)",
            (
                "S-" + uuid4().hex,
                trade["id"],
                key,
                trade["lifecycle_revision"],
                quantity,
                trade["price_cents"],
                batch,
                actor,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.db.execute(
            """INSERT INTO settlements VALUES(?,?,?) ON CONFLICT(trade_id) DO UPDATE SET
            quantity=quantity+excluded.quantity,amount_cents=amount_cents+excluded.amount_cents""",
            (trade["id"], quantity, amount),
        )
        filled = self.lifecycle_progress(trade["id"])["quantity"]
        self.db.execute(
            "UPDATE trades SET state=?,reason=NULL,version=version+1 WHERE id=?",
            ("SETTLED" if filled == trade["quantity"] else "PARTIALLY_SETTLED", trade["id"]),
        )
        return batch

    def recon_statement(self, key, by_id=False):
        row = self.db.execute(
            "SELECT * FROM recon_statements WHERE " + ("id" if by_id else "request_key") + "=?",
            (key,),
        ).fetchone()
        return dict(row) if row else None

    def recon_save(self, statement, cases):
        self.db.execute(
            "INSERT INTO recon_statements VALUES(?,?,?,?,?,?,?)",
            tuple(
                statement[k]
                for k in (
                    "id",
                    "key",
                    "fingerprint",
                    "rows",
                    "internal_snapshot",
                    "actor",
                    "created_at",
                )
            ),
        )
        for case in cases:
            self.db.execute(
                "INSERT INTO recon_cases(id,statement_id,trade_id,kind,expected,observed) VALUES(?,?,?,?,?,?)",
                (
                    "B-" + uuid4().hex,
                    statement["id"],
                    case["trade_id"],
                    case["kind"],
                    json.dumps(case.get("expected")),
                    json.dumps(case.get("observed")),
                ),
            )

    def recon_cases(self, statement=None):
        return [
            dict(r)
            for r in self.db.execute(
                "SELECT * FROM recon_cases"
                + (" WHERE statement_id=?" if statement else "")
                + " ORDER BY id",
                (statement,) if statement else (),
            )
        ]

    def recon_case(self, identifier):
        row = self.db.execute("SELECT * FROM recon_cases WHERE id=?", (identifier,)).fetchone()
        return dict(row) if row else None

    def recon_resolve(self, identifier, actor, reason, evidence, snapshot):
        self.db.execute(
            "UPDATE recon_cases SET status='RESOLVED',resolved_by=?,resolved_at=?,reason=?,evidence_statement_id=?,resolution_snapshot=? WHERE id=?",
            (
                actor,
                datetime.now(timezone.utc).isoformat(),
                reason,
                evidence,
                json.dumps(snapshot),
                identifier,
            ),
        )
