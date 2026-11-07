"""Small allowlisted acceptance DSL executed against an isolated real API."""

import json
import time
from importlib.resources import files

from .client import APIError
from .data import RunKeys, TradeFactory
from .fixtures import LocalEnvironment
from .http_steps import StepFailure, execute_http, external_environment, resolve
from .transport import TransportError

ACTIONS = {"identity", "create", "manager", "request", "approve", "fund", "settle", "snapshot"}


def catalog(target="settlement"):
    return [
        json.loads(path.read_text())
        for path in sorted(files("settlementlab.assurance").joinpath("catalog").iterdir(), key=str)
        if path.name.endswith(".json")
        and json.loads(path.read_text()).get("target", "settlement") == target
    ]


def lookup(value, path):
    for part in path.split("."):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def run_scenario(spec, base_url=None, timeout=10):
    target = spec.get("target", "settlement")
    actions = ACTIONS if target == "settlement" else {"http"}
    if not isinstance(spec.get("steps"), list) or not spec["steps"]:
        raise ValueError("Scenario needs nonempty steps")
    if any(step.get("action") not in actions for step in spec["steps"]):
        raise ValueError("Unknown scenario action")
    result = dict(
        id=spec["id"],
        suite="scenarios",
        target=target,
        name=spec["title"],
        status="passed",
        steps=[],
        duration=0.0,
    )
    start = time.perf_counter()
    try:
        fixture = (
            LocalEnvironment(
                business_date=spec.get("business_date", "2026-11-09"),
                closed_dates=spec.get("closed_dates", ()),
            )
            if target == "settlement"
            else external_environment(base_url, timeout)
        )
        with fixture as environment:
            result["environment"] = (
                environment.client.request("/api/health")["business_time"]
                if target == "settlement"
                else dict(
                    mode="external-http", base_url=environment.client.base_url, timeout=timeout
                )
            )
            client = environment.client
            factory = TradeFactory() if target == "settlement" else RunKeys()
            trade = None
            context = {"run_id": factory.namespace.upper()}
            for index, step in enumerate(spec["steps"], 1):
                item = dict(index=index, action=step["action"], status="passed")
                tick = time.perf_counter()
                try:
                    action = step["action"]
                    data = step.get("data", {})
                    view = None
                    try:
                        if action == "http":
                            view = execute_http(client, step, context)
                        elif action == "identity":
                            view = client.use_persona(data["persona"])
                        elif action == "create":
                            view = client.create(factory.broker(**data), factory.key("broker"))
                            trade = view
                        elif action == "manager":
                            view = client.submit_manager(
                                trade, factory.manager(**data), factory.key("manager")
                            )
                            trade = view
                        elif action == "request":
                            view = client.request_affirmation(
                                trade, "SYN-CUSTODY", factory.key("review")
                            )
                            trade = view
                        elif action == "approve":
                            view = client.approve(trade)
                            trade = view
                        elif action == "fund":
                            view = client.fund(
                                data["participant_id"],
                                data["asset"],
                                data["amount"],
                                factory.key("fund"),
                            )
                        elif action == "settle":
                            view = client.command(trade, "settle")
                            trade = view
                        elif action == "snapshot":
                            view = client.request("/api/snapshot")
                    except APIError as error:
                        if error.status != step.get("expect_status"):
                            raise
                        view = {"http_status": error.status}
                        item["expected_http_status"] = error.status
                    else:
                        if action != "http" and "expect_status" in step:
                            raise AssertionError(
                                "Expected HTTP failure " + str(step["expect_status"])
                            )
                    for path, expected in step.get("assert", {}).items():
                        expected = resolve(expected, context)
                        actual = lookup(view, path)
                        if actual != expected:
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
                        item["detail"] = str(error) + ": " + str(error.evidence)
                    if isinstance(error, TransportError):
                        item["failure"] = {"kind": error.kind}
                    result.update(status="failed", detail="Step %s: %s" % (index, item["detail"]))
                finally:
                    if action == "http" and client.last_exchange:
                        item["request"] = dict(client.last_exchange)
                    item["duration"] = time.perf_counter() - tick
                    result["steps"].append(item)
                if result["status"] == "failed":
                    break
    except Exception as error:
        result.update(status="failed", detail=str(error))
    result["duration"] = time.perf_counter() - start
    return result
