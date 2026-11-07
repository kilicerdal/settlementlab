"""Independent reference API; not a custody service or production deployment."""

import argparse
import json
import re
import sqlite3
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4


class Rejected(Exception):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


class Inventory:
    def __init__(self, path, fault=False):
        self.path = str(path)
        self.fault = fault
        with self.transaction() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS inventory(asset TEXT PRIMARY KEY,available INTEGER NOT NULL CHECK(available>=0))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS reservations(id TEXT PRIMARY KEY,request_key TEXT UNIQUE NOT NULL,asset TEXT NOT NULL REFERENCES inventory(asset),quantity INTEGER NOT NULL,status TEXT NOT NULL)"
            )

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def stock(self, db, asset):
        row = db.execute("SELECT * FROM inventory WHERE asset=?", (asset,)).fetchone()
        if not row:
            raise Rejected("Unknown asset", 404)
        return dict(row)

    def create(self, data):
        asset = data.get("asset")
        amount = data.get("quantity")
        if not isinstance(asset, str) or not re.fullmatch("[A-Z0-9-]{1,64}", asset):
            raise Rejected("Invalid synthetic asset")
        if isinstance(amount, bool) or not isinstance(amount, int) or not 0 < amount <= 10**9:
            raise Rejected("Invalid inventory quantity")
        with self.transaction() as db:
            if db.execute("SELECT 1 FROM inventory WHERE asset=?", (asset,)).fetchone():
                raise Rejected("Asset already exists", 409)
            db.execute("INSERT INTO inventory VALUES (?,?)", (asset, amount))
            return self.stock(db, asset)

    def reserve(self, data, key):
        if not isinstance(key, str) or not 1 <= len(key) <= 120:
            raise Rejected("Idempotency-Key required")
        quantity = data.get("quantity")
        asset = data.get("asset")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or not 0 < quantity <= 10**9:
            raise Rejected("Invalid reservation quantity")
        if not isinstance(asset, str):
            raise Rejected("Invalid asset")
        with self.transaction() as db:
            old = db.execute("SELECT * FROM reservations WHERE request_key=?", (key,)).fetchone()
            if old:
                if old["asset"] != asset or old["quantity"] != quantity:
                    raise Rejected("Replay payload conflicts", 409)
                if not self.fault:
                    return 200, dict(old)
                # Deliberately injected fault for the negative demonstration only.
                key = key + "-fault-" + uuid4().hex
            current = self.stock(db, asset)
            if current["available"] < quantity:
                raise Rejected("Insufficient inventory", 409)
            identifier = "R-" + uuid4().hex[:16].upper()
            db.execute(
                "UPDATE inventory SET available=available-? WHERE asset=?", (quantity, asset)
            )
            db.execute(
                "INSERT INTO reservations VALUES (?,?,?,?,'ACTIVE')",
                (identifier, key, asset, quantity),
            )
            return 201, dict(id=identifier, asset=asset, quantity=quantity, status="ACTIVE")

    def release(self, identifier):
        with self.transaction() as db:
            row = db.execute("SELECT * FROM reservations WHERE id=?", (identifier,)).fetchone()
            if not row:
                raise Rejected("Unknown reservation", 404)
            if row["status"] == "ACTIVE":
                db.execute("UPDATE reservations SET status='RELEASED' WHERE id=?", (identifier,))
                db.execute(
                    "UPDATE inventory SET available=available+? WHERE asset=?",
                    (row["quantity"], row["asset"]),
                )
            return dict(
                id=identifier, asset=row["asset"], quantity=row["quantity"], status="RELEASED"
            )


def handler(inventory):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, body):
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            try:
                if self.path == "/health":
                    return self.reply(
                        200,
                        dict(service="collateral-reservation-demo", fault_enabled=inventory.fault),
                    )
                if self.path.startswith("/inventory/"):
                    with inventory.transaction() as db:
                        return self.reply(
                            200, inventory.stock(db, self.path.removeprefix("/inventory/"))
                        )
                raise Rejected("Not found", 404)
            except Rejected as error:
                self.reply(error.status, dict(error=str(error)))

        def do_POST(self):
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 65536:
                    raise Rejected("Invalid body size", 413)
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise Rejected("Body must be an object")
                if self.path == "/inventory":
                    return self.reply(201, inventory.create(data))
                if self.path == "/reservations":
                    status, result = inventory.reserve(data, self.headers.get("Idempotency-Key"))
                    return self.reply(status, result)
                parts = self.path.strip("/").split("/")
                if len(parts) == 3 and parts[0] == "reservations" and parts[2] == "release":
                    return self.reply(200, inventory.release(parts[1]))
                raise Rejected("Not found", 404)
            except Rejected as error:
                self.reply(error.status, dict(error=str(error)))
            except (ValueError, UnicodeError):
                self.reply(400, dict(error="Malformed request"))

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--db", default="collateral-demo.db")
    parser.add_argument("--fault-duplicate-replay", action="store_true")
    args = parser.parse_args()
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port), handler(Inventory(args.db, args.fault_duplicate_replay))
    )
    print("Collateral demonstration on http://127.0.0.1:" + str(server.server_port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
