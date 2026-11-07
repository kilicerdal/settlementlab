"""Pure multi-asset posting invariants; no persistence or network access."""

from collections import defaultdict
from typing import Sequence

from .validation import DomainError

LIMIT = 10**15


def asset(value: object) -> str:
    if value == "CASH:USD":
        return "CASH:USD"
    if isinstance(value, str) and value.startswith("SEC:"):
        symbol = value[4:]
        if (
            symbol.isascii()
            and symbol.isalnum()
            and symbol.upper() == symbol
            and 1 <= len(symbol) <= 12
        ):
            return value
    raise DomainError("Asset must be CASH:USD or SEC:<uppercase symbol>")


def balanced_changes(lines: Sequence[tuple[str, str, int]]) -> dict[tuple[str, str], int]:
    if len(lines) < 2:
        raise DomainError("Journal requires balanced posting lines")
    totals: dict[str, int] = defaultdict(int)
    changes: dict[tuple[str, str], int] = defaultdict(int)
    for party, unit, delta in lines:
        asset(unit)
        if (
            isinstance(delta, bool)
            or not isinstance(delta, int)
            or not -LIMIT <= delta <= LIMIT
            or delta == 0
        ):
            raise DomainError("Journal deltas must be nonzero bounded integers")
        totals[unit] += delta
        changes[(party, unit)] += delta
    if any(totals.values()):
        raise DomainError("Journal must balance independently for every asset")
    return dict(changes)
