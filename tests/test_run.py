"""The test runner: a leak that Python notices only while garbage-collecting fails the test that caused it."""
import offline  # noqa: F401  (tests never reach the internet)
import contextlib
import io
import sqlite3
import sys
import unittest
import warnings

import run


class RunTest(unittest.TestCase):
    def test_fails_a_test_that_leaves_a_database_open(self):
        class Leaky(unittest.TestCase):
            def test_leaks(self):
                sqlite3.connect(":memory:")

        self.addCleanup(setattr, sys, "unraisablehook", sys.unraisablehook)
        result = run.Result(io.StringIO(), descriptions=True, verbosity=0)
        with warnings.catch_warnings(), contextlib.redirect_stderr(io.StringIO()) as printed:
            warnings.simplefilter("error", ResourceWarning)
            Leaky("test_leaks").run(result)
        ((test, report),) = result.errors
        self.assertEqual(test.id().rsplit(".", 1)[-1], "test_leaks")
        self.assertIn("ResourceWarning: unclosed database", report)
        self.assertIn("unclosed database", printed.getvalue())  # still printed, as Python would

    def test_passes_a_test_that_closes_its_database(self):
        class Tidy(unittest.TestCase):
            def test_closes(self):
                sqlite3.connect(":memory:").close()

        self.addCleanup(setattr, sys, "unraisablehook", sys.unraisablehook)
        result = run.Result(io.StringIO(), descriptions=True, verbosity=0)
        with warnings.catch_warnings():
            warnings.simplefilter("error", ResourceWarning)
            Tidy("test_closes").run(result)
        self.assertTrue(result.wasSuccessful())


if __name__ == "__main__":
    unittest.main()
