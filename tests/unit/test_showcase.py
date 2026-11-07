"""A showcase must preserve exact negative evidence and detect altered files."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.showcase import FILES, digest, main, require_outcomes, verify


def reports():
    return {
        "settlement": dict(
            status="passed", cases=[dict(id="S0" + str(n), status="passed") for n in range(1, 5)]
        ),
        "collateral-control": dict(
            status="passed", cases=[dict(id=n, status="passed") for n in ("C01", "C02")]
        ),
        "collateral-fault": dict(
            status="failed",
            cases=[
                dict(id="C01", status="passed"),
                dict(
                    id="C02",
                    status="failed",
                    steps=[dict(failure=dict(kind="http_status", expected=200, actual=201))],
                ),
            ],
        ),
    }


class ShowcaseControls(unittest.TestCase):
    def test_exact_defect_required_not_arbitrary_failure(self):
        original = reports()
        require_outcomes(original)
        for mutation in ("unrelated_failure", "missing_control", "skipped_control"):
            changed = copy.deepcopy(original)
            if mutation == "unrelated_failure":
                changed["collateral-fault"]["cases"][1]["steps"][0]["failure"]["actual"] = 500
            elif mutation == "missing_control":
                changed["settlement"]["cases"].pop()
            else:
                changed["collateral-control"]["cases"][0]["status"] = "skipped"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                require_outcomes(changed)

    def test_checksums_detect_tampering_and_missing_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in FILES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(reports()[name.split("/")[0]])
                    if name.endswith("results.json")
                    else "evidence"
                )
            manifest = dict(schema_version=1, files={name: digest(root / name) for name in FILES})
            (root / "manifest.json").write_text(json.dumps(manifest))
            verify(root)
            (root / "index.html").write_text("changed")
            with self.assertRaisesRegex(ValueError, "checksum"):
                verify(root)
            (root / "index.html").unlink()
            with self.assertRaises(OSError):
                verify(root)

    def test_manifest_rejects_paths_outside_known_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "manifest.json").write_text(
                json.dumps(dict(schema_version=1, files={"../secret": "x"}))
            )
            with self.assertRaisesRegex(ValueError, "incomplete"):
                verify(root)

    def test_verify_cli_fails_for_missing_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(main(["--verify", "--output", temporary]), 1)
