"""V1/V2 compatibility facade; new code uses bootstrap or SettlementService."""

from .application.service import SettlementService
from .core.validation import (
    DomainError as DomainError,
)
from .core.validation import (
    cents as cents,
)
from .core.validation import (
    next_business_day as next_business_day,
)
from .core.validation import (
    positive_int as positive_int,
)
from .infrastructure.store import SQLiteStore


class Ledger(SettlementService):
    def __init__(self, path, clock=None, calendar=None):
        from .core.calendar import BusinessCalendar
        from .infrastructure.clock import SystemClock

        super().__init__(SQLiteStore(path), clock or SystemClock(), calendar or BusinessCalendar())
        self.path = self.store.path

    def connection(self):
        """Legacy infrastructure access retained for fault-injection consumers."""
        return self.store.connection()
