"""Real loopback HTTP integration around the candidate arithmetic implementation."""

import json
import math
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen


def check(module) -> None:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            parsed = urlparse(self.path)
            status = 200
            try:
                if parsed.path != "/divide":
                    status, body = 404, {"error": "not_found"}
                else:
                    query = parse_qs(parsed.query)
                    a, b = float(query["a"][0]), float(query["b"][0])
                    if not math.isfinite(a) or not math.isfinite(b):
                        raise ValueError("nonfinite input")
                    body = {"result": module.divide(a, b)}
            except ZeroDivisionError:
                status, body = 400, {"error": "zero_denominator"}
            except (KeyError, ValueError):
                status, body = 400, {"error": "invalid_input"}
            content = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for path, status, expected in (("/divide?a=8&b=2", 200, {"result": 4}),
                                        ("/divide?a=1&b=0", 400, {"error": "zero_denominator"}),
                                        ("/divide?a=invalid&b=2", 400, {"error": "invalid_input"}),
                                        ("/divide?a=NaN&b=2", 400, {"error": "invalid_input"}),
                                        ("/divide?a=1", 400, {"error": "invalid_input"}),
                                        ("/missing", 404, {"error": "not_found"})):
            try:
                response = urlopen(f"http://127.0.0.1:{server.server_port}{path}", timeout=5)
            except HTTPError as error:
                response = error
            with response:
                assert response.status == status, "HTTP status"
                assert json.loads(response.read()) == expected, "HTTP response"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
