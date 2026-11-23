"""Composition root: explicitly wire application ports to local adapters."""

import argparse
from dataclasses import dataclass
from http.server import ThreadingHTTPServer

from .adapters.ai import Triage
from .adapters.http import handler
from .application.operations import DurableOperations
from .application.positions import PositionObserver
from .application.service import SettlementService
from .configuration import Settings
from .infrastructure.store import SQLiteStore


@dataclass
class Application:
    settings: Settings
    service: SettlementService
    triage: Triage
    operations: DurableOperations
    positions: PositionObserver


def create_application(settings):
    from .core.calendar import BusinessCalendar, FixedClock
    from .core.deadlines import FixedTimestampClock
    from .infrastructure.clock import SystemClock

    clock = (
        FixedTimestampClock(settings.business_timestamp)
        if settings.business_timestamp
        else FixedClock(settings.business_date)
        if settings.business_date
        else SystemClock()
    )
    service = SettlementService(
        SQLiteStore(settings.database),
        clock,
        BusinessCalendar(settings.calendar_id, settings.closed_dates),
        cutoff=settings.settlement_cutoff,
    )
    return Application(
        settings,
        service,
        Triage(model=settings.model),
        DurableOperations(service),
        PositionObserver(service),
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="SettlementLab operations workbench")
    parser.add_argument("--config", help="JSON environment configuration")
    parser.add_argument("--port", type=int)
    parser.add_argument("--db")
    parser.add_argument("--model")
    parser.add_argument(
        "--business-date", help="Explicit simulated business date; default uses the real UTC date"
    )
    parser.add_argument("--business-timestamp", help="Explicit simulated UTC ISO timestamp")
    parser.add_argument("--settlement-cutoff", help="Pinned UTC cutoff HH:MM")
    args = parser.parse_args(argv)
    settings = Settings.load(
        args.config,
        database=args.db,
        port=args.port,
        model=args.model,
        business_date=args.business_date,
        business_timestamp=args.business_timestamp,
        settlement_cutoff=args.settlement_cutoff,
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
