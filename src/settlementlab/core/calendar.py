"""Explicit simulation calendars; no exchange-holiday or cutoff claims."""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Mapping, Protocol

from .validation import DomainError


def iso_date(value: object) -> date:
    try:
        if not isinstance(value, str):
            raise ValueError()
        result = date.fromisoformat(value)
        if result.isoformat() != value:
            raise ValueError()
        return result
    except (TypeError, ValueError):
        raise DomainError("Business dates must use YYYY-MM-DD")


class Clock(Protocol):
    def today(self) -> date: ...
    def describe(self) -> dict[str, str]: ...


@dataclass(frozen=True)
class FixedClock:
    business_date: str

    def __post_init__(self) -> None:
        iso_date(self.business_date)

    def today(self) -> date:
        return iso_date(self.business_date)

    def describe(self) -> dict[str, str]:
        return dict(mode="simulated", date=self.business_date, timezone="date-only")


@dataclass(frozen=True)
class BusinessCalendar:
    id: str = "weekday-v1"
    closed_dates: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.id):
            raise DomainError(
                "Calendar ID must contain 1–64 letters, digits, underscores or hyphens"
            )
        if not isinstance(self.closed_dates, (tuple, list)) or len(self.closed_dates) > 3660:
            raise DomainError("Calendar closures must be an array of at most 3660 dates")
        for value in self.closed_dates:
            iso_date(value)
        if len(set(self.closed_dates)) != len(self.closed_dates):
            raise DomainError("Calendar closure dates must be unique")
        object.__setattr__(self, "closed_dates", tuple(sorted(self.closed_dates)))

    def is_open(self, day: date) -> bool:
        return day.weekday() < 5 and day.isoformat() not in self.closed_dates

    def next_day(self, value: str) -> str:
        try:
            day = iso_date(value) + timedelta(days=1)
            for _ in range(10000):
                if self.is_open(day):
                    return day.isoformat()
                day += timedelta(days=1)
        except OverflowError:
            pass
        raise DomainError("No supported business date follows this trade date")

    def to_dict(self) -> dict[str, Any]:
        data = dict(id=self.id, closed_dates=list(self.closed_dates), weekend=[5, 6])
        data["fingerprint"] = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
        return data

    @classmethod
    def from_dict(cls, data: object) -> "BusinessCalendar":
        try:
            if not isinstance(data, dict) or set(data) - {
                "id",
                "closed_dates",
                "weekend",
                "fingerprint",
            }:
                raise ValueError()
            if data.get("weekend", [5, 6]) != [5, 6]:
                raise ValueError()
            dates = data.get("closed_dates", [])
            if not isinstance(dates, list):
                raise ValueError()
            calendar = cls(data["id"], tuple(dates))
            if "fingerprint" in data and data["fingerprint"] != calendar.to_dict()["fingerprint"]:
                raise ValueError()
            return calendar
        except (KeyError, TypeError, ValueError, DomainError):
            raise DomainError(
                "Stored calendar policy is invalid or its fingerprint mismatches", 409
            )


def readiness(trade: Mapping[str, Any], clock: Clock) -> dict[str, Any]:
    if trade["settlement_model"] != "shared-ledger":
        return dict(
            governed=False, eligible=None, blockers=[], scope="Legacy trade-scoped contract"
        )
    try:
        policy = json.loads(trade["calendar_policy"])
    except (TypeError, ValueError):
        raise DomainError("Stored calendar policy is invalid", 409)
    calendar = BusinessCalendar.from_dict(policy)
    today = clock.today()
    due = iso_date(trade["settlement_date"])
    blockers = []

    def block(code: str, message: str) -> None:
        blockers.append(dict(code=code, message=message))

    if trade["state"] == "SETTLED":
        block("ALREADY_SETTLED", "Settlement is already recorded")
    elif trade["state"] not in ("AFFIRMED", "FAILED"):
        block("INSTRUCTIONS_NOT_APPROVED", "Current matched instructions require checker approval")
    if today < due:
        block("NOT_DUE", "Business date precedes the agreed settlement date")
    if not calendar.is_open(today):
        block("CALENDAR_CLOSED", "The business date is closed under the pinned calendar")
    if not calendar.is_open(due):
        block(
            "INVALID_SETTLEMENT_DAY", "Agreed settlement date is closed under the pinned calendar"
        )
    if trade["cash_cents"] < trade["quantity"] * trade["price_cents"]:
        block("INSUFFICIENT_CASH", "Buyer shared cash is insufficient")
    if trade["securities"] < trade["quantity"]:
        block("INSUFFICIENT_SECURITIES", "Seller shared securities are insufficient")
    return dict(
        governed=True,
        eligible=not blockers,
        business_time=clock.describe(),
        calendar=calendar.to_dict(),
        settlement_date=trade["settlement_date"],
        blockers=blockers,
    )
