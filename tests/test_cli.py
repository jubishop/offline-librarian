"""The librarian command, run the way a person runs it."""
import offline  # noqa: F401  (tests never reach the internet)
import json
import os
import subprocess
import sys
import tempfile
import unittest

from books import Page, wiki_page, write_book
from fake_ollama import FakeOllama
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


class MeaningCommandsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = tmp.name
        self.ollama = FakeOllama()
        self.addCleanup(self.ollama.close)
        write_book(self.home, "wikem_en_all nopic", "wikem_en_all_nopic_2026-10.zim",
                   [Page("Hypothermia", "Hypothermia", wiki_page("Hypothermia", [SHIVERING, REWARMING]))])

    def run_librarian(self, *args, host=None):
        env = {**os.environ, "OFFLINE_LIBRARIAN_HOME": self.home, "OLLAMA_HOST": host or self.ollama.host}
        return subprocess.run([sys.executable, "-B", "-m", "librarian", *args], cwd=ROOT, env=env,
                              capture_output=True, text=True, timeout=120)

    def test_embed_then_search_by_meaning(self):
        self.run_librarian("build", "--workers", "1")
        embedded = self.run_librarian("embed", "--model", "test-embedder")
        self.assertEqual(embedded.returncode, 0, embedded.stderr)
        self.assertIn("Embedded 1 passages", embedded.stdout)
        found = self.run_librarian("search", "--model", "test-embedder", "frozen", "and", "chilly")
        self.assertEqual(found.returncode, 0, found.stderr)
        self.assertRegex(found.stdout.splitlines()[0], r"^\[\d+\] Hypothermia ")

    def test_search_says_when_it_could_only_use_keywords(self):
        self.run_librarian("build", "--workers", "1")
        self.run_librarian("embed", "--model", "test-embedder")
        gone = FakeOllama()
        gone.close()
        found = self.run_librarian("search", "--model", "test-embedder", "hypothermia", host=gone.host)
        self.assertEqual(found.returncode, 0, found.stderr)
        self.assertIn("Hypothermia", found.stdout)
        self.assertIn("Searched by keyword only", found.stderr)

    def test_embed_fails_clearly_without_ollama(self):
        self.run_librarian("build", "--workers", "1")
        gone = FakeOllama()
        gone.close()
        embedded = self.run_librarian("embed", "--model", "test-embedder", host=gone.host)
        self.assertEqual(embedded.returncode, 1)
        self.assertIn("couldn't reach Ollama", embedded.stderr)
        self.assertIn("librarian embed", embedded.stderr)


class BackgroundWorkerCommandsTest(unittest.TestCase):
    """embed install, uninstall, status, pause and resume, with a stand-in for launchctl."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home, self.user = os.path.join(tmp.name, "library"), os.path.join(tmp.name, "user")
        bin_dir = os.path.join(tmp.name, "bin")
        for folder in (self.home, self.user, bin_dir):
            os.makedirs(folder)
        self.calls = os.path.join(tmp.name, "launchctl-calls")
        # Like launchd, bootout returns before the job is gone: print still finds it twice more, and bootstrap
        # fails with 5 (Input/output error) until it has gone.
        with open(os.path.join(bin_dir, "launchctl"), "w") as f:
            f.write(f"""#!/bin/sh
echo "$*" >> '{self.calls}'
state='{tmp.name}'
case "$1" in
  bootstrap) test -e "$state/loaded" && exit 5; touch "$state/loaded" ;;
  bootout) test -e "$state/loaded" && echo 2 > "$state/going" ;;
  print)
    if test -e "$state/going"; then
      left=$(cat "$state/going")
      if test "$left" -le 0; then rm -f "$state/going" "$state/loaded"; else echo $((left - 1)) > "$state/going"; fi
    fi
    test -e "$state/loaded" ;;
