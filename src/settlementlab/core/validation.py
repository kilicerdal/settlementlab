"""Shared exact-value validation and domain errors."""

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation


class DomainError(Exception):
    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def cents(value: object) -> int:
    try:
        amount = Decimal(str(value))
        exponent = amount.as_tuple().exponent
        if not amount.is_finite() or amount <= 0 or not isinstance(exponent, int) or exponent < -2:
            raise ValueError()
        result = int(amount * 100)
        if result > 10**12:
            raise ValueError()
        return result
    except (InvalidOperation, ValueError, TypeError):
        raise DomainError("Price must be positive, at most two decimal places, and within limits")


def positive_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= 10**9:
        raise DomainError("Quantity must be an integer between 1 and 1,000,000,000")
    return value


def next_business_day(value: str) -> str:
    """V1 calendar: weekdays only; no exchange holiday assumptions."""
    day = date.fromisoformat(value) + timedelta(days=1)
    while day.weekday() > 4:
        day += timedelta(days=1)
    return day.isoformat()
