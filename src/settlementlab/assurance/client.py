"""Settlement-specific commands over the reusable JSON transport."""

from .transport import APIError as APIError
from .transport import JsonClient


class SettlementClient(JsonClient):
    def create(self, trade, key):
        return self.request("/api/trades", trade, key)

    def command(self, trade, action, **data):
        return self.request(
            "/api/trades/%s/%s" % (trade["id"], action), dict(version=trade["version"], **data)
        )

    def submit_manager(self, trade, terms, key):
        return self.request(
            "/api/trades/%s/manager" % trade["id"], dict(terms, version=trade["version"]), key
        )

    def use_persona(self, persona):
        return self.request("/api/session", dict(persona=persona))

    def request_affirmation(self, trade, instruction, key):
        return self.request(
            "/api/trades/%s/request-affirmation" % trade["id"],
            dict(version=trade["version"], instruction=instruction),
            key,
        )

    def approve(self, trade):
        return self.command(trade, "approve", approval_id=trade["pending_approval"]["id"])

    def fund(self, participant_id, asset, amount, key):
        return self.request(
            "/api/treasury/fund",
            dict(participant_id=participant_id, asset=asset, amount=amount),
            key,
        )
