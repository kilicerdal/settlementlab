"""Transactional domain service. All amounts are integer cents in storage."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, date, timezone
from decimal import Decimal, InvalidOperation


class DomainError(Exception):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


def cents(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
            raise ValueError()
        result = int(amount * 100)
        if result > 10**12:
            raise ValueError()
        return result
    except (InvalidOperation, ValueError, TypeError):
        raise DomainError("Price must be positive, at most two decimal places, and within limits")


def positive_int(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= 10**9:
        raise DomainError("Quantity must be an integer between 1 and 1,000,000,000")
    return value


def next_business_day(value):
    """V1 calendar: weekdays only; no exchange holiday assumptions."""
    day = date.fromisoformat(value) + timedelta(days=1)
    while day.weekday() > 4:
        day += timedelta(days=1)
    return day.isoformat()


class Ledger:
    def __init__(self, path):
        self.path = str(path)
        with self.connection() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS trades (
              id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL,
              symbol TEXT NOT NULL, quantity INTEGER NOT NULL, price_cents INTEGER NOT NULL,
              trade_date TEXT NOT NULL, settlement_date TEXT NOT NULL,
              state TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
              allocations TEXT NOT NULL DEFAULT '[]', instruction TEXT, reason TEXT,
              cash_cents INTEGER NOT NULL DEFAULT 0, securities INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS audit (
              seq INTEGER PRIMARY KEY AUTOINCREMENT, trade_id TEXT NOT NULL,
              timestamp TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
              detail TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS settlements (
              trade_id TEXT PRIMARY KEY REFERENCES trades(id), quantity INTEGER NOT NULL,
              amount_cents INTEGER NOT NULL);
            ''')

    @contextmanager
    def connection(self):
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

    def event(self, db, trade, actor, action, detail):
        db.execute("INSERT INTO audit(trade_id,timestamp,actor,action,detail) VALUES (?,?,?,?,?)",
                   (trade, datetime.now(timezone.utc).isoformat(), actor, action, detail))

    def get(self, db, trade_id):
        row = db.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
        if row is None:
            raise DomainError("Trade not found", 404)
        return dict(row)

    def create(self, data, key, actor="broker"):
        if not isinstance(key, str) or not 1 <= len(key) <= 120:
            raise DomainError("An Idempotency-Key of 1–120 characters is required")
        symbol = data.get("symbol", "")
        if not isinstance(symbol, str) or not symbol.isascii() or not symbol.isalnum() or not 1 <= len(symbol) <= 12:
            raise DomainError("Symbol must contain 1–12 ASCII letters or digits")
        quantity = positive_int(data.get("quantity"))
        price = cents(data.get("price"))
        if quantity * price > 10**18:
            raise DomainError("Trade notional exceeds simulation limits")
        try:
            trade_date = date.fromisoformat(data["trade_date"]).isoformat()
            settlement_date = next_business_day(trade_date)
        except (KeyError, TypeError, ValueError, OverflowError):
            raise DomainError("trade_date must be an ISO date")
        fingerprint = json.dumps([symbol.upper(), quantity, price, trade_date])
        with self.connection() as db:
            existing = db.execute("SELECT * FROM trades WHERE request_key=?", (key,)).fetchone()
            if existing:
                if existing["fingerprint"] != fingerprint:
                    raise DomainError("Idempotency key already used for a different submission", 409)
                return dict(existing)
            number = db.execute("SELECT COUNT(*) FROM trades").fetchone()[0] + 1
            trade_id = "SL-%06d" % number
            db.execute('''INSERT INTO trades(id,request_key,fingerprint,symbol,quantity,price_cents,
                       trade_date,settlement_date,state) VALUES (?,?,?,?,?,?,?,?,?)''',
                       (trade_id, key, fingerprint, symbol.upper(), quantity, price, trade_date,
                        settlement_date, "RECEIVED"))
            self.event(db, trade_id, actor, "TRADE_RECEIVED", "Broker submission accepted")
            return self.get(db, trade_id)

    def command(self, trade_id, action, data, actor="operator"):
        with self.connection() as db:
            trade = self.get(db, trade_id)
            version = data.get("version")
            if isinstance(version, bool) or not isinstance(version, int) or version != trade["version"]:
                raise DomainError("Stale or missing version; refresh before updating", 409)
            state = trade["state"]
            if action == "allocate":
                if state not in ("RECEIVED", "EXCEPTION", "MATCHED"):
                    raise DomainError("Allocations cannot change after affirmation", 409)
                allocations = data.get("allocations")
                if not isinstance(allocations, list) or not 1 <= len(allocations) <= 100:
                    raise DomainError("Provide 1–100 allocations")
                accounts = set()
                for allocation in allocations:
                    if not isinstance(allocation, dict):
                        raise DomainError("Invalid allocation")
                    account = allocation.get("account")
                    if not isinstance(account, str) or not account.strip() or len(account) > 80 or account in accounts:
                        raise DomainError("Allocation accounts must be unique nonempty strings")
                    accounts.add(account)
                    positive_int(allocation.get("quantity"))
                total = sum(a["quantity"] for a in allocations)
                state = "MATCHED" if total == trade["quantity"] else "EXCEPTION"
                reason = None if state == "MATCHED" else "Allocation quantity %s differs from broker quantity %s" % (total, trade["quantity"])
                db.execute("UPDATE trades SET allocations=?,state=?,reason=? WHERE id=?",
                           (json.dumps(allocations), state, reason, trade_id))
            elif action == "affirm":
                if state != "MATCHED":
                    raise DomainError("Only matched trades can be affirmed", 409)
                instruction = data.get("instruction", "")
                if not isinstance(instruction, str) or not instruction.startswith("SYN-") or len(instruction) > 80:
                    raise DomainError("Provide a synthetic settlement instruction beginning SYN-")
                db.execute("UPDATE trades SET state='AFFIRMED',instruction=?,reason=NULL WHERE id=?", (instruction, trade_id))
            elif action == "fund":
                if state not in ("AFFIRMED", "FAILED"):
                    raise DomainError("Funding is available for affirmed or failed trades", 409)
                cash = data.get("cash_cents")
                securities = data.get("securities")
                if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 or v > 10**18 for v in (cash, securities)):
                    raise DomainError("Balances must be nonnegative bounded integers")
                db.execute("UPDATE trades SET cash_cents=?,securities=? WHERE id=?", (cash, securities, trade_id))
            elif action == "settle":
                if state not in ("AFFIRMED", "FAILED"):
                    raise DomainError("Only affirmed or failed trades can attempt settlement", 409)
                amount = trade["quantity"] * trade["price_cents"]
                ready = trade["cash_cents"] >= amount and trade["securities"] >= trade["quantity"]
                if ready:
                    db.execute("INSERT INTO settlements VALUES (?,?,?)", (trade_id, trade["quantity"], amount))
                    db.execute("UPDATE trades SET state='SETTLED',reason=NULL,cash_cents=cash_cents-?,securities=securities-? WHERE id=?", (amount, trade["quantity"], trade_id))
                else:
                    db.execute("UPDATE trades SET state='FAILED',reason=? WHERE id=?", ("Insufficient simulated cash or securities", trade_id))
            else:
                raise DomainError("Unknown action", 404)
            db.execute("UPDATE trades SET version=version+1 WHERE id=?", (trade_id,))
            updated = self.get(db, trade_id)
            detail = ("Demo balances provisioned; cash cents: %s, securities: %s" % (data["cash_cents"], data["securities"])) if action == "fund" else (updated["reason"] or "State: " + updated["state"])
            self.event(db, trade_id, actor, action.upper(), detail)
            return updated

    def snapshot(self):
        with self.connection() as db:
            trades = [dict(r) for r in db.execute("SELECT * FROM trades ORDER BY id DESC")]
            audit = [dict(r) for r in db.execute("SELECT * FROM audit ORDER BY seq DESC LIMIT 100")]
            return {"trades": trades, "audit": audit}

    def reconcile(self, rows):
        if not isinstance(rows, list) or len(rows) > 10000:
            raise DomainError("Provide a statement array of at most 10,000 rows")
        external = {}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("trade_id"), str):
                raise DomainError("Each statement row needs a trade_id")
            if row["trade_id"] in external:
                raise DomainError("Duplicate statement trade_id")
            for field in ("quantity", "amount_cents"):
                if isinstance(row.get(field), bool) or not isinstance(row.get(field), int) or row[field] < 0:
                    raise DomainError("Statement quantities and amounts must be nonnegative integers")
            external[row["trade_id"]] = row
        with self.connection() as db:
            internal = {r["trade_id"]: dict(r) for r in db.execute("SELECT * FROM settlements")}
        breaks = []
        for key in sorted(internal.keys() | external.keys()):
            if key not in external:
                breaks.append({"trade_id": key, "reason": "MISSING_EXTERNAL"})
            elif key not in internal:
                breaks.append({"trade_id": key, "reason": "MISSING_INTERNAL"})
            elif any(internal[key][f] != external[key][f] for f in ("quantity", "amount_cents")):
                breaks.append({"trade_id": key, "reason": "VALUE_MISMATCH"})
        return {"status": "BREAKS" if breaks else "BALANCED", "breaks": breaks,
                "internal_count": len(internal), "external_count": len(external)}
