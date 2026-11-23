"""V4.4 indexed statement membership and correction-aware financial event stream."""

import json


def initialize_positions(db):
    had_membership = db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='statement_membership'"
    ).fetchone()
    db.execute("""CREATE TABLE IF NOT EXISTS statement_membership(
        trade_id TEXT NOT NULL,statement_id TEXT NOT NULL REFERENCES recon_statements(id),
        PRIMARY KEY(trade_id,statement_id))""")
    if not had_membership:
        for row in db.execute("SELECT id,rows,internal_snapshot FROM recon_statements").fetchall():
            ids = {
                r["trade_id"]
                for r in json.loads(row["rows"]) + json.loads(row["internal_snapshot"])
            }
            db.executemany(
                "INSERT OR IGNORE INTO statement_membership VALUES(?,?)",
                [(trade, row["id"]) for trade in ids],
            )
        db.execute(
            "INSERT OR IGNORE INTO statement_membership SELECT trade_id,statement_id FROM recon_cases"
        )
        db.execute(
            "INSERT OR IGNORE INTO statement_membership SELECT trade_id,evidence_statement_id FROM recon_cases WHERE evidence_statement_id IS NOT NULL"
        )
    for sql in (
        "CREATE INDEX IF NOT EXISTS recon_trade_history ON recon_cases(trade_id,id)",
        "CREATE INDEX IF NOT EXISTS audit_trade_history ON audit(trade_id,seq)",
        "CREATE INDEX IF NOT EXISTS jobs_trade_history ON ops_jobs(trade_id,created_at,id)",
        "CREATE INDEX IF NOT EXISTS outbox_trade_history ON ops_outbox(trade_id,seq)",
    ):
        db.execute(sql)
    had_events = db.execute("SELECT 1 FROM sqlite_master WHERE name='position_outbox'").fetchone()
    db.execute("""CREATE TABLE IF NOT EXISTS position_outbox(
        seq INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT UNIQUE NOT NULL,
        trade_id TEXT NOT NULL REFERENCES trades(id),source_version INTEGER NOT NULL,
        event_type TEXT NOT NULL,payload TEXT NOT NULL,journal_id TEXT REFERENCES journal_batches(id),
        created_at REAL NOT NULL,status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','LEASED','DELIVERED','BLOCKED')),
        attempts INTEGER NOT NULL DEFAULT 0,lease_token TEXT,lease_until REAL,worker_id TEXT,error TEXT,
        UNIQUE(trade_id,source_version,event_type))""")
    db.execute("CREATE INDEX IF NOT EXISTS position_due ON position_outbox(status,seq)")
    db.execute("CREATE INDEX IF NOT EXISTS position_trade ON position_outbox(trade_id,seq)")
    db.execute(
        """CREATE TABLE IF NOT EXISTS position_inbox(event_id TEXT PRIMARY KEY REFERENCES position_outbox(event_id),consumed_at REAL NOT NULL)"""
    )
    db.execute("""CREATE TABLE IF NOT EXISTS position_projection(
        trade_id TEXT PRIMARY KEY REFERENCES trades(id),source_version INTEGER NOT NULL,
        event_seq INTEGER NOT NULL,event_id TEXT NOT NULL REFERENCES position_outbox(event_id),
        payload TEXT NOT NULL,updated_at REAL NOT NULL)""")
    if not had_events:
        from .position_repository import PositionRepository

        repository = PositionRepository()
        repository.db = db
        for row in db.execute(
            "SELECT t.id FROM trades t JOIN settlements s ON s.trade_id=t.id WHERE t.settlement_model='shared-ledger'"
        ).fetchall():
            repository.position_emit(row["id"], "PositionBaseline", None)
