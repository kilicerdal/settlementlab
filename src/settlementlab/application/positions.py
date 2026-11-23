"""At-least-once delivery of financial positions, including approved compensation."""

import time

from ..core.durable import LeaseLost, bounded_seconds, identifier


class PositionObserver:
    def __init__(self, service, now=time.time):
        self.service = service
        self.store = service.store
        self.now = now

    def deliver_one(self, worker, lease=30, fault=lambda phase: None):
        identifier(worker, 80)
        bounded_seconds(lease, 0.1, 300)
        with self.store.transaction() as repo:
            event = repo.position_claim(worker, self.now(), lease)
        if not event:
            return None
        try:
            with self.store.transaction() as repo:
                current = repo.position_owned(event["event_id"], event["lease_token"], self.now())
                applied = repo.position_consume(current, self.now())
                fault("before-projection-commit")
            fault("after-projection-commit")
            with self.store.transaction() as repo:
                repo.position_ack(event, self.now())
            return dict(event_id=event["event_id"], status="DELIVERED", applied=applied)
        except LeaseLost:
            return dict(event_id=event["event_id"], status="FENCED")
        except Exception as error:
            with self.store.transaction() as repo:
                status = repo.position_fail(event, self.now(), error)
            return dict(event_id=event["event_id"], status=status)

    def snapshot(self, trade_id):
        identifier(trade_id)
        with self.store.read_transaction() as repo:
            return repo.position_view(trade_id)
