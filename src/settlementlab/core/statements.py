"""Bounded independent-statement parsing and pure reconciliation classification."""

import csv
import io
from typing import Any

from .validation import DomainError


def statement_rows(value: object) -> list[dict[str, Any]]:
    if isinstance(value, str):
        if len(value.encode()) > 65536:
            raise DomainError("Statement CSV exceeds 64 KiB")
        try:
            reader = csv.DictReader(io.StringIO(value), strict=True)
            if reader.fieldnames != ["trade_id", "quantity", "amount_cents"]:
                raise DomainError("CSV header must be trade_id,quantity,amount_cents")
            rows = []
            for row in reader:
                if set(row) != set(reader.fieldnames) or any(v is None for v in row.values()):
                    raise DomainError("Malformed statement row")
                rows.append(
                    dict(
                        trade_id=row["trade_id"],
                        quantity=int(row["quantity"]),
                        amount_cents=int(row["amount_cents"]),
                    )
                )
        except (ValueError, csv.Error, TypeError):
            raise DomainError("Statement quantities and cents must be exact integers")
    elif isinstance(value, list):
        rows = value
    else:
        raise DomainError("Provide a CSV string or a statement row array")
    if len(rows) > 1000:
        raise DomainError("Statement exceeds 1,000 rows")
    seen = set()
    normalized = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"trade_id", "quantity", "amount_cents"}:
            raise DomainError("Invalid statement row fields")
        key = row["trade_id"]
        if (
            not isinstance(key, str)
            or not 1 <= len(key) <= 120
            or any(ord(c) < 32 for c in key)
            or key in seen
        ):
            raise DomainError("Statement trade IDs must be unique bounded strings")
        if any(
            type(row[k]) is not int or not 0 <= row[k] <= 10**15
            for k in ("quantity", "amount_cents")
        ):
            raise DomainError("Statement values must be nonnegative bounded exact integers")
        seen.add(key)
        normalized.append(dict(row))
    return sorted(normalized, key=lambda r: r["trade_id"])


def classify(
    internal: list[dict[str, Any]], external: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    left = {r["trade_id"]: r for r in internal}
    right = {r["trade_id"]: r for r in external}
    cases = []
    for trade in sorted(left.keys() | right.keys()):
        if trade not in left:
            kind = "MISSING_INTERNAL"
        elif trade not in right:
            kind = "MISSING_EXTERNAL"
        elif any(left[trade][k] != right[trade][k] for k in ("quantity", "amount_cents")):
            kind = "VALUE_MISMATCH"
        else:
            continue
        cases.append(
            dict(trade_id=trade, kind=kind, expected=left.get(trade), observed=right.get(trade))
        )
    return cases
