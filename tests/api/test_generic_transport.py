import unittest
from http.server import BaseHTTPRequestHandler

from settlementlab.assurance.fixtures import HTTPEnvironment
from settlementlab.assurance.transport import APIError, JsonClient, TransportError


class GenericTransportControls(unittest.TestCase):
    def test_non_json_errors_and_bounded_responses(self):
        class Example(BaseHTTPRequestHandler):
            def do_GET(self):
                code = 503 if self.path == "/error" else 200
                data = b"<html>synthetic error</html>" if self.path != "/large" else b"x" * 1048577
                self.send_response(code)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        with HTTPEnvironment(Example) as environment:
            client = JsonClient(environment.base_url)
            with self.assertRaises(APIError) as error:
                client.request("/error")
            self.assertEqual(error.exception.status, 503)
            self.assertEqual(error.exception.body, {"error": "Non-JSON error response"})
            for route, kind in [("/invalid", "invalid_json"), ("/large", "response_too_large")]:
                with self.assertRaises(TransportError) as failure:
                    client.request(route)
                self.assertEqual(failure.exception.kind, kind)

    def test_redirects_are_reported_not_silently_followed(self):
        calls = []

        class Redirect(BaseHTTPRequestHandler):
            def do_GET(self):
                calls.append(self.path)
                self.send_response(302)
                self.send_header("Location", "/unexpected")
                self.send_header("Content-Length", "0")
                self.end_headers()

        with HTTPEnvironment(Redirect) as environment:
            client = JsonClient(environment.base_url)
            with self.assertRaises(APIError) as error:
                client.request("/redirect")
            self.assertEqual(error.exception.status, 302)
            self.assertEqual(client.last_exchange["status"], 302)
            self.assertEqual(calls, ["/redirect"])
