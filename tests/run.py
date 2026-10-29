"""Runs the tests as `python -m unittest` does, but also fails a test that leaks something Python notices only while
garbage-collecting it, such as an unclosed database.

`-W error::ResourceWarning` makes most leaks fail, but a warning raised while an object is being finalized has no
caller to reach: Python prints "Exception ignored" and the run still passes. Here each test collects its garbage as it
ends, and anything Python ignored meanwhile becomes an error of that test."""
import gc
import sys
import unittest


class Result(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ignored = []
        sys.unraisablehook = self.ignore

    def ignore(self, unraisable):
        sys.__unraisablehook__(unraisable)  # still print it, as Python would
        # Keep the exception but not unraisable.object, which may be the object being finalized.
        self.ignored.append((unraisable.exc_type, unraisable.exc_value, unraisable.exc_traceback))

    def stopTest(self, test):
        gc.collect()
        for error in self.ignored:
            self.addError(test, error)
        self.ignored.clear()
        super().stopTest(test)


class Runner(unittest.TextTestRunner):
    resultclass = Result


if __name__ == "__main__":
    unittest.main(module=None, testRunner=Runner)
