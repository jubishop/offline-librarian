"""The launch agents that run Offline Librarian in the background: the embedding worker, which keeps the meaning
index current at the Background process type (like the user's Stories index), and the monthly update.

The worker starts at login and restarts after a crash; the update runs on a schedule. Install them from the permanent
checkout: an agent runs the code it was installed from.
"""
import os
import plistlib
import subprocess
import time

EMBED = "org.jubishop.offline-librarian.embed"
UPDATE = "org.jubishop.offline-librarian.update"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def plist_path(label=EMBED):
    return os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents", f"{label}.plist")


def _domain():
    return f"gui/{os.getuid()}"


def _install(label, arguments, home, log_name, calendar=None):
    environment = {"OFFLINE_LIBRARIAN_HOME": home, "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                   "HOME": os.path.expanduser("~")}
    if os.environ.get("OLLAMA_HOST"):
        environment["OLLAMA_HOST"] = os.environ["OLLAMA_HOST"]
    agent = {
        "Label": label,
        "ProgramArguments": [os.path.join(ROOT, "bin", "librarian"), *arguments],
        "EnvironmentVariables": environment,
        "ProcessType": "Background",
        "WorkingDirectory": home,
        "StandardOutPath": os.path.join(home, f"{log_name}.log"),
        "StandardErrorPath": os.path.join(home, f"{log_name}-error.log"),
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
    return _install(EMBED, ["embed", "worker", "--model", model], home, "embed")


def install_update(home):
    """Schedule the monthly update: the 1st of each month at 3:00, at Background priority."""
    return _install(UPDATE, ["update", "run"], home, "update", calendar={"Day": 1, "Hour": 3, "Minute": 0})


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
