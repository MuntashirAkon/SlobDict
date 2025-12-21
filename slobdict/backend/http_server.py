# SPDX-License-Identifier: AGPL-3.0-or-later

import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote, quote
import json
from typing import Optional

class DictionaryHTTPHandler(BaseHTTPRequestHandler):
    """HTTP handler for dictionary requests."""
    
    slob_client = None
    dark_mode = False
    dark_mode_css = None

    def do_GET(self):
        """Handle GET requests."""
        try:
            parsed_path = urlparse(self.path)
            path = parsed_path.path
            query = parse_qs(parsed_path.query)

            print(f"[HTTP] {self.command} {self.path}")  # Debug log
            print(f"       Path: {path}")
            print(f"       Query: {query}")
            print(f"       Headers: {dict(self.headers)}")  # Debug log

            if path == "/find":
                self._handle_find(query)
            elif path.startswith("/slob/"):
                self._handle_slob(path, query)
            else:
                print(f"[HTTP] 404: Unknown path {path}")
                self._not_found()
        except Exception as e:
            print(f"[HTTP] Error: {e}")
            import traceback
            traceback.print_exc()
            self._error_response(500, str(e))

    def _handle_slob(self, path, query):
        """
        Handle slob content request: /slob/{source}/{key}
        Returns raw content with proper content type
        """
        # Parse path: /slob/{source}/{key}
        parts = path.split("/")
        print(f"[HTTP] Slob path parts: {parts}")
        
        if len(parts) < 4:
            print(f"[HTTP] 404: Invalid path parts length {len(parts)}")
            self._not_found()
            return

        source = unquote(parts[2])
        key = unquote("/".join(parts[3:]))

        print(f"[HTTP] Looking for: key='{key}', source='{source}'")

        entry = self.slob_client.get_entry(key, source)
        if not entry:
            print(f"[HTTP] 404: Entry not found")
            self._not_found()
            return

        content = entry["content"]
        content_type = entry["content_type"]
        
        # Detect content type from key extension or content
        if key.endswith('.css'):
            content_type = "text/css; charset=utf-8"
            if self.dark_mode:
                content_str = content.decode('utf-8') if isinstance(content, bytes) else content
                content = f"{content_str}\n{self.dark_mode_css}"
        elif key.endswith('.js'):
            content_type = "application/javascript; charset=utf-8"
        elif key.endswith('.png'):
            content_type = "image/png"
        elif key.endswith('.jpg') or key.endswith('.jpeg'):
            content_type = "image/jpeg"
        elif key.endswith('.svg'):
            content_type = "image/svg+xml; charset=utf-8"
        elif key.endswith('.woff'):
            content_type = "application/font-woff"
        elif key.endswith('.ttf'):
            content_type = "application/x-font-ttf"
        elif key.endswith('.otf'):
            content_type = "application/x-font-opentype"
        elif key.endswith('.ico'):
            content_type = "image/x-icon"

        content_bytes = content.encode('utf-8') if isinstance(content, str) else content

        print(f"[HTTP] 200: Serving {content_type} ({len(content_bytes)} bytes) for {key}")

        # Serve content with appropriate cache headers
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", len(content_bytes))
        
        self.send_header("Cache-Control", "public, max-age=3600")
        # self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        # self.send_header("Pragma", "no-cache")
        # self.send_header("Expires", "0")
        
        self.end_headers()
        self.wfile.write(content_bytes)

    def _handle_find(self, query):
        """Handle find request: /find?key=<key>&limit=<limit>"""
        key = query.get("key", [""])[0]
        limit_str = query.get("limit", ["100"])[0]

        print(f"[HTTP] Find: key='{key}', limit={limit_str}")

        if not key:
            print(f"[HTTP] 400: Missing key")
            self._error_response(400, "Missing key parameter")
            return

        try:
            limit = int(limit_str)
            if limit > 10000:
                print(f"[HTTP] 413: Limit too large")
                self._error_response(413, "Limit too large")
                return
            if limit <= 0:
                limit = 100
        except ValueError:
            limit = 100

        results = self.slob_client.search(key, limit=limit)
        
        print(f"[HTTP] Found {len(results)} results")

        # Format response like Aard 2
        items = []
        for result in results:
            item = {
                "url": f"/slob/{result['source']}/{quote(result['id'], safe='')}",
                "label": result["title"],
                "dictLabel": result["source"],
            }
            items.append(item)
            print(f"[HTTP]   - {result['title']} ({result['source']})")

        response = json.dumps({"items": items})
        response_bytes = response.encode('utf-8')
        
        print(f"[HTTP] 200: JSON response ({len(response_bytes)} bytes)")

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", len(response_bytes))
        self.end_headers()
        self.wfile.write(response_bytes)

    def _json_response(self, data):
        """Send JSON response."""
        response = json.dumps(data)
        response_bytes = response.encode('utf-8')
        
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", len(response_bytes))
        self.end_headers()
        self.wfile.write(response_bytes)

    def _not_found(self):
        """Send 404 response."""
        self._error_response(404, "Not found")

    def _error_response(self, code, message):
        """Send error response."""
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        message_bytes = message.encode('utf-8')
        self.send_header("Content-Length", len(message_bytes))
        self.end_headers()
        self.wfile.write(message_bytes)

    def log_message(self, format, *args):
        """Suppress logging."""
        pass


class HTTPServer_:
    """Wrapper for HTTP server thread."""

    def __init__(self, slob_client, port=0):
        """Initialize HTTP server."""
        self.slob_client = slob_client
        self.port = port
        self.server = None
        self.thread = None
        self.actual_port = None

    def start(self):
        """Start HTTP server in background thread."""
        DictionaryHTTPHandler.slob_client = self.slob_client

        from ..utils.utils import load_dark_mode_css
        DictionaryHTTPHandler.dark_mode_css = load_dark_mode_css()
        self.server = HTTPServer(("127.0.0.1", self.port), DictionaryHTTPHandler)
        # Get actual port if we used 0 (OS assigns)
        self.actual_port = self.server.server_address[1]

        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        print(f"✓ HTTP server started on http://127.0.0.1:{self.port}")

    def set_dark_mode(self, dark_mode):
        DictionaryHTTPHandler.dark_mode = dark_mode

    def get_port(self):
        """Get the actual port the server is running on."""
        return self.actual_port

    def stop(self):
        """Stop HTTP server."""
        if self.server:
            self.server.shutdown()
            print("✓ HTTP server stopped")
