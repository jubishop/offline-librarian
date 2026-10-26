"""Answering a question: search first, then a local model writes the answer from numbered passages."""
import offline  # noqa: F401  (tests never reach the internet)
import json
import os
import subprocess
import sys
import tempfile
import unittest

from fake_ollama import FakeOllama
from librarian import answer
from librarian.library import Library
from test_meaning_search import LibraryFixture

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class AnswerTest(LibraryFixture):
    def ask(self, question, history=(), answer_text="Get them somewhere warm [1].", thinking="", think=False):
        self.chat_server = self.fake(answer=answer_text, thinking=thinking)
        library = Library(os.path.join(self.home, "library.sqlite"))
        self.addCleanup(library.close)
        chat = answer.Chat(host=self.chat_server.host, model="qwen-test", think=think)
        return list(answer.ask(library, question, history=list(history), chat=chat))

    def request(self):
        (body,) = self.chat_server.chats
        return body

    def test_answers_from_numbered_passages_and_reports_what_it_cited(self):
        events = self.ask("someone is shivering and confused after the cold")
        self.assertEqual(events[0]["type"], "passages")
        self.assertEqual(events[0]["passages"][0]["n"], 1)
        self.assertEqual(events[0]["passages"][0]["title"], "Hypothermia")
        text = "".join(e["text"] for e in events if e["type"] == "text")
        self.assertEqual(text, "Get them somewhere warm [1].")
        self.assertEqual(events[-1], {"type": "done", "answer": text, "cited": [1]})
        question = self.request()["messages"][-1]["content"]
        self.assertIn("[1] Hypothermia (WikEM emergency medicine)", question)
        self.assertIn("Shivering stops as it gets worse", question)
        self.assertTrue(question.endswith("Question: someone is shivering and confused after the cold"))
        self.assertIn("The library doesn't cover this.", self.request()["messages"][0]["content"])

    def test_uses_the_model_and_thinking_it_was_given_and_keeps_thinking_out_of_the_answer(self):
        events = self.ask("hypothermia", thinking="The passage says to warm the core first.", think=True)
        body = self.request()
        self.assertEqual((body["model"], body["think"], body["stream"]), ("qwen-test", True, True))
        self.assertEqual([e["type"] for e in events].count("thinking"), 1)
        self.assertNotIn("core first", events[-1]["answer"])

    def test_a_follow_up_keeps_the_conversation_and_searches_with_it(self):
        history = [{"role": "user", "content": "someone is shivering and confused after the cold"},
                   {"role": "assistant", "content": "Get them somewhere warm [1]."}]
        events = self.ask("what if it is a baby?", history=history)
        self.assertEqual(events[0]["passages"][0]["title"], "Hypothermia")
        roles = [m["role"] for m in self.request()["messages"]]
        self.assertEqual(roles, ["system", "user", "assistant", "user"])
        self.assertEqual(self.request()["messages"][1]["content"], history[0]["content"])

    def test_tells_the_model_when_nothing_was_found(self):
        events = self.ask("zzyzx qwfp", answer_text="The library doesn't cover this.")
        self.assertEqual(events[0]["passages"], [])
        self.assertIn("No passages in the library matched", self.request()["messages"][-1]["content"])
        self.assertEqual(events[-1]["cited"], [])

    def test_only_counts_citations_of_passages_it_was_given(self):
        events = self.ask("hypothermia", answer_text="Warm them [1], [2] and [9].")
        self.assertEqual(events[-1]["cited"], [1])

    def test_reports_an_unreachable_model(self):
        gone = FakeOllama()
        gone.close()
        library = Library(os.path.join(self.home, "library.sqlite"))
        self.addCleanup(library.close)
        events = list(answer.ask(library, "hypothermia", chat=answer.Chat(host=gone.host, model="qwen-test")))
        self.assertEqual(events[-1]["type"], "error")
        self.assertIn("Ollama", events[-1]["message"])


class SettingsTest(unittest.TestCase):
    def settings(self, values):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(values, f)
        self.addCleanup(os.remove, f.name)
        return answer.pi_settings(f.name)

    def test_follows_pi_model_and_thinking(self):
        self.assertEqual(self.settings({"defaultProvider": "ollama", "defaultModel": "qwen3.8:27b-mlx",
                                        "defaultThinkingLevel": "medium"}), ("qwen3.8:27b-mlx", True))
        self.assertEqual(self.settings({"defaultProvider": "ollama", "defaultModel": "gemma4:26b-nvfp4",
                                        "defaultThinkingLevel": "off"}), ("gemma4:26b-nvfp4", False))

    def test_keeps_its_default_model_when_pi_uses_another_provider(self):
        self.assertEqual(self.settings({"defaultProvider": "anthropic", "defaultModel": "claude-x"}),
                         (answer.DEFAULT_MODEL, True))

    def test_has_defaults_without_pi(self):
        self.assertEqual(answer.pi_settings("/nonexistent/settings.json"), (answer.DEFAULT_MODEL, True))


class AskCommandTest(LibraryFixture):
    def test_prints_the_answer_and_its_sources(self):
        chat = self.fake(answer="Move them somewhere warm and call for help [1].")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        user = tmp.name
        os.makedirs(os.path.join(user, ".pi", "agent"))
        with open(os.path.join(user, ".pi", "agent", "settings.json"), "w") as f:
            json.dump({"defaultProvider": "ollama", "defaultModel": "qwen-test", "defaultThinkingLevel": "off"}, f)
        env = {**os.environ, "OFFLINE_LIBRARIAN_HOME": self.home, "OLLAMA_HOST": chat.host, "HOME": user}
        result = subprocess.run([sys.executable, "-B", "-m", "librarian", "ask", "shivering", "and", "confused"],
                                cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Move them somewhere warm and call for help [1].", result.stdout)
        self.assertIn("Sources:\n[1] Hypothermia, WikEM emergency medicine, https://wikem.org/wiki/Hypothermia",
                      result.stdout)
        self.assertEqual((chat.chats[0]["model"], chat.chats[0]["think"]), ("qwen-test", False))


if __name__ == "__main__":
    unittest.main()
