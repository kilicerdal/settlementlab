"""Versioned amendments, immutable posted value and explicit partial execution."""

import json
from datetime import datetime

from ..core.calendar import BusinessCalendar
from ..core.durable import bounded_integer, fingerprint, identifier
from ..core.identity import require
from ..core.matching import normalize_terms
from ..core.postings import LIMIT
from ..core.validation import DomainError


def review_reason(value):
    if (
        not isinstance(value, str)
        or not 5 <= len(value.strip()) <= 300
        or any(ord(c) < 32 for c in value)
    ):
        raise DomainError("Review requires a single-line reason of 5–300 characters")
    return value.strip()


class Lifecycle:
    def __init__(self, service):
        self.service = service

    def command(self, repository, trade_id, action, data, principal):
        require(principal, "maker" if action == "amend" else "checker")
        key = identifier(data.get("request_key"))
        reason = review_reason(data.get("reason")) if action in ("amend", "cancel") else None
        allowed = (
            {"version", "request_key", "reason", "terms"}
            if action == "amend"
            else {"version", "request_key", "reason"}
            if action == "cancel"
            else {"version", "request_key", "quantity"}
        )
        if set(data) - allowed:
            raise DomainError("Unknown lifecycle command fields")
        digest = fingerprint(
            dict(
                action=action,
                data={k: v for k, v in data.items() if k != "request_key"},
                actor=principal.id,
            )
        )
        previous = repository.lifecycle_replay(trade_id, action, key)
        if previous:
            if previous["fingerprint"] != digest:
                raise DomainError("Lifecycle key conflicts with earlier command", 409)
            return json.loads(previous["response"])
        trade = self.service.get(repository, trade_id)
        if trade["settlement_model"] != "shared-ledger":
            raise DomainError("Lifecycle controls require a shared-ledger trade", 409)
        if type(data.get("version")) is not int or data["version"] != trade["version"]:
            raise DomainError("Stale expected trade version", 409)
        if trade["state"] in ("CORRECTION_PENDING", "CORRECTION_REVIEW", "REVERSED"):
            raise DomainError("Correction workflow closes ordinary lifecycle commands", 409)
        if action == "amend":
            if trade["settled_quantity"] or trade["state"] in ("SETTLED", "CANCELLED"):
                raise DomainError(
                    "Posted terms are immutable; only unposted trades may be amended", 409
                )
            raw = data.get("terms")
            if not isinstance(raw, dict) or set(raw) != {
                "symbol",
                "side",
                "currency",
                "quantity",
                "price",
                "trade_date",
                "settlement_date",
            }:
                raise DomainError("Amendment requires complete broker terms")
            terms = normalize_terms(raw)
            policy = BusinessCalendar.from_dict(json.loads(trade["calendar_policy"]))
            if terms["currency"] != "USD" or terms["quantity"] * terms["price_cents"] > LIMIT:
                raise DomainError("Shared-ledger amendment exceeds supported USD limits")
            if not policy.is_open(datetime.fromisoformat(terms["trade_date"]).date()) or terms[
                "settlement_date"
            ] != policy.next_day(terms["trade_date"]):
                raise DomainError("Amended dates must follow the pinned business calendar")
            manager, broker = (
                (trade["buyer_id"], trade["seller_id"])
                if trade["side"] == "BUY"
                else (trade["seller_id"], trade["buyer_id"])
            )
            terms.update(
                buyer_id=manager if terms["side"] == "BUY" else broker,
                seller_id=broker if terms["side"] == "BUY" else manager,
            )
            repository.lifecycle_fence(
                trade, "Amended terms require fresh matching and approval", principal.id
            )
            repository.lifecycle_amend(trade, terms)
            updated = self.service.get(repository, trade_id)
            repository.lifecycle_revision(updated, principal.id, reason)
        elif action == "cancel":
            if trade["state"] in ("SETTLED", "CANCELLED") or not trade["remaining_quantity"]:
                raise DomainError("No cancellable remaining obligation", 409)
            repository.lifecycle_fence(
                trade, "Remaining obligation cancelled: " + reason, principal.id
            )
            repository.lifecycle_cancel(trade, reason)
        elif action == "settle-partial":
            self.post_slice(
                repository,
                trade,
                data["quantity"] if "quantity" in data else None,
                key,
                principal.id,
            )
        else:
            raise DomainError("Unknown lifecycle action", 404)
        self.service.event(
            repository,
            trade_id,
            principal.id,
            action.upper(),
            reason or "Explicit execution slice " + key,
        )
        result = self.service.get(repository, trade_id)
        repository.lifecycle_record(trade_id, action, key, digest, result)
        return result

    def post_slice(self, repository, trade, quantity, key, actor):
        if trade["state"] not in (
            "AFFIRMED",
            "FAILED",
            "PARTIALLY_SETTLED",
        ) or not repository.current_authorized(trade):
            raise DomainError("Current trade revision requires independent checker approval", 409)
        bounded_integer(quantity, 1, trade["remaining_quantity"], "Execution quantity")
        blockers = [
            b["code"]
            for b in trade["settlement_readiness"]["blockers"]
            if b["code"]
            in ("NOT_DUE", "CALENDAR_CLOSED", "INVALID_SETTLEMENT_DAY", "CUTOFF_PASSED")
        ]
        if blockers:
            raise DomainError("Settlement calendar blocked: " + ", ".join(blockers), 409)
        if repository.treasury_snapshot()["controls"]["status"] != "BALANCED":
            raise DomainError("Ledger integrity check failed", 409)
        batch = repository.lifecycle_post_slice(trade, quantity, key, actor)
        if not batch:
            repository.fail_settlement(
                ("Insufficient shared capacity for requested execution slice", trade["id"])
            )
            repository.advance_version((trade["id"],))
        return self.service.get(repository, trade["id"])
