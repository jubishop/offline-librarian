"""A local stand-in for Ollama's /api/embed: deterministic vectors that put related words close together."""
import json
import math
import re
import threading
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIMENSIONS = 32
# Words that mean the same thing for these tests share a dimension, as a real embedding model would put them close.
CONCEPTS = {"cold": 0, "freezing": 0, "frozen": 0, "shivering": 0, "hypothermia": 0, "chilly": 0,
            "bread": 1, "sourdough": 1, "loaf": 1, "starter": 1, "baking": 1,
            "water": 2, "bleach": 2, "drinking": 2, "disinfect": 2}


def vector(text):
    """Count each word's dimension (a known concept, or a hash of the word), then normalize."""
    values = [0.0] * DIMENSIONS
    for word in re.findall(r"[a-z]+", text.lower()):
        if len(word) > 3:
            values[CONCEPTS.get(word, 3 + zlib.crc32(word.encode()) % (DIMENSIONS - 3))] += 1
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


class FakeOllama:
    def __init__(self, fail_after=None):
        self.requests, self.fail_after = [], fail_after
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append(body)
                if self.path != "/api/embed" or (fake.fail_after is not None and len(fake.requests) > fake.fail_after):
                    self.send_error(500, "model runner stopped")
                    return
                inputs = body["input"] if isinstance(body["input"], list) else [body["input"]]
                data = json.dumps({"model": body["model"], "embeddings": [vector(t) for t in inputs]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.host = f"127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, args=(0.05,), daemon=True).start()

    def inputs(self):
        return [text for body in self.requests for text in
                (body["input"] if isinstance(body["input"], list) else [body["input"]])]

    def close(self):
        self.server.shutdown()
        self.server.server_close()
