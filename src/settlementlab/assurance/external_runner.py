"""Standalone declarative HTTP runner with no reference-application dependency."""

import argparse
import platform
import time
from datetime import datetime, timezone
from uuid import uuid4

from .catalogs import load_external
from .http_steps import StepFailure, equal_json, execute_http, lookup, resolve
from .reporting import write_reports
from .transport import JsonClient, TransportError


def run_case(spec, base_url, timeout=10):
    client = JsonClient(base_url, timeout)
    context = {"run_id": uuid4().hex.upper()}
    result = dict(
        id=spec["id"],
        name=spec["title"],
        suite="scenarios",
        target=spec["target"],
        status="passed",
        steps=[],
    )
    started = time.perf_counter()
    for index, step in enumerate(spec["steps"], 1):
        item = dict(index=index, action="http", status="passed")
        tick = time.perf_counter()
        try:
            view = execute_http(client, step, context)
            for path, expected in step.get("assert", {}).items():
                actual = lookup(view, path)
                expected = resolve(expected, context)
                if not equal_json(actual, expected):
                    raise StepFailure(
                        "Assertion differs from contract",
                        kind="assertion",
                        path=path,
                        expected=expected,
                        actual=actual,
                    )
            item["assertions"] = len(step.get("assert", {}))
        except Exception as error:
            item.update(status="failed", detail=str(error))
            if isinstance(error, StepFailure):
                item["failure"] = error.evidence
            elif isinstance(error, TransportError):
                item["failure"] = dict(kind=error.kind)
            result["status"] = "failed"
        finally:
            if client.last_exchange:
                item["request"] = dict(client.last_exchange)
            item["duration"] = time.perf_counter() - tick
            result["steps"].append(item)
        if item["status"] == "failed":
            break
    result["duration"] = time.perf_counter() - started
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario-dir", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--report-dir", default="artifacts/http-assurance")
    args = parser.parse_args(argv)
    from .targets import TargetProfile

    profile = TargetProfile(target=args.target, base_url=args.base_url, timeout=args.timeout)
    specs = load_external(args.scenario_dir, profile.target)
    if not specs:
        parser.error("Scenario pack is empty")
    cases = [run_case(spec, profile.base_url, profile.timeout) for spec in specs]
    report = dict(
        version=1,
        target=profile.target,
        generated_at=datetime.now(timezone.utc).isoformat(),
        python=platform.python_version(),
        status="passed" if all(c["status"] == "passed" for c in cases) else "failed",
        duration=sum(c["duration"] for c in cases),
        cases=cases,
    )
    write_reports(report, args.report_dir)
    print(report["status"].upper() + ": " + str(len(cases)) + " HTTP scenarios")
    return int(report["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
