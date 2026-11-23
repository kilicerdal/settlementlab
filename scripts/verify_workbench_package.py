"""Verify an exact workbench wheel outside the checkout, including cold-WAL recovery."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

CHECK = r"""
import json, platform, sqlite3
from importlib.metadata import version
from pathlib import Path
from urllib.request import urlopen
from settlementlab import __version__
from settlementlab.infrastructure.sqlite_snapshot import readonly_connection
from settlementlab.assurance.fixtures import LocalEnvironment
from settlementlab.adapters.investigator import Investigator
from settlementlab.assurance.investigator_evaluation import corpus, sample
from unittest.mock import patch
assert version("settlementlab") == __version__ == EXPECTED
p = Path("cold # check?.db")
db = sqlite3.connect(p)
db.execute("CREATE TABLE probe(value INTEGER)")
db.execute("INSERT INTO probe VALUES (1)")
db.commit()
assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
db.close()
assert not Path(str(p)+"-wal").exists()
with readonly_connection(p) as reader:
    assert reader.execute("SELECT value FROM probe").fetchone()[0] == 1
    reader.execute("PRAGMA query_only=OFF")
    try:
        reader.execute("UPDATE probe SET value=2")
    except sqlite3.OperationalError:
        pass
    else:
        raise AssertionError("Consumer became writable")
case = next(c for c in corpus()["cases"] if c["id"] == "lagging-position")
raw = dict(case["response"], summary="POSITION_LAG and COMPENSATION_POSTED cite journal:inverse and position:event2 respectively.")
def wrong_prose(payload):
    return dict(done=True, message=dict(content=json.dumps(raw)))
with patch("settlementlab.adapters.investigator.observations", return_value=case["evidence"]):
    served = Investigator("installed-wheel-injection", wrong_prose).analyze({})
assert "POSITION_LAG [position:event2]:" in served["analysis"]["summary"]
assert "COMPENSATION_POSTED [journal:inverse]:" in served["analysis"]["summary"]
assert "respectively" not in served["analysis"]["summary"]
assert served["presentation"]["model_prose_displayed"] is False
counter = 0
def failed_then_grounded(payload):
    global counter
    from settlementlab.core.validation import DomainError
    counter += 1
    if counter == 1:
        raise DomainError("Injected unavailable model", 502)
    evidence = json.loads(payload["messages"][1]["content"])
    response = dict(summary="Supplied observations are retained.", uncertainty="Underlying cause is not established by supplied evidence.", abstained=not evidence["observations"], claims=[dict(code=o["code"], evidence_ids=o["evidence_ids"]) for o in evidence["observations"]])
    return dict(done=True, message=dict(content=json.dumps(response)))
evaluation = sample("installed-wheel-injection", failed_then_grounded, repeats=1)
assert evaluation["metrics"]["strict_success"]["numerator"] == 5
assert evaluation["metrics"]["strict_success"]["denominator"] == 6
assert evaluation["conditional_accepted_rate"] == 1
assert evaluation["accepted_rate"] == 5/6
assert evaluation["quality_status"] == "failed"
assert evaluation["cases"][1]["presentation_status"] == "rendered"
with LocalEnvironment() as env:
    with urlopen(env.base_url+"/investigation", timeout=5) as response:
        assert response.status == 200
    with urlopen(env.base_url+"/api/health", timeout=5) as response:
        assert response.status == 200
print(json.dumps(dict(status="passed",python=platform.python_version(),sqlite=sqlite3.sqlite_version,version=__version__,cold_read=True,physical_write_rejected=True,http_startup=True,canonical_ai_presentation=True,failed_ai_attempt_in_denominator=True,live_model_calls=0)))
"""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--expected-version", default="4.4.2")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--output", default="artifacts/v442/workbench-package", type=Path)
    args = parser.parse_args(argv)
    wheel = args.wheel.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ)
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        env.pop(name, None)
    env["PYTHONNOUSERSITE"] = "1"
    with tempfile.TemporaryDirectory(prefix="workbench-wheel-") as temporary:
        root = Path(temporary)
        subprocess.run([args.python, "-m", "venv", str(root / "venv")], check=True, env=env)
        python = root / "venv/bin/python"

        def run(arguments, log):
            result = subprocess.run(
                [str(python)] + arguments,
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            (output / log).write_text(result.stdout + result.stderr)
            if result.returncode != 0:
                raise RuntimeError(result.stdout + result.stderr)
            return result.stdout

        run(["-m", "pip", "install", "--no-index", "--no-deps", str(wheel)], "install.log")
        checks = json.loads(
            run(["-c", "EXPECTED=" + repr(args.expected_version) + "\n" + CHECK], "checks.log")
        )
        run(["-m", "settlementlab.server", "--help"], "cli.log")
        run(
            ["-m", "settlementlab.assurance.incident_demo", "--output", str(output / "incident")],
            "incident.log",
        )
        incident = json.loads((output / "incident/results.json").read_text())
        assert incident["status"] == "passed"
        assert incident["worker_checkpoint_exit"] == 73
        assert (
            incident["export_verification"]["verification_level"]
            == "INTEGRITY_AND_SCOPED_ECONOMICS"
        )
    report = dict(
        status="passed",
        wheel=wheel.name,
        wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),
        checks=checks,
        incident_status=incident["status"],
        incident_worker_exit=incident["worker_checkpoint_exit"],
        source_checkout_on_import_path=False,
        scope="Exact installed wheel in a fresh venv outside checkout; no model or paid service",
    )
    (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
