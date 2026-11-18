"""One-command V4.1 reviewer evidence: controls, economic oracle, load and recovery.

Run from a clean source checkout: python -m scripts.reviewer_ready --quality
No website changes, paid APIs or external services are used by default.
"""

import argparse
import hashlib
import html
import json
import os
import platform
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from settlementlab import __version__
from settlementlab.assurance.ai_review import run as ai_review
from settlementlab.assurance.campaign import benchmark, business_day, contention_probe

ROOT = Path(__file__).resolve().parents[1]


def command(args, output):
    result = subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=240,
    )
    output.write_text(result.stdout, encoding="utf-8")
    if result.returncode:
        raise RuntimeError("Check failed: " + " ".join(args) + "; inspect " + output.name)


def reuse(output):
    # This source-only example imports no financial application or oracle module.
    from examples.collateral_service.server import Inventory, handler
    from settlementlab.assurance.fixtures import HTTPEnvironment
    from settlementlab.assurance.runner import run
    from settlementlab.assurance.targets import TargetProfile

    statuses = {}
    with tempfile.TemporaryDirectory() as d:
        for name, fault in [("control", False), ("injected-defect", True)]:
            with HTTPEnvironment(handler(Inventory(Path(d) / (name + ".db"), fault=fault))) as env:
                report = run(
                    "scenarios",
                    ROOT,
                    output / name,
                    TargetProfile(target="owned-api", base_url=env.base_url),
                    ROOT / "examples/scenario_packs/inventory",
                )
            statuses[name] = report["status"]
            if fault:
                failures = [
                    step["failure"]
                    for case in report["cases"]
                    for step in case.get("steps", [])
                    if "failure" in step
                ]
                if not any(
                    f.get("kind") == "http_status"
                    and f.get("expected") == 200
                    and f.get("actual") == 201
                    for f in failures
                ):
                    raise AssertionError(
                        "Expected replay defect was not identified at its HTTP step"
                    )
    if statuses != {"control": "passed", "injected-defect": "failed"}:
        raise AssertionError(statuses)
    return dict(
        status="passed",
        observed=statuses,
        pack="examples/scenario_packs/inventory/reservation.json",
        core_changes_required=0,
        expected_available_after_one_reservation=90,
    )


