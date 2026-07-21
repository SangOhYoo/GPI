import http.server
import threading
import json
import time
import urllib.request

class MockLlamaServer(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass # Suppress logging
    def do_POST(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        chunks = [
            b'data: {"choices": [{"delta": {"content": "[ENGLISH] "}}]}\n\n',
            b'data: {"choices": [{"delta": {"content": "Hello "}}]}\n\n',
            b'data: {"choices": [{"delta": {"content": "[KOREAN] "}}]}\n\n',
            b'data: {"choices": [{"delta": {"content": "\\uc548\\ub155 "}}]}\n\n',
            b'data: [DONE]\n\n'
        ]
        for c in chunks:
            self.wfile.write(c)
            self.wfile.flush()
            time.sleep(0.1)

server = http.server.HTTPServer(('127.0.0.1', 8081), MockLlamaServer)
t = threading.Thread(target=server.serve_forever)
t.daemon = True
t.start()

from gpi.core.api import call_llama_cpp_text_stream
try:
    res = call_llama_cpp_text_stream('test', '', 'test')
    print('RESULT:', res)
except Exception as e:
    import traceback
    traceback.print_exc()

server.shutdown()
