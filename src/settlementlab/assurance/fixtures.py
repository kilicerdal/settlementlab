"""Isolated real HTTP environments with deterministic resource ownership."""

from contextlib import ExitStack
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread

from .client import SettlementClient


class LocalEnvironment:
    def __init__(self, business_date="2026-11-09", closed_dates=()):
        self.business_date = business_date
        self.closed_dates = closed_dates

    def __enter__(self):
        from ..adapters.http import handler
        from ..bootstrap import create_application
        from ..configuration import Settings

        self.stack = ExitStack()
        try:
            directory = self.stack.enter_context(TemporaryDirectory(prefix="settlementlab-"))
            self.app = create_application(
                Settings(
                    database=str(Path(directory) / "test.db"),
                    port=0,
                    model="",
                    business_date=self.business_date,
                    closed_dates=self.closed_dates,
                )
            )
            self.http = self.stack.enter_context(
                HTTPEnvironment(handler(self.app.service, self.app.triage))
            )
            self.server, self.thread, self.base_url = (
                self.http.server,
                self.http.thread,
                self.http.base_url,
            )
            self.client = SettlementClient(self.base_url)
            self.database = self.app.settings.database
            return self
        except Exception:
            self.stack.close()
            raise

    def __exit__(self, *args):
        return self.stack.__exit__(*args)


class HTTPEnvironment:
    """Reusable server lifetime; knows nothing about a financial application."""

    def __init__(self, handler):
        self.handler = handler

    def __enter__(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler)
        self.thread = Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.05), daemon=True
        )
        try:
            self.thread.start()
        except Exception:
            self.server.server_close()
            raise
        self.base_url = "http://127.0.0.1:" + str(self.server.server_port)
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()
        if self.thread.is_alive():
            raise RuntimeError("Test server did not stop")
