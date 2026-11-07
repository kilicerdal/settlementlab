"""Transactional domain service. All amounts are integer cents in storage."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from .validation import DomainError, cents, positive_int, next_business_day


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
            db.execute("BEGIN IMMEDIATE")
            # Additive, repeatable migration: existing allocation-only trades retain their contract.
            columns = {row['name'] for row in db.execute('PRAGMA table_info(trades)')}
            for name, declaration in (
                ('side', "TEXT NOT NULL DEFAULT 'BUY'"),
                ('currency', "TEXT NOT NULL DEFAULT 'USD'"),
                ('matching_mode', "TEXT NOT NULL DEFAULT 'allocation-only'"),
                ('matching_result', "TEXT NOT NULL DEFAULT '{}'"),
            ):
                if name not in columns:
                    db.execute('ALTER TABLE trades ADD COLUMN '+name+' '+declaration)
            db.execute('''CREATE TABLE IF NOT EXISTS manager_submissions (
              id INTEGER PRIMARY KEY AUTOINCREMENT, trade_id TEXT NOT NULL REFERENCES trades(id),
              revision INTEGER NOT NULL, submission_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
              payload TEXT NOT NULL, timestamp TEXT NOT NULL, result TEXT NOT NULL,
              UNIQUE(trade_id, revision), UNIQUE(trade_id, submission_key))''')
            db.execute('PRAGMA user_version=2')

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
        trade = dict(row)
        history = [dict(r) for r in db.execute(
            'SELECT revision,payload,timestamp FROM manager_submissions WHERE trade_id=? ORDER BY revision', (trade_id,))]
        trade['manager_submission'] = json.loads(history[-1]['payload']) if history else None
        trade['submission_history'] = [dict(revision=r['revision'], timestamp=r['timestamp'],
                                             terms=json.loads(r['payload'])) for r in history]
        trade['matching'] = json.loads(trade['matching_result'])
        return trade

    def create(self, data, key, actor="broker"):
        if not isinstance(key, str) or not 1 <= len(key) <= 120:
            raise DomainError("An Idempotency-Key of 1–120 characters is required")
        from .matching import normalize_terms
        mode = data.get('matching_mode', 'allocation-only')
        if mode not in ('allocation-only', 'two-sided'):
            raise DomainError('matching_mode must be allocation-only or two-sided')
        terms = normalize_terms(data, complete=mode == 'two-sided')
        if terms['currency'] != 'USD':
            raise DomainError('V2.1 broker trades support USD only; no FX conversion is simulated')
        symbol, quantity, price = terms['symbol'], terms['quantity'], terms['price_cents']
        trade_date, settlement_date = terms['trade_date'], terms['settlement_date']
        fingerprint = json.dumps(dict(terms, matching_mode=mode), sort_keys=True)
        with self.connection() as db:
            existing = db.execute("SELECT * FROM trades WHERE request_key=?", (key,)).fetchone()
            if existing:
                legacy_fingerprint = json.dumps([symbol, quantity, price, trade_date])
                legacy_replay = (mode == 'allocation-only' and terms['side'] == 'BUY'
                                 and existing['fingerprint'] == legacy_fingerprint)
                if existing["fingerprint"] != fingerprint and not legacy_replay:
                    raise DomainError("Idempotency key already used for a different submission", 409)
                return self.get(db, existing["id"])
            number = db.execute("SELECT COUNT(*) FROM trades").fetchone()[0] + 1
            trade_id = "SL-%06d" % number
            db.execute('''INSERT INTO trades(id,request_key,fingerprint,symbol,quantity,price_cents,
                       trade_date,settlement_date,state) VALUES (?,?,?,?,?,?,?,?,?)''',
                       (trade_id, key, fingerprint, symbol.upper(), quantity, price, trade_date,
                        settlement_date, "RECEIVED"))
            db.execute('UPDATE trades SET side=?,currency=?,matching_mode=? WHERE id=?',
                       (terms['side'],terms['currency'],mode,trade_id))
            self.event(db, trade_id, actor, "TRADE_RECEIVED", "Broker submission accepted")
            return self.get(db, trade_id)

    def command(self, trade_id, action, data, actor="operator"):
        if action == 'manager':
            return self.submit_manager(trade_id, data)
        with self.connection() as db:
            trade = self.get(db, trade_id)
            version = data.get("version")
            if isinstance(version, bool) or not isinstance(version, int) or version != trade["version"]:
                raise DomainError("Stale or missing version; refresh before updating", 409)
            state = trade["state"]
            if action == "allocate":
                if trade['matching_mode'] == 'two-sided':
                    raise DomainError('Two-sided trades require an independent manager submission', 409)
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
            trades = [self.get(db, r["id"]) for r in db.execute("SELECT id FROM trades ORDER BY id DESC").fetchall()]
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

    def evidence(self, trade_id, version):
        from .ai import build_evidence
        with self.connection() as db:
            trade = self.get(db, trade_id)
            if isinstance(version, bool) or not isinstance(version, int) or version != trade["version"]:
                raise DomainError("Stale or missing version; refresh before analysis", 409)
            events = [dict(r) for r in db.execute("SELECT * FROM audit WHERE trade_id=? ORDER BY seq", (trade_id,))]
            return build_evidence(trade, events)

    def submit_manager(self, trade_id, data):
        from .matching import normalize_terms, normalize_allocations, compare
        key = data.get('submission_key')
        if not isinstance(key, str) or not 1 <= len(key) <= 120:
            raise DomainError('Manager submissions require an Idempotency-Key of 1–120 characters')
        manager = normalize_terms(data)
        manager['allocations'] = normalize_allocations(data.get('allocations'))
        fingerprint = json.dumps(manager, sort_keys=True)
        with self.connection() as db:
            trade = self.get(db, trade_id)
            if trade['matching_mode'] != 'two-sided':
                raise DomainError('Manager submissions require a two-sided trade', 409)
            previous = db.execute('SELECT fingerprint,result FROM manager_submissions WHERE trade_id=? AND submission_key=?', (trade_id,key)).fetchone()
            if previous:
                if previous['fingerprint'] != fingerprint:
                    raise DomainError('Manager key already used for different terms', 409)
                return json.loads(previous['result'])
            version = data.get('version')
            if isinstance(version, bool) or not isinstance(version, int) or version != trade['version']:
                raise DomainError('Stale or missing version; refresh before submitting', 409)
            if trade['state'] not in ('RECEIVED','EXCEPTION','MATCHED'):
                raise DomainError('Manager terms are locked after affirmation', 409)
            report = compare(trade, manager)
            reason = '; '.join(f['message'] for f in report['findings']) or None
            revision = len(trade['submission_history']) + 1
            timestamp = datetime.now(timezone.utc).isoformat()
            db.execute('UPDATE trades SET allocations=?,matching_result=?,state=?,reason=?,version=version+1 WHERE id=?',
                       (json.dumps(manager['allocations']),json.dumps(report),report['status'],reason,trade_id))
            db.execute('INSERT INTO manager_submissions(trade_id,revision,submission_key,fingerprint,payload,timestamp,result) VALUES (?,?,?,?,?,?,?)',
                       (trade_id,revision,key,fingerprint,json.dumps(manager),timestamp,'{}'))
            self.event(db,trade_id,'investment-manager','MANAGER_SUBMITTED',
                       'Revision %s · %s · %s discrepancy(s) · %s' % (revision,report['status'],len(report['findings']),report['policy']))
            result = self.get(db,trade_id)
            db.execute('UPDATE manager_submissions SET result=? WHERE trade_id=? AND submission_key=?',
                       (json.dumps(result),trade_id,key))
            return result
