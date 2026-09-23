from http.server import BaseHTTPRequestHandler, HTTPServer
import json, os, time

PORT = 8081

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/data'):
            delay = float(os.getenv('EXTERNAL_DELAY', '0'))
            status = int(os.getenv('EXTERNAL_STATUS', '200'))
            if delay:
                time.sleep(min(delay, 30))
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'service': 'external-api', 'status': status}).encode())
        elif self.path == '/health':
            self.send_response(200); self.end_headers(); self.wfile.write(b'ok')
        else:
            self.send_response(404); self.end_headers()
    def log_message(self, fmt, *args):
        print(fmt % args)

HTTPServer(('0.0.0.0', PORT), Handler).serve_forever()
