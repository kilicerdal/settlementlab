"""Incident investigator grounded claims, abstention, no writes and declared evaluation."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from settlementlab.adapters.investigator import Investigator, observations
from settlementlab.application.investigation import Investigation
from settlementlab.assurance.durable_data import CHECKER, approved_trade
from settlementlab.assurance.investigator_evaluation import corpus, evaluate, sample
from settlementlab.bootstrap import create_application
from settlementlab.configuration import Settings
from settlementlab.core.validation import DomainError


class IncidentAIControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_application(
            Settings(
                database=str(Path(self.temp.name) / "ai.db"), model="", business_date="2026-11-09"
            )
        )
        trade = approved_trade(self.app.service)
        self.app.service.command(
            trade["id"],
            "settle-partial",
            dict(version=trade["version"], quantity=20, request_key="slice"),
            principal=CHECKER,
        )
        self.snapshot = Investigation(self.app.service).snapshot(trade["id"])
        self.response = dict(
            summary="A partial execution is recorded; the remaining obligation is unexecuted.",
            claims=[
                dict(
                    code="PARTIAL_EXECUTION",
                    evidence_ids=observations(self.snapshot)["observations"][0]["evidence_ids"],
                )
            ],
            abstained=False,
            uncertainty="Underlying cause is not established by supplied evidence.",
        )

    def transport(self, payload):
        self.payload = payload
        return dict(done=True, message=dict(content=json.dumps(self.response)))

    def test_validated_investigation_is_advisory_minimized_and_read_only(self):
        before = self.app.service.snapshot()
        result = Investigator("local-fixture", self.transport).analyze(self.snapshot)
        self.assertTrue(result["advisory_only"])
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(self.app.service.snapshot(), before)
        context = json.loads(self.payload["messages"][1]["content"])
        self.assertEqual(set(context), {"trade_id", "trade_version", "observations", "scope"})
        self.assertNotIn("SYN-ALPHA", json.dumps(context))

    def test_fabrication_wrong_citation_and_unsafe_actions_rejected(self):
        variants = [
            dict(claims=[dict(code="INSOLVENT", evidence_ids=["journal:fake"])]),
            dict(claims=[dict(code="PARTIAL_EXECUTION", evidence_ids=["audit:fake"])]),
            dict(summary="Automatically reverse the trade."),
            dict(abstained=True),
            dict(uncertainty="The root cause is proven."),
        ]
        original = copy.deepcopy(self.response)
        for change in variants:
            with self.subTest(change=change), self.assertRaises(DomainError):
                self.response = dict(original, **change)
                Investigator("local-fixture", self.transport).analyze(self.snapshot)

    def test_empty_context_requires_abstention_and_disabled_is_explicit(self):
        empty = copy.deepcopy(self.snapshot)
        empty["trade"]["settled_quantity"] = 0
        self.response = dict(
            summary="Insufficient evidence to identify an incident.",
            claims=[],
            abstained=True,
            uncertainty="Underlying cause is not established by supplied evidence.",
        )
        self.assertTrue(
            Investigator("local-fixture", self.transport).analyze(empty)["analysis"]["abstained"]
        )
        with self.assertRaises(DomainError) as error:
            Investigator().analyze(self.snapshot)
        self.assertEqual(error.exception.status, 503)

    def test_duplicate_output_fields_and_incomplete_responses_rejected(self):
        for response in [
            dict(done=False, message=dict(content=json.dumps(self.response))),
            dict(done=True, message=dict(content='{"summary":"one","summary":"two"}')),
        ]:
            with self.subTest(response=response), self.assertRaises(DomainError):
                Investigator("local-fixture", lambda payload: response).analyze(self.snapshot)

    def test_declared_rubric_detects_adversarial_cases_without_model_accuracy_claim(self):
        report = evaluate(corpus()["cases"])
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["metrics"]["false_acceptance_rate"], 0)
        self.assertEqual(report["metrics"]["insufficient_evidence_accuracy"], 1)
        self.assertGreaterEqual(report["metrics"]["cases"], 14)

    def test_unavailable_local_sampling_does_not_fabricate_metrics(self):
        def unavailable(payload):
            raise DomainError("Local model unavailable", 502)

        report = sample("absent-local-model", unavailable)
        self.assertEqual(report["recorded"], 0)
        self.assertIsNone(report["accepted_rate"])

    def test_live_sampler_records_valid_and_invalid_outputs_separately(self):
        def transport(payload):
            evidence = json.loads(payload["messages"][1]["content"])
            facts = evidence["observations"]
            response = dict(
                summary="Supported observations are retained."
                if facts
                else "Insufficient evidence for any claim.",
                claims=[dict(code=f["code"], evidence_ids=f["evidence_ids"]) for f in facts],
                abstained=not facts,
                uncertainty="Underlying cause is not established by supplied evidence.",
            )
            return dict(done=True, message=dict(content=json.dumps(response)))

        report = sample("fixture-local-model", transport)
        self.assertEqual(report["accepted_rate"], 1)
        self.assertEqual(report["correct_abstention_rate"], 1)
        incomplete = sample(
            "fixture-local-model",
            lambda payload: dict(done=True, done_reason="length", message=dict(content="{}")),
        )
        self.assertEqual(incomplete["recorded"], 0)
        self.assertIsNone(incomplete["correct_abstention_rate"])
