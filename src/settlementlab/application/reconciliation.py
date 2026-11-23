"""Immutable statement imports and evidence-verified break resolution."""

import json
from datetime import datetime, timezone
from uuid import uuid4

from ..core.durable import fingerprint, identifier
from ..core.identity import require
from ..core.statements import classify, statement_rows
from ..core.validation import DomainError
from .lifecycle import review_reason


class Reconciliation:
    def __init__(self, service):
        self.service = service

    def import_statement(self, value, key, principal):
        require(principal, "checker")
        identifier(key)
        rows = statement_rows(value)
        digest = fingerprint(rows)
        with self.service.store.transaction() as repository:
            existing = repository.recon_statement(key)
            if existing:
                if existing["fingerprint"] != digest or existing["actor"] != principal.id:
                    raise DomainError(
                        "Statement key conflicts with immutable imported evidence", 409
                    )
                return dict(
                    id=existing["id"], replayed=True, cases=repository.recon_cases(existing["id"])
                )
            internal = [dict(r) for r in repository.recon_executions()]
            cases = classify(internal, rows)
            statement = dict(
                id="R-" + uuid4().hex,
                key=key,
                fingerprint=digest,
                rows=json.dumps(rows),
                internal_snapshot=json.dumps(internal),
                actor=principal.id,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            repository.recon_save(statement, cases)
            self.service.event(
                repository,
                "RECONCILIATION",
                principal.id,
                "STATEMENT_IMPORTED",
                statement["id"] + ": " + str(len(cases)) + " break(s)",
            )
            return dict(
                id=statement["id"],
                replayed=False,
                accounting_basis="NET_AFTER_APPROVED_COMPENSATIONS",
                cases=repository.recon_cases(statement["id"]),
            )

    def resolve(self, case_id, statement_id, reason, principal):
        require(principal, "checker")
        identifier(case_id)
        identifier(statement_id)
        reason = review_reason(reason)
        with self.service.store.transaction() as repository:
            case = repository.recon_case(case_id)
            evidence = repository.recon_statement(statement_id, True)
            if not case or not evidence:
                raise DomainError("Break or evidence statement not found", 404)
            if case["statement_id"] == statement_id:
                raise DomainError(
                    "Resolution requires independently imported follow-up evidence", 409
                )
            if case["status"] == "RESOLVED":
                if (
                    case["reason"] != reason
                    or case["evidence_statement_id"] != statement_id
                    or case["resolved_by"] != principal.id
                ):
                    raise DomainError("Resolution conflicts with retained decision", 409)
                return dict(
                    case,
                    accounting_basis="NET_AFTER_APPROVED_COMPENSATIONS",
                    contract_version="net-statement-v1",
                )
            internal = [dict(r) for r in repository.recon_executions()]
            rows = json.loads(evidence["rows"])
            current = classify(internal, rows)
            if any(c["trade_id"] == case["trade_id"] for c in current):
                raise DomainError(
                    "Follow-up statement does not resolve this break against current records", 409
                )
            snapshot = dict(
                internal=internal,
                external_fingerprint=evidence["fingerprint"],
                remaining_breaks=current,
            )
            repository.recon_resolve(case_id, principal.id, reason, statement_id, snapshot)
            self.service.event(
                repository,
                "RECONCILIATION",
                principal.id,
                "BREAK_RESOLVED",
                case_id + ": " + reason,
            )
            return dict(
                repository.recon_case(case_id),
                accounting_basis="NET_AFTER_APPROVED_COMPENSATIONS",
                contract_version="net-statement-v1",
            )

    def statement(self, statement_id):
        identifier(statement_id)
        with self.service.store.read_transaction() as repository:
            result = repository.recon_statement(statement_id, True)
            if not result:
                raise DomainError("Imported statement not found", 404)
            result["accounting_basis"] = "NET_AFTER_APPROVED_COMPENSATIONS"
            result["contract_version"] = "net-statement-v1"
            result["rows"] = json.loads(result["rows"])
            result["internal_snapshot"] = json.loads(result["internal_snapshot"])
            return result

    def snapshot(self):
        with self.service.store.read_transaction() as repository:
            return dict(
                cases=repository.recon_cases(),
                accounting_basis="NET_AFTER_APPROVED_COMPENSATIONS",
                contract_version="net-statement-v1",
                scope="Full imported statement versus net executed obligations after approved compensations; original discrepancies and gross receipts are immutable",
            )
