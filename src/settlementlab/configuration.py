"""Strict configuration with defaults < JSON file < environment < CLI overrides."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from .core.validation import DomainError


@dataclass(frozen=True)
class Settings:
    database: str = "settlementlab.db"
    port: int = 8080
    model: str = "qwen2.5:3b"
    reports: str = "artifacts/reports"
    business_date: str = ""
    business_timestamp: str = ""
    settlement_cutoff: str = "17:00"
    calendar_id: str = "weekday-v1"
    closed_dates: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        from .core.calendar import BusinessCalendar, FixedClock
        from .core.deadlines import FixedTimestampClock, cutoff_time

        if not isinstance(self.business_timestamp, str):
            raise DomainError("Business timestamp must be a string")
        cutoff_time(self.settlement_cutoff)
        if self.business_timestamp:
            clock = FixedTimestampClock(self.business_timestamp)
            if self.business_date and self.business_date != clock.today().isoformat():
                raise DomainError("Business date and timestamp disagree")

        if not isinstance(self.business_date, str):
            raise DomainError("Business date must be a string")
        if self.business_date:
            FixedClock(self.business_date)
        BusinessCalendar(self.calendar_id, self.closed_dates)
        if (
            isinstance(self.port, bool)
            or not isinstance(self.port, int)
            or not 0 <= self.port <= 65535
        ):
            raise DomainError("Port must be an integer from 0 to 65535")
        for field in ("database", "reports"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise DomainError(field + " must be a nonempty path")
        if self.database == ":memory:":
            raise DomainError(
                "Use a temporary database file; transactions use separate connections"
            )
        if not isinstance(self.model, str):
            raise DomainError("Model must be a string; empty disables local AI")

    @classmethod
    def load(
        cls,
        path: "str | Path | None" = None,
        environ: "Mapping[str,str] | None" = None,
        **overrides: Any,
    ) -> "Settings":
        values = asdict(cls())
        env = os.environ if environ is None else environ
        if path:
            try:
                supplied = json.loads(Path(path).read_text())
            except (OSError, ValueError) as error:
                raise DomainError("Cannot read configuration: " + str(error))
            if not isinstance(supplied, dict) or set(supplied) - set(values):
                raise DomainError("Configuration has unknown fields or is not an object")
            values.update(supplied)
        for key, name in [
            ("database", "SETTLEMENTLAB_DB"),
            ("port", "SETTLEMENTLAB_PORT"),
            ("model", "SETTLEMENTLAB_MODEL"),
            ("reports", "SETTLEMENTLAB_REPORTS"),
            ("business_date", "SETTLEMENTLAB_BUSINESS_DATE"),
            ("business_timestamp", "SETTLEMENTLAB_BUSINESS_TIMESTAMP"),
            ("settlement_cutoff", "SETTLEMENTLAB_CUTOFF_UTC"),
        ]:
            if name in env:
                try:
                    values[key] = int(env[name]) if key == "port" else env[name]
                except (TypeError, ValueError):
                    raise DomainError("Invalid " + name)
        values.update({key: value for key, value in overrides.items() if value is not None})
        return cls(**values)
