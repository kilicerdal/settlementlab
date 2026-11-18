"""Additive durable queue/outbox tables, under the existing migration transaction."""


def initialize_operations(db):
    statements = [
        """CREATE TABLE IF NOT EXISTS ops_batches(
            id TEXT PRIMARY KEY,request_key TEXT UNIQUE NOT NULL,fingerprint TEXT NOT NULL,
            jobs TEXT NOT NULL,created_at REAL NOT NULL,requested_by TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS ops_jobs(
            id TEXT PRIMARY KEY,batch_id TEXT NOT NULL REFERENCES ops_batches(id),
            trade_id TEXT NOT NULL REFERENCES trades(id),expected_version INTEGER NOT NULL,
            generation INTEGER NOT NULL DEFAULT 1,status TEXT NOT NULL CHECK(status IN ('READY','RUNNING','RETRY_WAIT','SUCCEEDED','DEAD_LETTER')),
            attempts INTEGER NOT NULL DEFAULT 0,max_attempts INTEGER NOT NULL CHECK(max_attempts BETWEEN 1 AND 10),
            available_at REAL NOT NULL,lease_until REAL,lease_token TEXT,worker_id TEXT,
            requested_by TEXT NOT NULL,clock_policy TEXT NOT NULL,created_at REAL NOT NULL,updated_at REAL NOT NULL,error TEXT)""",
        "CREATE UNIQUE INDEX IF NOT EXISTS ops_one_active_trade ON ops_jobs(trade_id) WHERE status IN ('READY','RUNNING','RETRY_WAIT')",
        """CREATE TABLE IF NOT EXISTS ops_attempts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL REFERENCES ops_jobs(id),
            generation INTEGER NOT NULL,number INTEGER NOT NULL,token TEXT UNIQUE NOT NULL,worker_id TEXT NOT NULL,
            started_at REAL NOT NULL,finished_at REAL,status TEXT NOT NULL,detail TEXT,
            UNIQUE(job_id,generation,number))""",
        """CREATE TABLE IF NOT EXISTS ops_receipts(
            job_id TEXT NOT NULL REFERENCES ops_jobs(id),generation INTEGER NOT NULL,
            result TEXT NOT NULL,created_at REAL NOT NULL,PRIMARY KEY(job_id,generation))""",
        """CREATE TABLE IF NOT EXISTS ops_outbox(
            seq INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT UNIQUE NOT NULL,
            job_id TEXT NOT NULL REFERENCES ops_jobs(id),generation INTEGER NOT NULL,trade_id TEXT NOT NULL,
            event_type TEXT NOT NULL,payload TEXT NOT NULL,created_at REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','LEASED','DELIVERED','BLOCKED')),
            attempts INTEGER NOT NULL DEFAULT 0,available_at REAL NOT NULL,
            lease_until REAL,lease_token TEXT,worker_id TEXT,error TEXT,
            UNIQUE(job_id,generation,event_type))""",
        """CREATE TABLE IF NOT EXISTS ops_inbox(
            event_id TEXT PRIMARY KEY REFERENCES ops_outbox(event_id),received_at REAL NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS ops_projection(
            trade_id TEXT PRIMARY KEY,last_seq INTEGER NOT NULL,event_id TEXT NOT NULL,
            job_id TEXT NOT NULL,generation INTEGER NOT NULL,state TEXT NOT NULL,updated_at REAL NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS ops_timeline(
            seq INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL REFERENCES ops_jobs(id),
            generation INTEGER NOT NULL,kind TEXT NOT NULL,actor TEXT NOT NULL,at REAL NOT NULL,detail TEXT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS ops_jobs_due ON ops_jobs(status,available_at,lease_until)",
        "CREATE INDEX IF NOT EXISTS ops_outbox_due ON ops_outbox(status,available_at,lease_until)",
    ]
    for statement in statements:
        db.execute(statement)
