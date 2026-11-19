"""Explicit UTC simulation cutoffs and bounded business-day aging."""

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping

from .calendar import BusinessCalendar, iso_date
from .validation import DomainError


def cutoff_time(value: object) -> str:
    if not isinstance(value, str) or len(value) != 5:
        raise DomainError("Cutoff must use HH:MM in UTC")
    try:
        hour, minute = value.split(":")
        if f"{int(hour):02}:{int(minute):02}" != value or not (
            0 <= int(hour) <= 23 and 0 <= int(minute) <= 59
        ):
            raise ValueError()
    except ValueError:
        raise DomainError("Cutoff must use HH:MM in UTC")
    return value


@dataclass(frozen=True)
class FixedTimestampClock:
    timestamp: str

    def __post_init__(self) -> None:
        try:
            parsed = datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
                raise ValueError()
        except (ValueError, AttributeError):
            raise DomainError("Business timestamp must be ISO-8601 with an explicit UTC offset")

    def today(self) -> date:
        return datetime.fromisoformat(self.timestamp.replace("Z", "+00:00")).date()

    def describe(self) -> dict[str, str]:
        return dict(
            mode="simulated",
            date=self.today().isoformat(),
            timezone="UTC",
            timestamp=datetime.fromisoformat(self.timestamp.replace("Z", "+00:00")).isoformat(),
        )


def aging(trade: Mapping[str, Any], clock: Any) -> dict[str, Any]:
    due = iso_date(trade["settlement_date"])
    today = clock.today()
    try:
        calendar = BusinessCalendar.from_dict(json.loads(trade["calendar_policy"]))
    except (ValueError, TypeError, KeyError) as error:
        raise DomainError("Invalid pinned business calendar", 409) from error
    days = 0
    span = (today - due).days
    if span > 36600:
        raise DomainError("Aging interval exceeds the supported 100-year simulation window")
    for i in range(1, max(0, span) + 1):
        if calendar.is_open(due + timedelta(days=i)):
            days += 1
    description = clock.describe()
    timestamp = description.get("timestamp")
    if description.get("mode") == "system":
        timestamp = datetime.now(timezone.utc).isoformat()
    cutoff = trade.get("cutoff_utc", "")
    passed = bool(
        cutoff
        and timestamp
        and (
            today > due
            or (
                today == due
                and datetime.fromisoformat(timestamp.replace("Z", "+00:00")).strftime("%H:%M")
                >= cutoff
            )
        )
    )
    if trade["state"] in ("SETTLED", "CANCELLED"):
        bucket = "CLOSED"
    elif today < due:
        bucket = "NOT_DUE"
    elif today > due:
        bucket = "OVERDUE"
    elif passed:
        bucket = "CUTOFF_PASSED"
    elif timestamp and cutoff:
        minutes = (
            int(cutoff[:2]) * 60
            + int(cutoff[3:])
            - (
                datetime.fromisoformat(timestamp).hour * 60
                + datetime.fromisoformat(timestamp).minute
            )
        )
        bucket = "DUE_SOON" if 0 < minutes <= 60 else "DUE_TODAY"
    else:
        bucket = "DUE_TODAY"
    return dict(
        bucket=bucket,
        overdue_business_days=days,
        cutoff_utc=cutoff or None,
        cutoff_passed=passed,
        intraday_enforced=bool(timestamp and cutoff),
        business_time=description,
        scope="Project-defined UTC cutoff; date-only clocks do not infer an intraday time",
    )
