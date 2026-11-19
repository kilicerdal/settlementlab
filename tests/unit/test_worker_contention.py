"""Worker CLI distinguishes transient writer contention from a completed command."""

import io
import sqlite3
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch

from settlementlab.worker import main


class WorkerContention(unittest.TestCase):
    def test_once_reports_retryable_busy_without_claiming_completion(self):
        operations = Mock()
        operations.process_one.side_effect = sqlite3.OperationalError("database is locked")
        output = io.StringIO()
        with (
            patch(
                "settlementlab.worker.create_application",
                return_value=SimpleNamespace(operations=operations),
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(main(["--db", "unused.db", "--once"]), 75)
        self.assertIn("STORAGE_BUSY", output.getvalue())
        operations.deliver_one.assert_not_called()

    def test_noncontention_storage_error_is_not_suppressed(self):
        operations = Mock()
        operations.process_one.side_effect = sqlite3.OperationalError("no such table: ops_jobs")
        with (
            patch(
                "settlementlab.worker.create_application",
                return_value=SimpleNamespace(operations=operations),
            ),
            self.assertRaises(sqlite3.OperationalError),
        ):
            main(["--db", "unused.db", "--once"])
