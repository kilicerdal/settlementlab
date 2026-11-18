import random
import sqlite3
import tempfile
import unittest
from pathlib import Path

from settlementlab.application.operations import DurableOperations
from settlementlab.assurance.campaign import (
    application,
    benchmark,
    business_day,
    contention_probe,
    planned_trade,
)
from settlementlab.assurance.durable_data import CHECKER, entry
from settlementlab.assurance.oracle import audit
from settlementlab.infrastructure.backup import backup, main


class BackupRecovery(unittest.TestCase):
    def test_online_backup_preserves_pending_lease_then_recovers_in_new_application(self):
        with tempfile.TemporaryDirectory() as d:
            source, target = Path(d) / "source.db", Path(d) / "restored.db"
            app = application(source)
            trade, expected = planned_trade(app, "restore", random.Random(41))
            ops = DurableOperations(app.service, now=lambda: 1000)
            ops.enqueue_batch([entry(trade)], "batch", CHECKER)
            abandoned = ops.claim("lost", lease=1)
            with sqlite3.connect(source) as writer:
                writer.execute("BEGIN IMMEDIATE")
                writer.execute("UPDATE trades SET reason='uncommitted-change'")
                result = backup(source, target)
                writer.rollback()
            with sqlite3.connect(target) as restored_db:
                self.assertNotEqual(
                    restored_db.execute("SELECT reason FROM trades").fetchone()[0],
                    "uncommitted-change",
                )
            self.assertEqual(result["schema_version"], 5)
            restored = application(target)
            recovered = DurableOperations(restored.service, now=lambda: 1002)
            self.assertEqual(recovered.apply_claim(abandoned)["status"], "FENCED")
            self.assertEqual(recovered.process_one("new-process")["status"], "SUCCEEDED")
            self.assertEqual(audit(target, {trade["id"]: expected})["status"], "passed")
            self.assertEqual(audit(source, {})["status"], "passed")
            self.assertEqual(
                main(["--source", str(target), "--destination", str(Path(d) / "second.db")]), 0
            )

    def test_exclusive_destination_invalid_source_and_corruption(self):
        with tempfile.TemporaryDirectory() as d:
            source, target = Path(d) / "source.db", Path(d) / "backup.db"
            application(source)
            target.write_text("keep")
            for first, second in [
                (source, target),
                (source, source),
                (Path(d) / "missing", target),
            ]:
                with self.assertRaises((ValueError, FileExistsError)):
                    backup(first, second)
            self.assertEqual(target.read_text(), "keep")
            link = Path(d) / "link.db"
            link.symlink_to(target)
            with self.assertRaises(FileExistsError):
                backup(source, link)
            bad = Path(d) / "bad.db"
            bad.write_text("not sqlite")
            with self.assertRaises(sqlite3.DatabaseError):
                backup(bad, Path(d) / "failed.db")
            self.assertFalse((Path(d) / "failed.db").exists())

    def test_populated_v4_schema_migrates_without_losing_finance(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "legacy.db"
            app = application(db)
            trade, expected = planned_trade(app, "legacy", random.Random(41))
            app.operations.enqueue_batch([entry(trade)], "batch", CHECKER)
            app.operations.process_one("worker")
            with sqlite3.connect(db) as connection:
                # Historical schema 4: financial tables populated, durable tables absent.
                for name in [
                    "ops_projection",
                    "ops_inbox",
                    "ops_outbox",
                    "ops_timeline",
                    "ops_receipts",
                    "ops_attempts",
                    "ops_jobs",
                    "ops_batches",
                ]:
                    connection.execute("DROP TABLE " + name)
                connection.execute("PRAGMA user_version=4")
            backup(db, Path(d) / "before-upgrade.db")
            upgraded = application(db)
            self.assertEqual(audit(db, {trade["id"]: expected})["status"], "passed")
            self.assertEqual(upgraded.operations.snapshot()["receipts"], 0)

    def test_small_campaign_and_parallel_benchmark(self):
        with tempfile.TemporaryDirectory() as d:
            day = business_day(d, count=8)
            self.assertEqual(day["exact_totals"]["trades"], 8)
            self.assertEqual(day["shortages"], 2)
            self.assertEqual(contention_probe(d)["status"], "passed")
            load = benchmark(d, count=8, workers=2)
            self.assertEqual(load["performance"]["completed"], 8)
            self.assertEqual(load["financial_oracle"]["status"], "passed")
        with self.assertRaises(ValueError):
            business_day(".", count=1)
