"""Explicit synthetic setup for durable assurance; never used by production requests."""

from ..core.identity import Principal

MAKER = Principal("maker-alex", "maker")
CHECKER = Principal("checker-sam", "checker")
AUDITOR = Principal("auditor-casey", "auditor")


def approved_trade(
    service,
    key="durable-trade",
    funded=True,
    quantity=100,
    price="42.75",
    side="BUY",
    symbol="NOVA",
    initial_manager_price=None,
):
    terms = dict(
        symbol=symbol,
        side=side,
        currency="USD",
        quantity=quantity,
        price=price,
        trade_date="2026-11-06",
        settlement_date="2026-11-09",
    )
    trade = service.create(
        dict(terms, matching_mode="two-sided", settlement_model="shared-ledger"),
        key,
        principal=MAKER,
    )
    if initial_manager_price is not None:
        trade = service.command(
            trade["id"],
            "manager",
            dict(
                terms,
                price=initial_manager_price,
                version=trade["version"],
                submission_key=key + "-manager-initial",
                allocations=[dict(account="SYN-FUND", quantity=quantity)],
            ),
            principal=MAKER,
        )
        if trade["state"] != "EXCEPTION":
            raise AssertionError("Planned initial price break was not detected")
    trade = service.command(
        trade["id"],
        "manager",
        dict(
            terms,
            version=trade["version"],
            submission_key=key + "-manager",
            allocations=[dict(account="SYN-FUND", quantity=quantity)],
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
