"""Saved conversations: librarian ask saves its answers, pi saves its own with librarian history add, and
librarian history lists, shows, searches and deletes them, all in one history.sqlite the browser page reads too."""
import offline  # noqa: F401  (tests never reach the internet)
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import urllib.request

from fake_ollama import FakeOllama
from librarian import history, server
from test_meaning_search import LibraryFixture

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WARM = "Get them somewhere warm [1]."
PI_ANSWER = """1. Move them out of the cold [Hypothermia, WikEM emergency medicine].
2. Warm the chest first, not the arms and legs.

**Sources**
- Hypothermia, WikEM emergency medicine, https://wikem.org/wiki/Hypothermia"""


class HistoryCommandsTest(LibraryFixture):
    def setUp(self):
        super().setUp()
        self.chat = self.fake(answer=WARM)
        user = tempfile.TemporaryDirectory()  # pi's settings aren't read from the real home
        self.addCleanup(user.cleanup)
        self.user = user.name

    def run_librarian(self, *args, answer=None, host=None):
        env = {**os.environ, "OFFLINE_LIBRARIAN_HOME": self.home, "OLLAMA_HOST": host or self.chat.host,
               "HOME": self.user}
        return subprocess.run([sys.executable, "-B", "-m", "librarian", *args], cwd=ROOT, env=env,
                              input=answer or "", capture_output=True, text=True, timeout=120)

    def ok(self, *args, **options):
        result = self.run_librarian(*args, **options)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def ask(self, *args):
        printed = self.ok("ask", "--model", "qwen-test", "--think", "off", *args)
        return re.search(r"^Conversation: ([0-9a-f]{8})$", printed, re.M)[1]

    def saved(self):
        store = history.History(self.home)
        self.addCleanup(store.close)
        return [store.conversation(c["id"]) for c in store.conversations()]

    def passage_id(self, question):
        return json.loads(self.ok("search", "--json", question))[0]["id"]

    def add(self, question, answer, *passages, conversation=None):
        options = ["--conversation", conversation] if conversation else []
        printed = self.ok("history", "add", *options, "--question", question, *map(str, passages),
                          answer=answer + "\n")  # as a heredoc sends it
        return re.fullmatch(r"Conversation: ([0-9a-f]{32})\n", printed)[1]

    def test_ask_saves_each_answer_with_its_passages(self):
        short = self.ask("someone", "is", "shivering", "and", "confused")
        (saved,) = self.saved()
        self.assertTrue(saved["id"].startswith(short))
        self.assertEqual(saved["title"], "someone is shivering and confused")
        question, answered = saved["messages"]
        self.assertEqual((question["role"], question["content"]), ("user", "someone is shivering and confused"))
        self.assertEqual((answered["role"], answered["content"], answered["cited"]), ("assistant", WARM, [1]))
        self.assertEqual(answered["passages"][0]["title"], "Hypothermia")

    def test_continue_follows_up_on_the_most_recent_conversation(self):
        self.ask("someone is shivering and confused")
        short = self.ask("--continue", "what if it is a baby?")
        (saved,) = self.saved()
        self.assertTrue(saved["id"].startswith(short))
        self.assertEqual([m["content"] for m in saved["messages"] if m["role"] == "user"],
                         ["someone is shivering and confused", "what if it is a baby?"])
        sent = self.chat.chats[-1]["messages"]
        self.assertEqual([m["role"] for m in sent], ["system", "user", "assistant", "user"])
        self.assertEqual((sent[1]["content"], sent[2]["content"]), ("someone is shivering and confused", WARM))

    def test_conversation_follows_up_on_the_one_named(self):
        first = self.ask("someone is shivering and confused")
        self.ask("how do I keep a sourdough starter alive")
        self.assertEqual(self.ask("--conversation", first, "what if it is a baby?"), first)
        self.assertEqual(self.chat.chats[-1]["messages"][1]["content"], "someone is shivering and confused")
        counts = {c["id"][:8]: len(c["messages"]) for c in self.saved()}
        self.assertEqual(counts[first], 4)
        self.assertEqual(sorted(counts.values()), [2, 4])

    def test_ask_refuses_a_conversation_that_does_not_exist(self):
        result = self.run_librarian("ask", "--model", "qwen-test", "--conversation", "ffffffff", "hypothermia")
        self.assertEqual(result.returncode, 1)
        self.assertIn("There is no conversation ffffffff", result.stderr)
        self.assertEqual(self.chat.chats, [])

    def test_an_answer_that_fails_is_not_saved(self):
        gone = FakeOllama()
        gone.close()
        result = self.run_librarian("ask", "--model", "qwen-test", "hypothermia", host=gone.host)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.saved(), [])

    def test_pi_saves_its_answer_with_the_real_sources_and_follow_ups_join_it(self):
        passage = self.passage_id("shivering confused")
        conversation = self.add("someone is shivering and confused", PI_ANSWER, passage)
        follow_up = self.add("what if it is a baby?", "The library doesn't cover this.", conversation=conversation)
        self.assertEqual(follow_up, conversation)
        shown = json.loads(self.ok("history", "show", "--json", conversation))
        self.assertEqual(shown["id"], conversation)
        first, second = shown["turns"]
        self.assertEqual((first["question"], first["answer"]), ("someone is shivering and confused", PI_ANSWER))
        self.assertEqual(first["sources"], [{"n": 1, "id": passage, "title": "Hypothermia", "heading": "Hypothermia",
                                             "source": "WikEM emergency medicine",
                                             "url": "https://wikem.org/wiki/Hypothermia"}])
        self.assertEqual((second["question"], second["sources"]), ("what if it is a baby?", []))

    def test_pi_cannot_cite_a_passage_the_library_does_not_have(self):
        result = self.run_librarian("history", "add", "--question", "hypothermia", "999999", answer=PI_ANSWER)
        self.assertEqual(result.returncode, 1)
        self.assertIn("999999", result.stderr)
        self.assertEqual(self.saved(), [])

    def test_saving_needs_an_answer_and_a_real_conversation(self):
        empty = self.run_librarian("history", "add", "--question", "hypothermia", answer="  \n")
        self.assertEqual(empty.returncode, 1)
        self.assertIn("answer", empty.stderr)
        missing = self.run_librarian("history", "add", "--conversation", "ffffffff", "--question", "hypothermia",
                                     answer=PI_ANSWER)
        self.assertEqual(missing.returncode, 1)
        self.assertIn("There is no conversation ffffffff", missing.stderr)
        self.assertEqual(self.saved(), [])

    def test_lists_shows_searches_and_deletes_conversations(self):
        self.assertEqual(json.loads(self.ok("history", "--json")), [])
        cold = self.add("someone is shivering and confused", PI_ANSWER, self.passage_id("shivering confused"))
        bread = self.add("how do I keep a sourdough starter alive", "Feed it flour and water daily.")

        listed = self.ok("history").splitlines()
        self.assertEqual(len(listed), 2)
        self.assertRegex(listed[0], rf"^{bread[:8]}  \d{{4}}-\d\d-\d\d \d\d:\d\d  how do I keep a sourdough starter "
                                    r"alive$")
        self.assertTrue(listed[1].startswith(cold[:8]))
        self.assertEqual([c["id"] for c in json.loads(self.ok("history", "--json"))], [bread, cold])

        shown = self.ok("history", "show", cold[:8])
        self.assertIn("Question: someone is shivering and confused\n\n" + PI_ANSWER, shown)
        self.assertIn("Sources:\n[1] Hypothermia, WikEM emergency medicine, https://wikem.org/wiki/Hypothermia",
                      shown)
        self.assertIn("Question: how do I keep a sourdough starter alive", self.ok("history", "show", "last"))

        self.assertEqual(self.ok("history", "search", "shivers").splitlines()[0][:8], cold[:8])  # stemmed
        self.assertEqual([c["id"] for c in json.loads(self.ok("history", "search", "--json", "flour", "daily"))],
                         [bread])
        self.assertEqual(json.loads(self.ok("history", "search", "--json", "flour", "chest")), [])  # every word

        deleted = self.ok("history", "delete", cold[:8])
        self.assertIn(cold[:8], deleted)
        self.assertEqual([c["id"] for c in json.loads(self.ok("history", "--json"))], [bread])
        self.assertEqual(json.loads(self.ok("history", "search", "--json", "shivers")), [])
        gone = self.run_librarian("history", "show", cold)
        self.assertEqual(gone.returncode, 1)
        self.assertIn("There is no conversation", gone.stderr)

    def test_the_browser_page_reads_what_the_commands_saved(self):
        passage = self.passage_id("shivering confused")
        conversation = self.add("someone is shivering and confused", PI_ANSWER, passage)
        self.ask("--conversation", conversation, "what if it is a baby?")
        page = server.Server(self.home, port=0, bind="127.0.0.1", ollama_host=self.chat.host,
                             chat_settings=("qwen-test", False))
        page.start()
        self.addCleanup(page.stop)
        with urllib.request.urlopen(f"http://127.0.0.1:{page.port}/api/conversations/{conversation}",
                                    timeout=30) as resp:
            saved = json.load(resp)
        roles = [m["role"] for m in saved["messages"]]
        self.assertEqual(roles, ["user", "assistant", "user", "assistant"])
        pi, asked = saved["messages"][1], saved["messages"][3]
        self.assertEqual((pi["cited"], pi["passages"][0]["n"], pi["passages"][0]["id"]), ([1], 1, passage))
        self.assertIn("Shivering stops", pi["passages"][0]["text"])
        self.assertEqual((asked["content"], asked["cited"]), (WARM, [1]))


