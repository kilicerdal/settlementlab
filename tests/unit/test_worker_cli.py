import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from settlementlab import worker
from settlementlab.assurance.durable_data import CHECKER, approved_trade, entry
from settlementlab.bootstrap import create_application
from settlementlab.configuration import Settings


class WorkerCLI(unittest.TestCase):
    def test_once_process_delivery_and_idle_loop(self):
        with tempfile.TemporaryDirectory() as temp:
            database = str(Path(temp) / "worker.db")
            app = create_application(
                Settings(database=database, model="", business_date="2026-11-09")
            )
            trade = approved_trade(app.service)
            app.operations.enqueue_batch([entry(trade)], "batch", CHECKER)
            args = ["--db", database, "--business-date", "2026-11-09"]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(worker.main([*args, "--once", "--mode", "process"]), 0)
                self.assertEqual(worker.main([*args, "--once", "--mode", "deliver"]), 0)
                event = app.operations.snapshot()["outbox"][0]["event_id"]
                self.assertEqual(worker.main([*args, "--once", "--redeliver", event]), 0)
                self.assertEqual(worker.main([*args, "--once"]), 0)
                with patch("settlementlab.worker.time.sleep", side_effect=KeyboardInterrupt):
                    self.assertEqual(worker.main(args), 0)
            for invalid in [
                ["--fault", "after-claim"],
                ["--once", "--mode", "deliver", "--fault", "after-commit"],
                ["--once", "--mode", "process", "--fault", "after-consume"],
                ["--redeliver", event],
            ]:
                with (
                    self.subTest(invalid=invalid),
                    contextlib.redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit),
                ):
                    worker.main([*args, *invalid])
