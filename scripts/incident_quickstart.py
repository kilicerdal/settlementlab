"""Fresh-checkout incident demonstration: Python standard library only, no installation."""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-serve",
        action="store_true",
        help="Generate and verify evidence, then exit instead of serving the local UI",
    )
    parser.add_argument(
        "--output", help="Fresh output directory; existing evidence is never overwritten"
    )
    parser.add_argument("--model", default="", help="Optional already installed local Ollama model")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))
    from settlementlab.assurance.incident_demo import main as incident

    directory = args.output or str(
        root
        / "artifacts"
        / (
            "incident-"
            + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + uuid4().hex[:6]
        )
    )
    arguments = ["--output", directory, "--exercise", "--model", args.model]
    if not args.no_serve:
        arguments.append("--serve")
    return incident(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
