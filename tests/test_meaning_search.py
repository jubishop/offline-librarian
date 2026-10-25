"""Embedding every passage, then searching by meaning as well as by keyword."""
import os
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


class MeaningSearchTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = tmp.name
        self.ollama = FakeOllama()
        self.addCleanup(self.ollama.close)
        write_book(self.home, "wikem_en_all nopic", "wikem_en_all_nopic_2026-10.zim", [
            Page("Hypothermia", "Hypothermia", wiki_page("Hypothermia", [SHIVERING, REWARMING])),
            Page("Sourdough", "Sourdough", wiki_page("Sourdough", [STARTER])),
            Page("Sauerkraut", "Sauerkraut", wiki_page("Sauerkraut", [FERMENT])),
        ])
        build.build(self.home, workers=1, log=lambda line: None)

    def embedder(self):
        return meaning.Embedder(host=self.ollama.host, model="test-embedder")

    def embed(self, ollama=None):
        embedder = meaning.Embedder(host=(ollama or self.ollama).host, model="test-embedder")
        return meaning.embed_library(self.home, embedder, batch=2, log=lambda line: None)

    def library(self, embedder=None):
        library = Library(os.path.join(self.home, "library.sqlite"),
                          meaning=meaning.Meaning(self.home, embedder or self.embedder()))
        self.addCleanup(library.close)
        return library

    def test_finds_passages_that_share_no_words_with_the_question(self):
        self.embed()
        self.assertEqual(Library(os.path.join(self.home, "library.sqlite")).search("frozen and chilly"), [])
        hits = self.library().search("frozen and chilly")
        self.assertEqual(hits[0].title, "Hypothermia")

    def test_keyword_matches_still_count(self):
        self.embed()
        hits = self.library().search("sauerkraut brine")
        self.assertEqual(hits[0].title, "Sauerkraut")

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
        build.build(self.home, workers=1, log=lambda line: None)
        self.ollama.requests.clear()
        self.assertEqual(self.embed(), 1)
        self.assertEqual(len(self.ollama.inputs()), 1)

    def test_an_interrupted_run_picks_up_where_it_stopped(self):
        failing = FakeOllama(fail_after=1)
        self.addCleanup(failing.close)
        with self.assertRaises(meaning.MeaningUnavailable):
            self.embed(failing)
        self.assertEqual(self.embed(), 1)  # the first batch of two was kept
        hits = self.library().search("frozen and chilly")
        self.assertEqual(hits[0].title, "Hypothermia")

    def test_passages_of_a_rebuilt_book_are_found_once(self):
        self.embed()
        write_book(self.home, "wikem_en_all nopic", "wikem_en_all_nopic_2026-11.zim", [
            Page("Hypothermia", "Hypothermia", wiki_page("Hypothermia", [SHIVERING, REWARMING])),
        ])
        build.build(self.home, workers=1, log=lambda line: None)
        self.embed()
        hits = self.library().search("frozen and chilly")
        self.assertEqual([hit.title for hit in hits], ["Hypothermia"])

    def test_falls_back_to_keywords_when_ollama_is_unreachable(self):
        self.embed()
        gone = FakeOllama()
        gone.close()
        library = self.library(meaning.Embedder(host=gone.host, model="test-embedder"))
        hits = library.search("sauerkraut brine")
        self.assertEqual(hits[0].title, "Sauerkraut")
        self.assertIn("Ollama", library.meaning_problem)

    def test_refuses_to_mix_vectors_from_another_model(self):
        self.embed()
        with self.assertRaises(meaning.MeaningUnavailable) as caught:
            meaning.embed_library(self.home, meaning.Embedder(host=self.ollama.host, model="other-model"),
                                  log=lambda line: None)
        self.assertIn("test-embedder", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
