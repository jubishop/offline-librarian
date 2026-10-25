"""The browser page's server: what it serves, who it answers, and the shared history."""
import http.client
import json
import os
import re
import socket
import time

from librarian import server
from test_meaning_search import LibraryFixture


class ServerTest(LibraryFixture):
    def setUp(self):
        super().setUp()
        self.chat = self.fake(answer="Get them somewhere warm [1].")
        self.notices = []
        self.start()

    def start(self):
        self.server = server.Server(self.home, port=0, bind="127.0.0.1", ollama_host=self.chat.host,
                                    chat_settings=("qwen-test", False), notify=lambda t, m: self.notices.append(t))
        self.server.start()
        self.addCleanup(self.server.stop)
        self.port = self.server.port

    def request(self, method, path, body=None, host=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        self.addCleanup(connection.close)
        sent = {"Host": host or f"127.0.0.1:{self.port}", **(headers or {})}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            sent.setdefault("Content-Type", "application/json")
        connection.request(method, path, body=data, headers=sent)
        response = connection.getresponse()
        return response.status, response.getheader("Content-Type") or "", response.read().decode()

    def get_json(self, path):
        status, _, body = self.request("GET", path)
        self.assertEqual(status, 200, body)
        return json.loads(body)

    def ask(self, question, conversation=None):
        payload = {"question": question, **({"conversation": conversation} if conversation else {})}
        status, kind, body = self.request("POST", "/api/ask", payload)
        self.assertEqual(status, 200, body)
        self.assertTrue(kind.startswith("text/event-stream"))
        return [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]

    def test_serves_the_page_with_nothing_from_the_internet(self):
        status, kind, page = self.request("GET", "/")
        self.assertEqual((status, kind.split(";")[0]), (200, "text/html"))
        self.assertIn("<title>Offline Librarian</title>", page)
        self.assertFalse(re.search(r"""(src|href)\s*=\s*["']?(https?:)?//|url\(\s*["']?(https?:)?//|@import""", page))

    def test_answers_only_requests_addressed_to_this_mac(self):
        self.assertEqual(self.request("GET", "/", host="evil.example")[0], 403)
        self.assertEqual(self.request("GET", "/api/status", host=f"evil.example:{self.port}")[0], 403)
        self.assertEqual(self.request("GET", "/", host=f"localhost:{self.port}")[0], 200)

    def test_knows_this_macs_names(self):
        names = server.allowed_hosts()
        self.assertTrue({"localhost", "127.0.0.1", socket.gethostname().lower()} <= names)

    def test_refuses_writes_from_other_sites(self):
        payload = {"question": "hypothermia"}
        self.assertEqual(self.request("POST", "/api/ask", payload, headers={"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.request("POST", "/api/ask", payload, headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.chat.chats, [])
        ok = self.request("POST", "/api/ask", payload, headers={"Origin": f"http://127.0.0.1:{self.port}"})
        self.assertEqual(ok[0], 200)

    def test_searches_without_the_ai(self):
        found = self.get_json("/api/search?q=shivering%20confused")
        self.assertEqual(found["passages"][0]["title"], "Hypothermia")
        self.assertEqual(self.chat.chats, [])

    def test_asks_streams_the_answer_and_saves_it(self):
        events = self.ask("someone is shivering and confused")
        kinds = [e["type"] for e in events]
        self.assertEqual((kinds[0], kinds[1], kinds[-1]), ("conversation", "passages", "done"))
        self.assertEqual(events[-1]["cited"], [1])
        conversation = events[0]["id"]
        listed = self.get_json("/api/conversations")
        self.assertEqual([(c["id"], c["title"]) for c in listed], [(conversation, "someone is shivering and confused")])
        saved = self.get_json(f"/api/conversations/{conversation}")
        self.assertEqual([m["role"] for m in saved["messages"]], ["user", "assistant"])
        self.assertEqual(saved["messages"][1]["content"], "Get them somewhere warm [1].")
        self.assertEqual(saved["messages"][1]["cited"], [1])
        self.assertEqual(saved["messages"][1]["passages"][0]["title"], "Hypothermia")

    def test_a_follow_up_continues_the_conversation(self):
        conversation = self.ask("someone is shivering and confused")[0]["id"]
        self.ask("what if it is a baby?", conversation=conversation)
        roles = [m["role"] for m in self.chat.chats[-1]["messages"]]
        self.assertEqual(roles, ["system", "user", "assistant", "user"])
        saved = self.get_json(f"/api/conversations/{conversation}")
        self.assertEqual(len(saved["messages"]), 4)
        self.assertEqual(len(self.get_json("/api/conversations")), 1)

    def test_history_is_shared_by_every_device(self):
        conversation = self.ask("someone is shivering and confused")[0]["id"]
        self.server.stop()
        self.start()  # a restart, or another device: the same history
        self.assertEqual(self.get_json("/api/conversations")[0]["id"], conversation)

    def test_reads_an_article(self):
        passage = self.get_json("/api/search?q=sauerkraut")["passages"][0]
        article = self.get_json(f"/api/article?passage={passage['id']}")
        self.assertEqual(article["title"], "Sauerkraut")
        self.assertIn("kahm yeast", article["text"])
        self.assertIn("CC BY-SA 4.0", article["license"])
        self.assertEqual(self.request("GET", "/api/article?passage=999999")[0], 404)

    def test_reports_status(self):
        status = self.get_json("/api/status")
        self.assertEqual(status["articles"], 3)
        self.assertEqual(status["model"], "qwen-test")

    def test_says_when_it_restarted_after_a_crash_at_most_hourly(self):
        self.assertEqual(self.notices, [])
        crashed = lambda: open(os.path.join(self.home, "server.running"), "w").close()  # noqa: E731
        self.server.stop()
        crashed()
        self.start()
        self.assertEqual(self.notices, ["Offline Librarian: the page server restarted after a crash"])
        self.server.stop()
        crashed()
        self.start()
        self.assertEqual(len(self.notices), 1)  # not again within the hour

    def test_a_clean_stop_is_not_a_crash(self):
        self.server.stop()
        self.start()
        self.assertEqual(self.notices, [])
        time.sleep(0)
