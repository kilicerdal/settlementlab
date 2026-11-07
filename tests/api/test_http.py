import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from settlementlab.domain import Ledger
from settlementlab.server import handler
from settlementlab.ai import Triage
from settlementlab.assurance.client import SettlementClient, APIError


class HTTPTests(unittest.TestCase):
    def setUp(self):
        from settlementlab.assurance.fixtures import LocalEnvironment
        self.environment=LocalEnvironment().__enter__()
        self.addCleanup(self.environment.__exit__,None,None,None)
        self.client=self.environment.client

    def test_real_http_lifecycle(self):
        self.assertEqual(self.client.request('/api/health')['status'],'healthy')
        t=self.client.create(dict(symbol='NOVA',quantity=10,price='0.29',trade_date='2026-11-06'),'http-1')
        t=self.client.command(t,'allocate',allocations=[dict(account='SYN-A',quantity=10)])
        t=self.client.command(t,'affirm',instruction='SYN-CUSTODY')
        t=self.client.command(t,'fund',cash_cents=290,securities=10)
        t=self.client.command(t,'settle')
        self.assertEqual(t['state'],'SETTLED')
        self.assertEqual(self.client.request('/api/reconcile',{'statement':[dict(trade_id=t['id'],quantity=10,amount_cents=290)]})['status'],'BALANCED')

    def test_errors_preserve_status(self):
        with self.assertRaises(APIError) as error:self.client.create({},'invalid')
        self.assertEqual(error.exception.status,422)
        with self.assertRaises(APIError) as error:self.client.request('/missing')
        self.assertEqual(error.exception.status,404)

    def test_console_assets_are_served(self):
        from urllib.request import urlopen
        for path, expected in [('/', 'SettlementLab'), ('/app.js', 'use strict'), ('/style.css', ':root')]:
            with self.subTest(path=path):
                with urlopen(self.client.base_url+path) as response:
                    self.assertEqual(response.status,200)
                    self.assertIn(expected,response.read().decode())
                    self.assertEqual(response.headers['X-Content-Type-Options'],'nosniff')

    def test_disabled_ai_and_stale_analysis_do_not_mutate_trade(self):
        t=self.client.create(dict(symbol='NOVA',quantity=10,price='0.29',trade_date='2026-11-06'),'ai-http')
        before=self.client.request('/api/snapshot')
        with self.assertRaises(APIError) as error:
            self.client.request('/api/trades/'+t['id']+'/analyze',{'version':t['version']-1})
        self.assertEqual(error.exception.status,409)
        self.assertEqual(self.client.request('/api/snapshot'),before)
        with self.assertRaises(APIError) as error:
            self.client.request('/api/trades/'+t['id']+'/analyze',{'version':t['version']})
        self.assertEqual(error.exception.status,503)
        self.assertEqual(self.client.request('/api/snapshot'),before)

    def test_two_sided_http_submission_revision_and_replay(self):
        broker=dict(symbol='NOVA',side='BUY',currency='USD',quantity=100,price='42.75',
                    trade_date='2026-11-06',settlement_date='2026-11-09')
        t=self.client.create(dict(broker,matching_mode='two-sided'),'http-two-sided')
        manager=dict(broker,price='42.76',allocations=[dict(account='SYN-A',quantity=100)])
        broken=self.client.submit_manager(t,manager,'manager-initial')
        self.assertEqual(broken['matching']['findings'][0]['code'],'PRICE_MISMATCH')
        self.assertEqual(broken['price_cents'],4275)
        fixed=self.client.submit_manager(broken,dict(manager,price='42.75'),'manager-corrected')
        self.assertEqual(fixed['state'],'MATCHED')
        replay=self.client.submit_manager(t,manager,'manager-initial')
        self.assertEqual(replay,broken)
        self.assertEqual(self.client.request('/api/snapshot')['trades'][0]['version'],fixed['version'])
        policy=self.client.request('/api/matching-policy')
        self.assertEqual(policy['id'],'equity-exact-v1')
        self.assertEqual(len(policy['rules']),8)

    def test_server_resolved_roles_and_shared_settlement(self):
        terms=dict(symbol='NOVA',side='BUY',currency='USD',quantity=100,price='42.75',
                   trade_date='2026-11-06',settlement_date='2026-11-09')
        payload=dict(terms,matching_mode='two-sided',settlement_model='shared-ledger')
        with self.assertRaises(APIError) as error:self.client.create(dict(payload,role='maker'),'governed')
        self.assertEqual(error.exception.status,403)
        self.client.use_persona('maker-alex')
        t=self.client.create(payload,'governed')
        t=self.client.submit_manager(t,dict(terms,allocations=[dict(account='SYN-A',quantity=100)]),'manager')
        t=self.client.request_affirmation(t,'SYN-CUSTODY','review')
        with self.assertRaises(APIError) as error:self.client.command(t,'approve',approval_id=t['pending_approval']['id'],role='checker',actor='checker-sam')
        self.assertEqual(error.exception.status,403)
        self.client.use_persona('checker-sam')
        t=self.client.approve(t)
        self.assertEqual(t['state'],'AFFIRMED')
        self.client.fund('SYN-ALPHA','CASH:USD',427500,'cash')
        self.client.fund('SYN-BROKER','SEC:NOVA',100,'stock')
        t=self.client.command(t,'settle')
        self.assertEqual(t['state'],'SETTLED')
        treasury=self.client.request('/api/treasury')
        self.assertEqual(treasury['controls']['status'],'BALANCED')
        self.client.use_persona('auditor-casey')
        with self.assertRaises(APIError) as error:self.client.fund('SYN-ALPHA','CASH:USD',1,'unauthorized')
        self.assertEqual(error.exception.status,403)
        self.assertEqual(self.client.request('/api/session')['principal']['role'],'auditor')

    def test_unknown_cookie_and_invented_persona_do_not_grant_access(self):
        with self.assertRaises(APIError) as error:self.client.use_persona('root')
        self.assertEqual(error.exception.status,422)
        from urllib.request import Request,urlopen
        from urllib.error import HTTPError
        import json
        request=Request(self.client.base_url+'/api/treasury/fund',
            data=json.dumps(dict(participant_id='SYN-ALPHA',asset='CASH:USD',amount=1,role='checker')).encode(),
            headers={'Cookie':'settlementlab_session=forged','Content-Type':'application/json','Idempotency-Key':'forged'})
        with self.assertRaises(HTTPError) as error:urlopen(request)
        self.assertEqual(error.exception.code,403)
