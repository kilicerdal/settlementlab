"""Local multi-process worker; CLI fault checkpoints affect only this worker process."""

import argparse
import json
import os
import time
from uuid import uuid4

from .bootstrap import create_application
from .configuration import Settings
from .core.identity import Principal

PHASES = (
    "after-claim",
    "before-commit",
    "after-commit",
    "after-delivery-claim",
    "before-observer-commit",
    "after-consume",
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument(
        "--business-date", help="Explicit simulated date, otherwise actual UTC date"
    )
    parser.add_argument("--worker-id", default="worker-" + uuid4().hex[:12])
    parser.add_argument("--lease", type=float, default=30)
    parser.add_argument("--mode", choices=["process", "deliver", "both"], default="both")
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--fault",
        choices=PHASES,
        help="Exit 73 at a named checkpoint; explicit local assurance only",
    )
    parser.add_argument(
        "--redeliver", help="Deliberately redeliver an already delivered synthetic event"
    )
    args = parser.parse_args(argv)
    if args.fault and not args.once:
        parser.error("--fault requires --once")
    if args.fault in PHASES[:3] and args.mode == "deliver":
        parser.error("Processing fault requires process or both mode")
    if args.fault in PHASES[3:] and args.mode == "process":
        parser.error("Delivery fault requires deliver or both mode")
    if args.redeliver and (args.fault or not args.once):
        parser.error("--redeliver requires --once without --fault")
    from .core.durable import bounded_seconds, identifier

    bounded_seconds(args.lease, 0.1, 300)
    identifier(args.worker_id, 80)
    app = create_application(
        Settings(database=args.db, model="", business_date=args.business_date or "")
    )
    operations = app.operations
    if args.redeliver:
        print(
            json.dumps(operations.redeliver(args.redeliver, Principal("checker-sam", "checker"))),
            flush=True,
        )
        return 0

    def checkpoint(phase):
        if phase == args.fault:
            print(json.dumps(dict(fault=phase, exit=73)), flush=True)
            os._exit(73)

    try:
        while True:
            processed = (
                operations.process_one(args.worker_id, args.lease, checkpoint)
                if args.mode in ("process", "both")
                else None
            )
            delivered = (
                operations.deliver_one(args.worker_id, args.lease, checkpoint)
                if args.mode in ("deliver", "both")
                else None
            )
            print(
                json.dumps(dict(processed=processed, delivered=delivered)), flush=True
            ) if processed or delivered or args.once else None
            if args.once:
                return 0
            if not processed and not delivered:
                time.sleep(0.25)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
