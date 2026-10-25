"""Embedding every passage, then searching by meaning as well as by keyword."""
import os
import sqlite3
import tempfile
import unittest

from books import Page, wiki_page, write_book
from fake_ollama import FakeOllama
from librarian import build, meaning
from librarian.library import Library
from test_build_and_search import REWARMING, SHIVERING, STARTER

FERMENT = ("Lactic acid bacteria ferment cabbage into sauerkraut in about three weeks. Pack shredded cabbage with two "
           "percent salt by weight, keep it under its own brine, and taste it every few days until it is sour enough. "
           "A white film on top is harmless kahm yeast; skim it off. Pink, slimy or fuzzy growth means the batch "
           "has spoiled and should be thrown away.")
HYPOTHERMIA = Page("Hypothermia", "Hypothermia", wiki_page("Hypothermia", [SHIVERING, REWARMING]))


class Clock:
    """Time that moves only when the code under test sleeps."""

    def __init__(self):
        self.now, self.sleeps = 0.0, []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class LibraryFixture(unittest.TestCase):
    """A small built library with three articles, and a fake Ollama."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = tmp.name
        self.ollama = self.fake()
        write_book(self.home, "wikem_en_all nopic", "wikem_en_all_nopic_2026-10.zim", [
            HYPOTHERMIA,
            Page("Sourdough", "Sourdough", wiki_page("Sourdough", [STARTER])),
            Page("Sauerkraut", "Sauerkraut", wiki_page("Sauerkraut", [FERMENT])),
        ])
        self.build()

    def fake(self, **options):
        fake = FakeOllama(**options)
        self.addCleanup(fake.close)
        return fake

    def build(self):
        build.build(self.home, workers=1, log=lambda line: None)

    def embedder(self, ollama=None, model="test-embedder"):
        return meaning.Embedder(host=(ollama or self.ollama).host, model=model)

    def embed(self, ollama=None, **options):
        lines = []
        options.setdefault("sleep", lambda seconds: None)
        count = meaning.embed_library(self.home, self.embedder(ollama), batch=2, log=lines.append, **options)
        self.lines = lines
        return count

    def library(self, embedder=None):
        found = meaning.Meaning(self.home, embedder or self.embedder())
        self.addCleanup(found.close)
        library = Library(os.path.join(self.home, "library.sqlite"), meaning=found)
        self.addCleanup(library.close)
        return library


class MeaningSearchTest(LibraryFixture):
    def test_finds_passages_that_share_no_words_with_the_question(self):
        self.embed()
        self.assertEqual(Library(os.path.join(self.home, "library.sqlite")).search("frozen and chilly"), [])
        self.assertEqual(self.library().search("frozen and chilly")[0].title, "Hypothermia")

    def test_keyword_matches_still_count(self):
        self.embed()
        self.assertEqual(self.library().search("sauerkraut brine")[0].title, "Sauerkraut")

    def test_embeds_documents_and_questions_with_their_prompts(self):
        self.embed()
        self.assertTrue(all(text.startswith("title: ") and " | text: " in text for text in self.ollama.inputs()))
        self.assertIn("title: Hypothermia | text: ", self.ollama.inputs()[0])
        self.ollama.requests.clear()
        self.library().search("frozen and chilly")
        self.assertEqual(self.ollama.inputs(), ["task: search result | query: frozen and chilly"])
        self.assertEqual({body["model"] for body in self.ollama.requests}, {"test-embedder"})

    def test_embedding_again_only_does_new_passages(self):
        self.assertEqual(self.embed(), 3)
        self.assertEqual(self.embed(), 0)
        write_book(self.home, "appropedia_en_all maxi", "appropedia_en_all_maxi_2026-02.zim",
                   [Page("Bread", "Bread", wiki_page("Bread", [STARTER]))])
        self.build()
        self.ollama.requests.clear()
        self.assertEqual(self.embed(), 1)
        self.assertEqual(len(self.ollama.inputs()), 1)

    def test_a_new_edition_reuses_the_vectors_of_unchanged_text(self):
        self.embed()
        write_book(self.home, "wikem_en_all nopic", "wikem_en_all_nopic_2026-11.zim", [
            HYPOTHERMIA, Page("Sourdough", "Sourdough", wiki_page("Sourdough", [STARTER + " Bake it hot."])),
        ])
        self.build()
        self.ollama.requests.clear()
        self.assertEqual(self.embed(), 1)  # only the edited Sourdough passage
        self.assertIn("Bake it hot.", self.ollama.inputs()[0])
        self.assertEqual(self.library().search("frozen and chilly")[0].title, "Hypothermia")
        self.assertNotIn("Sauerkraut", [hit.title for hit in self.library().search("cabbage brine")])

    def test_the_same_text_in_two_books_is_embedded_once(self):
        write_book(self.home, "wikipedia_en_medicine nopic", "wikipedia_en_medicine_nopic_2026-10.zim",
                   [HYPOTHERMIA])
        self.build()
        self.assertEqual(self.embed(), 3)

    def test_an_interrupted_run_picks_up_where_it_stopped(self):
        with self.assertRaises(meaning.MeaningUnavailable):
            self.embed(self.fake(fail_after=1))
        self.assertEqual(self.embed(), 1)  # the first batch of two was kept
        self.assertEqual(self.library().search("frozen and chilly")[0].title, "Hypothermia")

    def test_waits_while_another_model_is_loaded(self):
        busy = self.fake(loaded=[["qwen3.8:27b-mlx"], ["qwen3.8:27b-mlx", "test-embedder"], ["test-embedder"]])
        clock = Clock()
        self.assertEqual(self.embed(busy, yield_seconds=30, sleep=clock.sleep, clock=clock), 3)
        self.assertEqual(busy.calls[:3], ["ps", "ps", "ps"])  # nothing embedded until Qwen unloaded
        self.assertEqual(clock.sleeps[:2], [30, 30])
        self.assertIn("waiting while qwen3.8:27b-mlx is loaded", self.lines)

    def test_a_paused_run_stops_and_resumes_later(self):
        meaning.pause(self.home)
        self.assertEqual(self.embed(), 0)
        self.assertEqual(self.ollama.requests, [])
        self.assertTrue(meaning.status(self.home)["paused"])
        meaning.resume(self.home)
        self.assertEqual(self.embed(), 3)

    def test_the_worker_waits_out_an_ollama_outage_and_says_so_once(self):
        flaky, clock, sent = self.fake(failures=40), Clock(), []
        count = self.embed(flaky, worker=True, notify=lambda title, message: sent.append(title),
                           retry_seconds=30, sleep=clock.sleep, clock=clock)
        self.assertEqual(count, 3)
        self.assertEqual(sent, ["Offline Librarian: Ollama unavailable"])
        self.assertLessEqual(max(clock.sleeps), 300)

    def test_skips_a_passage_ollama_refuses(self):
        self.assertEqual(self.embed(self.fake(refuse=["sauerkraut"])), 2)
        self.assertIn("skipped a passage Ollama refused", " ".join(self.lines))

    def test_status_reports_progress(self):
        self.assertEqual(meaning.status(self.home)["state"], "not started")
        self.embed()
        report = meaning.status(self.home)
        self.assertEqual((report["state"], report["embedded"], report["pending"]), ("current", 3, 0))

    def test_a_library_built_before_text_keys_gets_them_on_the_next_build(self):
        db = sqlite3.connect(os.path.join(self.home, "library.sqlite"))
        db.execute("UPDATE passages SET hash = NULL")
        db.commit()
        db.close()
        self.build()
        self.assertEqual(self.embed(), 3)
        self.assertEqual(self.library().search("frozen and chilly")[0].title, "Hypothermia")

    def test_falls_back_to_keywords_when_ollama_is_unreachable(self):
        self.embed()
        gone = FakeOllama()
        gone.close()
        library = self.library(self.embedder(gone))
        self.assertEqual(library.search("sauerkraut brine")[0].title, "Sauerkraut")
        self.assertIn("Ollama", library.meaning_problem)

    def test_refuses_to_mix_vectors_from_another_model(self):
        self.embed()
        with self.assertRaises(meaning.MeaningUnavailable) as caught:
            meaning.embed_library(self.home, self.embedder(model="other-model"), log=lambda line: None)
        self.assertIn("test-embedder", str(caught.exception))



class WorkerTest(LibraryFixture):
    """The background worker's passes and notifications."""

    def run_worker(self, ollama=None, passes=1):
        sent, lines = [], []
        meaning.worker(self.home, self.embedder(ollama), notify=lambda title, message: sent.append(title),
                       log=lines.append, sleep=lambda seconds: None, passes=passes)
        return sent, lines

    def test_says_once_when_the_first_full_pass_is_done(self):
        sent, _ = self.run_worker(passes=2)
        self.assertEqual(sent, ["Offline Librarian: meaning index complete"])

    def test_says_once_when_a_pass_fails_and_carries_on(self):
        self.addCleanup(os.chmod, os.path.join(self.home, "library.sqlite"), 0o644)
        os.chmod(os.path.join(self.home, "library.sqlite"), 0)  # unreadable library: every pass fails
        sent, lines = self.run_worker(passes=3)
        self.assertEqual(sent, ["Offline Librarian: embedding stopped"])
        self.assertEqual(len([line for line in lines if line.startswith("embedding stopped")]), 3)

    def test_a_failed_notification_does_not_stop_the_work(self):
        def broken(title, message):
            raise OSError("no internet")
        lines = []
        meaning.worker(self.home, self.embedder(), notify=broken, log=lines.append, sleep=lambda s: None, passes=1)
        self.assertEqual(meaning.status(self.home)["state"], "current")
        self.assertIn("couldn't send a notification (no internet)", lines)


class PushoverTest(unittest.TestCase):
    def test_sends_with_the_keys_from_the_env_file(self):
        import threading
        import urllib.parse
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from librarian import notify
        received = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                received.append(urllib.parse.parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode()))
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as env:
            env.write("export PUSHOVER_USER_KEY='user-1'\nPUSHOVER_API_KEY=\"token-1\"\nOTHER=x\n")
        self.addCleanup(os.remove, env.name)
        notify.pushover(env.name, f"http://127.0.0.1:{server.server_address[1]}/")("Title", "Message")
        self.assertEqual(received, [{"token": ["token-1"], "user": ["user-1"], "title": ["Title"],
                                     "message": ["Message"]}])

    def test_says_when_the_keys_are_missing(self):
        from librarian import notify
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as env:
            env.write("OTHER=x\n")
        self.addCleanup(os.remove, env.name)
        with self.assertRaises(RuntimeError) as caught:
            notify.pushover(env.name, "http://127.0.0.1:9/")("Title", "Message")
        self.assertIn("Pushover keys are missing", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
