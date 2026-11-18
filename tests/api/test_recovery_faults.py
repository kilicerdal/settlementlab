"""Real post-commit response loss, bounded timeout and hard-process restart checks."""

import queue
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path

from examples.collateral_service.server import Inventory, handler
from settlementlab.assurance.fixtures import HTTPEnvironment
from settlementlab.assurance.transport import APIError, JsonClient, TransportError


@contextmanager
def process_service(database):
    root = Path(__file__).resolve().parents[2]
    process = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-m",
            "examples.collateral_service.server",
            "--port",
            "0",
            "--db",
            str(database),
        ],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    ready = queue.Queue()
    thread = threading.Thread(target=lambda: ready.put(process.stdout.readline()), daemon=True)
    thread.start()
    try:
        line = ready.get(timeout=10)
        if not line.startswith("Collateral demonstration on http://127.0.0.1:"):
            raise RuntimeError("Independent process did not become ready")
        yield process, JsonClient(line.strip().split(" on ", 1)[1])
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        process.stdout.close()
        thread.join(timeout=2)


class RecoveryFaults(unittest.TestCase):
    def assert_one_reservation(self, store, identifier, client):
        self.assertEqual(client.request("/inventory/RECOVERY")["available"], 90)
        with store.transaction() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT id FROM reservations").fetchone()[0], identifier)

    def test_response_lost_after_commit_requires_explicit_safe_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Inventory(Path(temp) / "recovery.db")
            base = handler(store)

            class DropOnce(base):
                dropped = False

                def reply(self, status, body):
                    if self.path == "/reservations" and status == 201 and not type(self).dropped:
                        type(self).dropped = True
                        self.connection.shutdown(socket.SHUT_RDWR)
                        self.connection.close()
                        return
                    return super().reply(status, body)

            with HTTPEnvironment(DropOnce) as env:
                client = JsonClient(env.base_url)
                client.request("/inventory", dict(asset="RECOVERY", quantity=100))
                with self.assertRaises(TransportError) as failed:
                    client.request(
                        "/reservations", dict(asset="RECOVERY", quantity=10), "lost-response"
                    )
                self.assertEqual(failed.exception.kind, "connection")
                # A client-side failure cannot establish whether the write committed.
                with store.transaction() as db:
                    self.assertEqual(
                        db.execute("SELECT available FROM inventory").fetchone()[0], 90
                    )
                    original = db.execute("SELECT id FROM reservations").fetchone()[0]
                replay = client.request(
                    "/reservations", dict(asset="RECOVERY", quantity=10), "lost-response"
                )
                self.assertEqual(client.last_exchange["status"], 200)
                self.assertEqual(replay["id"], original)
                self.assert_one_reservation(store, original, client)
                with self.assertRaises(APIError) as conflict:
                    client.request(
                        "/reservations", dict(asset="RECOVERY", quantity=11), "lost-response"
                    )
                self.assertEqual(conflict.exception.status, 409)
                self.assert_one_reservation(store, original, client)

    def test_timeout_after_committed_write_does_not_trigger_automatic_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Inventory(Path(temp) / "timeout.db")
            committed = threading.Event()
            release = threading.Event()
            base = handler(store)

            class StallOnce(base):
                def reply(self, status, body):
                    if self.path == "/reservations" and status == 201:
                        committed.set()
                        release.wait(timeout=5)
                    try:
                        return super().reply(status, body)
                    except (BrokenPipeError, ConnectionResetError):
                        return None

            with HTTPEnvironment(StallOnce) as env:
                client = JsonClient(env.base_url, timeout=0.1)
                client.request("/inventory", dict(asset="RECOVERY", quantity=100))
                try:
                    with self.assertRaises(TransportError) as failed:
                        client.request(
                            "/reservations", dict(asset="RECOVERY", quantity=10), "timed-out"
                        )
                    self.assertEqual(failed.exception.kind, "timeout")
                    self.assertTrue(committed.is_set())
                    with store.transaction() as db:
                        self.assertEqual(
                            db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0], 1
                        )
                finally:
                    release.set()
                replay = JsonClient(env.base_url).request(
                    "/reservations", dict(asset="RECOVERY", quantity=10), "timed-out"
                )
                self.assert_one_reservation(store, replay["id"], client)

    def test_replay_survives_hard_process_restart_without_second_debit(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "restart.db"
            with process_service(database) as (process, client):
                client.request("/inventory", dict(asset="RECOVERY", quantity=100))
                original = client.request(
                    "/reservations", dict(asset="RECOVERY", quantity=10), "survives-restart"
                )
                process.kill()
                process.wait(timeout=10)
            with process_service(database) as (_, restarted):
                replay = restarted.request(
                    "/reservations", dict(asset="RECOVERY", quantity=10), "survives-restart"
                )
                self.assertEqual(restarted.last_exchange["status"], 200)
                self.assertEqual(replay["id"], original["id"])
                self.assert_one_reservation(Inventory(database), original["id"], restarted)
                restarted.request("/reservations/" + original["id"] + "/release", {})
                restarted.request("/reservations/" + original["id"] + "/release", {})
                self.assertEqual(restarted.request("/inventory/RECOVERY")["available"], 100)

    def test_truncated_response_is_not_treated_as_success(self):
        base = handler(None)

        class Truncated(base):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "100")
                self.end_headers()
                self.wfile.write(b"{}")
                self.wfile.flush()
                self.connection.shutdown(socket.SHUT_RDWR)

        with HTTPEnvironment(Truncated) as env:
            with self.assertRaises(TransportError) as failed:
                JsonClient(env.base_url).request("/truncated")
            self.assertEqual(failed.exception.kind, "incomplete_response")
