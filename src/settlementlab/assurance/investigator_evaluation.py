"""Reproducible incident-AI rubric checks and optional bounded local-model sampling."""

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from ..adapters.ai import send_request
from ..adapters.investigator import assess_response, render_analysis
from ..core.validation import DomainError


def corpus():
    path = Path(__file__).with_name("datasets") / "incident_investigator.json"
    return json.loads(path.read_text())


def evaluate_case(case, response):
    checks = assess_response(response, case["evidence"])
    return dict(
        id=case["id"],
        checks=checks,
        accepted=all(checks.values()),
        expected_accepted=case["expected_accepted"],
        correct=all(checks.values()) == case["expected_accepted"],
    )


def evaluate(cases):
    results = [evaluate_case(case, case["response"]) for case in cases]
    unsupported = [(c, r) for c, r in zip(cases, results) if not c["expected_accepted"]]
    insufficient = [
        (c, r) for c, r in zip(cases, results) if c["category"] == "insufficient-evidence"
    ]
    unsupported_claims = [
        r for r in results if r["checks"]["schema"] and not r["checks"]["supported_claims"]
    ]
    bad_citations = [r for r in results if r["checks"]["schema"] and not r["checks"]["citations"]]
    return dict(
        status="passed" if results and all(r["correct"] for r in results) else "failed",
        cases=results,
        metrics=dict(
            cases=len(results),
            unsupported_claim_cases=len(unsupported_claims),
            unsupported_claim_acceptance_rate=sum(r["accepted"] for r in unsupported_claims)
            / len(unsupported_claims)
            if unsupported_claims
            else None,
            invalid_citation_cases=len(bad_citations),
            invalid_citation_acceptance_rate=sum(r["accepted"] for r in bad_citations)
            / len(bad_citations)
            if bad_citations
            else None,
            negative_cases=len(unsupported),
            false_acceptance_rate=sum(r["accepted"] for _, r in unsupported) / len(unsupported)
            if unsupported
            else None,
            insufficient_evidence_accuracy=sum(r["correct"] for _, r in insufficient)
            / len(insufficient)
            if insufficient
            else None,
        ),
        scope="Declared fixture responses and deliberately adversarial mutations; contract/rubric detection, not measured model quality or independent human review",
    )


