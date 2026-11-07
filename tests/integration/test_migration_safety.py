import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from settlementlab.core.validation import DomainError
from settlementlab.infrastructure.store import SQLiteStore


class MigrationSafety(unittest.TestCase):
    def test_failed_initial_upgrade_leaves_no_partial_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "failed.db"
            with patch(
                "settlementlab.infrastructure.schema.initialize",
                side_effect=RuntimeError("injected migration failure"),
            ):
                with self.assertRaises(RuntimeError):
                    SQLiteStore(path)
            with sqlite3.connect(path) as db:
                self.assertEqual(
                    db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), []
                )
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 0)
            SQLiteStore(path)
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 4)

    def test_future_schema_is_not_downgraded_or_modified(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "future.db"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE sentinel(value TEXT)")
                db.execute("INSERT INTO sentinel VALUES ('keep')")
                db.execute("PRAGMA user_version=99")
            with self.assertRaises(DomainError):
                SQLiteStore(path)
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 99)
                self.assertEqual(db.execute("SELECT * FROM sentinel").fetchall(), [("keep",)])
                self.assertEqual(
                    db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(),
                    [("sentinel",)],
                )
