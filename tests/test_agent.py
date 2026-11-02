"""The launch agents' logs: each stays under a size limit and keeps one previous file."""
import offline  # noqa: F401  (tests never reach the internet)
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from librarian import agent

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class BoundedLogsTest(unittest.TestCase):
    """bound_logs on descriptors opened the way launchd opens a job's StandardOutPath and StandardErrorPath."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = tmp.name
        self.out, self.err = agent.log_paths(self.home)
        self.fds = [self.open(self.out), self.open(self.err)]

    def open(self, path):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        self.addCleanup(lambda: os.close(fd))
        return fd

    def read(self, path):
        with open(path, "rb") as f:
            return f.read()

    def bound(self, limit=10):
        agent.bound_logs(self.home, limit=limit, fds=self.fds)

    def test_the_logs_are_the_ones_launchd_writes(self):
        self.assertEqual((self.out, self.err), (os.path.join(self.home, "embed.log"),
                                                os.path.join(self.home, "embed-error.log")))
        self.assertEqual(agent.log_paths(self.home, agent.UPDATE),
                         (os.path.join(self.home, "update.log"), os.path.join(self.home, "update-error.log")))

    def test_a_full_log_moves_aside_and_the_job_writes_on_in_a_fresh_one(self):
        os.write(self.fds[0], b"progress line one\n")
        self.bound()
        os.write(self.fds[0], b"progress line two\n")
        self.assertEqual(self.read(os.path.join(self.home, "embed.previous.log")), b"progress line one\n")
        self.assertEqual(self.read(self.out), b"progress line two\n")

    def test_only_one_previous_file_is_kept(self):
        for line in (b"first full log\n", b"second full log\n", b"third\n"):  # the third stays under the limit
            os.write(self.fds[0], line)
            self.bound()
        self.assertEqual(self.read(os.path.join(self.home, "embed.previous.log")), b"second full log\n")
        self.assertEqual(self.read(self.out), b"third\n")
        self.assertEqual(sorted(os.listdir(self.home)), ["embed-error.log", "embed.log", "embed.previous.log"])

    def test_the_error_log_is_bounded_too(self):
        os.write(self.fds[1], b"Traceback (most recent call last):\n")
        self.bound()
        os.write(self.fds[1], b"embedding stopped\n")
        self.assertEqual(self.read(os.path.join(self.home, "embed-error.previous.log")),
                         b"Traceback (most recent call last):\n")
        self.assertEqual(self.read(self.err), b"embedding stopped\n")

    def test_a_log_under_the_limit_stays(self):
        os.write(self.fds[0], b"short\n")
        self.bound(limit=6)
        self.assertEqual(self.read(self.out), b"short\n")
        self.assertFalse(os.path.exists(os.path.join(self.home, "embed.previous.log")))

    def test_output_that_goes_elsewhere_is_left_alone(self):
        # Run by hand, the job writes to a terminal or a file of the user's choosing, not to the agent's logs.
        elsewhere = os.path.join(self.home, "mine.txt")
        self.fds[0] = self.open(elsewhere)
        os.write(self.fds[0], b"a long run, kept whole\n")
        with open(self.out, "wb") as f:
            f.write(b"an old agent log\n")
        self.bound()
        self.assertEqual(self.read(elsewhere), b"a long run, kept whole\n")
        self.assertEqual(self.read(self.out), b"an old agent log\n")
        self.assertFalse(os.path.exists(os.path.join(self.home, "embed.previous.log")))

    def test_threads_that_log_at_once_move_the_full_log_aside_once(self):
        # The monthly update's downloads log from several threads. Here one thread is moving the full log aside
        # when another logs: had the second moved it too, the fresh log would have replaced the full one.
        os.write(self.fds[0], b"a full log\n")
        replace, moving, second_done = os.replace, threading.Event(), threading.Event()

        def slow_replace(source, target):
            if not moving.is_set():
                moving.set()
                second_done.wait(timeout=0.2)
            replace(source, target)

        def second():
            moving.wait()
            self.bound()
            second_done.set()

        thread = threading.Thread(target=second, daemon=True)  # if bound_logs regresses, fail instead of hanging
        with mock.patch("os.replace", slow_replace):
            thread.start()
            self.bound()
            thread.join(timeout=10)
        os.write(self.fds[0], b"next line\n")
        self.assertEqual(self.read(os.path.join(self.home, "embed.previous.log")), b"a full log\n")
        self.assertEqual(self.read(self.out), b"next line\n")


class JobLogTest(unittest.TestCase):
    def test_a_long_running_job_keeps_its_logs_bounded_as_it_prints(self):
        with tempfile.TemporaryDirectory() as home:
            out, err = agent.log_paths(home)
            job = ("import sys\n"
                   "from librarian import agent\n"
                   f"log = agent.job_log({home!r}, agent.EMBED, limit=40)\n"
                   "for n in range(10):\n"
                   "    log(f'embedded batch {n}')\n"
                   "    print(f'warning {n}', file=sys.stderr)\n")
            with open(out, "ab") as stdout, open(err, "ab") as stderr:  # as launchd opens them
                subprocess.run([sys.executable, "-B", "-c", job], env={**os.environ, "PYTHONPATH": ROOT},
                               stdout=stdout, stderr=stderr, check=True, timeout=60)
            logs = {}
            for name in sorted(os.listdir(home)):
                with open(os.path.join(home, name)) as f:
                    logs[name] = f.read()
        # Each log moves aside at the first line logged after it passes 40 bytes; the oldest lines are gone.
        self.assertEqual(logs, {
            "embed.previous.log": "embedded batch 6\nembedded batch 7\nembedded batch 8\n",
            "embed.log": "embedded batch 9\n",
            "embed-error.previous.log": "warning 0\nwarning 1\nwarning 2\nwarning 3\nwarning 4\n",
            "embed-error.log": "warning 5\nwarning 6\nwarning 7\nwarning 8\nwarning 9\n",
        })


class EarlyFailureTest(unittest.TestCase):
    """A worker start that fails before the job's own code can bound its logs, which launchd repeats every minute
    under KeepAlive: the agent's launch command bounds them before the job starts."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = tmp.name

    def logs(self):
        found = {}
        for name in os.listdir(self.home):
            with open(os.path.join(self.home, name), "rb") as f:
                found[name] = f.read()
        return found

    def start_again_and_again(self, limit, starts, **env):
        """Start the worker as launchd does, its outputs appended to the logs it was installed with, and check after
        each start that every log holds at most limit bytes plus one start's output. Returns the logs at the end."""
        command = agent.launch_command(self.home, agent.EMBED, ["embed", "worker", "--model", "m"], limit=limit)
        out, err = agent.log_paths(self.home)
        env = {"PATH": os.pathsep.join(agent.SYSTEM_PATH), "HOME": self.home, "OFFLINE_LIBRARIAN_HOME": self.home,
               **env}
        one = None
        for start in range(starts):
            with open(out, "ab") as stdout, open(err, "ab") as stderr:
                result = subprocess.run(command, cwd=self.home, env=env, stdout=stdout, stderr=stderr, timeout=60)
            self.assertNotEqual(result.returncode, 0)
            logs = self.logs()
            one = one or len(logs["embed-error.log"])  # what the first start wrote, as every start does
            self.assertLessEqual(set(logs), {"embed.log", "embed-error.log", "embed.previous.log",
                                             "embed-error.previous.log"})
            for name, text in logs.items():
                self.assertLessEqual(len(text), limit + one, f"{name} after start {start + 1}")
        self.assertIn("embed-error.previous.log", logs)
        return logs

    def test_a_worker_without_its_python_keeps_its_logs_bounded(self):
        # With its .venv deleted, the launcher says so and stops before any Python runs.
        logs = self.start_again_and_again(limit=300, starts=10,
                                          OFFLINE_LIBRARIAN_PYTHON=os.path.join(self.home, "no-python"))
        self.assertEqual(logs["embed.log"], b"")
        self.assertIn(b"Offline Librarian isn't set up yet", logs["embed-error.log"])

    def test_a_worker_whose_imports_fail_keeps_its_logs_bounded(self):
        # The worker imports NumPy before it bounds its own logs, so a broken NumPy prints a traceback every start.
        with tempfile.TemporaryDirectory() as broken:
            os.mkdir(os.path.join(broken, "numpy"))
            with open(os.path.join(broken, "numpy", "__init__.py"), "w") as f:
                f.write("raise ImportError('this NumPy is broken')\n")
            logs = self.start_again_and_again(limit=3000, starts=8, OFFLINE_LIBRARIAN_PYTHON=sys.executable,
                                              PYTHONPATH=broken)
        self.assertEqual(logs["embed.log"], b"")
        self.assertIn(b"ImportError: this NumPy is broken", logs["embed-error.log"])


if __name__ == "__main__":
    unittest.main()
