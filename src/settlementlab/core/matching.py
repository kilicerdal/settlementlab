"""Versioned matching policy with explicit, independently inspectable findings."""
from datetime import date
from .validation import DomainError, cents, positive_int, next_business_day

POLICY = 'equity-exact-v1'
FIELDS = (
    ('symbol', 'SECURITY'), ('side', 'SIDE'), ('quantity', 'QUANTITY'),
    ('price_cents', 'PRICE'), ('currency', 'CURRENCY'),
    ('trade_date', 'TRADE_DATE'), ('settlement_date', 'SETTLEMENT_DATE'),
)


def normalize_terms(data, complete=True):
    symbol = data.get('symbol')
    if not isinstance(symbol, str) or not symbol.isascii() or not symbol.isalnum() or not 1 <= len(symbol) <= 12:
        raise DomainError('Symbol must contain 1–12 ASCII letters or digits')
    side = data.get('side', None if complete else 'BUY')
    currency = data.get('currency', None if complete else 'USD')
    if side not in ('BUY', 'SELL'):
        raise DomainError('Side must be BUY or SELL, from the investment manager perspective')
    if currency not in ('USD', 'EUR', 'GBP', 'CAD', 'CHF', 'JPY'):
        raise DomainError('Provide a supported currency code: USD, EUR, GBP, CAD, CHF, or JPY')
    quantity, price = positive_int(data.get('quantity')), cents(data.get('price'))
    if quantity * price > 10**18:
        raise DomainError('Trade notional exceeds simulation limits')
    try:
        trade_date = date.fromisoformat(data['trade_date']).isoformat()
        if trade_date != data['trade_date']:
            raise ValueError()
        # Explicit dates are required from each participant in two-sided mode.
        settlement_date = date.fromisoformat(data['settlement_date']).isoformat() if complete else next_business_day(trade_date)
        if complete and settlement_date != data['settlement_date']:
            raise ValueError()
        if settlement_date <= trade_date:
            raise ValueError()
    except (ValueError, TypeError, KeyError, OverflowError):
        raise DomainError('Provide ISO trade and settlement dates; settlement must follow trade date')
    return dict(symbol=symbol.upper(), side=side, currency=currency, quantity=quantity,
                price_cents=price, trade_date=trade_date, settlement_date=settlement_date)


def normalize_allocations(allocations):
    if not isinstance(allocations, list) or not 1 <= len(allocations) <= 100:
        raise DomainError('Provide 1–100 allocations')
    accounts, result = set(), []
    for allocation in allocations:
        if not isinstance(allocation, dict):
            raise DomainError('Invalid allocation')
        account = allocation.get('account')
        if not isinstance(account, str) or not account.strip() or len(account) > 80:
            raise DomainError('Allocation accounts must be nonempty strings of at most 80 characters')
        account = account.strip()
        if account in accounts:
            raise DomainError('Allocation accounts must be unique')
        accounts.add(account)
        result.append(dict(account=account, quantity=positive_int(allocation.get('quantity'))))
    return sorted(result, key=lambda item: item['account'])


def compare(broker, manager):
    findings = []
    for field, code in FIELDS:
        if broker[field] != manager[field]:
            findings.append(dict(field=field, code=code+'_MISMATCH', rule_id=POLICY+':'+code,
                                 expected=broker[field], observed=manager[field],
                                 message=field.replace('_', ' ').capitalize()+' differs between broker and manager'))
    total = sum(item['quantity'] for item in manager['allocations'])
    if total != manager['quantity']:
        findings.append(dict(field='allocation_total', code='ALLOCATION_TOTAL_MISMATCH',
                             rule_id=POLICY+':ALLOCATION_TOTAL', expected=manager['quantity'], observed=total,
                             message='Allocations do not sum to the manager declared quantity'))
    return dict(policy=POLICY, status='EXCEPTION' if findings else 'MATCHED',
                compared_fields=len(FIELDS), findings=findings)


def policy_description():
    return dict(id=POLICY, version=1, scope='Synthetic USD equities; no FX or tolerance bands',
                side_convention='Both submissions use the investment manager economic BUY/SELL perspective',
                rules=[dict(id=POLICY+':'+code, field=field, comparison='exact equality') for field,code in FIELDS]
                      +[dict(id=POLICY+':ALLOCATION_TOTAL', field='allocation_total',comparison='sum equals manager quantity')])
