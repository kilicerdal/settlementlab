"""Reusable HTTP scenario operations; no financial application imports."""

import re
from contextlib import contextmanager

from .transport import APIError, JsonClient


def lookup(value, path):
    for part in path.split("."):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def resolve(value, context):
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


@contextmanager
def external_environment(base_url, timeout):
    class Environment:
        pass

    env = Environment()
    env.client = JsonClient(base_url, timeout)
    yield env


class StepFailure(AssertionError):
    def __init__(self, message, **evidence):
        super().__init__(message)
        self.evidence = evidence


def execute_http(client, step, context):
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
