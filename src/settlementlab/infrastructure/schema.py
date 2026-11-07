"""Additive, repeatable SQLite schema migration."""

from ..core.validation import DomainError
from .journal import initialize


def migrate(db):
    # SQLiteStore owns the transaction. executescript must not be used here:
    # it implicitly commits and can leave a partial upgrade behind.
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version > 4:
        raise DomainError("Database schema is newer than this application; refusing downgrade", 409)
    db.execute(
        "CREATE TABLE IF NOT EXISTS trades (\n              id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL,\n              symbol TEXT NOT NULL, quantity INTEGER NOT NULL, price_cents INTEGER NOT NULL,\n              trade_date TEXT NOT NULL, settlement_date TEXT NOT NULL,\n              state TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,\n              allocations TEXT NOT NULL DEFAULT '[]', instruction TEXT, reason TEXT,\n              cash_cents INTEGER NOT NULL DEFAULT 0, securities INTEGER NOT NULL DEFAULT 0)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS audit (\n              seq INTEGER PRIMARY KEY AUTOINCREMENT, trade_id TEXT NOT NULL,\n              timestamp TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,\n              detail TEXT NOT NULL)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS settlements (\n              trade_id TEXT PRIMARY KEY REFERENCES trades(id), quantity INTEGER NOT NULL,\n              amount_cents INTEGER NOT NULL)"
    )
    columns = {row["name"] for row in db.execute("PRAGMA table_info(trades)")}
    for name, declaration in (
        ("side", "TEXT NOT NULL DEFAULT 'BUY'"),
        ("currency", "TEXT NOT NULL DEFAULT 'USD'"),
        ("matching_mode", "TEXT NOT NULL DEFAULT 'allocation-only'"),
        ("matching_result", "TEXT NOT NULL DEFAULT '{}'"),
        ("settlement_model", "TEXT NOT NULL DEFAULT 'trade-scoped'"),
        ("buyer_id", "TEXT"),
        ("seller_id", "TEXT"),
    ):
        if name not in columns:
            db.execute("ALTER TABLE trades ADD COLUMN " + name + " " + declaration)
    db.execute(
        "CREATE TABLE IF NOT EXISTS manager_submissions (\n              id INTEGER PRIMARY KEY AUTOINCREMENT, trade_id TEXT NOT NULL REFERENCES trades(id),\n              revision INTEGER NOT NULL, submission_key TEXT NOT NULL, fingerprint TEXT NOT NULL,\n              payload TEXT NOT NULL, timestamp TEXT NOT NULL, result TEXT NOT NULL,\n              UNIQUE(trade_id, revision), UNIQUE(trade_id, submission_key))"
    )
    if "calendar_policy" not in columns:
        db.execute(
            'ALTER TABLE trades ADD COLUMN calendar_policy TEXT NOT NULL DEFAULT \'{"id":"weekday-v1","closed_dates":[]}\''
        )
    initialize(db)
    db.execute(
        "CREATE TABLE IF NOT EXISTS approval_requests (\n              id TEXT PRIMARY KEY,trade_id TEXT NOT NULL REFERENCES trades(id),maker_id TEXT NOT NULL,\n              instruction TEXT NOT NULL,status TEXT NOT NULL,trade_version INTEGER NOT NULL,\n              request_key TEXT NOT NULL,fingerprint TEXT NOT NULL,created_at TEXT NOT NULL,\n              decided_by TEXT,decided_at TEXT,reason TEXT,UNIQUE(trade_id,request_key))"
    )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS one_pending_approval ON approval_requests(trade_id) WHERE status='PENDING'"
    )
    db.execute("PRAGMA user_version=4")
