import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from settlementlab.domain import Ledger
from settlementlab.server import handler
from settlementlab.assurance.client import SettlementClient, APIError


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler(Ledger(Path(self.temp.name)/'http.db')))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.client=SettlementClient('http://127.0.0.1:%d'%self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

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
