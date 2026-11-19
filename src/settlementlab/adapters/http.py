"""Local-only HTTP adapter. No production authentication is implied."""

import json
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from threading import BoundedSemaphore
from urllib.parse import urlsplit

from .. import __version__
from ..core.validation import DomainError
from ..infrastructure.demo_sessions import PERSONAS, DemoSessions
from .ai import Triage

ASSETS = Path(__file__).resolve().parents[1] / "static"


def handler(ledger, triage=None, operations=None):
    from ..application.operations import DurableOperations

    operations = operations or DurableOperations(ledger)
    triage = triage or Triage()
    ai_slots = BoundedSemaphore(1)
    sessions = DemoSessions()

    class Handler(BaseHTTPRequestHandler):
        def validate_host(self):
            try:
                parsed = urlsplit("http://" + self.headers.get("Host", ""))
                valid = (
                    parsed.hostname in ("127.0.0.1", "localhost", "::1")
                    and parsed.username is None
                    and parsed.password is None
                    and not parsed.path
                    and not parsed.query
                    and not parsed.fragment
                    and (parsed.port is None or 0 < parsed.port <= 65535)
                )
            except ValueError:
                valid = False
            if not valid:
                raise DomainError("Local demo requires a loopback Host", 400)

        def reply(self, status, body, content_type="application/json", cookie=None):
            raw = json.dumps(body).encode() if content_type == "application/json" else body
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'",
            )
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(raw)

        def operation_reply(self, status, body):
            def public(value):
                if isinstance(value, dict):
                    return {
                        key: public(item) for key, item in value.items() if key != "lease_token"
                    }
                if isinstance(value, list):
                    return [public(item) for item in value]
                return value

            return self.reply(status, public(body))

        def session_info(self, principal):
            return dict(
                principal=dict(id=principal.id, role=principal.role) if principal else None,
                mode="freely-switchable-local-demo",
                personas=[dict(id=p.id, role=p.role) for p in PERSONAS.values()],
            )

        def do_GET(self):
            try:
                self.read_request()
            except DomainError as error:
                self.reply(error.status, {"error": str(error)})
            except Exception:
                self.log_error("Unhandled read failure")
                self.reply(500, {"error": "Internal server error"})

        def read_request(self):
            self.validate_host()
            parts = self.path.strip("/").split("/")
            if len(parts) == 4 and parts[:2] == ["api", "trades"] and parts[3] == "readiness":
                try:
                    return self.reply(200, ledger.settlement_readiness(parts[2]))
                except DomainError as error:
                    return self.reply(error.status, {"error": str(error)})
            if len(parts) == 4 and parts[:3] == ["api", "reconciliation", "statements"]:
                from ..application.reconciliation import Reconciliation

                return self.reply(200, Reconciliation(ledger).statement(parts[3]))
            if self.path == "/api/reconciliation":
                from ..application.reconciliation import Reconciliation

                return self.reply(200, Reconciliation(ledger).snapshot())
            if self.path == "/api/operations":
                return self.reply(200, operations.snapshot())
            if self.path == "/api/session":
                return self.reply(
                    200, self.session_info(sessions.resolve(self.headers.get("Cookie")))
                )
            if self.path == "/api/treasury":
                return self.reply(200, ledger.snapshot()["treasury"])
            if self.path == "/api/health":
                return self.reply(
                    200,
                    {
                        "status": "healthy",
                        "version": __version__,
                        "ai_enabled": triage.enabled,
                        "business_time": ledger.clock.describe(),
                    },
                )
            if self.path == "/api/matching-policy":
                from ..core.matching import policy_description

                return self.reply(200, policy_description())
            if self.path == "/api/snapshot":
                return self.reply(200, ledger.snapshot())
            assets = {
                "/": ("index.html", "text/html; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript"),
                "/style.css": ("style.css", "text/css"),
                "/lifecycle": ("lifecycle.html", "text/html; charset=utf-8"),
                "/lifecycle.css": ("lifecycle.css", "text/css"),
                "/lifecycle.js": ("lifecycle.js", "text/javascript"),
                "/operations": ("operations.html", "text/html; charset=utf-8"),
                "/operations.js": ("operations.js", "text/javascript"),
                "/operations.css": ("operations.css", "text/css"),
            }
            if self.path in assets:
                name, mime = assets[self.path]
                return self.reply(200, (ASSETS / name).read_bytes(), mime)
            self.reply(404, {"error": "Not found"})

        def do_POST(self):
            try:
                self.validate_host()
            except DomainError as error:
                return self.reply(error.status, {"error": str(error)})
            # Reject cross-origin browser writes to the unauthenticated local demo.
            origin = self.headers.get("Origin")
            if origin and origin != "http://" + self.headers.get("Host", ""):
                return self.reply(403, {"error": "Cross-origin writes are disabled"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 65536:
                    raise DomainError("Request body must contain 1–65536 bytes", 413)

                def unique_fields(pairs):
                    result = {}
                    for key, value in pairs:
                        if key in result:
                            raise ValueError("Duplicate JSON field")
                        result[key] = value
                    return result

                def reject_constant(value):
                    raise ValueError("Nonfinite JSON number")

                data = json.loads(
                    self.rfile.read(length),
                    object_pairs_hook=unique_fields,
                    parse_constant=reject_constant,
                )
                if not isinstance(data, dict):
                    raise DomainError("Request body must be an object")
                principal = sessions.resolve(self.headers.get("Cookie"))
                if self.path == "/api/session":
                    token, principal = sessions.start(data.get("persona"))
                    return self.reply(
                        200,
                        self.session_info(principal),
                        cookie="settlementlab_session="
                        + token
                        + "; HttpOnly; SameSite=Strict; Path=/; Max-Age=3600",
                    )
                if self.path == "/api/operations/batches":
                    if set(data) - {"trades", "max_attempts"}:
                        raise DomainError("Unknown batch fields")
                    return self.operation_reply(
                        202,
                        operations.enqueue_batch(
                            data.get("trades"),
                            self.headers.get("Idempotency-Key"),
                            principal,
                            data.get("max_attempts", 3),
                        ),
                    )
                operation_parts = self.path.strip("/").split("/")
                if len(operation_parts) == 5 and operation_parts[:2] == ["api", "operations"]:
                    kind, identifier, action = operation_parts[2:]
                    if kind == "jobs" and action == "requeue":
                        if set(data) != {"version", "reason"}:
                            raise DomainError("Requeue requires only version and reason")
                        return self.operation_reply(
                            200,
                            operations.requeue(
                                identifier, data.get("version"), data.get("reason"), principal
                            ),
                        )
                    if kind == "events" and action == "retry":
                        if set(data) != {"reason"}:
                            raise DomainError("Retry requires only reason")
                        return self.reply(
                            200, operations.retry_event(identifier, data.get("reason"), principal)
                        )
                    if kind == "events" and action == "redeliver":
                        if data:
                            raise DomainError("Redelivery takes an empty object")
                        return self.reply(200, operations.redeliver(identifier, principal))
                if self.path == "/api/treasury/fund":
                    return self.reply(
                        200,
                        ledger.fund_participant(
                            data, self.headers.get("Idempotency-Key"), principal
                        ),
                    )
                if self.path == "/api/trades":
                    return self.reply(
                        201,
                        ledger.create(
                            data, self.headers.get("Idempotency-Key"), principal=principal
                        ),
                    )
                if self.path == "/api/reconciliation/statements":
                    from ..application.reconciliation import Reconciliation

                    return self.reply(
                        201,
                        Reconciliation(ledger).import_statement(
                            data.get("statement"), self.headers.get("Idempotency-Key"), principal
                        ),
                    )
                resolution = self.path.strip("/").split("/")
                if (
                    len(resolution) == 5
                    and resolution[:3] == ["api", "reconciliation", "cases"]
                    and resolution[4] == "resolve"
                ):
                    from ..application.reconciliation import Reconciliation

                    return self.reply(
                        200,
                        Reconciliation(ledger).resolve(
                            resolution[3], data.get("statement_id"), data.get("reason"), principal
                        ),
                    )
                if self.path == "/api/reconcile":
                    return self.reply(200, ledger.reconcile(data.get("statement")))
                parts = self.path.strip("/").split("/")
                if len(parts) == 4 and parts[:2] == ["api", "trades"]:
                    if parts[3] == "analyze":
                        evidence = ledger.evidence(parts[2], data.get("version"))
                        if not ai_slots.acquire(blocking=False):
                            raise DomainError(
                                "An AI analysis is already running; try again shortly", 429
                            )
                        try:
                            return self.reply(200, triage.analyze(evidence))
                        finally:
                            ai_slots.release()
                    if parts[3] in ("request-affirmation", "amend", "cancel", "settle-partial"):
                        data["request_key"] = self.headers.get("Idempotency-Key")
                    if parts[3] == "manager":
                        data["submission_key"] = self.headers.get("Idempotency-Key")
                    return self.reply(
                        200, ledger.command(parts[2], parts[3], data, principal=principal)
                    )
                raise DomainError("Not found", 404)
            except DomainError as error:
                self.reply(error.status, {"error": str(error)})
            except (ValueError, UnicodeError, RecursionError):
                self.reply(400, {"error": "Malformed JSON or content length"})
            except Exception:
                self.log_error("Unhandled request failure")
                self.reply(500, {"error": "Internal server error"})

    return Handler
