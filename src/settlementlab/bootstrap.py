"""Composition root: explicitly wire application ports to local adapters."""
import argparse
from dataclasses import dataclass
from http.server import ThreadingHTTPServer
from .configuration import Settings
from .application.service import SettlementService
from .infrastructure.store import SQLiteStore
from .adapters.ai import Triage
from .adapters.http import handler


@dataclass
class Application:
    settings: Settings
    service: SettlementService
    triage: Triage


def create_application(settings):
    from .core.calendar import FixedClock,BusinessCalendar
    from .infrastructure.clock import SystemClock
    clock=FixedClock(settings.business_date) if settings.business_date else SystemClock()
    return Application(settings,SettlementService(SQLiteStore(settings.database),clock,BusinessCalendar(settings.calendar_id,settings.closed_dates)),Triage(model=settings.model))


def main(argv=None):
    parser=argparse.ArgumentParser(description='SettlementLab operations workbench')
    parser.add_argument('--config',help='JSON environment configuration')
    parser.add_argument('--port',type=int)
    parser.add_argument('--db')
    parser.add_argument('--model')
    parser.add_argument('--business-date',help='Explicit simulated business date; default uses the real UTC date')
    args=parser.parse_args(argv)
    settings=Settings.load(args.config,database=args.db,port=args.port,model=args.model,business_date=args.business_date)
    app=create_application(settings)
    server=ThreadingHTTPServer(('127.0.0.1',settings.port),handler(app.service,app.triage))
    print('SettlementLab running at http://127.0.0.1:%s'%server.server_port,flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
