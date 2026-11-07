"""Business invariants for shared multi-asset settlement and checker controls."""
import concurrent.futures
import tempfile
import unittest
from pathlib import Path
from settlementlab.domain import Ledger, DomainError
from settlementlab.identity import Principal
from settlementlab import journal

MAKER=Principal('maker-alex','maker')
CHECKER=Principal('checker-sam','checker')
AUDITOR=Principal('auditor-casey','auditor')


class SharedLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.ledger=Ledger(Path(self.temp.name)/'shared.db')
        self.terms=dict(symbol='NOVA',side='BUY',currency='USD',quantity=100,price='42.75',
                        trade_date='2026-11-06',settlement_date='2026-11-09')

    def create(self,key='trade-1',**terms):
        return self.ledger.create(dict(self.terms,**terms,matching_mode='two-sided',settlement_model='shared-ledger'),key,principal=MAKER)

    def manager(self,t,key='manager-1',**terms):
        return self.ledger.command(t['id'],'manager',dict(self.terms,**terms,allocations=[dict(account='SYN-FUND',quantity=100)],
                                  version=t['version'],submission_key=key),principal=MAKER)

    def command(self,t,action,principal=CHECKER,**data):
        return self.ledger.command(t['id'],action,dict(version=t['version'],**data),principal=principal)

    def approve(self,t):
        t=self.command(t,'request-affirmation',MAKER,instruction='SYN-CUSTODY',request_key='review-1')
        return self.command(t,'approve',approval_id=t['pending_approval']['id'])

    def ready(self,key='trade-1'):
        return self.approve(self.manager(self.create(key)))

    def fund(self,party,asset,amount,key):
        return self.ledger.fund_participant(dict(participant_id=party,asset=asset,amount=amount),key,CHECKER)

    def balances(self):
        return {(r['participant_id'],r['asset']):r['balance'] for r in self.ledger.snapshot()['treasury']['balances']}

    def test_buy_transfers_four_balanced_lines(self):
        t=self.ready()
        self.fund('SYN-ALPHA','CASH:USD',427500,'cash')
        self.fund('SYN-BROKER','SEC:NOVA',100,'stock')
        t=self.command(t,'settle')
        self.assertEqual(t['state'],'SETTLED')
        balances=self.balances()
        self.assertEqual(balances[('SYN-ALPHA','CASH:USD')],0)
        self.assertEqual(balances[('SYN-BROKER','CASH:USD')],427500)
        self.assertEqual(balances[('SYN-ALPHA','SEC:NOVA')],100)
        self.assertEqual(balances[('SYN-BROKER','SEC:NOVA')],0)
        treasury=self.ledger.snapshot()['treasury']
        batch=next(b for b in treasury['batches'] if b['kind']=='DVP_SETTLEMENT')
        self.assertEqual(len(batch['lines']),4)
        for asset in ('CASH:USD','SEC:NOVA'):
            self.assertEqual(sum(l['delta'] for l in batch['lines'] if l['asset']==asset),0)
        self.assertEqual(treasury['controls']['status'],'BALANCED')

    def test_sell_reverses_buyer_and_seller(self):
        t=self.create(side='SELL');t=self.manager(t,side='SELL');t=self.approve(t)
        self.assertEqual((t['buyer_id'],t['seller_id']),('SYN-BROKER','SYN-ALPHA'))
        self.fund('SYN-BROKER','CASH:USD',427500,'cash')
        self.fund('SYN-ALPHA','SEC:NOVA',100,'stock')
        t=self.command(t,'settle')
        self.assertEqual(t['state'],'SETTLED')
        self.assertEqual(self.balances()[('SYN-ALPHA','CASH:USD')],427500)
        self.assertEqual(self.balances()[('SYN-BROKER','SEC:NOVA')],100)

    def test_two_trades_cannot_spend_same_cash(self):
        first,second=self.ready('first'),self.ready('second')
        self.fund('SYN-ALPHA','CASH:USD',427500,'cash')
        self.fund('SYN-BROKER','SEC:NOVA',200,'stock')
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            states=list(pool.map(lambda t:self.command(t,'settle')['state'],[first,second]))
        self.assertCountEqual(states,['SETTLED','FAILED'])
        self.assertEqual(self.balances()[('SYN-ALPHA','CASH:USD')],0)
        self.assertEqual(len([b for b in self.ledger.snapshot()['treasury']['batches'] if b['kind']=='DVP_SETTLEMENT']),1)

    def test_failure_preserves_balances_then_recovers_once(self):
        t=self.ready();self.fund('SYN-ALPHA','CASH:USD',427500,'cash')
        before=self.ledger.snapshot()['treasury']
        t=self.command(t,'settle')
        self.assertEqual(t['state'],'FAILED')
        self.assertEqual(self.ledger.snapshot()['treasury'],before)
        self.fund('SYN-BROKER','SEC:NOVA',100,'stock')
        t=self.command(t,'settle')
        self.assertEqual(t['state'],'SETTLED')
        before=self.ledger.snapshot()
        with self.assertRaises(DomainError):self.command(t,'settle')
        self.assertEqual(self.ledger.snapshot(),before)

    def test_self_approval_and_role_spoof_are_rejected(self):
        t=self.manager(self.create())
        t=self.command(t,'request-affirmation',MAKER,instruction='SYN-CUSTODY',request_key='review')
        before=self.ledger.snapshot()
        # Even a principal with checker capability cannot approve its own maker ID.
        for identity in [MAKER,Principal(MAKER.id,'checker'),AUDITOR,None]:
            with self.subTest(identity=identity):
                with self.assertRaises(DomainError) as error:self.command(t,'approve',identity,approval_id=t['pending_approval']['id'])
                self.assertEqual(error.exception.status,403)
                self.assertEqual(self.ledger.snapshot(),before)

    def test_terms_revision_cancels_pending_approval(self):
        t=self.manager(self.create())
        t=self.command(t,'request-affirmation',MAKER,instruction='SYN-CUSTODY',request_key='review')
        old_request=t['pending_approval']['id']
        revised=self.manager(t,'new-terms')
        self.assertIsNone(revised['pending_approval'])
        self.assertEqual(revised['approval_history'][0]['status'],'CANCELLED')
        with self.assertRaises(DomainError):self.command(revised,'approve',approval_id=old_request)
        self.assertEqual(revised['state'],'MATCHED')

    def test_rejection_requires_reason_and_allows_new_request(self):
        t=self.manager(self.create())
        t=self.command(t,'request-affirmation',MAKER,instruction='SYN-CUSTODY',request_key='review')
        with self.assertRaises(DomainError):self.command(t,'reject',approval_id=t['pending_approval']['id'])
        t=self.command(t,'reject',approval_id=t['pending_approval']['id'],reason='Review custody instruction')
        self.assertEqual(t['state'],'MATCHED')
        self.assertEqual(t['approval_history'][0]['status'],'REJECTED')
        t=self.command(t,'request-affirmation',MAKER,instruction='SYN-NEW',request_key='review-2')
        self.assertEqual(len(t['approval_history']),2)

    def test_funding_is_checker_only_idempotent_and_conflict_safe(self):
        data=dict(participant_id='SYN-ALPHA',asset='CASH:USD',amount=100)
        for identity in [MAKER,AUDITOR,None]:
            with self.assertRaises(DomainError):self.ledger.fund_participant(data,'fund',identity)
        first=self.ledger.fund_participant(data,'fund',CHECKER)
        again=self.ledger.fund_participant(data,'fund',CHECKER)
        self.assertEqual(first['batch_id'],again['batch_id'])
        self.assertTrue(again['replayed'])
        self.assertEqual(self.balances()[('SYN-ALPHA','CASH:USD')],100)
        with self.assertRaises(DomainError):self.ledger.fund_participant(dict(data,amount=101),'fund',CHECKER)
        self.assertEqual(self.balances()[('SYN-ALPHA','CASH:USD')],100)

    def test_bypass_paths_and_unauthenticated_writes_fail(self):
        with self.assertRaises(DomainError):self.ledger.create(dict(self.terms,matching_mode='two-sided',settlement_model='shared-ledger'),'no-session')
        t=self.manager(self.create())
        for action,identity in [('affirm',MAKER),('affirm',CHECKER),('fund',CHECKER),('settle',None)]:
            with self.subTest(action=action):
                with self.assertRaises(DomainError):self.command(t,action,identity,instruction='SYN-BYPASS',cash_cents=427500,securities=100)

    def test_journal_and_settlement_rollback_together_on_failure(self):
        import sqlite3
        t=self.ready();self.fund('SYN-ALPHA','CASH:USD',427500,'cash');self.fund('SYN-BROKER','SEC:NOVA',100,'stock')
        with self.ledger.connection() as db:
            db.execute("CREATE TRIGGER injected_failure BEFORE INSERT ON settlements BEGIN SELECT RAISE(ABORT,'injected storage failure'); END")
        before=self.ledger.snapshot()
        with self.assertRaises(sqlite3.IntegrityError):self.command(t,'settle')
        self.assertEqual(self.ledger.snapshot(),before)

    def test_projection_check_detects_direct_balance_corruption(self):
        self.fund('SYN-ALPHA','CASH:USD',100,'cash')
        with self.ledger.connection() as db:db.execute("UPDATE balances SET balance=99 WHERE participant_id='SYN-ALPHA'")
        self.assertEqual(self.ledger.snapshot()['treasury']['controls']['status'],'BREAKS')

    def test_unbalanced_batch_is_rejected_without_writes(self):
        before=self.ledger.snapshot()['treasury']
        with self.assertRaises(DomainError):
            with self.ledger.connection() as db:journal.post(db,'bad','TEST',[('SYN-ALPHA','CASH:USD',100),('SYN-BROKER','CASH:USD',-99)],'test')
        self.assertEqual(self.ledger.snapshot()['treasury'],before)

    def test_approval_replay_and_stale_checker(self):
        t=self.manager(self.create());old=t
        t=self.command(t,'request-affirmation',MAKER,instruction='SYN-CUSTODY',request_key='review')
        before=self.ledger.snapshot()
        replay=self.command(old,'request-affirmation',MAKER,instruction='SYN-CUSTODY',request_key='review')
        self.assertEqual(replay,t)
        self.assertEqual(self.ledger.snapshot(),before)
        with self.assertRaises(DomainError):self.command(old,'approve',approval_id=t['pending_approval']['id'])
        self.assertEqual(self.ledger.snapshot(),before)

    def test_two_trades_cannot_spend_same_securities(self):
        first,second=self.ready('first'),self.ready('second')
        self.fund('SYN-ALPHA','CASH:USD',855000,'cash')
        self.fund('SYN-BROKER','SEC:NOVA',100,'stock')
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            states=list(pool.map(lambda t:self.command(t,'settle')['state'],[first,second]))
        self.assertCountEqual(states,['SETTLED','FAILED'])
        self.assertEqual(self.balances()[('SYN-BROKER','SEC:NOVA')],0)
        self.assertEqual(self.balances()[('SYN-ALPHA','CASH:USD')],427500)

    def test_concurrent_funding_replay_posts_one_batch(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:self.fund('SYN-ALPHA','CASH:USD',100,'same'),range(8)))
        self.assertEqual(len({r['batch_id'] for r in results}),1)
        self.assertEqual(self.balances()[('SYN-ALPHA','CASH:USD')],100)
        self.assertEqual(len(self.ledger.snapshot()['treasury']['batches']),1)

    def test_competing_checker_decisions_apply_once(self):
        t=self.manager(self.create())
        t=self.command(t,'request-affirmation',MAKER,instruction='SYN-CUSTODY',request_key='review')
        def decide(_):
            try:return self.command(t,'approve',approval_id=t['pending_approval']['id'])['state']
            except DomainError:return 'CONFLICT'
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(decide,range(2))),['AFFIRMED','CONFLICT'])
        current=self.ledger.snapshot()['trades'][0]
        self.assertEqual(current['version'],4)
        self.assertEqual(current['approval_history'][0]['status'],'APPROVED')

    def test_integrity_break_prevents_settlement_posting(self):
        t=self.ready();self.fund('SYN-ALPHA','CASH:USD',427500,'cash');self.fund('SYN-BROKER','SEC:NOVA',100,'stock')
        with self.ledger.connection() as db:db.execute("UPDATE balances SET balance=427501 WHERE participant_id='SYN-ALPHA'")
        before=self.ledger.snapshot()
        with self.assertRaises(DomainError) as error:self.command(t,'settle')
        self.assertEqual(error.exception.status,409)
        self.assertEqual(self.ledger.snapshot(),before)

    def test_invalid_funding_and_limits_preserve_journal(self):
        before=self.ledger.snapshot()
        for data in [dict(participant_id='UNKNOWN',asset='CASH:USD',amount=1),
                     dict(participant_id='SYN-RESERVE',asset='CASH:USD',amount=1),
                     dict(participant_id='SYN-ALPHA',asset='USD',amount=1),
                     dict(participant_id='SYN-ALPHA',asset='CASH:USD',amount=True),
                     dict(participant_id='SYN-ALPHA',asset='CASH:USD',amount=10**15+1)]:
            with self.subTest(data=data):
                with self.assertRaises(DomainError):self.ledger.fund_participant(data,'invalid',CHECKER)
                self.assertEqual(self.ledger.snapshot(),before)
        self.fund('SYN-ALPHA','CASH:USD',10**15,'full')
        before=self.ledger.snapshot()
        with self.assertRaises(DomainError):self.fund('SYN-ALPHA','CASH:USD',1,'overflow')
        self.assertEqual(self.ledger.snapshot(),before)

    def test_shared_journal_and_approvals_survive_restart(self):
        t=self.ready();self.fund('SYN-ALPHA','CASH:USD',427500,'cash');self.fund('SYN-BROKER','SEC:NOVA',100,'stock')
        self.command(t,'settle')
        before=self.ledger.snapshot()
        reopened=Ledger(self.ledger.path)
        self.assertEqual(reopened.snapshot(),before)
