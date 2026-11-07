"""SQLite transaction boundary and migration composition."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .repository import SQLiteRepository
from .schema import migrate


class SQLiteStore:
    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            migrate(db)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connection() as db:
            yield SQLiteRepository(db)
