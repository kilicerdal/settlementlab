"""Evaluation regressions: failures, omissions and interrupts must remain visible."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from settlementlab.assurance.investigator_evaluation import corpus, main, sample
from settlementlab.assurance.investigator_metrics import observation_coverage
from settlementlab.core.validation import DomainError


def grounded(payload):
    evidence = json.loads(payload["messages"][1]["content"])
    observations = evidence["observations"]
    return dict(
        done=True,
        message=dict(
            content=json.dumps(
                dict(
                    summary="The supplied observations are retained.",
                    uncertainty="Underlying cause is not established by supplied evidence.",
                    abstained=not observations,
                    claims=[
                        dict(code=o["code"], evidence_ids=o["evidence_ids"]) for o in observations
                    ],
                )
            )
        ),
    )


class InvestigatorMeasurementControls(unittest.TestCase):
    def test_failed_call_reduces_all_attempt_success_without_changing_conditional_rate(self):
        counter = 0

        def transport(payload):
            nonlocal counter
            counter += 1
            if counter == 1:
                raise DomainError("Unavailable", 502)
            return grounded(payload)

        report = sample("injected", transport, repeats=1)
        self.assertEqual(report["accepted_rate"], 5 / 6)
        self.assertEqual(report["conditional_accepted_rate"], 1)
        self.assertEqual(
            report["metrics"]["strict_success"], dict(numerator=5, denominator=6, rate=5 / 6)
        )
        self.assertEqual(report["failure_categories"], {"transport": 1})
        self.assertEqual(report["latency_seconds"]["count"], 6)
        self.assertIsNone(report["repeat_consistency"][0]["consistent"])

    def test_supported_subset_can_pass_contract_but_fail_complete_observation_coverage(self):
        def transport(payload):
            response = grounded(payload)
            parsed = json.loads(response["message"]["content"])
            parsed["claims"] = parsed["claims"][:1]
            response["message"]["content"] = json.dumps(parsed)
            return response

        report = sample("injected", transport, repeats=1)
        self.assertEqual(report["accepted_rate"], 1)
        self.assertLess(report["metrics"]["strict_success"]["rate"], 1)
        self.assertLess(report["metrics"]["observation_coverage"]["rate"], 1)
        self.assertTrue(
            next(c for c in report["per_context"] if c["id"] == "complete-incident")[
                "missing_codes"
            ]
        )

    def test_misattributed_citations_do_not_count_as_covered_observations(self):
        evidence = next(c for c in corpus()["cases"] if c["id"] == "complete-incident")["evidence"]
        response = dict(claims=[dict(code="PARTIAL_EXECUTION", evidence_ids=["case:amount"])])
        self.assertEqual(observation_coverage(response, evidence)["numerator"], 0)

    def test_invalid_and_truncated_outputs_retain_raw_text_and_context(self):
        report = sample(
            "injected",
            lambda payload: dict(done=True, done_reason="length", message=dict(content="{broken")),
            repeats=1,
        )
        self.assertEqual(report["accepted_rate"], 0)
        self.assertEqual(report["cases"][0]["raw_response"], "{broken")
        self.assertIn("context_sha256", report["cases"][0])
        self.assertEqual(report["failure_categories"], {"invalid-response": 6})

    def test_interruption_checkpoints_attempt_and_leaves_unrun_slots_explicit(self):
        checkpoints = []

        def interrupted(payload):
            raise KeyboardInterrupt()

        report = sample(
            "injected",
            interrupted,
            repeats=2,
            on_progress=lambda r: checkpoints.append(copy.deepcopy(r)),
        )
        self.assertEqual(report["run_status"], "interrupted")
        self.assertEqual(report["attempted"], 1)
        self.assertEqual(report["not_attempted"], 11)
        self.assertEqual(report["metrics"]["strict_success"]["denominator"], 12)
        self.assertEqual(checkpoints[-1]["cases"][0]["status"], "interrupted")

    def test_citation_changes_are_inconsistent_even_when_claim_codes_match(self):
        counter = 0

        def transport(payload):
            nonlocal counter
            counter += 1
            response = grounded(payload)
            parsed = json.loads(response["message"]["content"])
            if counter > 6 and parsed["claims"]:
                parsed["claims"][0]["evidence_ids"] = ["invented:1"]
            response["message"]["content"] = json.dumps(parsed)
            return response

        report = sample("injected", transport, repeats=2)
        self.assertFalse(report["repeat_consistency"][0]["consistent"])
        self.assertEqual(report["options"]["temperature"], 0)
        self.assertEqual(len(report["prompt_sha256"]), 64)

    def test_single_repeat_does_not_claim_repeat_consistency(self):
        report = sample("injected", grounded, repeats=1)
        self.assertIsNone(report["consistent_context_rate"])
        self.assertEqual(report["metrics"]["repeat_consistency"]["denominator"], 0)

    def test_cli_persists_interruption_and_refuses_to_overwrite_retained_evidence(self):
        def interrupted(payload):
            raise KeyboardInterrupt()

        with tempfile.TemporaryDirectory() as directory:

            def run(model, repeats, on_progress):
                return sample(model, interrupted, repeats, on_progress)

            with (
                patch("settlementlab.assurance.investigator_evaluation.sample", side_effect=run),
                patch("builtins.print"),
            ):
                self.assertEqual(main(["--live-model", "injected", "--output", directory]), 130)
            path = Path(directory) / "results.json"
            saved = path.read_bytes()
            self.assertEqual(json.loads(saved)["live"]["run_status"], "interrupted")
            with self.assertRaises(SystemExit), patch("sys.stderr"):
                main(["--output", directory])
            self.assertEqual(path.read_bytes(), saved)
