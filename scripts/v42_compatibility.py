"""Exercise a genuine V4.1 database upgrade and refusal to downgrade in place."""

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from settlementlab.bootstrap import create_application
from settlementlab.configuration import Settings

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="artifacts/v42/compatibility")
    args = parser.parse_args(argv)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="settlementlab-upgrade-") as directory:
        root = Path(directory)
        archive = root / "v41.zip"
        subprocess.run(
            ["git", "archive", "--format=zip", "-o", str(archive), "v4.1.0", "src"],
            cwd=ROOT,
            check=True,
        )
        with zipfile.ZipFile(archive) as zipped:
            zipped.extractall(root / "old")
        env = dict(os.environ, PYTHONPATH=str(root / "old/src"))
        database = root / "upgrade.db"
        setup = """import sys
from settlementlab.bootstrap import create_application
from settlementlab.configuration import Settings
from settlementlab.assurance.durable_data import approved_trade, CHECKER, entry
app=create_application(Settings(database=sys.argv[1],model='',business_date='2026-11-09'))
trade=approved_trade(app.service)
app.operations.enqueue_batch([entry(trade)],'legacy-batch',CHECKER)
app.operations.claim('old-worker',0.1)
"""
        subprocess.run([sys.executable, "-c", setup, str(database)], cwd=root, env=env, check=True)
        with sqlite3.connect(database) as db:
            before = dict(
                version=db.execute("PRAGMA user_version").fetchone()[0],
                balances=db.execute(
                    "SELECT * FROM balances ORDER BY participant_id,asset"
                ).fetchall(),
                journal=db.execute("SELECT * FROM journal_lines ORDER BY batch_id,line").fetchall(),
            )
            backup = root / "pre-upgrade.db"
            with sqlite3.connect(backup) as dest:
                db.backup(dest)
        app = create_application(
            Settings(database=str(database), model="", business_date="2026-11-09")
        )
        with app.service.store.transaction() as repo:
            after_balances = [
                tuple(r)
                for r in repo.db.execute("SELECT * FROM balances ORDER BY participant_id,asset")
            ]
            after_journal = [
                tuple(r)
                for r in repo.db.execute("SELECT * FROM journal_lines ORDER BY batch_id,line")
            ]
            version = repo.db.execute("PRAGMA user_version").fetchone()[0]
        assert before["version"] == 5 and version == 6
        assert before["balances"] == after_balances and before["journal"] == after_journal
        # Expired legacy lease is reclaimed and settled once under the upgraded application.
        import time

        time.sleep(0.15)
        assert app.operations.process_one("new-worker")["status"] == "SUCCEEDED"
        assert app.operations.process_one("second-worker") is None
        open_code = "from settlementlab.bootstrap import create_application; from settlementlab.configuration import Settings; import sys; create_application(Settings(database=sys.argv[1],model=''))"
        downgrade = subprocess.run(
            [sys.executable, "-c", open_code, str(database)],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
        )
        assert downgrade.returncode != 0 and "newer" in downgrade.stderr.lower(), downgrade.stderr
        restored = subprocess.run(
            [sys.executable, "-c", open_code, str(backup)],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
        )
        assert restored.returncode == 0, restored.stderr
        report = dict(
            status="passed",
            source_release="v4.1.0",
            schema_before=5,
            schema_after=6,
            financial_rows_unchanged=True,
            legacy_claim_recovered_once=True,
            downgrade_refused=True,
            pre_upgrade_backup_opens_in_old_release=True,
            scope="Populated V4.1 database and claimed job; restore backup for rollback, never overwrite newer data",
        )
        (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
        shutil.copyfile(backup, output / "synthetic-v41-backup.db")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
