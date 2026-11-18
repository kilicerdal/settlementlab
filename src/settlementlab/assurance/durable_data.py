"""Explicit synthetic setup for durable assurance; never used by production requests."""

from ..core.identity import Principal

MAKER = Principal("maker-alex", "maker")
CHECKER = Principal("checker-sam", "checker")
AUDITOR = Principal("auditor-casey", "auditor")


def approved_trade(service, key="durable-trade", funded=True):
    terms = dict(
        symbol="NOVA",
        side="BUY",
        currency="USD",
        quantity=100,
        price="42.75",
        trade_date="2026-11-06",
        settlement_date="2026-11-09",
    )
    trade = service.create(
        dict(terms, matching_mode="two-sided", settlement_model="shared-ledger"),
        key,
        principal=MAKER,
    )
    trade = service.command(
        trade["id"],
        "manager",
        dict(
            terms,
            version=trade["version"],
            submission_key=key + "-manager",
            allocations=[dict(account="SYN-FUND", quantity=100)],
        ),
        principal=MAKER,
    )
    trade = service.command(
        trade["id"],
        "request-affirmation",
        dict(version=trade["version"], instruction="SYN-CUSTODY", request_key=key + "-approval"),
        principal=MAKER,
    )
    trade = service.command(
        trade["id"],
        "approve",
        dict(version=trade["version"], approval_id=trade["pending_approval"]["id"]),
        principal=CHECKER,
    )
    if funded:
        fund_trade(service, trade, key)
    return trade


def fund_trade(service, trade, key):
    for participant, asset, amount in [
        (trade["buyer_id"], "CASH:USD", trade["quantity"] * trade["price_cents"]),
        (trade["seller_id"], "SEC:" + trade["symbol"], trade["quantity"]),
    ]:
        service.fund_participant(
            dict(participant_id=participant, asset=asset, amount=amount), key + "-" + asset, CHECKER
        )


def entry(trade):
    return dict(trade_id=trade["id"], version=trade["version"])
