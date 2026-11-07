import concurrent.futures
import tempfile
import unittest
from pathlib import Path
from settlementlab.domain import Ledger, DomainError, cents, next_business_day


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = Ledger(Path(self.temp.name) / 'test.db')
        self.payload = dict(symbol='NOVA', quantity=100, price='42.75', trade_date='2026-11-06')

    def create(self, key='request-1'):
        return self.ledger.create(self.payload, key)

    def command(self, trade, action, **data):
        return self.ledger.command(trade['id'], action, dict(version=trade['version'], **data))

    def affirm(self):
        t = self.create()
        t = self.command(t, 'allocate', allocations=[dict(account='SYN-A', quantity=100)])
        return self.command(t, 'affirm', instruction='SYN-CUSTODY')

    def test_exception_correction_failure_recovery_and_reconciliation(self):
        t = self.create()
        t = self.command(t, 'allocate', allocations=[dict(account='SYN-A', quantity=99)])
        self.assertEqual(t['state'], 'EXCEPTION')
        t = self.command(t, 'allocate', allocations=[dict(account='SYN-A', quantity=60),dict(account='SYN-B', quantity=40)])
        self.assertEqual(t['state'], 'MATCHED')
        t = self.command(t, 'affirm', instruction='SYN-CUSTODY')
        t = self.command(t, 'settle')
        self.assertEqual(t['state'], 'FAILED')
        t = self.command(t, 'fund', cash_cents=427500, securities=100)
        t = self.command(t, 'settle')
        self.assertEqual((t['state'], t['cash_cents'], t['securities']), ('SETTLED',0,0))
        statement=[dict(trade_id=t['id'],quantity=100,amount_cents=427500)]
        self.assertEqual(self.ledger.reconcile(statement)['status'],'BALANCED')
        statement[0]['amount_cents']=427499
        self.assertEqual(self.ledger.reconcile(statement)['breaks'][0]['reason'],'VALUE_MISMATCH')
        self.assertEqual(self.ledger.reconcile([])['breaks'][0]['reason'],'MISSING_EXTERNAL')
        self.assertEqual(len(self.ledger.snapshot()['audit']),7)

    def test_idempotency_and_conflicting_payload(self):
        self.assertEqual(self.create()['id'],self.create()['id'])
        with self.assertRaises(DomainError):
            self.ledger.create(dict(self.payload,quantity=101),'request-1')
        self.assertEqual(len(self.ledger.snapshot()['audit']),1)

    def test_concurrent_duplicate_submissions(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            ids=list(pool.map(lambda _: self.create()['id'],range(16)))
        self.assertEqual(len(set(ids)),1)
        self.assertEqual(len(self.ledger.snapshot()['trades']),1)

    def test_stale_version_and_invalid_transition_are_atomic(self):
        t=self.create()
        with self.assertRaises(DomainError):self.command(t,'settle')
        current=self.command(t,'allocate',allocations=[dict(account='SYN-A',quantity=100)])
        with self.assertRaises(DomainError):self.command(t,'allocate',allocations=[dict(account='SYN-A',quantity=99)])
        self.assertEqual(self.ledger.snapshot()['trades'][0]['state'],current['state'])
        self.assertEqual(len(self.ledger.snapshot()['audit']),2)

    def test_concurrent_settlement_is_once_only(self):
        t=self.command(self.affirm(),'fund',cash_cents=427500,securities=100)
        def attempt(_):
            try:return self.command(t,'settle')['state']
            except DomainError:return 'CONFLICT'
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(attempt,range(2))),['SETTLED','CONFLICT'])
        self.assertEqual(self.ledger.snapshot()['trades'][0]['cash_cents'],0)

    def test_validation_and_calendar(self):
        self.assertEqual(next_business_day('2026-11-06'),'2026-11-09')
        self.assertEqual(cents('0.29'),29)
        for value in ['NaN','Infinity','1.001','-1',None]:
            with self.assertRaises(DomainError):cents(value)
        for quantity in [True,0,-1,1.5]:
            with self.assertRaises(DomainError):self.ledger.create(dict(self.payload,quantity=quantity),'bad')

    def test_duplicate_accounts_rollback(self):
        t=self.create()
        with self.assertRaises(DomainError):self.command(t,'allocate',allocations=[dict(account='A',quantity=50)]*2)
        self.assertEqual(self.ledger.snapshot()['trades'][0]['version'],1)

    def test_terminal_trade_cannot_change(self):
        t=self.command(self.affirm(),'fund',cash_cents=427500,securities=100)
        t=self.command(t,'settle')
        for action in ['allocate','affirm','fund','settle']:
            with self.assertRaises(DomainError):self.command(t,action)

    def test_external_only_and_duplicate_statement(self):
        row=dict(trade_id='UNKNOWN',quantity=1,amount_cents=100)
        self.assertEqual(self.ledger.reconcile([row])['breaks'][0]['reason'],'MISSING_INTERNAL')
        with self.assertRaises(DomainError):self.ledger.reconcile([row,row])

    def test_persistence(self):
        t=self.create()
        reopened=Ledger(self.ledger.path)
        self.assertEqual(reopened.snapshot()['trades'][0]['id'],t['id'])

    def test_notional_and_date_bounds(self):
        with self.assertRaises(DomainError):
            self.ledger.create(dict(self.payload,quantity=10**9,price='10000000000'),'huge')
        with self.assertRaises(DomainError):
            self.ledger.create(dict(self.payload,trade_date='9999-12-31'),'future')
