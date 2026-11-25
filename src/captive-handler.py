
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from http.client import HTTPConnection
from pathlib import Path
import subprocess
import threading

PORT = 8080
HOST = "10.42.0.1"
PHP_PORT = 8081

# Start PHP's built-in server
php_server = subprocess.Popen([
    "php",
    "-S", f"127.0.0.1:{PHP_PORT}",
    "-t", str(Path("../portal").resolve())
])

class PortalHandler(BaseHTTPRequestHandler):

    def handle_request(self):

        path = urlsplit(self.path).path

        if path not in ("/", "/index.php"):
            self.send_response(302)
            self.send_header("Location", f"http://{HOST}:{PORT}/")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return

        # Forward request to PHP
        body = None
        if self.command == "POST":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)

        conn = HTTPConnection("127.0.0.1", PHP_PORT)

        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in ("host", "connection")
        }

        conn.request(
            self.command,
            "/index.php" + (
                "?" + urlsplit(self.path).query
                if urlsplit(self.path).query else ""
            ),
            body=body,
            headers=headers
        )

        response = conn.getresponse()
        data = response.read()

        self.send_response(response.status)

        for key, value in response.getheaders():
            if key.lower() not in ("connection", "transfer-encoding"):
                self.send_header(key, value)

        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

        conn.close()

    def do_GET(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request()


server = ThreadingHTTPServer((HOST, PORT), PortalHandler)

print(f"Listening on port {PORT}")

try:
    server.serve_forever()
finally:
    server.server_close()
    php_server.terminate()
