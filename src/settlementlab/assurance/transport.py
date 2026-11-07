"""Target-independent JSON transport with bounded, metadata-only diagnostics."""

import json
import socket
import time
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, Request, build_opener


class APIError(Exception):
    def __init__(self, status, body):
        self.status, self.body = status, body
        super().__init__("HTTP " + str(status))


class TransportError(Exception):
    def __init__(self, kind):
        self.kind = kind
        super().__init__("Transport failure: " + kind)


def validate_base_url(value):
    if not isinstance(value, str):
        raise ValueError("Base URL must be a string")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValueError("Invalid base URL")
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Base URL must be HTTP(S), without credentials, query or fragment")
    if port is not None and not 0 < port < 65536:
        raise ValueError("Invalid base URL port")
    return value.rstrip("/")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class JsonClient:
    def __init__(self, base_url, timeout=10):
        self.base_url = validate_base_url(base_url)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not 0 < timeout <= 60
        ):
            raise ValueError("Timeout must be greater than zero and at most 60 seconds")
        self.timeout = timeout
        self.cookies = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies), NoRedirect())
        self.last_exchange = None

    def request(self, path, data=None, key=None, method=None):
        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
            raise ValueError("Request path must be relative to the configured target")
        verb = method or ("GET" if data is None else "POST")
        if verb not in ("GET", "POST"):
            raise ValueError("Only GET and POST are supported")
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Idempotency-Key"] = key
        request = Request(
            self.base_url + path,
            data=None if data is None else json.dumps(data).encode(),
            headers=headers,
            method=verb,
        )
        start = time.perf_counter()
        self.last_exchange = dict(method=verb, path=urlsplit(path).path, status=None)
        try:
            try:
                response = self.opener.open(request, timeout=self.timeout)
            except HTTPError as error:
                response = error
            with response:
                self.last_exchange["status"] = response.code
                raw = response.read(1048577)
            if len(raw) > 1048576:
                raise TransportError("response_too_large")
            try:
                body = json.loads(raw)
            except (ValueError, UnicodeError):
                if self.last_exchange["status"] >= 300:
                    body = {"error": "Non-JSON error response"}
                else:
                    raise TransportError("invalid_json")
            if self.last_exchange["status"] >= 300:
                raise APIError(self.last_exchange["status"], body)
            return body
        except (TimeoutError, socket.timeout):
            raise TransportError("timeout")
        except URLError as error:
            raise TransportError(
                "timeout"
                if isinstance(error.reason, (TimeoutError, socket.timeout))
                else "connection"
            )
        except OSError:
            raise TransportError("connection")
        finally:
            self.last_exchange["duration"] = time.perf_counter() - start
