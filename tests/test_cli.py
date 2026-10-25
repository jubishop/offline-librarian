"""The librarian command, run the way a person runs it."""
import os
import subprocess
import sys
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
