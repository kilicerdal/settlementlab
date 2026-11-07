"""Workflow principal and role policy, independent of session transport."""

from dataclasses import dataclass

from .validation import DomainError


@dataclass(frozen=True)
class Principal:
    id: str
    role: str


def require(principal: object, role: str) -> None:
    if not isinstance(principal, Principal) or principal.role != role:
        raise DomainError("This operation requires the " + role + " demo identity", 403)