def write_report(report, output):
    output.mkdir(parents=True, exist_ok=True)
    if "business_day" in report:
        (output / "economic-oracle.json").write_text(
            json.dumps(report["business_day"]["financial_oracle"], indent=2) + "\n",
            encoding="utf-8",
        )
    (output / "scorecard.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    sections = "".join(
        "<details><summary>"
        + html.escape(key.replace("_", " ").title())
        + "</summary><pre>"
        + html.escape(json.dumps(value, indent=2))
        + "</pre></details>"
        for key, value in report.items()
        if key not in ("schema_version", "status")
    )
    day = report.get("business_day", {})
    controls = report.get("controls", {})
    coverage = report.get("coverage", {}).get("percent_covered")
    cards = [
        ("Deterministic cases", controls.get("cases", "Not completed")),
        (
            "Trades independently verified",
            day.get("financial_oracle", {}).get("expected_settlements", "Not completed"),
        ),
        ("Reviewed shortage recoveries", day.get("reviewed_recoveries", "Not completed")),
        ("Price breaks corrected", day.get("price_corrections", "Not completed")),
        ("Combined coverage", f"{coverage:.2f}%" if coverage is not None else "Not measured"),
        (
            "Live AI sampling",
            "Opted in"
            if report.get("ai", {}).get("live_local", {}).get("model_calls")
            else "Not run",
        ),
    ]
    headline = (
        '<div class="cards">'
        + "".join(
            '<div class="card"><small>'
            + html.escape(label)
            + "</small><strong>"
            + html.escape(str(value))
            + "</strong></div>"
            for label, value in cards
        )
        + "</div>"
    )
    performance = ""
    for sample in report.get("load", []):
        measured = sample["performance"]
        performance += (
            "<tr>"
            + "".join(
                "<td>" + html.escape(str(value)) + "</td>"
                for value in [
                    measured["workers_requested"],
                    measured["workers_with_claims"],
                    measured["completed"],
                    f"{measured['elapsed_seconds']:.3f}",
                    f"{measured['settlements_per_second']:.2f}",
                    f"{measured['attempt_seconds']['p95'] * 1000:.2f}",
                ]
            )
            + "</tr>"
        )
    performance = (
        '<h2>Measured worker workloads</h2><p>Same seeded 40-trade inputs. One sample per worker count. SQLite serializes writes; startup, scheduling and lock contention affect results. No scaling or capacity promise.</p><div class="scroll"><table><tr><th>Workers started</th><th>Workers with claims</th><th>Settlements</th><th>Elapsed seconds</th><th>Settlements / second</th><th>Attempt p95 ms</th></tr>'
        + performance
        + "</table></div>"
        if performance
        else ""
    )
    page = (
        """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SettlementLab engineering scorecard</title><style>
    :root{color-scheme:dark}body{margin:0;background:#0b1421;color:#dfebf4;font:16px/1.6 system-ui}main{max-width:1150px;margin:auto;padding:48px 24px}h1{font:clamp(32px,6vw,60px)/1.1 Georgia;margin:12px 0 24px}a{color:#9adfc8}.eyebrow{color:#9adfc8;letter-spacing:3px;font-size:12px}details{background:#121f30;border:1px solid #2a3b50;border-radius:12px;padding:20px;margin:16px 0}summary{cursor:pointer;font-size:20px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.6 ui-monospace,monospace}p{max-width:850px;color:#aebfd0}.status{color:#9adfc8}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px;margin:28px 0}.card{padding:20px;background:#121f30;border:1px solid #2a3b50;border-radius:12px}.card small{display:block;color:#aebfd0}.card strong{display:block;font:32px Georgia;margin-top:8px}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:12px;border-bottom:1px solid #2a3b50;white-space:nowrap}.scroll{overflow:auto}</style><main><div class="eyebrow">SETTLEMENTLAB / ENGINEERING EVIDENCE</div><h1>Financial correctness.<br>Measured recovery.</h1><div class="status">"""
        + html.escape(report["status"].upper())
        + """</div><p>Reproducible synthetic evidence with independent economic expectations. Timing is specific to this machine and workload; it is not a production SLA. AI rubric agreement is not model accuracy. Read the exact scopes and provenance below.</p><p><a href="scorecard.json">Machine-readable scorecard</a> · <a href="controls/index.html">Control evidence</a> · <a href="ai/index.html">AI rubric review</a> · <a href="reuse/injected-defect/index.html">Expected second-service failure</a> · <a href="economic-oracle.json">All economic comparisons</a></p>"""
        + headline
        + performance
        + "<h2>Evidence and limits</h2>"
        + sections
        + "</main></html>"
    )
    (output / "index.html").write_text(page, encoding="utf-8")
    hashes = {
        str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in output.rglob("*")
        if p.is_file() and p.name != "checksums.json"
    }
    (output / "checksums.json").write_text(json.dumps(hashes, indent=2) + "\n")


def verify(output):
    output = Path(output).resolve()
    hashes = json.loads((output / "checksums.json").read_text())
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError("Evidence manifest must contain file hashes")
    for name, expected in hashes.items():
        target = (output / name).resolve()
        if output not in target.parents or not target.is_file():
            raise ValueError("Evidence path missing or outside report directory")
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise ValueError("Evidence checksum mismatch: " + name)
    return dict(status="passed", files=len(hashes))


