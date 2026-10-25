"""The browser page's server: the page, AI-free search, answers streamed as server-sent events, articles, and the
shared history.

It listens on every network the Mac is on, with no password, as the user chose (docs/design.md#the-browser-page).
Two checks keep other web pages from using it through someone's browser: it answers only requests addressed to
this Mac's own names and addresses, which defeats DNS rebinding, and it takes writes only as JSON from its own
page, which a cross-site form or fetch can't send without the browser asking first.
"""
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from librarian import answer, history, meaning
from librarian.library import Library

PORT = 8740
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
NOTICE_EVERY = 3600  # seconds between crash notifications
_names = {"at": 0.0, "names": set()}


def _command(*args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def allowed_hosts():
    """This Mac's names and addresses, lowercased: what a request's Host may name. Refreshed every minute, since
    addresses change when the Mac moves between networks or Tailscale connects."""
    if time.monotonic() - _names["at"] < 60 and _names["names"]:
        return _names["names"]
    names = {"localhost", "127.0.0.1", "::1"}
    host = socket.gethostname().lower()
    names |= {host, host.removesuffix(".local"), host.removesuffix(".local") + ".local"}
    local = _command("scutil", "--get", "LocalHostName").strip().lower()
    if local:
        names |= {local, local + ".local"}
    names |= {m.lower().split("%")[0] for m in re.findall(r"\binet6?\s+([0-9a-fA-F:.%a-z0-9]+)", _command("ifconfig"))}
    tailscale = shutil.which("tailscale") or "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
    if os.path.exists(tailscale):
        try:
            me = json.loads(_command(tailscale, "status", "--json") or "{}").get("Self") or {}
            if me.get("DNSName"):
                full = me["DNSName"].rstrip(".").lower()
                names |= {full, full.split(".")[0]}
            names |= {ip.lower() for ip in me.get("TailscaleIPs") or []}
        except ValueError:
            pass
    _names.update(at=time.monotonic(), names=names)
    return names


def _host_name(value):
    """The name part of a Host header or origin: no port, no brackets, lowercased."""
    value = (value or "").strip().lower()
    if value.startswith("["):
        return value[1:value.find("]")] if "]" in value else value[1:]
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


class App:
    def __init__(self, home, ollama_host, chat_settings):
        self.home, self.ollama_host = home, ollama_host
        self.model, self.think = chat_settings or answer.pi_settings()
        self.lock = threading.Lock()

    def library(self):
        embedder = meaning.Embedder(host=self.ollama_host)
        return Library(os.path.join(self.home, "library.sqlite"), meaning=meaning.Meaning(self.home, embedder))

    def chat(self):
        return answer.Chat(host=self.ollama_host, model=self.model, think=self.think)


class Handler(BaseHTTPRequestHandler):
    server_version = "OfflineLibrarian"

    def log_message(self, *args):
        pass

    @property
    def app(self):
        return self.server.app

    def send(self, status, body, kind="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def addressed_here(self):
        if _host_name(self.headers.get("Host")) in allowed_hosts():
            return True
        self.send(403, {"error": "This server only answers requests addressed to its own names."})
        return False

    def do_GET(self):
        if not self.addressed_here():
            return
        url = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/":
            with open(os.path.join(STATIC, "index.html"), "rb") as f:
                return self.send(200, f.read(), "text/html; charset=utf-8")
        if not os.path.exists(os.path.join(self.app.home, "library.sqlite")):
            return self.send(503, {"error": "There is no library yet: run librarian fetch, then librarian build."})
        if url.path == "/api/status":
            return self.status()
        if url.path == "/api/search":
            return self.search(query.get("q", ""))
        if url.path == "/api/article":
            return self.article(query.get("passage", ""))
        if url.path == "/api/conversations":
            return self.with_history(lambda h: self.send(200, h.conversations()))
        found = re.fullmatch(r"/api/conversations/([0-9a-f]{32})", url.path)
        if found:
            return self.with_history(lambda h: self.send(*((200, c) if (c := h.conversation(found[1]))
                                                            else (404, {"error": "No such conversation."}))))
        self.send(404, {"error": "Not found."})

    def do_POST(self):
        if not self.addressed_here():
            return
        origin = self.headers.get("Origin")
        if origin and _host_name(urlparse(origin).netloc) not in allowed_hosts():
            return self.send(403, {"error": "Only this page can ask questions."})
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            return self.send(415, {"error": "Send JSON."})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self.send(400, {"error": "Send JSON."})
        if urlparse(self.path).path == "/api/ask":
            return self.ask(body)
        self.send(404, {"error": "Not found."})

    def with_history(self, use):
        store = history.History(self.app.home)
        try:
            return use(store)
        finally:
            store.close()

    def status(self):
        library = self.app.library()
        try:
            articles, passages, sources = library.stats()
        finally:
            library.meaning.close()
            library.close()
        embedding = meaning.status(self.app.home)
        self.send(200, {"articles": articles, "passages": passages, "sources": sources, "model": self.app.model,
                        "think": self.app.think, "embedded": embedding.get("embedded", 0),
                        "embedding": embedding.get("state"), "to_embed": embedding.get("pending")})

    def search(self, question):
        library = self.app.library()
        try:
            hits = library.search(question, limit=12) if question.strip() else []
            problem = library.meaning_problem
        finally:
            library.meaning.close()
            library.close()
        self.send(200, {"passages": [{"id": h.id, "title": h.title, "heading": h.heading, "source": h.source,
                                      "url": h.url, "text": h.text} for h in hits], "problem": problem})

    def article(self, passage):
        library = Library(os.path.join(self.app.home, "library.sqlite"))
        try:
            found = library.article(int(passage)) if passage.isdigit() else None
        finally:
            library.close()
        if not found:
            return self.send(404, {"error": "No such passage."})
        self.send(200, {"title": found.title, "source": found.source, "url": found.url, "license": found.license,
                        "text": found.text, "passages": found.passages, "passage": int(passage)})

    def event(self, payload):
        self.wfile.write(b"data: " + json.dumps(payload).encode() + b"\n\n")
        self.wfile.flush()

    def ask(self, body):
        question = str(body.get("question") or "").strip()
        if not question:
            return self.send(400, {"error": "Ask a question."})
        store = history.History(self.app.home)
        conversation = str(body.get("conversation") or "")
        new = not (re.fullmatch(r"[0-9a-f]{32}", conversation) and store.exists(conversation))
        if new:
            conversation = store.start(question)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        library = self.app.library()
        saved = False
        try:
            self.event({"type": "conversation", "id": conversation})
            passages = []
            for event in answer.ask(library, question, history=store.turns(conversation), chat=self.app.chat()):
                if event["type"] == "passages":
                    passages = event["passages"]
                elif event["type"] == "done":
                    store.add_turn(conversation, question, event["answer"], passages, event["cited"])
                    saved = True
                self.event(event)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the page went away; an unfinished answer isn't saved
        finally:
            if new and not saved:
                store.drop_if_empty(conversation)
            library.meaning.close()
            library.close()
            store.close()


class Server:
    """The server, started and stopped from code (librarian serve, or a test). A start after a run that never
    stopped cleanly means it crashed; that is reported through notify, at most once an hour."""

    def __init__(self, home, port=PORT, bind="0.0.0.0", ollama_host=None, chat_settings=None, notify=None,
                 log=lambda line: None):
        self.home, self.bind, self.notify, self.log = home, bind, notify, log
        self.requested_port = port
        self.app = App(home, ollama_host, chat_settings)
        self.marker = os.path.join(home, "server.running")
        self.httpd = None

    def _notice(self, title, message):
        stamp = os.path.join(self.home, "server-notified")
        try:
            if time.time() - os.path.getmtime(stamp) < NOTICE_EVERY:
                return
        except OSError:
            pass
        open(stamp, "w").close()
        if self.notify:
            try:
                self.notify(title, message)
            except Exception as exc:  # no internet, or no keys: keep serving
                self.log(f"couldn't send a notification ({exc})")

    def start(self):
        os.makedirs(self.home, exist_ok=True)
        if os.path.exists(self.marker):
            self._notice("Offline Librarian: the page server restarted after a crash",
                         f"It stopped without shutting down, and is running again. Logs: {self.home}/server-error.log")
        try:
            self.httpd = ThreadingHTTPServer((self.bind, self.requested_port), Handler)
        except OSError as exc:
            self._notice("Offline Librarian: the page server can't start",
                         f"It couldn't listen on port {self.requested_port}: {exc}")
            raise
        self.httpd.app = self.app
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        open(self.marker, "w").close()
        threading.Thread(target=self.httpd.serve_forever, args=(0.2,), daemon=True).start()

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
            if os.path.exists(self.marker):
                os.remove(self.marker)
