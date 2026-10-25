"""The librarian command, run the way a person runs it."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from books import Page, wiki_page, write_book
from test_build_and_search import REWARMING, SHIVERING
from test_kiwix_fetch import WATER, Site

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FetchCommandTest(unittest.TestCase):
    def setUp(self):
        self.site = Site()
        self.addCleanup(self.site.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = tmp.name

    def run_librarian(self, *args):
        env = {**os.environ, "OFFLINE_LIBRARIAN_HOME": self.home}
        return subprocess.run([sys.executable, "-B", "-m", "librarian", *args], cwd=ROOT, env=env,
                              capture_output=True, text=True, timeout=60)

    def test_fetch_puts_books_in_the_library_folder(self):
        filename, entry = self.site.book("zimgit-water_en", "", WATER)
        result = self.run_librarian("fetch", "--catalog", self.site.catalog(entry), "zimgit-water_en")
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(os.path.join(self.home, "zim", filename), "rb") as f:
            self.assertEqual(f.read(), WATER)
        self.assertIn("zimgit-water_en: done", result.stdout)

    def test_fetch_fails_when_a_book_is_missing(self):
        result = self.run_librarian("fetch", "--catalog", self.site.catalog(), "zimgit-water_en")
        self.assertEqual(result.returncode, 1)
        self.assertIn("zimgit-water_en: not in the Kiwix catalog", result.stderr)

    def test_fetch_rejects_a_book_that_is_not_a_source(self):
        result = self.run_librarian("fetch", "--catalog", self.site.catalog(), "not-a-book")
        self.assertEqual(result.returncode, 2)
        self.assertIn("not-a-book", result.stderr)


class LibraryCommandsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = tmp.name

    def run_librarian(self, *args):
        env = {**os.environ, "OFFLINE_LIBRARIAN_HOME": self.home}
        return subprocess.run([sys.executable, "-B", "-m", "librarian", *args], cwd=ROOT, env=env,
                              capture_output=True, text=True, timeout=120)

    def test_build_then_search_and_read(self):
        write_book(self.home, "wikem_en_all nopic", "wikem_en_all_nopic_2026-10.zim",
                   [Page("Hypothermia", "Hypothermia", wiki_page("Hypothermia", [SHIVERING, REWARMING]))])
        built = self.run_librarian("build", "--workers", "1")
        self.assertEqual(built.returncode, 0, built.stderr)
        self.assertIn("wikem: done, 1 articles", built.stdout)
        self.assertIn("Not downloaded yet:", built.stdout)

        found = self.run_librarian("search", "shivering", "and", "confused")
        self.assertEqual(found.returncode, 0, found.stderr)
        first = found.stdout.splitlines()[0]
        self.assertRegex(first, r"^\[\d+\] Hypothermia \(WikEM emergency medicine\)$")
        self.assertIn("https://wikem.org/wiki/Hypothermia", found.stdout)

        as_json = json.loads(self.run_librarian("search", "--json", "shivering").stdout)
        self.assertEqual(as_json[0]["title"], "Hypothermia")
        self.assertIn("Shivering stops", as_json[0]["text"])

        read = self.run_librarian("read", str(as_json[0]["id"]))
        self.assertEqual(read.returncode, 0, read.stderr)
        self.assertTrue(read.stdout.startswith("# Hypothermia\n"))
        self.assertIn("License: CC BY-SA 4.0", read.stdout)
        self.assertIn("Do not rub the arms and legs", read.stdout)

    def test_search_explains_when_there_is_no_library(self):
        found = self.run_librarian("search", "anything")
        self.assertEqual(found.returncode, 1)
        self.assertIn("librarian build", found.stderr)

    def test_read_rejects_an_unknown_passage(self):
        write_book(self.home, "wikem_en_all nopic", "wikem_en_all_nopic_2026-10.zim",
                   [Page("Hypothermia", "Hypothermia", wiki_page("Hypothermia", [SHIVERING, REWARMING]))])
        self.run_librarian("build", "--workers", "1")
        read = self.run_librarian("read", "999999")
        self.assertEqual(read.returncode, 1)
        self.assertIn("999999", read.stderr)


if __name__ == "__main__":
    unittest.main()
