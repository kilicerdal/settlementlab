"""Local-only HTTP adapter. No production authentication is implied."""
import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .domain import Ledger, DomainError
from .ai import Triage
from threading import BoundedSemaphore

ASSETS = Path(__file__).resolve().parent / "static"


def handler(ledger, triage=None):
    triage = triage or Triage()
    ai_slots = BoundedSemaphore(1)
    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, body, content_type="application/json"):
            raw = json.dumps(body).encode() if content_type == "application/json" else body
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path == "/api/health":
                return self.reply(200, {"status": "healthy", "version": "2.1.0", "ai_enabled": triage.enabled})
            if self.path == '/api/matching-policy':
                from .matching import policy_description
                return self.reply(200, policy_description())
            if self.path == "/api/snapshot":
                return self.reply(200, ledger.snapshot())
            assets = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css")}
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
                if self.path == "/api/trades":
                    return self.reply(201, ledger.create(data, self.headers.get("Idempotency-Key")))
                if self.path == "/api/reconcile":
                    return self.reply(200, ledger.reconcile(data.get("statement")))
                parts = self.path.strip("/").split("/")
                if len(parts) == 4 and parts[:2] == ["api", "trades"]:
                    if parts[3] == "analyze":
                        evidence = ledger.evidence(parts[2], data.get("version"))
                        if not ai_slots.acquire(blocking=False):
                            raise DomainError("An AI analysis is already running; try again shortly", 429)
                        try:
                            return self.reply(200, triage.analyze(evidence))
                        finally:
                            ai_slots.release()
                    if parts[3] == 'manager':
                        data['submission_key'] = self.headers.get('Idempotency-Key')
                    return self.reply(200, ledger.command(parts[2], parts[3], data))
                raise DomainError("Not found", 404)
            except DomainError as error:
                self.reply(error.status, {"error": str(error)})
            except (ValueError, UnicodeError):
                self.reply(400, {"error": "Malformed JSON or content length"})
            except Exception:
                self.log_error("Unhandled request failure")
                self.reply(500, {"error": "Internal server error"})
    return Handler


def main():
    parser = argparse.ArgumentParser(description="SettlementLab local operations workbench")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--db", default=os.getenv("SETTLEMENTLAB_DB", "settlementlab.db"))
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(Ledger(args.db)))
    print("SettlementLab running at http://127.0.0.1:%s" % args.port, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
