"""SQLite queue leases, receipts, ordered outbox and idempotent local observer."""

import json
from uuid import uuid4

from ..core.durable import LeaseLost
from ..core.validation import DomainError


class OperationsRepository:
    def ops_timeline(self, job, kind, actor, now, detail):
        self.db.execute(
            "INSERT INTO ops_timeline(job_id,generation,kind,actor,at,detail) VALUES(?,?,?,?,?,?)",
            (job["id"], job["generation"], kind, actor, now, detail),
        )

    def ops_batch(self, key):
        row = self.db.execute("SELECT * FROM ops_batches WHERE request_key=?", (key,)).fetchone()
        return dict(row) if row else None

    def ops_insert_batch(self, batch):
        self.db.execute(
            "INSERT INTO ops_batches VALUES(?,?,?,?,?,?)",
            (
                batch["id"],
                batch["key"],
                batch["fingerprint"],
                json.dumps(batch["jobs"]),
                batch["now"],
                batch["actor"],
            ),
        )

    def ops_insert_job(self, job):
        if self.db.execute(
            "SELECT 1 FROM ops_jobs WHERE trade_id=? AND status IN ('READY','RUNNING','RETRY_WAIT')",
            (job["trade_id"],),
        ).fetchone():
            raise DomainError("Trade already has active durable work", 409)
        self.db.execute(
            "INSERT INTO ops_jobs(id,batch_id,trade_id,expected_version,status,max_attempts,available_at,requested_by,clock_policy,created_at,updated_at) VALUES(?,?,?,?,'READY',?,?,?,?,?,?)",
            (
                job["id"],
                job["batch_id"],
                job["trade_id"],
                job["expected_version"],
                job["max_attempts"],
                job["now"],
                job["actor"],
                job["clock_policy"],
                job["now"],
                job["now"],
            ),
        )
        self.db.execute(
            "UPDATE ops_jobs SET requested_quantity=? WHERE id=?",
            (job.get("requested_quantity"), job["id"]),
        )
        result = self.ops_job(job["id"])
        self.ops_timeline(
            result,
            "QUEUED",
            job["actor"],
            job["now"],
            "Settlement command accepted; no value moved",
        )
        return result

    def ops_job(self, identifier):
        row = self.db.execute("SELECT * FROM ops_jobs WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise DomainError("Operation not found", 404)
        return dict(row)

    def ops_claim_job(self, worker, now, lease):
        rows = self.db.execute(
            "SELECT * FROM ops_jobs WHERE status='RUNNING' AND lease_until<=?", (now,)
        ).fetchall()
        for row in rows:
            job = dict(row)
            self.db.execute(
                "UPDATE ops_attempts SET status='EXPIRED',finished_at=?,detail='Lease expired' WHERE token=? AND status='CLAIMED'",
                (now, job["lease_token"]),
            )
            status = "DEAD_LETTER" if job["attempts"] >= job["max_attempts"] else "RETRY_WAIT"
            self.db.execute(
                "UPDATE ops_jobs SET status=?,error=?,available_at=?,updated_at=?,lease_token=NULL,lease_until=NULL WHERE id=?",
                (status, "Worker lease expired", now, now, job["id"]),
            )
            self.ops_timeline(
                job, "LEASE_EXPIRED", worker, now, "Abandoned attempt fenced; " + status
            )
        row = self.db.execute(
            "SELECT * FROM ops_jobs WHERE status IN ('READY','RETRY_WAIT') AND available_at<=? AND attempts<max_attempts ORDER BY created_at,id LIMIT 1",
            (now,),
        ).fetchone()
        if not row:
            return None
        job = dict(row)
        token = uuid4().hex
        self.db.execute(
            "UPDATE ops_jobs SET status='RUNNING',attempts=attempts+1,lease_until=?,lease_token=?,worker_id=?,updated_at=? WHERE id=?",
            (now + lease, token, worker, now, job["id"]),
        )
        self.db.execute(
            "INSERT INTO ops_attempts(job_id,generation,number,token,worker_id,started_at,status) VALUES(?,?,?,?,?,?,'CLAIMED')",
            (job["id"], job["generation"], job["attempts"] + 1, token, worker, now),
        )
        job = self.ops_job(job["id"])
        self.ops_timeline(job, "CLAIMED", worker, now, "Attempt " + str(job["attempts"]))
        return job

    def ops_owned_job(self, identifier, token, now):
        job = self.ops_job(identifier)
        if job["status"] != "RUNNING" or job["lease_token"] != token or job["lease_until"] <= now:
            raise LeaseLost()
        return job

    def ops_receipt(self, job):
        row = self.db.execute(
            "SELECT result FROM ops_receipts WHERE job_id=? AND generation=?",
            (job["id"], job["generation"]),
        ).fetchone()
        return json.loads(row["result"]) if row else None

    def ops_complete(self, job, result, now, actor):
        status = (
            "SUCCEEDED" if result["state"] in ("SETTLED", "PARTIALLY_SETTLED") else "DEAD_LETTER"
        )
        error = (
            None if status == "SUCCEEDED" else result.get("reason") or "Settlement did not complete"
        )
        self.db.execute(
            "INSERT INTO ops_receipts VALUES(?,?,?,?)",
            (job["id"], job["generation"], json.dumps(result), now),
        )
        self.db.execute(
            "UPDATE ops_jobs SET status=?,error=?,updated_at=?,lease_token=NULL,lease_until=NULL WHERE id=?",
            (status, error, now, job["id"]),
        )
        self.db.execute(
            "UPDATE ops_attempts SET status=?,finished_at=?,detail=? WHERE token=?",
            (status, now, error, job["lease_token"]),
        )
        event = "SettlementSucceeded" if status == "SUCCEEDED" else "SettlementAttemptFailed"
        payload = dict(
            trade_id=result["id"],
            state=result["state"],
            version=result["version"],
            journal=result.get("settlement_journal"),
        )
        self.db.execute(
            "INSERT INTO ops_outbox(event_id,job_id,generation,trade_id,event_type,payload,created_at,available_at) VALUES(?,?,?,?,?,?,?,?)",
            (
                "E-" + uuid4().hex,
                job["id"],
                job["generation"],
                job["trade_id"],
                event,
                json.dumps(payload),
                now,
                now,
            ),
        )
        self.ops_timeline(
            job, status, actor, now, event + " committed with processing receipt and outbox"
        )
        return self.ops_job(job["id"])

    def ops_fail(self, identifier, token, now, transient, detail):
        job = self.ops_job(identifier)
        if job["status"] != "RUNNING" or job["lease_token"] != token:
            return job
        status = (
            "RETRY_WAIT" if transient and job["attempts"] < job["max_attempts"] else "DEAD_LETTER"
        )
        delay = min(60, 2 ** (job["attempts"] - 1)) if status == "RETRY_WAIT" else 0
        self.db.execute(
            "UPDATE ops_jobs SET status=?,error=?,available_at=?,updated_at=?,lease_until=NULL,lease_token=NULL WHERE id=?",
            (status, detail, now + delay, now, identifier),
        )
        self.db.execute(
            "UPDATE ops_attempts SET status=?,finished_at=?,detail=? WHERE token=?",
            (status, now, detail, token),
        )
        self.ops_timeline(job, status, job["worker_id"], now, detail)
        return self.ops_job(identifier)

    def ops_requeue(self, identifier, version, actor, reason, now, clock_policy):
        job = self.ops_job(identifier)
        if job["status"] != "DEAD_LETTER":
            raise DomainError("Only dead-letter work can be requeued", 409)
        if self.db.execute(
            "SELECT 1 FROM ops_jobs WHERE trade_id=? AND id!=? AND status IN ('READY','RUNNING','RETRY_WAIT')",
            (job["trade_id"], identifier),
        ).fetchone():
            raise DomainError("Trade has another active job", 409)
        self.ops_timeline(job, "REQUEUE_REQUESTED", actor, now, reason)
        self.db.execute(
            "UPDATE ops_jobs SET generation=generation+1,expected_version=?,clock_policy=?,status='READY',attempts=0,available_at=?,lease_token=NULL,lease_until=NULL,worker_id=NULL,error=NULL,updated_at=? WHERE id=?",
            (version, clock_policy, now, now, identifier),
        )
        current = self.ops_job(identifier)
        self.ops_timeline(current, "REQUEUED", actor, now, "Explicit operator review; " + reason)
        return current

    def ops_claim_event(self, worker, now, lease):
        rows = self.db.execute(
            "SELECT * FROM ops_outbox WHERE status='LEASED' AND lease_until<=?", (now,)
        ).fetchall()
        for row in rows:
            status = "BLOCKED" if row["attempts"] >= 5 else "PENDING"
            self.db.execute(
                "UPDATE ops_outbox SET status=?,lease_until=NULL,lease_token=NULL,error=? WHERE event_id=?",
                (status, "Delivery lease expired", row["event_id"]),
            )
            self.ops_timeline(
                dict(id=row["job_id"], generation=row["generation"]),
                "DELIVERY_LEASE_EXPIRED",
                "system",
                now,
                row["event_id"] + " / " + status,
            )
        row = self.db.execute(
            """SELECT e.* FROM ops_outbox e WHERE e.status='PENDING' AND e.available_at<=? AND e.attempts<5
            AND NOT EXISTS(SELECT 1 FROM ops_outbox older WHERE older.trade_id=e.trade_id AND older.seq<e.seq AND older.status!='DELIVERED')
            ORDER BY e.seq LIMIT 1""",
            (now,),
        ).fetchone()
        if not row:
            return None
        token = uuid4().hex
        self.db.execute(
            "UPDATE ops_outbox SET status='LEASED',attempts=attempts+1,lease_until=?,lease_token=?,worker_id=? WHERE event_id=?",
            (now + lease, token, worker, row["event_id"]),
        )
        claimed = dict(
            self.db.execute(
                "SELECT * FROM ops_outbox WHERE event_id=?", (row["event_id"],)
            ).fetchone()
        )
        self.ops_timeline(
            dict(id=claimed["job_id"], generation=claimed["generation"]),
            "EVENT_CLAIMED",
            worker,
            now,
            claimed["event_id"] + " / attempt " + str(claimed["attempts"]),
        )
        return claimed

    def ops_event(self, identifier):
        row = self.db.execute("SELECT * FROM ops_outbox WHERE event_id=?", (identifier,)).fetchone()
        if not row:
            raise DomainError("Event not found", 404)
        return dict(row)

    def ops_owned_event(self, identifier, token, now):
        event = self.ops_event(identifier)
        if (
            event["status"] != "LEASED"
            or event["lease_token"] != token
            or event["lease_until"] <= now
        ):
            raise LeaseLost()
        return event

    def ops_consume(self, event, now):
        if self.db.execute(
            "SELECT 1 FROM ops_inbox WHERE event_id=?", (event["event_id"],)
        ).fetchone():
            self.ops_timeline(
                dict(id=event["job_id"], generation=event["generation"]),
                "DUPLICATE_IGNORED",
                event["worker_id"] or "redelivery",
                now,
                event["event_id"],
            )
            return False
        payload = json.loads(event["payload"])
        if payload.get("trade_id") != event["trade_id"] or payload.get("state") not in (
            "SETTLED",
            "PARTIALLY_SETTLED",
            "FAILED",
        ):
            raise DomainError("Invalid outbox envelope", 409)
        self.db.execute("INSERT INTO ops_inbox VALUES(?,?)", (event["event_id"], now))
        self.db.execute(
            """INSERT INTO ops_projection VALUES(?,?,?,?,?,?,?) ON CONFLICT(trade_id) DO UPDATE SET
            last_seq=excluded.last_seq,event_id=excluded.event_id,job_id=excluded.job_id,generation=excluded.generation,state=excluded.state,updated_at=excluded.updated_at
            WHERE excluded.last_seq>ops_projection.last_seq""",
            (
                event["trade_id"],
                event["seq"],
                event["event_id"],
                event["job_id"],
                event["generation"],
                payload["state"],
                now,
            ),
        )
        job = self.ops_job(event["job_id"])
        self.ops_timeline(
            dict(job, generation=event["generation"]),
            "OBSERVER_APPLIED",
            event["worker_id"] or "redelivery",
            now,
            event["event_id"],
        )
        return True

    def ops_ack_event(self, event, now):
        self.db.execute(
            "UPDATE ops_outbox SET status='DELIVERED',lease_token=NULL,lease_until=NULL,error=NULL WHERE event_id=?",
            (event["event_id"],),
        )
        job = self.ops_job(event["job_id"])
        self.ops_timeline(
            dict(job, generation=event["generation"]),
            "DELIVERED",
            event["worker_id"],
            now,
            event["event_id"],
        )

    def ops_fail_event(self, event, now):
        current = self.ops_event(event["event_id"])
        if current["lease_token"] != event["lease_token"] or current["status"] != "LEASED":
            return "FENCED"
        status = "BLOCKED" if current["attempts"] >= 5 else "PENDING"
        self.db.execute(
            "UPDATE ops_outbox SET status=?,available_at=?,lease_token=NULL,lease_until=NULL,error=? WHERE event_id=?",
            (
                status,
                now + min(60, 2 ** (current["attempts"] - 1)),
                "Observer delivery failed",
                event["event_id"],
            ),
        )
        self.ops_timeline(
            dict(id=event["job_id"], generation=event["generation"]),
            "DELIVERY_" + status,
            current["worker_id"],
            now,
            event["event_id"] + " / observer delivery failed",
        )
        return status

    def ops_retry_event(self, identifier, now, actor, reason):
        event = self.ops_event(identifier)
        if event["status"] != "BLOCKED":
            raise DomainError("Only blocked deliveries can be retried", 409)
        self.db.execute(
            "UPDATE ops_outbox SET status='PENDING',attempts=0,available_at=?,error=NULL WHERE event_id=?",
            (now, identifier),
        )
        self.ops_timeline(
            dict(id=event["job_id"], generation=event["generation"]),
            "DELIVERY_RETRY",
            actor,
            now,
            reason,
        )
        return self.ops_event(identifier)

    def ops_snapshot(self, now):
        jobs = [
            dict(row)
            for row in self.db.execute(
                "SELECT * FROM ops_jobs ORDER BY created_at DESC,id DESC LIMIT 200"
            )
        ]
        # Exact totals cover the entire database; displayed history is bounded separately.
        totals = {
            row["status"]: row["n"]
            for row in self.db.execute("SELECT status,COUNT(*) n FROM ops_jobs GROUP BY status")
        }
        oldest = self.db.execute(
            "SELECT MIN(created_at) FROM ops_jobs WHERE status IN ('READY','RUNNING','RETRY_WAIT')"
        ).fetchone()[0]
        events = [
            dict(row)
            for row in self.db.execute("SELECT * FROM ops_outbox ORDER BY seq DESC LIMIT 200")
        ]
        for row in [*jobs, *events]:
            row.pop("lease_token", None)
        return dict(
            jobs=jobs,
            totals=totals,
            oldest_pending_age=max(0, now - oldest) if oldest is not None else 0,
            outbox=events,
            outbox_totals={
                row["status"]: row["n"]
                for row in self.db.execute(
                    "SELECT status,COUNT(*) n FROM ops_outbox GROUP BY status"
                )
            },
            attempts=[
                dict(row)
                for row in self.db.execute(
                    "SELECT job_id,generation,number,worker_id,started_at,finished_at,status,detail FROM ops_attempts ORDER BY id DESC LIMIT 400"
                )
            ],
            timeline=[
                dict(row)
                for row in self.db.execute("SELECT * FROM ops_timeline ORDER BY seq DESC LIMIT 500")
            ],
            observer=[
                dict(row)
                for row in self.db.execute(
                    "SELECT * FROM ops_projection ORDER BY last_seq DESC LIMIT 200"
                )
            ],
            receipts=self.db.execute("SELECT COUNT(*) FROM ops_receipts").fetchone()[0],
            inbox_count=self.db.execute("SELECT COUNT(*) FROM ops_inbox").fetchone()[0],
            history_limits=dict(jobs=200, outbox=200, attempts=400, timeline=500, observer=200),
        )