esac
""")
        os.chmod(os.path.join(bin_dir, "launchctl"), 0o755)
        self.path = bin_dir + os.pathsep + os.environ["PATH"]

    def run_librarian(self, *args):
        env = {**os.environ, "OFFLINE_LIBRARIAN_HOME": self.home, "HOME": self.user, "PATH": self.path}
        return subprocess.run([sys.executable, "-B", "-m", "librarian", *args], cwd=ROOT, env=env,
                              capture_output=True, text=True, timeout=120)

    def launchctl_calls(self):
        with open(self.calls) as f:
            return [line.split()[0] for line in f]

    def test_install_writes_a_background_launch_agent_and_starts_it(self):
        import plistlib
        result = self.run_librarian("embed", "install")
        self.assertEqual(result.returncode, 0, result.stderr)
        path = os.path.join(self.user, "Library", "LaunchAgents", "org.jubishop.offline-librarian.embed.plist")
        with open(path, "rb") as f:
            agent = plistlib.load(f)
        self.assertEqual(agent["ProcessType"], "Background")
        self.assertTrue(agent["KeepAlive"] and agent["RunAtLoad"])
        # /bin/sh bounds the logs before the job starts, then runs bin/librarian (tested in test_agent).
        self.assertEqual(agent["ProgramArguments"][0], "/bin/sh")
        self.assertEqual(agent["ProgramArguments"][-5:], [os.path.join(ROOT, "bin", "librarian"), "embed", "worker",
                                                          "--model", "embeddinggemma-2:270m-bf16-text"])
        self.assertEqual(agent["EnvironmentVariables"]["OFFLINE_LIBRARIAN_HOME"], self.home)
        self.assertEqual((agent["StandardOutPath"], agent["StandardErrorPath"]),
                         (os.path.join(self.home, "embed.log"), os.path.join(self.home, "embed-error.log")))
        self.assertEqual(self.launchctl_calls(), ["bootout", "print", "bootstrap"])
        self.assertIn("background worker: running", self.run_librarian("embed", "status").stdout)

        again = self.run_librarian("embed", "install")  # over the running worker, as after an update
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn("background worker: running", self.run_librarian("embed", "status").stdout)

        removed = self.run_librarian("embed", "uninstall")
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assertFalse(os.path.exists(path))
        self.assertIn("background worker: not installed", self.run_librarian("embed", "status").stdout)

    def test_update_install_schedules_a_monthly_background_job(self):
        import plistlib
        result = self.run_librarian("update", "install")
        self.assertEqual(result.returncode, 0, result.stderr)
        path = os.path.join(self.user, "Library", "LaunchAgents", "org.jubishop.offline-librarian.update.plist")
        with open(path, "rb") as f:
            agent = plistlib.load(f)
        self.assertEqual(agent["ProcessType"], "Background")
        self.assertEqual(agent["StartCalendarInterval"], {"Day": 1, "Hour": 3, "Minute": 0})
        self.assertFalse(agent.get("KeepAlive") or agent.get("RunAtLoad"))
        self.assertEqual(agent["ProgramArguments"][0], "/bin/sh")
        self.assertEqual(agent["ProgramArguments"][-3:], [os.path.join(ROOT, "bin", "librarian"), "update", "run"])
        self.assertEqual((agent["StandardOutPath"], agent["StandardErrorPath"]),
                         (os.path.join(self.home, "update.log"), os.path.join(self.home, "update-error.log")))
        self.assertIn("monthly update: scheduled", self.run_librarian("update", "status").stdout)
        self.assertEqual(self.run_librarian("update", "uninstall").returncode, 0)
        self.assertFalse(os.path.exists(path))

    def test_update_install_gives_the_job_the_folder_that_holds_pdftotext(self):
        # launchd's PATH leaves out Homebrew, where pdftotext usually is.
        import plistlib
        tools = os.path.join(self.user, "tools")
        os.makedirs(tools)
        with open(os.path.join(tools, "pdftotext"), "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(os.path.join(tools, "pdftotext"), 0o755)
        self.path = os.pathsep.join([self.path.split(os.pathsep)[0], tools, *self.path.split(os.pathsep)[1:]])
        result = self.run_librarian("update", "install")
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(os.path.join(self.user, "Library", "LaunchAgents", "org.jubishop.offline-librarian.update.plist"),
                  "rb") as f:
            path = plistlib.load(f)["EnvironmentVariables"]["PATH"]
        self.assertEqual(path.split(os.pathsep), [tools, "/usr/bin", "/bin", "/usr/sbin", "/sbin"])

    def test_update_install_refuses_without_pdftotext(self):
        self.path = self.path.split(os.pathsep)[0]  # only the stand-in launchctl
        result = self.run_librarian("update", "install")
        self.assertEqual(result.returncode, 1)
        self.assertIn("pdftotext isn't installed", result.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.user, "Library", "LaunchAgents")))

    def run_as_agent(self, name, *args):
        """Run the job as launchd does: its output appended to the name.log and name-error.log it was installed
        with, each already past the size limit. Returns the four files' contents by name."""
        from librarian import agent
        full = b"an old line\n" * (agent.LOG_LIMIT // 12 + 1)
        logs = [os.path.join(self.home, f"{name}.log"), os.path.join(self.home, f"{name}-error.log")]
        for path in logs:
            with open(path, "wb") as f:
                f.write(full)
        env = {**os.environ, "OFFLINE_LIBRARIAN_HOME": self.home, "HOME": self.user, "PATH": self.path}
        with open(logs[0], "ab") as out, open(logs[1], "ab") as err:
            subprocess.run([sys.executable, "-B", "-m", "librarian", *args], cwd=ROOT, env=env, stdout=out,
                           stderr=err, timeout=120)
        found = {}
        for path in os.listdir(self.home):
            if path.endswith(".log"):
                with open(os.path.join(self.home, path), "rb") as f:
                    found[path] = f.read()
        self.assertEqual(sorted(found), sorted(
            f"{name}{kind}{suffix}" for kind in ("", "-error") for suffix in (".log", ".previous.log")))
        self.assertEqual(found[f"{name}.previous.log"], full)
        self.assertEqual(found[f"{name}-error.previous.log"], full)
        return found

    def test_the_worker_starts_fresh_logs_when_its_old_ones_are_full(self):
        # With no library yet, the worker says so and stops, and launchd starts it again a minute later.
        logs = self.run_as_agent("embed", "embed", "worker")
        self.assertEqual(logs["embed.log"], b"")
        self.assertIn(b"There is no library to embed yet", logs["embed-error.log"])
        self.assertNotIn(b"an old line", logs["embed-error.log"])

    def test_the_update_starts_fresh_logs_when_its_old_ones_are_full(self):
        site = Site()
        self.addCleanup(site.close)
        logs = self.run_as_agent("update", "update", "run", "--catalog", site.catalog())
        self.assertIn(b"couldn't send a notification", logs["update.log"])
        self.assertIn(b"the build failed", logs["update-error.log"])
        for log in ("update.log", "update-error.log"):
            self.assertNotIn(b"an old line", logs[log])

    def test_pause_and_resume_show_in_status(self):
        self.assertIn("state: not started", self.run_librarian("embed", "status").stdout)
        self.run_librarian("embed", "pause")
        self.assertIn("(paused)", self.run_librarian("embed", "status").stdout)
        self.run_librarian("embed", "resume")
        self.assertNotIn("(paused)", self.run_librarian("embed", "status").stdout)


if __name__ == "__main__":
    unittest.main()
