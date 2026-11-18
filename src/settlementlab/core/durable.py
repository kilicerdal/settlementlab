"""Pure validation and identity for local durable commands."""

import hashlib
import json
import math
from typing import Any

from .validation import DomainError


def bounded_integer(value: Any, lower: int, upper: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
        raise DomainError(label + " is outside the allowed integer range")
    return int(value)


def bounded_seconds(value: Any, lower: float, upper: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (float, int))
        or not math.isfinite(value)
        or not lower <= value <= upper
    ):
        raise DomainError("Invalid bounded duration")
    return float(value)


def identifier(value: Any, limit: int = 120) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= limit
        or any(ord(c) < 32 for c in value)
    ):
        raise DomainError("Invalid operation identifier")
    return value


def fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class LeaseLost(DomainError):
    def __init__(self) -> None:
        super().__init__("Worker lease is expired or fenced", 409)
