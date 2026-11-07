"""Validated target profiles: defaults < file < environment < explicit overrides."""

import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .transport import validate_base_url


@dataclass(frozen=True)
class TargetProfile:
    target: str = "settlement"
    base_url: str = ""
    timeout: float = 10

    def __post_init__(self):
        if not isinstance(self.target, str) or not re.fullmatch(
            "[a-z][a-z0-9_-]{0,40}", self.target
        ):
            raise ValueError("Invalid target name")
        if (
            isinstance(self.timeout, bool)
            or not isinstance(self.timeout, (int, float))
            or not math.isfinite(self.timeout)
            or not 0 < self.timeout <= 60
        ):
            raise ValueError("Invalid target timeout")
        if self.base_url:
            validate_base_url(self.base_url)
        if self.target != "settlement" and not self.base_url:
            raise ValueError("External target requires a base URL")
        if self.target == "settlement" and self.base_url:
            raise ValueError(
                "Settlement catalog owns isolated fixtures; external URLs use an HTTP target"
            )

    @classmethod
    def load(cls, path=None, environ=None, **overrides):
        values = dict(target="settlement", base_url="", timeout=10)
        if path:
            supplied = json.loads(Path(path).read_text())
            if not isinstance(supplied, dict) or set(supplied) - set(values):
                raise ValueError("Unknown target profile fields")
            values.update(supplied)
        env = os.environ if environ is None else environ
        for field, key in [
            ("target", "SETTLEMENTLAB_TARGET"),
            ("base_url", "SETTLEMENTLAB_BASE_URL"),
            ("timeout", "SETTLEMENTLAB_TIMEOUT"),
        ]:
            if key in env:
                values[field] = float(env[key]) if field == "timeout" else env[key]
        values.update({key: value for key, value in overrides.items() if value is not None})
        return cls(**values)
