"""Reusable HTTP scenario operations; no financial application imports."""

import re
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from .transport import APIError, JsonClient


def lookup(value: Any, path: str) -> Any:
    for part in path.split("."):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def equal_json(actual: Any, expected: Any) -> bool:
    """JSON assertions distinguish booleans from numbers, including nested values."""
    if type(actual) is not type(expected):
        return False
    if isinstance(actual, dict):
        return actual.keys() == expected.keys() and all(
            equal_json(v, expected[k]) for k, v in actual.items()
        )
    if isinstance(actual, list):
        return len(actual) == len(expected) and all(
            equal_json(a, e) for a, e in zip(actual, expected)
        )
    return bool(actual == expected)


def resolve(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        if set(value) == {"$ref"}:
            return lookup(context, value["$ref"])
        return {key: resolve(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve(item, context) for item in value]
    if isinstance(value, str):
        return re.sub(
            r"\$\{([A-Za-z0-9_.]+)\}", lambda match: str(lookup(context, match.group(1))), value
        )
    return value


@dataclass
class ExternalEnvironment:
    client: JsonClient


@contextmanager
def external_environment(base_url: str, timeout: float) -> Iterator[ExternalEnvironment]:
    yield ExternalEnvironment(JsonClient(base_url, timeout))


class StepFailure(AssertionError):
    def __init__(self, message: str, **evidence: Any) -> None:
        super().__init__(message)
        self.evidence = evidence


def execute_http(
    client: JsonClient, step: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    client.last_exchange = None
    path = resolve(step["path"], context)
    payload = resolve(step.get("data"), context)
    key = resolve(step.get("key"), context)
    method = step.get("method", "GET")
    expected = step.get("status", 200)
    if isinstance(expected, bool) or not isinstance(expected, int) or not 100 <= expected <= 599:
        raise ValueError("Invalid expected HTTP status")
    try:
        body = client.request(path, payload, key, method)
    except APIError as error:
        body = error.body
    if client.last_exchange is None:
        raise RuntimeError("Transport returned without request metadata")
    status = client.last_exchange["status"]
    if status != expected:
        raise StepFailure(
            "HTTP status differs from contract",
            kind="http_status",
            expected=expected,
            actual=status,
        )
    if "save" in step:
        if not re.fullmatch("[A-Za-z][A-Za-z0-9_]*", step["save"]) or step["save"] == "run_id":
            raise ValueError("Invalid response alias")
        context[step["save"]] = body
    return dict(status=status, body=body)
