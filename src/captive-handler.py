from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from pathlib import Path

page = Path("../portal/index.html").read_bytes()

class PortalHandler(BaseHTTPRequestHandler):

    def do_GET(self):

        path = urlsplit(self.path).path

        if path in ("/", "/index.html"):

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        else:

            self.send_response(302)
            self.send_header(
                "Location",
                "http://10.42.0.1:8080/"
            )
            self.send_header("Cache-Control", "no-store")
            self.end_headers()


server = ThreadingHTTPServer(
    ("10.42.0.1", 8080),
    PortalHandler
)

print("Captive portal listening on port 8080")

server.serve_forever()
