"""Execute guarded source mutants in isolated temporary copies against real tests."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST = "tests.integration.test_v42_workflows.WorkflowControls."
MUTANTS = [
    (
        "overfill",
        "application/lifecycle.py",
        'bounded_integer(quantity, 1, trade["remaining_quantity"], "Execution quantity")',
        'bounded_integer(quantity, 1, 10**9, "Execution quantity")',
        "test_overfill_stale_version_and_wrong_role_do_not_post",
    ),
    (
        "replay-conflict",
        "application/lifecycle.py",
        'previous["fingerprint"] != digest',
        "False",
        "test_partial_replay_remaining_and_final_receipt",
    ),
    (
        "cash-economics",
        "infrastructure/lifecycle_repository.py",
        'amount = quantity * trade["price_cents"]',
        'amount = quantity * trade["price_cents"] + 1',
        "test_partial_replay_remaining_and_final_receipt",
    ),
    (
        "revision-approval",
        "infrastructure/lifecycle_repository.py",
        "AND r.revision=? AND a.maker_id<>a.decided_by",
        "AND r.revision<=? AND a.maker_id<>a.decided_by",
        "test_amend_fences_claimed_worker_and_invalidates_old_approval",
    ),
    (
        "cutoff",
        "core/deadlines.py",
        "today == due",
        "today < due",
        "test_cutoff_uses_explicit_utc_timestamp",
    ),
    (
        "statement-evidence",
        "application/reconciliation.py",
        'if any(c["trade_id"] == case["trade_id"] for c in current):',
        "if False:",
        "test_statement_break_requires_distinct_corrected_evidence",
    ),
]


def execute(source, test):
    env = dict(os.environ, PYTHONPATH=str(source), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(
        [sys.executable, "-m", "unittest", test],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="artifacts/v42/mutations")
    args = parser.parse_args(argv)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for name, relative, old, new, test in MUTANTS:
        baseline = execute(ROOT / "src", TEST + test)
        if baseline.returncode:
            raise RuntimeError(
                "Baseline must pass before mutation: " + test + "\n" + baseline.stderr
            )
        with tempfile.TemporaryDirectory(prefix="settlementlab-mutant-") as directory:
            source = Path(directory) / "src"
            shutil.copytree(
                ROOT / "src", source, ignore=shutil.ignore_patterns("__pycache__", "*.egg-info")
            )
            target = source / "settlementlab" / relative
            original = target.read_text()
            if original.count(old) != 1:
                raise RuntimeError("Mutation anchor drift: " + name)
            target.write_text(original.replace(old, new))
            result = execute(source, TEST + test)
            log = result.stdout + result.stderr
            # Import/setup errors are invalid; only an assertion failure detects a mutant.
            status = (
                "survived"
                if result.returncode == 0
                else "killed"
                if "FAIL:" in log and "ERROR:" not in log
                else "invalid"
            )
            (output / (name + ".log")).write_text(log)
            results.append(
                dict(
                    id=name,
                    status=status,
                    source=relative,
                    original_sha256=hashlib.sha256(original.encode()).hexdigest(),
                    test=TEST + test,
                )
            )
    valid = [r for r in results if r["status"] != "invalid"]
    report = dict(
        status="passed" if all(r["status"] == "killed" for r in results) else "failed",
        mutants=results,
        killed=sum(r["status"] == "killed" for r in results),
        valid=len(valid),
        score=sum(r["status"] == "killed" for r in valid) / len(valid) if valid else None,
        scope="Six targeted financial workflow mutants; not exhaustive mutation coverage",
    )
    (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return int(report["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
