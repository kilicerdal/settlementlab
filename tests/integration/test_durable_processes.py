"""Kill only disposable worker processes at reproducible durability checkpoints."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from settlementlab.assurance.durable_data import CHECKER, approved_trade, entry
from settlementlab.bootstrap import create_application
from settlementlab.configuration import Settings


class DurableProcesses(unittest.TestCase):
    def setup_case(self, root, name):
        database = root / (name + ".db")
        app = create_application(
            Settings(database=str(database), model="", business_date="2026-11-09")
        )
        trade = approved_trade(app.service)
        app.operations.enqueue_batch([entry(trade)], "batch", CHECKER)
        return database, app

    def worker(self, database, *args):
        root = Path(__file__).resolve().parents[2]
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "settlementlab.worker",
                "--db",
                str(database),
                "--business-date",
                "2026-11-09",
                "--worker-id",
                "process-assurance",
                "--once",
                *args,
            ],
            cwd=root,
            env=dict(os.environ, PYTHONPATH=str(root / "src")),
            capture_output=True,
            text=True,
            timeout=15,
        )

    def wait_expiry(self, until):
        # Wait only for the deliberately short persisted lease, not arbitrary workflow progress.
        deadline = time.monotonic() + 5
        while time.time() <= until:
            if time.monotonic() > deadline:
                self.fail("Owned worker lease did not expire")
            time.sleep(0.02)

    def test_processing_crashes_preserve_effect_and_outbox_atomicity(self):
        with tempfile.TemporaryDirectory() as temp:
            for phase in ["after-claim", "before-commit", "after-commit"]:
                with self.subTest(phase=phase):
                    database, app = self.setup_case(Path(temp), phase)
                    before = app.service.snapshot()
                    result = self.worker(
                        database, "--mode", "process", "--lease", "1", "--fault", phase
                    )
                    self.assertEqual(result.returncode, 73, result.stdout + result.stderr)
                    snap = app.operations.snapshot()
                    job = snap["jobs"][0]
                    if phase != "after-commit":
                        self.assertEqual(app.service.snapshot(), before)
                        self.assertEqual(snap["receipts"], 0)
                        self.assertEqual(snap["outbox"], [])
                        self.wait_expiry(job["lease_until"])
                    else:
                        self.assertEqual(snap["receipts"], 1)
                        self.assertEqual(len(snap["outbox"]), 1)
                        self.assertEqual(job["status"], "SUCCEEDED")
                    resumed = self.worker(database, "--mode", "both", "--lease", "30")
                    self.assertEqual(resumed.returncode, 0, resumed.stderr)
                    final = app.operations.snapshot()
                    self.assertEqual(final["jobs"][0]["status"], "SUCCEEDED")
                    self.assertEqual(final["receipts"], 1)
                    self.assertEqual(final["inbox_count"], 1)
                    self.assertEqual(len(final["outbox"]), 1)
                    self.assertEqual(final["outbox"][0]["status"], "DELIVERED")
                    treasury = app.service.snapshot()["treasury"]
                    self.assertEqual(treasury["controls"]["status"], "BALANCED")
                    self.assertEqual(
                        len(
                            app.service.reconcile(
                                [
                                    dict(
                                        trade_id=app.service.snapshot()["trades"][0]["id"],
                                        quantity=100,
                                        amount_cents=427500,
                                    )
                                ]
                            )["breaks"]
                        ),
                        0,
                    )

    def test_consumer_commit_before_ack_is_redelivered_once(self):
        with tempfile.TemporaryDirectory() as temp:
            for phase in ["after-delivery-claim", "before-observer-commit", "after-consume"]:
                with self.subTest(phase=phase):
                    database, app = self.setup_case(Path(temp), phase)
                    app.operations.process_one("financial")
                    financial_before = app.service.snapshot()
                    crashed = self.worker(
                        database, "--mode", "deliver", "--lease", "1", "--fault", phase
                    )
                    self.assertEqual(crashed.returncode, 73, crashed.stdout + crashed.stderr)
                    snap = app.operations.snapshot()
                    self.assertEqual(snap["inbox_count"], 1 if phase == "after-consume" else 0)
                    self.wait_expiry(snap["outbox"][0]["lease_until"])
                    resumed = self.worker(database, "--mode", "deliver")
                    self.assertEqual(resumed.returncode, 0, resumed.stderr)
                    final = app.operations.snapshot()
                    self.assertEqual(final["inbox_count"], 1)
                    self.assertEqual(len(final["observer"]), 1)
                    self.assertEqual(final["outbox"][0]["status"], "DELIVERED")
                    if phase == "after-consume":
                        self.assertFalse(json.loads(resumed.stdout)["delivered"]["applied"])
                    self.assertEqual(app.service.snapshot(), financial_before)
                    duplicate = self.worker(database, "--redeliver", final["outbox"][0]["event_id"])
                    self.assertEqual(duplicate.returncode, 0, duplicate.stderr)
                    self.assertFalse(json.loads(duplicate.stdout)["applied"])
                    self.assertEqual(app.service.snapshot(), financial_before)
