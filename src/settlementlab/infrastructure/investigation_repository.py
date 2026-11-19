"""Correction accounting and complete trade-scoped investigation queries."""

import json
from datetime import datetime, timezone

from ..core.validation import DomainError
from . import journal


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class InvestigationRepository:
    def recon_executions(self):
        return [
            dict(r)
            for r in self.db.execute(
                """SELECT s.trade_id,s.quantity-COALESCE(r.quantity,0) AS quantity,s.amount_cents-COALESCE(r.amount_cents,0) AS amount_cents FROM settlements s LEFT JOIN (SELECT trade_id,SUM(quantity) AS quantity,SUM(amount_cents) AS amount_cents FROM reversal_requests WHERE status='APPROVED' GROUP BY trade_id) r ON r.trade_id=s.trade_id"""
            )
        ]

    def reversal_requests(self, trade_id):
        return [
            dict(r)
            for r in self.db.execute(
                "SELECT * FROM reversal_requests WHERE trade_id=? ORDER BY created_at,id",
                (trade_id,),
            )
        ]

    def reversal_find(self, request_id):
        row = self.db.execute(
            "SELECT * FROM reversal_requests WHERE id=?", (request_id,)
        ).fetchone()
        return dict(row) if row else None

    def reversal_original(self, trade, batch_id):
        batch = self.db.execute("SELECT * FROM journal_batches WHERE id=?", (batch_id,)).fetchone()
        slice_row = self.db.execute(
            "SELECT * FROM settlement_slices WHERE trade_id=? AND batch_id=?",
            (trade["id"], batch_id),
        ).fetchone()
        if not batch or not (
            (batch["kind"] == "DVP_SETTLEMENT" and batch["trade_id"] == trade["id"])
            or (batch["kind"] == "DVP_PARTIAL" and slice_row)
        ):
            raise DomainError("Choose an original execution batch belonging to this trade", 409)
        quantity = slice_row["quantity"] if slice_row else trade["quantity"]
        amount = quantity * trade["price_cents"]
        lines = [
            tuple(r)
            for r in self.db.execute(
                "SELECT participant_id,asset,delta FROM journal_lines WHERE batch_id=? ORDER BY line",
                (batch_id,),
            )
        ]
        expected = [
            (trade["buyer_id"], "CASH:USD", -amount),
            (trade["seller_id"], "CASH:USD", amount),
            (trade["seller_id"], "SEC:" + trade["symbol"], -quantity),
            (trade["buyer_id"], "SEC:" + trade["symbol"], quantity),
        ]
        if sorted(lines) != sorted(expected):
            raise DomainError(
                "Original posting does not match retained terms; investigate integrity", 409
            )
        return dict(quantity=quantity, amount_cents=amount, lines=lines)

    def reversal_insert(self, request, trade):
        self.db.execute(
            """INSERT INTO reversal_requests(id,trade_id,original_batch,request_key,fingerprint,maker_id,reason,created_at,original_state,quantity,amount_cents)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            tuple(
                request[k]
                for k in (
                    "id",
                    "trade_id",
                    "original_batch",
                    "request_key",
                    "fingerprint",
                    "maker_id",
                    "reason",
                    "created_at",
                    "original_state",
                    "quantity",
                    "amount_cents",
                )
            ),
        )
        self.db.execute(
            "UPDATE trades SET state='CORRECTION_PENDING',reason=?,version=version+1 WHERE id=?",
            (request["reason"], trade["id"]),
        )

    def reversal_decide(self, request, trade, decision, actor, reason, digest, original):
        decided_at = utc_now()
        batch = None
        state = request["original_state"]
        if decision == "approve-reversal":
            batch = journal.post(
                self.db,
                "reversal:" + request["id"],
                "DVP_REVERSAL",
                [(party, asset, -delta) for party, asset, delta in original["lines"]],
                actor,
            )
            self.db.execute(
                "UPDATE reversal_requests SET compensation_batch=? WHERE id=?",
                (batch, request["id"]),
            )
            reversed_quantity = (
                sum(
                    r["quantity"]
                    for r in self.reversal_requests(trade["id"])
                    if r["status"] == "APPROVED"
                )
                + request["quantity"]
            )
            state = (
                "REVERSED"
                if reversed_quantity == self.lifecycle_progress(trade["id"])["quantity"]
                else "CORRECTION_REVIEW"
            )
        self.db.execute(
            """UPDATE reversal_requests SET status=?,checker_id=?,decision_reason=?,decided_at=?,decision_fingerprint=? WHERE id=?""",
            ("APPROVED" if batch else "REJECTED", actor, reason, decided_at, digest, request["id"]),
        )
        self.db.execute(
            "UPDATE trades SET state=?,reason=?,version=version+1 WHERE id=?",
            (state, reason, trade["id"]),
        )
        return self.reversal_find(request["id"])

    def investigation_records(self, trade_id):
        def rows(sql, values=(trade_id,)):
            return [dict(r) for r in self.db.execute(sql, values)]

        batches = rows(
            """SELECT * FROM journal_batches WHERE trade_id=? OR id IN (SELECT batch_id FROM settlement_slices WHERE trade_id=?) OR id IN (SELECT compensation_batch FROM reversal_requests WHERE trade_id=?) ORDER BY timestamp,id""",
            (trade_id, trade_id, trade_id),
        )
        for batch in batches:
            batch["lines"] = rows(
                "SELECT * FROM journal_lines WHERE batch_id=? ORDER BY line", (batch["id"],)
            )
        cases = rows("SELECT * FROM recon_cases WHERE trade_id=? ORDER BY id")
        statement_ids = {c["statement_id"] for c in cases} | {
            c["evidence_statement_id"] for c in cases if c["evidence_statement_id"]
        }
        # Include matching full statements even when they produced no discrepancy.
        statements = []
        for row in self.db.execute("SELECT * FROM recon_statements ORDER BY created_at,id"):
            data = dict(row)
            if data["id"] in statement_ids or any(
                r["trade_id"] == trade_id for r in json.loads(data["rows"])
            ):
                statements.append(data)
        return dict(
            audit=rows("SELECT * FROM audit WHERE trade_id=? ORDER BY seq"),
            jobs=rows("SELECT * FROM ops_jobs WHERE trade_id=? ORDER BY created_at,id"),
            attempts=rows(
                "SELECT a.* FROM ops_attempts a JOIN ops_jobs j ON j.id=a.job_id WHERE j.trade_id=? ORDER BY a.id"
            ),
            receipts=rows(
                "SELECT r.* FROM ops_receipts r JOIN ops_jobs j ON j.id=r.job_id WHERE j.trade_id=? ORDER BY r.created_at"
            ),
            outbox=rows("SELECT * FROM ops_outbox WHERE trade_id=? ORDER BY seq"),
            operations=rows(
                "SELECT t.* FROM ops_timeline t JOIN ops_jobs j ON j.id=t.job_id WHERE j.trade_id=? ORDER BY t.seq"
            ),
            approvals=rows(
                "SELECT a.*,r.revision AS lifecycle_revision FROM approval_requests a JOIN approval_revisions r ON r.approval_id=a.id WHERE a.trade_id=? ORDER BY a.created_at"
            ),
            managers=rows("SELECT * FROM manager_submissions WHERE trade_id=? ORDER BY revision"),
            revisions=self.lifecycle_revisions(trade_id),
            batches=batches,
            reversals=self.reversal_requests(trade_id),
            statements=statements,
            cases=cases,
        )