def sample(model, transport=send_request, repeats=2, on_progress=None):
    from ..adapters.investigator import INSTRUCTIONS, SCHEMA
    from .investigator_metrics import observation_coverage, summarize

    data = corpus()
    cases = [c for c in data["cases"] if c.get("sample")]
    if type(repeats) is not int or not 1 <= repeats <= 5 or len(cases) * repeats > 30:
        raise ValueError("Local evaluation allows 1–5 repeats and at most 30 model calls")
    options = dict(temperature=0, num_predict=1000, num_ctx=4096)
    output = []
    generated = datetime.now(timezone.utc).isoformat()

    def report(status):
        return dict(
            mode="live-local-model",
            run_status=status,
            generated_at=generated,
            evaluation_version="incident-evaluation-v3",
            prompt_version="incident-v44.1",
            prompt_sha256=hashlib.sha256(INSTRUCTIONS.encode()).hexdigest(),
            schema_sha256=hashlib.sha256(json.dumps(SCHEMA, sort_keys=True).encode()).hexdigest(),
            corpus_sha256=hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest(),
            model=model,
            options=options,
            cases=list(output),
            **summarize(cases, output, repeats),
            scope="Six synthetic development contexts; strict success requires contract acceptance, correct abstention and complete supported-observation coverage. Not blind evaluation, independent human review or unrestricted prose accuracy. Failure rates and denominators are explicit; stable wrong answers can still be consistent.",
        )

    if on_progress:
        on_progress(report("running"))
    interrupted = False
    for repeat in range(1, repeats + 1):
        for case in cases:
            started = time.perf_counter()
            evidence = case["evidence"]
            row = dict(
                id=case["id"],
                repeat=repeat,
                context_sha256=hashlib.sha256(
                    json.dumps(evidence, sort_keys=True).encode()
                ).hexdigest(),
                expected_abstention=not evidence["observations"],
            )
            raw = None
            try:
                response = transport(
                    dict(
                        model=model,
                        stream=False,
                        format=SCHEMA,
                        options=options,
                        messages=[
                            dict(role="system", content=INSTRUCTIONS),
                            dict(role="user", content=json.dumps(evidence)),
                        ],
                    )
                )
                raw = response["message"]["content"]
                if isinstance(raw, str):
                    row["raw_response"] = raw[:16384]
                    row["raw_response_truncated"] = len(raw) > 16384
                if response.get("done") is not True or response.get("done_reason") not in (
                    "stop",
                    None,
                ):
                    raise ValueError("Incomplete sample: " + str(response.get("done_reason")))
                if not isinstance(raw, str) or len(raw) > 16384:
                    raise ValueError("Non-text or oversized sample")

                def unique(pairs):
                    result = {}
                    for key, value in pairs:
                        if key in result:
                            raise ValueError("Duplicate output field")
                        result[key] = value
                    return result

                parsed = json.loads(raw, object_pairs_hook=unique)
                checks = assess_response(parsed, evidence)
                row.update(
                    status="recorded",
                    response=parsed,
                    checks=checks,
                    accepted=all(checks.values()),
                    correct_abstention=checks["schema"]
                    and parsed["abstained"] == row["expected_abstention"],
                    observation_coverage=observation_coverage(parsed, evidence),
                )
                if row["accepted"]:
                    try:
                        row["displayed_analysis"] = render_analysis(parsed, evidence)
                        row["presentation_status"] = "rendered"
                    except ValueError as error:
                        row["presentation_status"] = "rejected"
                        row["presentation_detail"] = str(error)
                else:
                    row["presentation_status"] = "not-rendered-contract-rejected"
            except KeyboardInterrupt:
                row.update(
                    status="interrupted",
                    failure_category="interrupted",
                    detail="Interrupted during local inference",
                )
                interrupted = True
            except (DomainError, ValueError, TypeError, KeyError, AttributeError) as error:
                row.update(
                    status="unavailable-or-invalid",
                    failure_category="transport"
                    if isinstance(error, DomainError)
                    else "invalid-response",
                    detail=str(error),
                )
            row["elapsed_seconds"] = time.perf_counter() - started
            output.append(row)
            if on_progress:
                on_progress(report("interrupted" if interrupted else "running"))
            if interrupted:
                break
        if interrupted:
            break
    final = report("interrupted" if interrupted else "completed")
    if on_progress:
        on_progress(final)
    return final


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="artifacts/v43-ai")
    parser.add_argument(
        "--live-model",
        help="Optional already installed local Ollama model; no downloads or paid calls",
    )
    parser.add_argument(
        "--repeats", type=int, default=2, help="1–5 repeats; at most 30 total local calls"
    )
    args = parser.parse_args(argv)
    output = Path(args.output)
    if (output / "results.json").exists():
        parser.error("Evidence already exists; choose a fresh --output directory")
    output.mkdir(parents=True, exist_ok=True)
    report = evaluate(corpus()["cases"])

    def checkpoint(live):
        report["live"] = live
        temporary = output / "results.json.tmp"
        temporary.write_text(json.dumps(report, indent=2) + "\n")
        temporary.replace(output / "results.json")
        print(
            "Local AI: "
            + str(live["attempted"])
            + "/"
            + str(live["requested"])
            + " attempted; "
            + live["run_status"],
            file=sys.stderr,
            flush=True,
        )

    report["live"] = (
        sample(args.live_model, repeats=args.repeats, on_progress=checkpoint)
        if args.live_model
        else dict(
            mode="not-run",
            reason="No local model sampling requested; offline fixtures are not model outputs",
        )
    )
    (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if args.live_model and report["live"]["run_status"] == "interrupted":
        return 130
    return int(
        report["status"] != "passed"
        or bool(args.live_model and report["live"]["quality_status"] != "passed")
    )


if __name__ == "__main__":
    raise SystemExit(main())
