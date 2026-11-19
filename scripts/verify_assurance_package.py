"""Install only the standalone wheel and test a healthy/faulty independent service."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from examples.collateral_service.server import Inventory, handler
from settlementlab.assurance.fixtures import HTTPEnvironment

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel-dir", default="dist")
    parser.add_argument("--output", default="artifacts/v42/package")
    args = parser.parse_args(argv)
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    wheels = list(Path(args.wheel_dir).glob("settlementlab_assurance-*.whl"))
    if len(wheels) != 1:
        parser.error("Provide a directory containing exactly one assurance wheel")
    outcomes = {}
    with tempfile.TemporaryDirectory(prefix="assurance-install-") as directory:
        root = Path(directory)
        subprocess.run([sys.executable, "-m", "venv", str(root / "venv")], check=True)
        python = root / "venv/bin/python"
        subprocess.run(
            [str(python), "-m", "pip", "install", "--no-index", str(wheels[0].resolve())],
            check=True,
            capture_output=True,
        )
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        absence = subprocess.run(
            [
                str(python),
                "-c",
                'import importlib.util; assert importlib.util.find_spec("settlementlab") is None; import settlementlab_assurance',
            ],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
        )
        assert absence.returncode == 0, absence.stderr
        for name, fault in [("healthy", False), ("injected-replay-defect", True)]:
            with HTTPEnvironment(handler(Inventory(root / (name + ".db"), fault=fault))) as server:
                result = subprocess.run(
                    [
                        str(python),
                        "-m",
                        "settlementlab_assurance.external_runner",
                        "--scenario-dir",
                        str(ROOT / "examples/scenario_packs/inventory"),
                        "--target",
                        "owned-api",
                        "--base-url",
                        server.base_url,
                        "--report-dir",
                        str(output / name),
                    ],
                    cwd=root,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            assert result.returncode == int(fault), result.stdout + result.stderr
            report = json.loads((output / name / "results.json").read_text())
            if fault:
                failures = [
                    s.get("failure")
                    for c in report["cases"]
                    for s in c["steps"]
                    if s.get("failure")
                ]
                assert dict(kind="http_status", expected=200, actual=201) in failures
            outcomes[name] = report["status"]
    report = dict(
        status="passed",
        reference_application_installed=False,
        outcomes=outcomes,
        scenario_pack="examples/scenario_packs/inventory",
        scope="Clean wheel installation outside checkout; reusable framework requires no financial application",
    )
    (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
