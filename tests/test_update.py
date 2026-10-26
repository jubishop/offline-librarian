"""The monthly update: newer Kiwix editions downloaded, rebuilt, and the old files removed."""
import offline  # noqa: F401  (tests never reach the internet)
import json
import os
import tempfile
import unittest

from books import Page, wiki_page, write_book
from librarian import build, kiwix, update
from librarian.library import Library
from test_build_and_search import REWARMING, SHIVERING, STARTER
from test_kiwix_fetch import Site


def zim_bytes(pages):
    """A real ZIM file holding pages, as bytes to serve."""
    with tempfile.TemporaryDirectory() as scratch:
        write_book(scratch, "scratch", "book.zim", pages)
        with open(os.path.join(scratch, "zim", "book.zim"), "rb") as f:
            return f.read()


OLD = zim_bytes([Page("Hypothermia", "Hypothermia", wiki_page("Hypothermia", [SHIVERING]))])
NEW = zim_bytes([Page("Hypothermia", "Hypothermia", wiki_page("Hypothermia", [SHIVERING, REWARMING])),
                 Page("Sourdough", "Sourdough", wiki_page("Sourdough", [STARTER]))])


class UpdateTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = tmp.name
        self.site = Site()
        self.addCleanup(self.site.close)
        self.sent = []
        self.old_file, entry = self.site.book("wikem_en_all", "nopic", OLD, edition="2026-09")
        kiwix.fetch([("wikem_en_all", "nopic")], os.path.join(self.home, "zim"), catalog_url=self.site.catalog(entry),
                    log=lambda line: None)
        build.build(self.home, workers=1, log=lambda line: None)

    def run_update(self, catalog):
        return update.update(self.home, catalog_url=catalog, workers=1, log=lambda line: None,
                             notify=lambda title, message: self.sent.append((title, message)))

    def library(self):
        library = Library(os.path.join(self.home, "library.sqlite"))
        self.addCleanup(library.close)
        return library

    def test_fetches_a_newer_edition_rebuilds_it_and_removes_the_old_file(self):
        self.assertEqual(self.library().search("sourdough starter"), [])
        new_file, entry = self.site.book("wikem_en_all", "nopic", NEW, edition="2026-10")
        self.assertEqual(self.run_update(self.site.catalog(entry)), [])
        self.assertEqual(self.library().search("sourdough starter")[0].title, "Sourdough")
        self.assertEqual(sorted(os.listdir(os.path.join(self.home, "zim"))), ["manifest.json", new_file])
        with open(os.path.join(self.home, "zim", "manifest.json")) as f:
            self.assertEqual(json.load(f)["wikem_en_all nopic"]["file"], new_file)
        self.assertEqual(self.sent, [])

    def test_refreshes_only_the_books_already_downloaded(self):
        _, unrelated = self.site.book("ifixit_en_all", "", NEW)
        _, same = self.site.book("wikem_en_all", "nopic", OLD, edition="2026-09")
        self.assertEqual(self.run_update(self.site.catalog(same, unrelated)), [])
        with open(os.path.join(self.home, "zim", "manifest.json")) as f:
            self.assertNotIn("ifixit_en_all", json.load(f))

    def test_says_when_something_went_wrong_and_keeps_the_library(self):
        failures = self.run_update(self.site.catalog())  # the book has gone from the catalog
        self.assertEqual(len(failures), 1)
        self.assertEqual(len(self.sent), 1)
        title, message = self.sent[0]
        self.assertEqual(title, "Offline Librarian: the monthly update had problems")
        self.assertIn("wikem_en_all nopic: not in the Kiwix catalog", message)
        self.assertEqual(self.library().search("hypothermia shivering")[0].title, "Hypothermia")
        self.assertIn(self.old_file, os.listdir(os.path.join(self.home, "zim")))


if __name__ == "__main__":
    unittest.main()