def capture(output, trades=240, quality=False, model=None):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    # Child workers inherit the explicitly selected checkout; no installed stale version.
    old_pythonpath = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = env["PYTHONPATH"]
    report = dict(
        schema_version=1,
        status="failed",
        version=__version__,
        generated_at=datetime.now(timezone.utc).isoformat(),
        environment=dict(
            python=platform.python_version(),
            platform=platform.platform(),
            machine=platform.machine(),
            sqlite=sqlite3.sqlite_version,
            cpu_count=os.cpu_count(),
        ),
        limits=[
            "Shared SQLite serializes writes; worker scaling is measured, not promised",
            "Seeded bounded generation, not exhaustive proof or shrinking",
            "Synthetic identities and balances; no production authentication or external institution",
            "Backup recovery covers committed SQLite state, not arbitrary external side effects",
        ],
    )
    started = time.perf_counter()
    try:
        report["source"] = dict(
            commit=subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            dirty=bool(
                subprocess.check_output(
                    ["git", "status", "--porcelain"], cwd=ROOT, text=True
                ).strip()
            ),
        )
        if quality:
            for name, args in [
                ("lint", ["-m", "ruff", "check", "src", "tests", "scripts", "examples"]),
                (
                    "format",
                    ["-m", "ruff", "format", "--check", "src", "tests", "scripts", "examples"],
                ),
                ("types", ["-m", "mypy"]),
            ]:
                command(args, output / (name + ".log"))
            command(
                [
                    "-m",
                    "coverage",
                    "run",
                    "-m",
                    "settlementlab.assurance.runner",
                    "--suite",
                    "all",
                    "--root",
                    str(ROOT),
                    "--report-dir",
                    str(output / "controls"),
                ],
                output / "controls.log",
            )
            command(["-m", "coverage", "report"], output / "coverage.log")
            command(
                ["-m", "coverage", "json", "-o", str(output / "coverage.json")],
                output / "coverage-json.log",
            )
            report["coverage"] = json.loads((output / "coverage.json").read_text())["totals"]
        else:
            command(
                [
                    "-m",
                    "settlementlab.assurance.runner",
                    "--suite",
                    "all",
                    "--root",
                    str(ROOT),
                    "--report-dir",
                    str(output / "controls"),
                ],
                output / "controls.log",
            )
            report["coverage"] = dict(
                status="not-measured", reason="Use --quality with pinned requirements-quality.txt"
            )
        controls = json.loads((output / "controls/results.json").read_text())
        report["controls"] = dict(
            status=controls["status"],
            cases=len(controls["cases"]),
            generated_conservation_cases=2000,
            generated_financial_sequences=24,
        )
        if controls["status"] != "passed":
            raise AssertionError("Control suite failed")
        print("Controls verified; measuring worker workloads and full business day", flush=True)
        with tempfile.TemporaryDirectory(prefix="settlementlab-review-") as d:
            report["load"] = [benchmark(d, count=40, workers=w) for w in (1, 4)]
            report["contention"] = contention_probe(d)
            report["business_day"] = business_day(d, count=trades)
        report["reuse"] = reuse(output / "reuse")
        report["ai"] = ai_review(output / "ai", model)
        if report["ai"]["status"] != "passed":
            raise AssertionError("Adversarial rubric annotations failed")
        if model and any(
            "error" in c or not all(c["checks"].values())
            for c in report["ai"]["live_local"]["cases"]
        ):
            raise AssertionError("Live local model did not meet bounded rubric; failures retained")
        report["status"] = "passed"
    except Exception as error:
        report["error"] = str(error)
    finally:
        if old_pythonpath is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = old_pythonpath
        report["duration_seconds"] = time.perf_counter() - started
        write_report(report, output)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", default="artifacts/reviewer-ready")
    parser.add_argument("--trades", type=int, default=240)
    parser.add_argument("--quality", action="store_true")
    parser.add_argument(
        "--verify", action="store_true", help="Verify existing report checksums without rerunning"
    )
    parser.add_argument("--model", help="Optional already installed local Ollama model")
    args = parser.parse_args(argv)
    if args.verify:
        try:
            print(json.dumps(verify(args.report_dir)))
            return 0
        except (OSError, ValueError, TypeError) as error:
            print("FAILED: " + str(error))
            return 1
    if not 8 <= args.trades <= 1000:
        parser.error("--trades must be 8–1000")
    report = capture(args.report_dir, args.trades, args.quality, args.model)
    print(report["status"].upper() + ": " + str(Path(args.report_dir) / "index.html"), flush=True)
    if report.get("error"):
        print(report["error"], flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
