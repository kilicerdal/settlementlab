"""Durable financial effects, fencing, outbox ordering and review boundaries."""

import concurrent.futures
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from settlementlab.application.operations import DurableOperations
from settlementlab.assurance.durable_data import (
    AUDITOR,
    CHECKER,
    MAKER,
    approved_trade,
    entry,
    fund_trade,
)
from settlementlab.bootstrap import create_application
from settlementlab.configuration import Settings
from settlementlab.core.calendar import FixedClock
from settlementlab.core.durable import bounded_integer, bounded_seconds, identifier
from settlementlab.core.validation import DomainError


class DurableControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_application(
            Settings(
                database=str(Path(self.temp.name) / "operations.db"),
                model="",
                business_date="2026-11-09",
            )
        )
        self.service = self.app.service
        self.clock = [1000.0]
        self.ops = DurableOperations(self.service, now=lambda: self.clock[0])
        self.trade = approved_trade(self.service)

    def queue(self, trade=None, key="batch", attempts=3):
        return self.ops.enqueue_batch([entry(trade or self.trade)], key, CHECKER, attempts)["jobs"][
            0
        ]

    def test_batch_replay_conflicts_and_atomic_acceptance(self):
        before = self.service.snapshot()
        job = self.queue()
        replay = self.ops.enqueue_batch([entry(self.trade)], "batch", CHECKER)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["jobs"][0]["id"], job["id"])
        self.assertEqual(self.service.snapshot(), before)
        with self.assertRaises(DomainError):
            self.ops.enqueue_batch([entry(self.trade)], "batch", CHECKER, 4)
        with self.assertRaises(DomainError):
            self.queue(key="different-key")
        second = approved_trade(self.service, "second")
        with self.assertRaises(DomainError):
            self.ops.enqueue_batch(
                [entry(second), dict(trade_id="unknown", version=1)], "bad-batch", CHECKER
            )
        self.assertEqual(len(self.ops.snapshot()["jobs"]), 1)
        self.assertEqual(len(self.ops.snapshot()["timeline"]), 1)

    def test_posting_receipt_outbox_and_job_commit_together(self):
        job = self.queue()
        done = self.ops.process_one("worker-a")
        self.assertEqual(done["status"], "SUCCEEDED")
        snap = self.ops.snapshot()
        self.assertEqual(snap["receipts"], 1)
        self.assertEqual(len(snap["outbox"]), 1)
        trade = self.service.snapshot()["trades"][0]
        self.assertEqual(trade["state"], "SETTLED")
        self.assertIsNotNone(trade["settlement_journal"])
        before = self.service.snapshot()
        self.assertIsNone(self.ops.process_one("worker-b"))
        self.assertEqual(self.service.snapshot(), before)
        self.assertEqual(snap["jobs"][0]["id"], job["id"])
        self.assertNotIn("lease_token", snap["jobs"][0])

    def test_precommit_fault_rolls_back_all_financial_and_event_writes(self):
        self.queue()
        before = self.service.snapshot()

        def fail(phase):
            if phase == "before-commit":
                raise RuntimeError("injected transient failure")

        result = self.ops.process_one("failing", fault=fail)
        self.assertEqual(result["status"], "RETRY_WAIT")
        self.assertEqual(self.service.snapshot(), before)
        self.assertEqual(self.ops.snapshot()["receipts"], 0)
        self.assertEqual(self.ops.snapshot()["outbox"], [])
        self.assertIsNone(self.ops.process_one("too-early"))
        self.clock[0] += 1
        self.assertEqual(self.ops.process_one("recovered")["status"], "SUCCEEDED")

    def test_stale_worker_token_cannot_apply_after_reclaim(self):
        self.queue()
        abandoned = self.ops.claim("abandoned", lease=1)
        self.clock[0] += 2
        new = self.ops.claim("new-owner", lease=30)
        self.assertNotEqual(abandoned["lease_token"], new["lease_token"])
        before = self.service.snapshot()
        self.assertEqual(self.ops.apply_claim(abandoned)["status"], "FENCED")
        self.assertEqual(self.service.snapshot(), before)
        self.assertEqual(self.ops.apply_claim(new)["status"], "SUCCEEDED")
        self.assertEqual(self.ops.snapshot()["receipts"], 1)
        self.assertIn("EXPIRED", [a["status"] for a in self.ops.snapshot()["attempts"]])

    def test_expiry_and_transient_failure_are_bounded(self):
        self.queue(attempts=2)
        for _ in range(2):
            self.ops.claim("crashing", lease=1)
            self.clock[0] += 2
        self.assertIsNone(self.ops.claim("cleanup"))
        self.assertEqual(self.ops.snapshot()["jobs"][0]["status"], "DEAD_LETTER")
        self.assertEqual(len(self.ops.snapshot()["attempts"]), 2)

    def test_capacity_failure_needs_explicit_review_and_new_generation(self):
        unfunded = approved_trade(self.service, "unfunded", False)
        # First drain the funded trade's capacity so the second really lacks shared funds.
        self.queue()
        self.ops.process_one("first")
        dead = self.queue(unfunded, "unfunded-job")
        dead = self.ops.process_one("underfunded")
        self.assertEqual(dead["status"], "DEAD_LETTER")
        current = next(t for t in self.service.snapshot()["trades"] if t["id"] == unfunded["id"])
        self.assertEqual(current["state"], "FAILED")
        fund_trade(self.service, current, "recovery-fund")
        with self.assertRaises(DomainError):
            self.ops.requeue(dead["id"], unfunded["version"], "Reviewed after funding", CHECKER)
        queued = self.ops.requeue(
            dead["id"], current["version"], "Reviewed after synthetic funding", CHECKER
        )
        self.assertEqual(queued["generation"], 2)
        self.assertEqual(self.ops.process_one("recovery")["status"], "SUCCEEDED")
        self.assertEqual(self.ops.snapshot()["receipts"], 3)
        # Events for one trade must retain failure-before-success order.
        deliveries = []
        while True:
            event = self.ops.deliver_one("observer")
            if not event:
                break
            deliveries.append(event)
        view = next(v for v in self.ops.snapshot()["observer"] if v["trade_id"] == unfunded["id"])
        self.assertEqual(view["state"], "SETTLED")
        self.assertEqual(view["generation"], 2)
        self.assertEqual(len(deliveries), 3)

    def test_duplicate_delivery_does_not_repeat_observer_or_financial_effect(self):
        self.queue()
        self.ops.process_one("financial")
        delivered = self.ops.deliver_one("delivery")
        before = self.service.snapshot()
        projection = self.ops.snapshot()["observer"]
        for _ in range(3):
            self.assertFalse(self.ops.redeliver(delivered["event_id"], CHECKER)["applied"])
        self.assertEqual(self.ops.snapshot()["inbox_count"], 1)
        self.assertEqual(self.ops.snapshot()["observer"], projection)
        self.assertEqual(self.service.snapshot(), before)

    def test_after_consumer_commit_retry_is_deduplicated(self):
        self.queue()
        self.ops.process_one("financial")

        def fail(phase):
            if phase == "after-consume":
                raise RuntimeError("lost acknowledgement")

        self.assertEqual(self.ops.deliver_one("lost-ack", fault=fail)["status"], "RETRY_WAIT")
        projection = self.ops.snapshot()["observer"]
        self.assertEqual(self.ops.snapshot()["inbox_count"], 1)
        self.clock[0] += 1
        replayed = self.ops.deliver_one("recovery")
        self.assertFalse(replayed["applied"])
        self.assertEqual(replayed["status"], "DELIVERED")
        self.assertEqual(self.ops.snapshot()["observer"], projection)

    def test_two_workers_claim_one_job_and_stale_financial_version_is_not_overridden(self):
        self.queue()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda n: self.ops.claim("worker-" + str(n)), range(2)))
        self.assertEqual(sum(r is not None for r in results), 1)
        claimed = next(r for r in results if r)
        self.service.command(
            self.trade["id"], "settle", dict(version=self.trade["version"]), principal=CHECKER
        )
        before = self.service.snapshot()
        self.assertEqual(self.ops.apply_claim(claimed)["status"], "DEAD_LETTER")
        self.assertEqual(self.service.snapshot(), before)
        self.assertEqual(self.ops.snapshot()["outbox"], [])

    def test_calendar_role_and_clock_policy_are_not_bypassed(self):
        for principal in [None, MAKER, AUDITOR]:
            with self.assertRaises(DomainError):
                self.ops.enqueue_batch([entry(self.trade)], "not-authorized", principal)
        job = self.queue()
        self.service.clock = FixedClock("2026-11-06")
        before = self.service.snapshot()
        dead = self.ops.process_one("wrong-clock")
        self.assertEqual(dead["status"], "DEAD_LETTER")
        self.assertIn("business clock", dead["error"])
        self.assertEqual(self.service.snapshot(), before)
        queued = self.ops.requeue(
            job["id"], self.trade["version"], "Reviewed early business-date simulation", CHECKER
        )
        self.assertEqual(queued["generation"], 2)
        dead = self.ops.process_one("too-early")
        self.assertEqual(dead["status"], "DEAD_LETTER")
        self.assertIn("calendar blocked", dead["error"])

    def test_invalid_inputs_and_review_boundaries(self):
        for entries in [
            [],
            [entry(self.trade)] * 2,
            [dict(trade_id=self.trade["id"], version=True)],
            ["invalid"],
        ]:
            with self.assertRaises(DomainError):
                self.ops.enqueue_batch(entries, "invalid", CHECKER)
        for value in [0, True, 11]:
            with self.assertRaises(DomainError):
                self.queue(key="invalid", attempts=value)
        for value in [float("nan"), 0, 301]:
            with self.assertRaises(DomainError):
                self.ops.claim("worker", value)
        job = self.queue()
        with self.assertRaises(DomainError):
            self.ops.requeue(job["id"], self.trade["version"], "Reviewed", CHECKER)
        with self.assertRaises(DomainError):
            self.ops.requeue(job["id"], 1, "bad", CHECKER)
        with self.assertRaises(DomainError):
            self.ops.redeliver("missing", CHECKER)
        with self.assertRaises(DomainError):
            self.ops.retry_event("missing", "Reviewed", CHECKER)
        for function, args in [
            (bounded_integer, (True, 1, 10, "value")),
            (bounded_seconds, (float("inf"), 0.1, 10)),
            (identifier, ("bad\nvalue",)),
        ]:
            with self.assertRaises(DomainError):
                function(*args)

    def test_blocked_delivery_budget_requires_review_and_keeps_receipt(self):
        self.queue()
        self.ops.process_one("financial")
        financial = self.service.snapshot()
        for attempt in range(5):
            with patch(
                "settlementlab.infrastructure.operations_repository.OperationsRepository.ops_consume",
                side_effect=RuntimeError("observer unavailable"),
            ):
                result = self.ops.deliver_one("failing-delivery")
            self.assertEqual(result["status"], "BLOCKED" if attempt == 4 else "RETRY_WAIT")
            self.clock[0] += 64
        snapshot = self.ops.snapshot()
        event = snapshot["outbox"][0]
        self.assertEqual(event["status"], "BLOCKED")
        self.assertEqual(event["attempts"], 5)
        self.assertEqual(snapshot["inbox_count"], 0)
        with self.assertRaises(DomainError):
            self.ops.retry_event(event["event_id"], "Reviewed delivery", AUDITOR)
        with self.assertRaises(DomainError):
            self.ops.retry_event(event["event_id"], "no", CHECKER)
        reset = self.ops.retry_event(event["event_id"], "Reviewed observer recovery", CHECKER)
        self.assertEqual(reset["attempts"], 0)
        self.assertTrue(self.ops.deliver_one("recovered")["applied"])
        self.assertEqual(self.service.snapshot(), financial)
        self.assertIn(
            "DELIVERY_BLOCKED", [event["kind"] for event in self.ops.snapshot()["timeline"]]
        )

    def test_delivery_lease_expiration_and_fencing(self):
        self.queue()
        self.ops.process_one("financial")
        with self.ops.store.transaction() as repo:
            abandoned = repo.ops_claim_event("abandoned", self.clock[0], 1)
        self.clock[0] += 2
        with self.ops.store.transaction() as repo:
            recovered = repo.ops_claim_event("recovered", self.clock[0], 30)
            with self.assertRaises(DomainError):
                repo.ops_owned_event(abandoned["event_id"], abandoned["lease_token"], self.clock[0])
            self.assertTrue(repo.ops_consume(recovered, self.clock[0]))
            repo.ops_ack_event(recovered, self.clock[0])
            self.assertEqual(repo.ops_fail_event(abandoned, self.clock[0]), "FENCED")
        self.assertEqual(self.ops.snapshot()["inbox_count"], 1)
        self.assertIn(
            "DELIVERY_LEASE_EXPIRED", [event["kind"] for event in self.ops.snapshot()["timeline"]]
        )

    def test_migration_failure_does_not_advance_version_or_leave_partial_tables(self):
        import sqlite3

        from settlementlab.infrastructure.store import SQLiteStore

        database = self.app.settings.database
        with sqlite3.connect(database) as db:
            db.execute("PRAGMA user_version=4")

        def fail(db):
            db.execute("CREATE TABLE partial_upgrade_marker(value TEXT)")
            raise RuntimeError("migration failure")

        with patch("settlementlab.infrastructure.schema.initialize_operations", fail):
            with self.assertRaises(RuntimeError):
                SQLiteStore(database)
        with sqlite3.connect(database) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 4)
            self.assertIsNone(
                db.execute(
                    "SELECT name FROM sqlite_master WHERE name='partial_upgrade_marker'"
                ).fetchone()
            )
        SQLiteStore(database)
        with sqlite3.connect(database) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 6)
