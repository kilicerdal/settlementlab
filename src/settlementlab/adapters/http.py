"""Local-only HTTP adapter. No production authentication is implied."""

import json
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from threading import BoundedSemaphore

from ..core.validation import DomainError
from ..infrastructure.demo_sessions import PERSONAS, DemoSessions
from .ai import Triage

ASSETS = Path(__file__).resolve().parents[1] / "static"


def handler(ledger, triage=None):
    triage = triage or Triage()
    ai_slots = BoundedSemaphore(1)
    sessions = DemoSessions()

    class Handler(BaseHTTPRequestHandler):
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

        def session_info(self, principal):
            return dict(
                principal=dict(id=principal.id, role=principal.role) if principal else None,
                mode="freely-switchable-local-demo",
                personas=[dict(id=p.id, role=p.role) for p in PERSONAS.values()],
            )

        def do_GET(self):
            parts = self.path.strip("/").split("/")
            if len(parts) == 4 and parts[:2] == ["api", "trades"] and parts[3] == "readiness":
                try:
                    return self.reply(200, ledger.settlement_readiness(parts[2]))
                except DomainError as error:
                    return self.reply(error.status, {"error": str(error)})
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
                        "version": "2.5.0",
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
            }
            if self.path in assets:
                name, mime = assets[self.path]
                return self.reply(200, (ASSETS / name).read_bytes(), mime)
            self.reply(404, {"error": "Not found"})

        def do_POST(self):
            # Reject cross-origin browser writes to the unauthenticated local demo.
            origin = self.headers.get("Origin")
            if origin and origin != "http://" + self.headers.get("Host", ""):
                return self.reply(403, {"error": "Cross-origin writes are disabled"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 65536:
                    raise DomainError("Request body must contain 1–65536 bytes", 413)
                data = json.loads(self.rfile.read(length))
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
                    if parts[3] == "request-affirmation":
                        data["request_key"] = self.headers.get("Idempotency-Key")
                    if parts[3] == "manager":
                        data["submission_key"] = self.headers.get("Idempotency-Key")
                    return self.reply(
                        200, ledger.command(parts[2], parts[3], data, principal=principal)
                    )
                raise DomainError("Not found", 404)
            except DomainError as error:
                self.reply(error.status, {"error": str(error)})
            except (ValueError, UnicodeError):
                self.reply(400, {"error": "Malformed JSON or content length"})
            except Exception:
                self.log_error("Unhandled request failure")
                self.reply(500, {"error": "Internal server error"})

    return Handler
