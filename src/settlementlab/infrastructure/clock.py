"""Wall-clock adapter; simulated dates use the pure FixedClock instead."""

from datetime import datetime, timezone


class SystemClock:
    def today(self):
        return datetime.now(timezone.utc).date()

    def describe(self):
        return dict(mode="system", date=self.today().isoformat(), timezone="UTC")
