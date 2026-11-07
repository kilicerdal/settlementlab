"""Capture positive and deliberately negative runs against a separate API."""

import hashlib
import json
import tempfile
from pathlib import Path

from examples.collateral_service.server import Inventory, handler
from settlementlab.assurance.fixtures import HTTPEnvironment
from settlementlab.assurance.runner import run
from settlementlab.assurance.targets import TargetProfile

reports = {}
for name, fault in [("control", False), ("injected_fault", True)]:
    with tempfile.TemporaryDirectory() as directory:
        inventory = Inventory(Path(directory) / "independent.db", fault)
        with HTTPEnvironment(handler(inventory)) as environment:
            reports[name] = run(
                "scenarios",
                ".",
                "artifacts/reuse-" + name,
                TargetProfile("collateral", environment.base_url),
            )
assert reports["control"]["status"] == "passed"
failed = next(case for case in reports["injected_fault"]["cases"] if case["status"] == "failed")
assert failed["steps"][-1]["failure"] == dict(kind="http_status", expected=200, actual=201)
paths = [
    Path("examples/collateral_service/server.py"),
    *Path("src/settlementlab/assurance").glob("*.py"),
]
evidence = dict(
    version="2.6.0",
    scope="Two owned synthetic local services, not a third-party production integration",
    source_state="working-tree",
    source_hashes={str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths},
    checks=dict(healthy_target_passed=True, injected_defect_detected=True),
    reports=reports,
)
Path("docs/evidence/reuse-v26.json").write_text(json.dumps(evidence, indent=2) + "\n")
print("Healthy target passed; duplicate replay defect detected with structured evidence.")
