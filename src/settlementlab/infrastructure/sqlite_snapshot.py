"""Read-only SQLite handles with cold-WAL sidecar initialization when required."""

import sqlite3
from contextlib import ExitStack, closing, contextmanager
from pathlib import Path


def _open_readonly(uri):
    db = sqlite3.connect(uri + "?mode=ro", uri=True, timeout=10)
    try:
        db.execute("PRAGMA query_only=ON")
        # Force opening the WAL before returning: connect() alone can succeed.
        db.execute("PRAGMA schema_version").fetchone()
        return db
    except BaseException:
        db.close()
        raise


@contextmanager
def readonly_connection(path):
    uri = Path(path).resolve().as_uri()
    with ExitStack() as stack:
        try:
            db = _open_readonly(uri)
        except sqlite3.OperationalError as error:
            if str(error) != "unable to open database file":
                raise
            # Some system SQLite builds cannot create cold WAL sidecars through
            # a mode=ro handle. A query-only mode=rw handle initializes them.
            # mode=rw cannot create a missing database; no DML or writer BEGIN
            # is issued. Hold it until the actual read-only consumer is closed.
            warm = stack.enter_context(
                closing(sqlite3.connect(uri + "?mode=rw", uri=True, timeout=10))
            )
            warm.execute("PRAGMA query_only=ON")
            if warm.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
                raise error
            warm.execute("PRAGMA schema_version").fetchone()
            db = _open_readonly(uri)
        stack.enter_context(closing(db))
        yield db
