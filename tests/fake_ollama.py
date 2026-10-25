"""A local stand-in for Ollama: /api/embed with deterministic vectors that put related words close together, and
/api/ps with a scripted list of loaded models."""
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
    """fail_after: embed requests after this many fail with 500 (for good). failures: the next this many embed
    requests fail with 500, then they work again. loaded: lists of loaded model names, one per /api/ps call; the
    last one repeats."""

    def __init__(self, fail_after=None, failures=0, loaded=None, refuse=(), answer="", thinking=""):
        self.requests, self.calls, self.chats = [], [], []
        self.answer, self.thinking = answer, thinking  # what /api/chat streams back, a few characters at a time
        self.fail_after, self.failures, self.loaded, self.refuse = fail_after, failures, list(loaded or [[]]), refuse
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, code, payload):
                data = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                fake.calls.append("ps")
                if self.path != "/api/ps":
                    return self.reply(404, {"error": "not found"})
                names = fake.loaded.pop(0) if len(fake.loaded) > 1 else fake.loaded[0]
                self.reply(200, {"models": [{"name": name, "model": name} for name in names]})

            def chat(self, body):
                fake.chats.append(body)
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.end_headers()
                chunks = [("thinking", fake.thinking[i:i + 7]) for i in range(0, len(fake.thinking), 7)]
                chunks += [("content", fake.answer[i:i + 5]) for i in range(0, len(fake.answer), 5)]
                for field, text in chunks:
                    message = {"role": "assistant", "content": text if field == "content" else ""}
                    if field == "thinking":
                        message["thinking"] = text
                    self.wfile.write(json.dumps({"model": body["model"], "message": message, "done": False}).encode()
                                     + b"\n")
                self.wfile.write(json.dumps({"model": body["model"], "message": {"role": "assistant", "content": ""},
                                             "done": True, "done_reason": "stop"}).encode() + b"\n")

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path == "/api/chat":
                    return self.chat(body)
                fake.calls.append("embed")
                fake.requests.append(body)
                inputs = body["input"] if isinstance(body["input"], list) else [body["input"]]
                if fake.fail_after is not None and len(fake.requests) > fake.fail_after:
                    return self.reply(500, {"error": "model runner stopped"})
                if fake.failures:
                    fake.failures -= 1
                    return self.reply(500, {"error": "model runner stopped"})
                if any(word in text for text in inputs for word in fake.refuse):
                    return self.reply(400, {"error": "input is not valid"})
                self.reply(200, {"model": body["model"], "embeddings": [vector(t) for t in inputs]})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.host = f"127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, args=(0.05,), daemon=True).start()

    def inputs(self):
        return [text for body in self.requests for text in
                (body["input"] if isinstance(body["input"], list) else [body["input"]])]

    def close(self):
        self.server.shutdown()
        self.server.server_close()
