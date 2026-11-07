"""Explicit local demo identities; not a production login or identity proof."""
from http.cookies import SimpleCookie, CookieError
import secrets
import threading
import time
from ..core.validation import DomainError
from ..core.identity import Principal, require


PERSONAS = {
    'maker-alex': Principal('maker-alex', 'maker'),
    'checker-sam': Principal('checker-sam', 'checker'),
    'auditor-casey': Principal('auditor-casey', 'auditor'),
}


def require(principal, role):
    if not isinstance(principal, Principal) or principal.role != role:
        raise DomainError('This operation requires the '+role+' demo identity', 403)


class DemoSessions:
    """Opaque, server-resolved cookies prevent request-body role spoofing.

    Anyone using the local demo can select a persona. This models separation of
    duties between identities, not authentication of different human operators.
    """
    def __init__(self):
        self.sessions = {}
        self.lock = threading.Lock()

    def start(self, persona):
        if not isinstance(persona,str) or persona not in PERSONAS:
            raise DomainError('Unknown demo identity')
        token = secrets.token_urlsafe(32)
        now = time.monotonic()
        with self.lock:
            self.sessions = {key:value for key,value in self.sessions.items() if value[1] > now}
            if len(self.sessions) >= 1000:
                raise DomainError('Too many local demo sessions; restart the server', 429)
            self.sessions[token] = (PERSONAS[persona], now+3600)
        return token, PERSONAS[persona]

    def resolve(self, header):
        try:
            cookies = SimpleCookie()
            cookies.load(header or '')
            token = cookies['settlementlab_session'].value
        except (KeyError, ValueError, CookieError):
            return None
        with self.lock:
            record = self.sessions.get(token)
        return record[0] if record and record[1] > time.monotonic() else None
