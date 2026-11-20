"""Disposable HTTP routing fixture; never imports application configuration."""

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        data = json.dumps(
            {
                "marker": os.environ["PROBE_MARKER"],
                "path": self.path,
                "header": self.headers.get("X-Book-Ninja-Probe"),
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
