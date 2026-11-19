"""Durable settlement orchestration over the same transaction/repository ports."""

import json
import time
from uuid import uuid4

from ..core.durable import LeaseLost, bounded_integer, bounded_seconds, fingerprint, identifier
from ..core.identity import Principal, require
from ..core.validation import DomainError


def no_fault(phase):
    pass


class DurableOperations:
    def __init__(self, settlement, now=time.time):
        self.settlement = settlement
        self.store = settlement.store
        self.now = now

    def eligible(self, repository, trade_id, version):
        bounded_integer(version, 1, 10**9, "Expected trade version")
        trade = self.settlement.get(repository, identifier(trade_id))
        if trade["settlement_model"] != "shared-ledger" or trade["state"] not in (
            "AFFIRMED",
            "FAILED",
            "PARTIALLY_SETTLED",
        ):
            raise DomainError("Durable settlement requires an approved shared-ledger trade", 409)
        if trade["version"] != version:
            raise DomainError("Stale expected trade version", 409)
        return trade

    def enqueue_batch(self, entries, key, principal, max_attempts=3):
        require(principal, "checker")
        identifier(key)
        bounded_integer(max_attempts, 1, 10, "Maximum attempts")
        if not isinstance(entries, list) or not 1 <= len(entries) <= 50:
            raise DomainError("Batch must contain 1–50 approved trade/version entries")
        normalized = []
        seen = set()
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) not in (
                {"trade_id", "version"},
                {"trade_id", "version", "quantity"},
            ):
                raise DomainError("Invalid batch entry")
            trade_id = identifier(entry["trade_id"])
            bounded_integer(entry["version"], 1, 10**9, "Expected trade version")
            if trade_id in seen:
                raise DomainError("Duplicate trade in batch")
            seen.add(trade_id)
            normalized.append(dict(trade_id=trade_id, version=entry["version"]))
            if "quantity" in entry:
                bounded_integer(entry["quantity"], 1, 10**9, "Execution quantity")
                normalized[-1]["quantity"] = entry["quantity"]
        digest = fingerprint(
            dict(entries=normalized, actor=principal.id, max_attempts=max_attempts)
        )
        with self.store.transaction() as repository:
            old = repository.ops_batch(key)
            if old:
                if old["fingerprint"] != digest:
                    raise DomainError("Batch request key conflicts", 409)
                return dict(
                    id=old["id"],
                    replayed=True,
                    jobs=[repository.ops_job(i) for i in json.loads(old["jobs"])],
                )
            for entry in normalized:
                trade = self.eligible(repository, entry["trade_id"], entry["version"])
                if "quantity" in entry:
                    bounded_integer(
                        entry["quantity"], 1, trade["remaining_quantity"], "Execution quantity"
                    )
            batch_id = "B-" + uuid4().hex
            job_ids = ["J-" + uuid4().hex for _ in normalized]
            now = self.now()
            repository.ops_insert_batch(
                dict(
                    id=batch_id,
                    key=key,
                    fingerprint=digest,
                    jobs=job_ids,
                    now=now,
                    actor=principal.id,
                )
            )
            jobs = []
            for entry, job_id in zip(normalized, job_ids):
                jobs.append(
                    repository.ops_insert_job(
                        dict(
                            id=job_id,
                            batch_id=batch_id,
                            trade_id=entry["trade_id"],
                            expected_version=entry["version"],
                            requested_quantity=entry.get("quantity"),
                            max_attempts=max_attempts,
                            now=now,
                            actor=principal.id,
                            clock_policy=json.dumps(self.settlement.clock.describe()),
                        )
                    )
                )
            return dict(id=batch_id, replayed=False, jobs=jobs)

    def claim(self, worker, lease=30):
        identifier(worker, 80)
        bounded_seconds(lease, 0.1, 300)
        with self.store.transaction() as repository:
            return repository.ops_claim_job(worker, self.now(), lease)

    def apply_claim(self, job, fault=no_fault):
        try:
            with self.store.transaction() as repository:
                current = repository.ops_owned_job(job["id"], job["lease_token"], self.now())
                accepted_clock = json.loads(current["clock_policy"])
                worker_clock = self.settlement.clock.describe()
                if accepted_clock.get("mode") != worker_clock["mode"] or (
                    accepted_clock.get("mode") == "simulated"
                    and accepted_clock.get("date") != worker_clock["date"]
                ):
                    raise DomainError(
                        "Worker business clock differs from accepted job; operator review required",
                        409,
                    )
                if repository.ops_receipt(current):
                    raise DomainError(
                        "Inconsistent running job already has a receipt; operator review required",
                        409,
                    )
                if accepted_clock.get("mode") == "simulated" and accepted_clock.get(
                    "timestamp"
                ) != worker_clock.get("timestamp"):
                    raise DomainError("Worker timestamp differs from accepted job", 409)
                command = dict(version=current["expected_version"])
                action = "settle"
                if current.get("requested_quantity") is not None:
                    action = "settle-partial"
                    command.update(
                        quantity=current["requested_quantity"],
                        request_key=current["id"] + "-" + str(current["generation"]),
                    )
                result = self.settlement.command_in_transaction(
                    repository,
                    current["trade_id"],
                    action,
                    command,
                    principal=Principal(current["requested_by"], "checker"),
                )
                repository.ops_owned_job(current["id"], current["lease_token"], self.now())
                completed = repository.ops_complete(
                    current, result, self.now(), current["worker_id"]
                )
                fault("before-commit")
            fault("after-commit")
            return completed
        except LeaseLost:
            return dict(id=job["id"], status="FENCED")
        except Exception as error:
            transient = not isinstance(error, DomainError)
            detail = (
                "Transient worker failure: " + type(error).__name__ if transient else str(error)
            )
            with self.store.transaction() as repository:
                return repository.ops_fail(
                    job["id"], job["lease_token"], self.now(), transient, detail
                )

    def process_one(self, worker, lease=30, fault=no_fault):
        job = self.claim(worker, lease)
        if not job:
            return None
        fault("after-claim")
        return self.apply_claim(job, fault)

    def deliver_one(self, worker, lease=30, fault=no_fault):
        identifier(worker, 80)
        bounded_seconds(lease, 0.1, 300)
        with self.store.transaction() as repository:
            event = repository.ops_claim_event(worker, self.now(), lease)
        if not event:
            return None
        fault("after-delivery-claim")
        try:
            with self.store.transaction() as repository:
                current = repository.ops_owned_event(
                    event["event_id"], event["lease_token"], self.now()
                )
                applied = repository.ops_consume(current, self.now())
                fault("before-observer-commit")
            # Deliberate at-least-once gap: observer receipt commits before publisher acknowledgement.
            fault("after-consume")
            with self.store.transaction() as repository:
                current = repository.ops_owned_event(
                    event["event_id"], event["lease_token"], self.now()
                )
                repository.ops_ack_event(current, self.now())
            return dict(event_id=event["event_id"], applied=applied, status="DELIVERED")
        except LeaseLost:
            return dict(event_id=event["event_id"], status="FENCED")
        except Exception:
            with self.store.transaction() as repository:
                status = repository.ops_fail_event(event, self.now())
            return dict(
                event_id=event["event_id"], status="RETRY_WAIT" if status == "PENDING" else status
            )

    def requeue(self, job_id, version, reason, principal):
        require(principal, "checker")
        identifier(job_id)
        identifier(reason, 300)
        if len(reason.strip()) < 5:
            raise DomainError("Provide a review reason of 5–300 characters")
        with self.store.transaction() as repository:
            job = repository.ops_job(job_id)
            self.eligible(repository, job["trade_id"], version)
            return repository.ops_requeue(
                job_id,
                version,
                principal.id,
                reason,
                self.now(),
                json.dumps(self.settlement.clock.describe()),
            )

    def retry_event(self, event_id, reason, principal):
        require(principal, "checker")
        identifier(event_id)
        identifier(reason, 300)
        if len(reason.strip()) < 5:
            raise DomainError("Provide a review reason of 5–300 characters")
        with self.store.transaction() as repository:
            return repository.ops_retry_event(event_id, self.now(), principal.id, reason)

    def redeliver(self, event_id, principal):
        require(principal, "checker")
        with self.store.transaction() as repository:
            event = repository.ops_event(identifier(event_id))
            if event["status"] != "DELIVERED":
                raise DomainError("Only delivered events can be deliberately redelivered", 409)
            return dict(event_id=event_id, applied=repository.ops_consume(event, self.now()))

    def snapshot(self):
        with self.store.transaction() as repository:
            now = self.now()
            snapshot = repository.ops_snapshot(now)
            snapshot.update(
                now=now,
                business_time=self.settlement.clock.describe(),
                financial_audit=repository.list_audit(),
            )
            snapshot["history_limits"]["financial_audit"] = 100
            return snapshot
