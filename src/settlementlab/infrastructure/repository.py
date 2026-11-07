"""SQLite repositories; SQL and cursor handling stay in this adapter."""

from . import journal


class SQLiteRepository:
    def __init__(self, db):
        self.db = db

    def append_audit(self, parameters=()):
        self.db.execute(
            "INSERT INTO audit(trade_id,timestamp,actor,action,detail) VALUES (?,?,?,?,?)",
            parameters,
        )

    def find_trade(self, parameters=()):
        cursor = self.db.execute("SELECT * FROM trades WHERE id=?", parameters)
        row = cursor.fetchone()
        return dict(row) if row else None

    def list_manager_revisions(self, parameters=()):
        cursor = self.db.execute(
            "SELECT revision,payload,timestamp FROM manager_submissions WHERE trade_id=? ORDER BY revision",
            parameters,
        )
        return [dict(row) for row in cursor.fetchall()]

    def list_approvals(self, parameters=()):
        cursor = self.db.execute(
            "SELECT * FROM approval_requests WHERE trade_id=? ORDER BY created_at", parameters
        )
        return [dict(row) for row in cursor.fetchall()]

    def find_settlement_batch(self, parameters=()):
        cursor = self.db.execute("SELECT id FROM journal_batches WHERE trade_id=?", parameters)
        row = cursor.fetchone()
        return dict(row) if row else None

    def find_trade_by_key(self, parameters=()):
        cursor = self.db.execute("SELECT * FROM trades WHERE request_key=?", parameters)
        row = cursor.fetchone()
        return dict(row) if row else None

    def count_trades(self, parameters=()):
        cursor = self.db.execute("SELECT COUNT(*) FROM trades", parameters)
        return cursor.fetchone()[0]

    def insert_trade(self, parameters=()):
        self.db.execute(
            "INSERT INTO trades(id,request_key,fingerprint,symbol,quantity,price_cents,\n                       trade_date,settlement_date,state) VALUES (?,?,?,?,?,?,?,?,?)",
            parameters,
        )

    def set_trade_terms(self, parameters=()):
        self.db.execute(
            "UPDATE trades SET side=?,currency=?,matching_mode=? WHERE id=?", parameters
        )

    def set_settlement_parties(self, parameters=()):
        self.db.execute(
            "UPDATE trades SET settlement_model=?,buyer_id=?,seller_id=? WHERE id=?", parameters
        )

    def set_legacy_allocation(self, parameters=()):
        self.db.execute("UPDATE trades SET allocations=?,state=?,reason=? WHERE id=?", parameters)

    def affirm_trade(self, parameters=()):
        self.db.execute(
            "UPDATE trades SET state='AFFIRMED',instruction=?,reason=NULL WHERE id=?", parameters
        )

    def set_legacy_balances(self, parameters=()):
        self.db.execute("UPDATE trades SET cash_cents=?,securities=? WHERE id=?", parameters)

    def insert_settlement(self, parameters=()):
        self.db.execute("INSERT INTO settlements VALUES (?,?,?)", parameters)

    def complete_shared_settlement(self, parameters=()):
        self.db.execute("UPDATE trades SET state='SETTLED',reason=NULL WHERE id=?", parameters)

    def fail_settlement(self, parameters=()):
        self.db.execute("UPDATE trades SET state='FAILED',reason=? WHERE id=?", parameters)

    def complete_legacy_settlement(self, parameters=()):
        self.db.execute(
            "UPDATE trades SET state='SETTLED',reason=NULL,cash_cents=cash_cents-?,securities=securities-? WHERE id=?",
            parameters,
        )

    def advance_version(self, parameters=()):
        self.db.execute("UPDATE trades SET version=version+1 WHERE id=?", parameters)

    def list_trade_ids(self, parameters=()):
        cursor = self.db.execute("SELECT id FROM trades ORDER BY id DESC", parameters)
        return [dict(row) for row in cursor.fetchall()]

    def list_audit(self, parameters=()):
        cursor = self.db.execute("SELECT * FROM audit ORDER BY seq DESC LIMIT 100", parameters)
        return [dict(row) for row in cursor.fetchall()]

    def list_settlements(self, parameters=()):
        cursor = self.db.execute("SELECT * FROM settlements", parameters)
        return [dict(row) for row in cursor.fetchall()]

    def list_trade_audit(self, parameters=()):
        cursor = self.db.execute("SELECT * FROM audit WHERE trade_id=? ORDER BY seq", parameters)
        return [dict(row) for row in cursor.fetchall()]

    def find_manager_replay(self, parameters=()):
        cursor = self.db.execute(
            "SELECT fingerprint,result FROM manager_submissions WHERE trade_id=? AND submission_key=?",
            parameters,
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def cancel_approval(self, parameters=()):
        self.db.execute(
            "UPDATE approval_requests SET status='CANCELLED',decided_by='system',decided_at=?,reason=? WHERE id=?",
            parameters,
        )

    def apply_manager_revision(self, parameters=()):
        self.db.execute(
            "UPDATE trades SET allocations=?,matching_result=?,state=?,reason=?,version=version+1 WHERE id=?",
            parameters,
        )

    def insert_manager_revision(self, parameters=()):
        self.db.execute(
            "INSERT INTO manager_submissions(trade_id,revision,submission_key,fingerprint,payload,timestamp,result) VALUES (?,?,?,?,?,?,?)",
            parameters,
        )

    def store_manager_response(self, parameters=()):
        self.db.execute(
            "UPDATE manager_submissions SET result=? WHERE trade_id=? AND submission_key=?",
            parameters,
        )

    def find_approval_replay(self, parameters=()):
        cursor = self.db.execute(
            "SELECT fingerprint FROM approval_requests WHERE trade_id=? AND request_key=?",
            parameters,
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def insert_approval(self, parameters=()):
        self.db.execute(
            "INSERT INTO approval_requests VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", parameters
        )

    def decide_approval(self, parameters=()):
        self.db.execute(
            "UPDATE approval_requests SET status=?,decided_by=?,decided_at=?,reason=? WHERE id=?",
            parameters,
        )

    def balance(self, participant, asset):
        return journal.balance(self.db, participant, asset)

    def settle(self, trade, actor):
        return journal.settle(self.db, trade, actor)

    def treasury_snapshot(self):
        return journal.snapshot(self.db)

    def provision(self, data, key, actor):
        return journal.provision(self.db, data, key, actor)

    def participant(self, value):
        return journal.participant(self.db, value)

    def pin_calendar(self, parameters):
        self.db.execute("UPDATE trades SET calendar_policy=? WHERE id=?", parameters)
