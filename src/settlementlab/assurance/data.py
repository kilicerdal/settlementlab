"""Independent synthetic input builders; no application calculation imports."""
from copy import deepcopy
from uuid import uuid4


class TradeFactory:
    def __init__(self,namespace=None):
        self.namespace=namespace or uuid4().hex[:12]
        self.sequence=0

    def key(self,label='request'):
        self.sequence+=1
        return self.namespace+'-'+label+'-'+str(self.sequence)

    def terms(self,**changes):
        values=dict(symbol='NOVA',side='BUY',currency='USD',quantity=100,price='42.75',
                    trade_date='2026-11-06',settlement_date='2026-11-09')
        values.update(changes)
        return deepcopy(values)

    def broker(self,**changes):
        return dict(self.terms(**changes),matching_mode='two-sided',settlement_model='shared-ledger')

    def manager(self,**changes):
        values=self.terms(**changes)
        values.setdefault('allocations',[dict(account='SYN-FUND',quantity=100)])
        return values
