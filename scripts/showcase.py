"""Build and verify a portable, model-free showcase from executed scenarios."""

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from examples.collateral_service.server import Inventory, handler
from settlementlab import __version__
from settlementlab.assurance.fixtures import HTTPEnvironment
from settlementlab.assurance.runner import run
from settlementlab.assurance.targets import TargetProfile

RUNS = ("settlement", "collateral-control", "collateral-fault")
FILES = tuple(
    name + "/" + file for name in RUNS for file in ("index.html", "results.json", "junit.xml")
) + ("index.html",)


def require_outcomes(reports):
    for name, ids in (
        ("settlement", {"S01", "S02", "S03", "S04"}),
        ("collateral-control", {"C01", "C02"}),
    ):
        report = reports[name]
        if (
            report["status"] != "passed"
            or {c["id"] for c in report["cases"]} != ids
            or any(c["status"] != "passed" for c in report["cases"])
        ):
            raise ValueError("Unexpected control outcome: " + name)
    fault = reports["collateral-fault"]
    cases = {case["id"]: case for case in fault["cases"]}
    if (
        fault["status"] != "failed"
        or set(cases) != {"C01", "C02"}
        or cases["C01"]["status"] != "passed"
        or cases["C02"]["status"] != "failed"
        or cases["C02"]["steps"][-1].get("failure")
        != dict(kind="http_status", expected=200, actual=201)
    ):
        raise ValueError("Expected duplicate replay defect was not precisely detected")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(directory):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("schema_version") != 1 or set(manifest.get("files", {})) != set(FILES):
        raise ValueError("Unsupported or incomplete showcase manifest")
    for name in FILES:
        path = directory / name
        if (
            path.is_symlink()
            or directory.resolve() not in path.resolve().parents
            or digest(path) != manifest["files"][name]
        ):
            raise ValueError("Evidence checksum mismatch: " + name)
    reports = {name: json.loads((directory / name / "results.json").read_text()) for name in RUNS}
    require_outcomes(reports)
    return manifest


def build(directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    reports = {"settlement": run("scenarios", ".", directory / "settlement")}
    for name, fault in (("collateral-control", False), ("collateral-fault", True)):
        with tempfile.TemporaryDirectory() as temporary:
            inventory = Inventory(Path(temporary) / "inventory.db", fault)
            with HTTPEnvironment(handler(inventory)) as environment:
                reports[name] = run(
                    "scenarios",
                    ".",
                    directory / name,
                    TargetProfile("collateral", environment.base_url),
                )
    require_outcomes(reports)
    (directory / "index.html").write_text(
        """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SettlementLab showcase</title><style>body{margin:60px auto;padding:0 24px;max-width:900px;background:#0a111c;color:#dbe6ef;font:16px/1.7 system-ui}h1,a{color:#a3dfca}article{border-top:1px solid #304050;padding:24px 0}h1{font-size:44px}code{overflow-wrap:anywhere}</style><main><p>SETTLEMENTLAB / EXECUTED SHOWCASE</p><h1>One framework.<br>Two financial services.</h1><p>These reports come from local synthetic execution. The deliberately faulty service must fail its replay contract for this showcase to succeed.</p><article><h2>01 / Settlement lifecycle — passing</h2><p>Matching correction, approvals, settlement recovery and calendar rejection.</p><a href="settlement/index.html">Inspect four executed scenarios</a></article><article><h2>02 / Independent collateral service — passing</h2><p>Capacity, reservation replay and once-only release through the shared HTTP engine.</p><a href="collateral-control/index.html">Inspect the healthy control</a></article><article><h2>03 / Injected duplicate replay — expected failure</h2><p>The faulty service returns 201 instead of replaying the original reservation with 200. C01 passes; C02 records the defect.</p><a href="collateral-fault/index.html">Inspect the detected defect</a></article><p><a href="manifest.json">Execution manifest and SHA-256 checksums</a></p><p>Checksums detect changed files relative to this manifest; they are not signatures or independent attestations. No browser or live AI run is included. AI contract tests and optional Ollama execution are separate. No production connectivity or authenticated multi-user service is claimed.</p></main></html>"""
    )
    root = Path(__file__).resolve().parents[1]
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    dirty = bool(
        subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=normal"], cwd=root, text=True
        ).strip()
    )
    manifest = dict(
        schema_version=1,
        framework_version=__version__,
        generated_at=datetime.now(timezone.utc).isoformat(),
        python=platform.python_version(),
        source=dict(commit=commit, dirty=dirty),
        scope="Owned synthetic local services; model-free scenario execution",
        checks=dict(
            settlement_passed=True, independent_target_passed=True, injected_defect_detected=True
        ),
        files={name: digest(directory / name) for name in FILES},
    )
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return verify(directory)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="artifacts/showcase")
    parser.add_argument(
        "--verify", action="store_true", help="Verify existing evidence without rerunning services"
    )
    args = parser.parse_args(argv)
    try:
        manifest = verify(args.output) if args.verify else build(args.output)
    except (
        OSError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        subprocess.CalledProcessError,
    ) as error:
        print("SHOWCASE FAILED: " + str(error), file=sys.stderr)
        return 1
    print(
        "SHOWCASE VERIFIED: "
        + manifest["framework_version"]
        + " / "
        + str(Path(args.output) / "index.html")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
