"""Local SQLite online backup with exclusive destination and integrity verification."""

import argparse
import hashlib
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from .sqlite_snapshot import readonly_connection


def backup(source, destination):
    source, destination = Path(source).resolve(), Path(destination).absolute()
    if not source.is_file() or source == destination.resolve():
        raise ValueError("Source must be an existing database; destination must differ")
    if any(Path(str(destination) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError("Destination has existing SQLite sidecars; choose a fresh path")
    # Exclusive create prevents accidental replacement, including symlink targets.
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        with readonly_connection(source) as original:
            with closing(sqlite3.connect(destination)) as copy:
                original.backup(copy)
                copy.commit()
                # A returned backup is a portable single-file image. Do not leave
                # a live destination handle or WAL checkpoint to a later finalizer.
                mode = copy.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
                if mode != "delete":
                    raise ValueError("Backup could not be finalized as a standalone database")
                if copy.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Backup integrity verification failed")
                if copy.execute("PRAGMA foreign_key_check").fetchall():
                    raise ValueError("Backup contains foreign key violations")
                schema = copy.execute("PRAGMA user_version").fetchone()[0]
        # SQLite may leave an unused SHM after WAL -> DELETE conversion on
        # some system builds. All owned handles are closed and the finalized
        # backup has no WAL; only that destination's disposable SHM is removed.
        if Path(str(destination) + "-wal").exists():
            raise ValueError("Finalized backup still has a WAL sidecar")
        Path(str(destination) + "-shm").unlink(missing_ok=True)
        return dict(
            path=str(destination),
            schema_version=schema,
            sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
            integrity="ok",
        )
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--destination", required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(backup(args.source, args.destination)))
        return 0
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(2, "Backup failed: " + str(error) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
