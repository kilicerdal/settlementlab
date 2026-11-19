"""Additive V4.2 lifecycle and reconciliation schema; caller owns the transaction."""

import json


def initialize_lifecycle(db):
    columns = {r["name"] for r in db.execute("PRAGMA table_info(trades)")}
    for name, declaration in [
        ("lifecycle_revision", "INTEGER NOT NULL DEFAULT 1"),
        ("cutoff_utc", "TEXT NOT NULL DEFAULT ''"),
    ]:
        if name not in columns:
            db.execute("ALTER TABLE trades ADD COLUMN " + name + " " + declaration)
    if "requested_quantity" not in {r["name"] for r in db.execute("PRAGMA table_info(ops_jobs)")}:
        db.execute("ALTER TABLE ops_jobs ADD COLUMN requested_quantity INTEGER")
    statements = [
        """CREATE TABLE IF NOT EXISTS trade_revisions(
            trade_id TEXT NOT NULL REFERENCES trades(id),revision INTEGER NOT NULL,
            terms TEXT NOT NULL,actor TEXT NOT NULL,reason TEXT NOT NULL,created_at TEXT NOT NULL,
            PRIMARY KEY(trade_id,revision))""",
        """CREATE TABLE IF NOT EXISTS approval_revisions(
            approval_id TEXT PRIMARY KEY REFERENCES approval_requests(id),revision INTEGER NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS manager_trade_revisions(
            trade_id TEXT NOT NULL,manager_revision INTEGER NOT NULL,revision INTEGER NOT NULL,
            PRIMARY KEY(trade_id,manager_revision))""",
        """CREATE TABLE IF NOT EXISTS lifecycle_commands(
            trade_id TEXT NOT NULL REFERENCES trades(id),action TEXT NOT NULL,request_key TEXT NOT NULL,
            fingerprint TEXT NOT NULL,response TEXT NOT NULL,PRIMARY KEY(trade_id,action,request_key))""",
        """CREATE TABLE IF NOT EXISTS settlement_slices(
            id TEXT PRIMARY KEY,trade_id TEXT NOT NULL REFERENCES trades(id),request_key TEXT NOT NULL,
            revision INTEGER NOT NULL,quantity INTEGER NOT NULL CHECK(quantity>0),
            price_cents INTEGER NOT NULL CHECK(price_cents>0),batch_id TEXT UNIQUE NOT NULL REFERENCES journal_batches(id),
            actor TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(trade_id,request_key))""",
        """CREATE TABLE IF NOT EXISTS recon_statements(
            id TEXT PRIMARY KEY,request_key TEXT UNIQUE NOT NULL,fingerprint TEXT NOT NULL,
            rows TEXT NOT NULL,internal_snapshot TEXT NOT NULL,actor TEXT NOT NULL,created_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS recon_cases(
            id TEXT PRIMARY KEY,statement_id TEXT NOT NULL REFERENCES recon_statements(id),
            trade_id TEXT NOT NULL,kind TEXT NOT NULL,expected TEXT,observed TEXT,
            status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','RESOLVED')),
            resolved_by TEXT,resolved_at TEXT,reason TEXT,evidence_statement_id TEXT REFERENCES recon_statements(id),
            resolution_snapshot TEXT)""",
        "CREATE INDEX IF NOT EXISTS slices_by_trade ON settlement_slices(trade_id,created_at)",
        "CREATE INDEX IF NOT EXISTS recon_open ON recon_cases(status,trade_id)",
    ]
    for sql in statements:
        db.execute(sql)
    db.execute("INSERT OR IGNORE INTO approval_revisions SELECT id,1 FROM approval_requests")
    db.execute(
        "INSERT OR IGNORE INTO manager_trade_revisions SELECT trade_id,revision,1 FROM manager_submissions"
    )

    for row in db.execute(
        "SELECT * FROM trades t WHERE NOT EXISTS (SELECT 1 FROM trade_revisions r WHERE r.trade_id=t.id)"
    ).fetchall():
        trade = dict(row)
        terms = {
            k: trade[k]
            for k in (
                "symbol",
                "side",
                "currency",
                "quantity",
                "price_cents",
                "trade_date",
                "settlement_date",
                "buyer_id",
                "seller_id",
                "cutoff_utc",
            )
        }
        db.execute(
            "INSERT INTO trade_revisions VALUES(?,?,?,?,?,?)",
            (
                trade["id"],
                trade["lifecycle_revision"],
                json.dumps(terms),
                "migration",
                "Imported existing terms without rewriting financial history",
                "1970-01-01T00:00:00+00:00",
            ),
        )
