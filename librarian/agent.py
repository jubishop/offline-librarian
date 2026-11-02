"""The launch agents that run Offline Librarian in the background: the embedding worker, which keeps the meaning
index current at the Background process type (like the user's Stories index), and the monthly update.

The worker starts at login and restarts after a crash; the update runs on a schedule. Install them from the permanent
checkout: an agent runs the code it was installed from. Each keeps its logs beside the library, bounded as it starts
(launch_command) and as the job logs (bound_logs): rotating them with newsyslog would need root.
"""
import os
import plistlib
import subprocess
import sys
import threading
import time

EMBED = "org.jubishop.offline-librarian.embed"
UPDATE = "org.jubishop.offline-librarian.update"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def plist_path(label=EMBED):
    return os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents", f"{label}.plist")


def _domain():
    return f"gui/{os.getuid()}"


SYSTEM_PATH = ["/usr/bin", "/bin", "/usr/sbin", "/sbin"]
LOG_LIMIT = 1_000_000  # bytes: a log past this moves aside, and one previous file is kept
LOGS = {EMBED: "embed", UPDATE: "update"}
_BOUNDING = threading.Lock()  # the update's downloads log from several threads, and only one may move a log aside


def log_paths(home, label=EMBED):
    """The agent's output and error logs, beside the library."""
    return os.path.join(home, f"{LOGS[label]}.log"), os.path.join(home, f"{LOGS[label]}-error.log")


def _previous(path):
    base, extension = os.path.splitext(path)
    return f"{base}.previous{extension}"


def bound_logs(home, label=EMBED, limit=LOG_LIMIT, fds=(1, 2)):
    """Keep the agent's logs to about limit bytes each, plus one previous file. launchd opens a job's logs when it
    starts the job, and nothing trims them, so the job does: when an output (fds, in log_paths' order) writes to
    its log and that log has passed limit, the log moves to its .previous name, replacing the one there, and the
    output carries on in a fresh file. Output that goes elsewhere, such as to a terminal, is left alone."""
    with _BOUNDING:
        sys.stdout.flush()
        sys.stderr.flush()
        for fd, path in zip(fds, log_paths(home, label)):
            try:
                status = os.fstat(fd)
                if status.st_size <= limit or not os.path.samestat(status, os.stat(path)):
                    continue
            except OSError:  # no such output, or no such log
                continue
            os.replace(path, _previous(path))
            fresh = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
            os.dup2(fresh, fd)
            os.close(fresh)


def job_log(home, label, limit=LOG_LIMIT):
    """A log(line) for the agent's job that bounds its logs before each line it prints, and bounds them now, so
    a job that stops early and restarts every minute, such as a worker with no library yet, stays bounded too."""
    def log(line):
        bound_logs(home, label, limit)
        print(line, flush=True)
    bound_logs(home, label, limit)
    return log


# Run by /bin/sh as launchd starts the job, with the limit, the two logs and then the job's command: bound_logs'
# rule, applied before the job runs.
_BOUND_AT_START = """\
limit=$1 out=$2 err=$3
shift 3
for log in "$out" "$err"; do
  if [ -n "$(find "$log" -size +"$limit"c 2>/dev/null)" ]; then mv -f "$log" "${log%.log}.previous.log"; fi
done
exec >>"$out" 2>>"$err"
exec "$@"
"""


def launch_command(home, label, arguments, limit=LOG_LIMIT):
    """The agent's ProgramArguments: bin/librarian with arguments, after a /bin/sh step that bounds its logs as
    bound_logs does, so output from a start that fails before the job can log, such as from a missing interpreter
    or a failed import, stays bounded too. Without it, launchd would append each such start's error, every minute
    for the worker, to a log that nothing trims until a start succeeds."""
    return ["/bin/sh", "-c", _BOUND_AT_START, label, str(limit), *log_paths(home, label),
            os.path.join(ROOT, "bin", "librarian"), *arguments]


def _install(label, arguments, home, calendar=None, path=SYSTEM_PATH):
    environment = {"OFFLINE_LIBRARIAN_HOME": home, "PATH": os.pathsep.join(dict.fromkeys(path)),
                   "HOME": os.path.expanduser("~")}
    if os.environ.get("OLLAMA_HOST"):
        environment["OLLAMA_HOST"] = os.environ["OLLAMA_HOST"]
    out, err = log_paths(home, label)
    agent = {
        "Label": label,
        "ProgramArguments": launch_command(home, label, arguments),
        "EnvironmentVariables": environment,
        "ProcessType": "Background",
        "WorkingDirectory": home,
        "StandardOutPath": out,
        "StandardErrorPath": err,
    }
    if calendar:  # a scheduled job: launchd runs it then, or on waking if the Mac was asleep
        agent["StartCalendarInterval"] = calendar
    else:  # a service: running from login on, and restarted when it stops
        agent.update(RunAtLoad=True, KeepAlive=True, ThrottleInterval=60)
    os.makedirs(os.path.dirname(plist_path(label)), exist_ok=True)
    with open(plist_path(label), "wb") as f:
        plistlib.dump(agent, f)
    _stop(label)  # an older copy, if any
    for attempt in range(5):
        result = subprocess.run(["launchctl", "bootstrap", _domain(), plist_path(label)], capture_output=True,
                                text=True)
        if result.returncode == 0:
            return plist_path(label)
        time.sleep(1)  # launchd can still be removing the old job
    raise RuntimeError(f"launchctl couldn't start {label} (exit {result.returncode}: "
                       f"{(result.stderr or result.stdout).strip()})")


def install(home, model):
    """Install (or reinstall) the embedding worker. Returns the plist's path."""
    return _install(EMBED, ["embed", "worker", "--model", model], home)


def install_update(home):
    """Schedule the monthly update: the 1st of each month at 3:00, at Background priority. Its build runs
    pdftotext from where this shell finds it, since launchd's PATH leaves out Homebrew."""
    from librarian import convert
    return _install(UPDATE, ["update", "run"], home, calendar={"Day": 1, "Hour": 3, "Minute": 0},
                    path=[os.path.dirname(convert.pdftotext()), *SYSTEM_PATH])


def _stop(label, timeout=15):
    """Stop an agent and wait until launchd has removed it: bootout returns before the job is gone, and starting a
    new copy before then fails with 5 (Input/output error)."""
    subprocess.run(["launchctl", "bootout", f"{_domain()}/{label}"], capture_output=True)
    deadline = time.monotonic() + timeout
    while running(label) and time.monotonic() < deadline:
        time.sleep(0.2)


def uninstall(label=EMBED):
    _stop(label)
    if os.path.exists(plist_path(label)):
        os.remove(plist_path(label))


def running(label=EMBED):
    """Whether launchd has the agent loaded."""
    return subprocess.run(["launchctl", "print", f"{_domain()}/{label}"], capture_output=True).returncode == 0
