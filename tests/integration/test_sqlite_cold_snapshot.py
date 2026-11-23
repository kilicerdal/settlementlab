"""Cold WAL reads retain physical read-only enforcement and live snapshot semantics."""

import concurrent.futures
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from settlementlab.infrastructure import sqlite_snapshot
from settlementlab.infrastructure.backup import backup
from settlementlab.infrastructure.sqlite_snapshot import readonly_connection


class ColdSnapshotControls(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "cold # query?.db"
        db = sqlite3.connect(self.path)
        try:
            db.execute("CREATE TABLE sample(value INTEGER)")
            db.execute("INSERT INTO sample VALUES (1)")
            db.commit()
            self.assertEqual(db.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
        finally:
            db.close()
        # Closing the final SQLite writer, not deleting active sidecars, makes
        # a genuine cold database. This reproduces the system SQLite failure.
        self.assertFalse(Path(str(self.path) + "-wal").exists())
        self.assertFalse(Path(str(self.path) + "-shm").exists())

    def test_cold_reader_is_physically_readonly_even_without_query_only(self):
        with readonly_connection(self.path) as db:
            self.assertEqual(db.execute("SELECT value FROM sample").fetchone()[0], 1)
            db.execute("PRAGMA query_only=OFF")
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("UPDATE sample SET value=99")
        with readonly_connection(self.path) as db:
            self.assertEqual(db.execute("SELECT value FROM sample").fetchone()[0], 1)

    def test_cold_snapshot_does_not_block_writer_or_hide_later_commit(self):
        def write():
            db = sqlite3.connect(self.path, timeout=1)
            try:
                db.execute("UPDATE sample SET value=2")
                db.commit()
            finally:
                db.close()

        with readonly_connection(self.path) as db:
            db.execute("BEGIN")
            self.assertEqual(db.execute("SELECT value FROM sample").fetchone()[0], 1)
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(write).result(timeout=3)
            self.assertEqual(db.execute("SELECT value FROM sample").fetchone()[0], 1)
            db.rollback()
        with readonly_connection(self.path) as db:
            self.assertEqual(db.execute("SELECT value FROM sample").fetchone()[0], 2)

    def test_sidecar_initialization_retry_on_runtimes_without_the_cold_wal_failure(self):
        original = sqlite_snapshot._open_readonly
        calls = []

        def cold_once(uri):
            calls.append(uri)
            if len(calls) == 1:
                raise sqlite3.OperationalError("unable to open database file")
            return original(uri)

        with patch.object(sqlite_snapshot, "_open_readonly", side_effect=cold_once):
            with readonly_connection(self.path) as db:
                self.assertEqual(db.execute("SELECT value FROM sample").fetchone()[0], 1)
                db.execute("PRAGMA query_only=OFF")
                with self.assertRaises(sqlite3.OperationalError):
                    db.execute("DELETE FROM sample")
        self.assertEqual(len(calls), 2)

    def test_missing_source_is_not_created(self):
        missing = self.path.parent / "missing.db"
        with self.assertRaises(sqlite3.OperationalError), readonly_connection(missing):
            self.fail("A missing source must not open")
        self.assertFalse(missing.exists())

    def test_online_backup_of_cold_wal_is_standalone_and_preserves_content(self):
        destination = self.path.parent / "backup.db"
        result = backup(self.path, destination)
        self.assertEqual(result["integrity"], "ok")
        self.assertFalse(Path(str(destination) + "-wal").exists())
        self.assertFalse(Path(str(destination) + "-shm").exists())
        db = sqlite3.connect(destination)
        try:
            self.assertEqual(db.execute("SELECT value FROM sample").fetchone()[0], 1)
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "delete")
        finally:
            db.close()
