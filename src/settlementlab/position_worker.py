"""Deliver financial-position events separately from historical settlement receipts."""

import argparse
import json
import sqlite3
import time

from .bootstrap import create_application
from .configuration import Settings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--worker-id", default="position-observer")
    args = parser.parse_args(argv)
    app = create_application(Settings(database=args.db, model=""))
    try:
        while True:
            try:
                result = app.positions.deliver_one(args.worker_id)
            except sqlite3.OperationalError as error:
                if "locked" not in str(error).lower() and "busy" not in str(error).lower():
                    raise
                print(json.dumps(dict(status="STORAGE_BUSY", retryable=True)), flush=True)
                if args.once:
                    return 75
                time.sleep(0.25)
                continue
            if result or args.once:
                print(json.dumps(result), flush=True)
            if args.once:
                return 0
            if not result or result.get("status") == "PENDING":
                time.sleep(0.25)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
