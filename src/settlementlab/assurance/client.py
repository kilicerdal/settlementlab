import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError


class APIError(Exception):
    def __init__(self, status, body):
        self.status, self.body = status, body
        super().__init__('HTTP %s: %s' % (status, body))


class SettlementClient:
    """Environment-configurable API client; returns JSON, preserves error status."""
    def __init__(self, base_url, timeout=10):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout

    def request(self, path, data=None, key=None):
        headers={'Content-Type':'application/json'}
        if key: headers['Idempotency-Key']=key
        request=Request(self.base_url+path, data=None if data is None else json.dumps(data).encode(), headers=headers)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except HTTPError as error:
            raise APIError(error.code,json.load(error)) from error

    def create(self, trade, key):
        return self.request('/api/trades',trade,key)

    def command(self, trade, action, **data):
        return self.request('/api/trades/%s/%s' % (trade['id'],action),dict(version=trade['version'],**data))

    def submit_manager(self, trade, terms, key):
        return self.request('/api/trades/%s/manager' % trade['id'], dict(terms,version=trade['version']), key)
