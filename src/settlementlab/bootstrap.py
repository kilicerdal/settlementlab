"""Composition root: explicitly wire application ports to local adapters."""

import argparse
from dataclasses import dataclass
from http.server import ThreadingHTTPServer

from .adapters.ai import Triage
from .adapters.http import handler
from .application.operations import DurableOperations
from .application.service import SettlementService
from .configuration import Settings
from .infrastructure.store import SQLiteStore


@dataclass
class Application:
    settings: Settings
    service: SettlementService
    triage: Triage
    operations: DurableOperations


def create_application(settings):
    from .core.calendar import BusinessCalendar, FixedClock
    from .infrastructure.clock import SystemClock

    clock = FixedClock(settings.business_date) if settings.business_date else SystemClock()
    service = SettlementService(
        SQLiteStore(settings.database),
        clock,
        BusinessCalendar(settings.calendar_id, settings.closed_dates),
    )
    return Application(settings, service, Triage(model=settings.model), DurableOperations(service))


def main(argv=None):
    parser = argparse.ArgumentParser(description="SettlementLab operations workbench")
    parser.add_argument("--config", help="JSON environment configuration")
    parser.add_argument("--port", type=int)
    parser.add_argument("--db")
    parser.add_argument("--model")
    parser.add_argument(
        "--business-date", help="Explicit simulated business date; default uses the real UTC date"
    )
    args = parser.parse_args(argv)
    settings = Settings.load(
        args.config,
        database=args.db,
        port=args.port,
        model=args.model,
        business_date=args.business_date,
    )
    app = create_application(settings)
    server = ThreadingHTTPServer(
        ("127.0.0.1", settings.port), handler(app.service, app.triage, app.operations)
    )
    print("SettlementLab running at http://127.0.0.1:%s" % server.server_port, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