class MigrationTest(unittest.TestCase):
    def test_finds_words_in_conversations_saved_before_search_existed(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = sqlite3.connect(os.path.join(tmp.name, "history.sqlite"))
        db.executescript("""
CREATE TABLE conversations(id TEXT PRIMARY KEY, title TEXT, created TEXT, updated TEXT);
CREATE TABLE messages(id INTEGER PRIMARY KEY, conversation_id TEXT, role TEXT, content TEXT, passages TEXT,
                      cited TEXT, created TEXT);
INSERT INTO conversations VALUES('0123456789abcdef0123456789abcdef', 'water', '2026-10-27T10:00:00+00:00',
                                 '2026-10-27T10:00:00+00:00');
INSERT INTO messages(conversation_id, role, content, passages, cited, created) VALUES
  ('0123456789abcdef0123456789abcdef', 'user', 'how much bleach per gallon', NULL, NULL, '2026-10-27T10:00:00+00:00'),
  ('0123456789abcdef0123456789abcdef', 'assistant', 'Eight drops of bleach [1].', '[]', '[]',
   '2026-10-27T10:00:00+00:00');
""")
        db.close()
        store = history.History(tmp.name)
        self.addCleanup(store.close)
        self.assertEqual([c["id"] for c in store.search("eight drops")], ["0123456789abcdef0123456789abcdef"])
        self.assertEqual(store.conversation("0123456789abcdef0123456789abcdef")["messages"][1]["content"],
                         "Eight drops of bleach [1].")
