"""V1/V2 compatibility facade; new code uses bootstrap or SettlementService."""
from .application.service import SettlementService
from .infrastructure.store import SQLiteStore
from .core.validation import DomainError, cents, positive_int, next_business_day

class Ledger(SettlementService):
    def __init__(self,path,clock=None,calendar=None):
        from .infrastructure.clock import SystemClock
        from .core.calendar import BusinessCalendar
        super().__init__(SQLiteStore(path),clock or SystemClock(),calendar or BusinessCalendar())
        self.path=self.store.path

    def connection(self):
        """Legacy infrastructure access retained for fault-injection consumers."""
        return self.store.connection()
