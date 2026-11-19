"""Maker/checker compensating entries; original execution receipts stay immutable."""

from uuid import uuid4

from ..core.durable import fingerprint, identifier
from ..core.identity import require
from ..core.validation import DomainError
from .lifecycle import review_reason


class Corrections:
    def __init__(self, service):
        self.service = service

    def command(self, repository, trade_id, action, data, principal):
        requesting = action == "request-reversal"
        require(principal, "maker" if requesting else "checker")
        allowed = (
            {"version", "original_batch", "reason", "request_key"}
            if requesting
            else {"version", "reversal_id", "reason"}
        )
        if set(data) != allowed:
            raise DomainError("Correction command requires exactly the documented fields")
        reason = review_reason(data.get("reason"))
        digest = fingerprint(dict(action=action, data=data, actor=principal.id))
        trade = self.service.get(repository, identifier(trade_id))
        if trade["settlement_model"] != "shared-ledger":
            raise DomainError("Corrections require shared-ledger execution", 409)
        if requesting:
            key = identifier(data["request_key"])
            old = next(
                (r for r in repository.reversal_requests(trade_id) if r["request_key"] == key), None
            )
            if old:
                if old["fingerprint"] != digest:
                    raise DomainError("Reversal request key conflicts", 409)
                return old
        else:
            request = repository.reversal_find(identifier(data["reversal_id"]))
            if not request or request["trade_id"] != trade_id:
                raise DomainError("Reversal request not found", 404)
            if request["maker_id"] == principal.id:
                raise DomainError("Reversal requires a different checker identity", 403)
            if request["status"] != "PENDING":
                if request["decision_fingerprint"] == digest:
                    return request
                raise DomainError("Correction decision conflicts with retained evidence", 409)
        if type(data["version"]) is not int or data["version"] != trade["version"]:
            raise DomainError("Stale expected trade version", 409)
        if requesting:
            if trade["state"] == "CORRECTION_PENDING":
                raise DomainError("Review the pending correction before requesting another", 409)
            batch_id = identifier(data["original_batch"])
            original = repository.reversal_original(trade, batch_id)
            if any(
                r["original_batch"] == batch_id and r["status"] in ("PENDING", "APPROVED")
                for r in repository.reversal_requests(trade_id)
            ):
                raise DomainError("Execution already has a pending or posted reversal", 409)
            from datetime import datetime, timezone

            request = dict(
                id="CR-" + uuid4().hex,
                trade_id=trade_id,
                original_batch=batch_id,
                request_key=key,
                fingerprint=digest,
                maker_id=principal.id,
                reason=reason,
                created_at=datetime.now(timezone.utc).isoformat(),
                original_state=trade["state"],
                quantity=original["quantity"],
                amount_cents=original["amount_cents"],
            )
            repository.lifecycle_fence(
                trade, "Correction requested; independent review required", principal.id
            )
            repository.reversal_insert(request, trade)
            result = repository.reversal_find(request["id"])
        else:
            if trade["state"] != "CORRECTION_PENDING":
                raise DomainError("Trade is no longer awaiting this correction", 409)
            original = repository.reversal_original(trade, request["original_batch"])
            result = repository.reversal_decide(
                request, trade, action, principal.id, reason, digest, original
            )
        self.service.event(
            repository, trade_id, principal.id, action.upper(), result["id"] + ": " + reason
        )
        return result
