"""Position worker command response and clean continuous shutdown."""

import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch

from settlementlab.position_worker import main


class PositionWorkerCLI(unittest.TestCase):
    def test_once_reports_delivery_without_starting_financial_work(self):
        positions = Mock()
        positions.deliver_one.return_value = dict(status="DELIVERED", applied=True)
        output = io.StringIO()
        with (
            patch(
                "settlementlab.position_worker.create_application",
                return_value=SimpleNamespace(positions=positions),
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(main(["--db", "fixture.db", "--once"]), 0)
        self.assertIn("DELIVERED", output.getvalue())
        positions.deliver_one.assert_called_once_with("position-observer")

    def test_continuous_worker_shuts_down_after_idle_interrupt(self):
        positions = Mock()
        positions.deliver_one.return_value = None
        with (
            patch(
                "settlementlab.position_worker.create_application",
                return_value=SimpleNamespace(positions=positions),
            ),
            patch("settlementlab.position_worker.time.sleep", side_effect=KeyboardInterrupt),
        ):
            self.assertEqual(main(["--db", "fixture.db"]), 0)

    def test_once_reports_retryable_storage_contention(self):
        import sqlite3

        positions = Mock()
        positions.deliver_one.side_effect = sqlite3.OperationalError("database is locked")
        output = io.StringIO()
        with (
            patch(
                "settlementlab.position_worker.create_application",
                return_value=SimpleNamespace(positions=positions),
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(main(["--db", "fixture.db", "--once"]), 75)
        self.assertIn("STORAGE_BUSY", output.getvalue())
