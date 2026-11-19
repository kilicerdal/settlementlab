"""Additive V4.3 correction evidence; transaction is owned by SQLiteStore."""


def initialize_investigation(db):
    db.execute("""CREATE TABLE IF NOT EXISTS reversal_requests(
        id TEXT PRIMARY KEY,trade_id TEXT NOT NULL REFERENCES trades(id),
        original_batch TEXT NOT NULL REFERENCES journal_batches(id),
        request_key TEXT NOT NULL, fingerprint TEXT NOT NULL,maker_id TEXT NOT NULL,
        reason TEXT NOT NULL,created_at TEXT NOT NULL,original_state TEXT NOT NULL,
        quantity INTEGER NOT NULL,amount_cents INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','APPROVED','REJECTED')),
        checker_id TEXT,decision_reason TEXT,decided_at TEXT,decision_fingerprint TEXT,
        compensation_batch TEXT UNIQUE REFERENCES journal_batches(id),
        UNIQUE(trade_id,request_key))""")
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS one_live_reversal ON reversal_requests(original_batch) WHERE status IN ('PENDING','APPROVED')"
    )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS one_pending_correction ON reversal_requests(trade_id) WHERE status='PENDING'"
    )
