"""The launch agent that keeps the meaning index current in the background, like the user's Stories index.

It runs `librarian embed worker` with the Background process type, starts at login, and restarts after a crash.
Install it from the permanent checkout: the agent runs the code it was installed from.
"""
import os
import plistlib
import subprocess
import time

LABEL = "org.jubishop.offline-librarian.embed"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def plist_path():
    return os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents", f"{LABEL}.plist")


def _domain():
    return f"gui/{os.getuid()}"


def install(home, model):
    """Write the agent and (re)start it. Returns the plist's path."""
    environment = {"OFFLINE_LIBRARIAN_HOME": home, "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}
    if os.environ.get("OLLAMA_HOST"):
        environment["OLLAMA_HOST"] = os.environ["OLLAMA_HOST"]
    agent = {
        "Label": LABEL,
        "ProgramArguments": [os.path.join(ROOT, "bin", "librarian"), "embed", "worker", "--model", model],
        "EnvironmentVariables": environment,
        "ProcessType": "Background",
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 60,
        "WorkingDirectory": home,
        "StandardOutPath": os.path.join(home, "embed.log"),
        "StandardErrorPath": os.path.join(home, "embed-error.log"),
    }
    os.makedirs(os.path.dirname(plist_path()), exist_ok=True)
    with open(plist_path(), "wb") as f:
        plistlib.dump(agent, f)
    _stop()  # an older copy, if any
    for attempt in range(5):
        result = subprocess.run(["launchctl", "bootstrap", _domain(), plist_path()], capture_output=True, text=True)
        if result.returncode == 0:
            return plist_path()
        time.sleep(1)  # launchd can still be removing the old job
    raise RuntimeError(f"launchctl couldn't start the worker (exit {result.returncode}: "
                       f"{(result.stderr or result.stdout).strip()})")


def _stop(timeout=15):
    """Stop the agent and wait until launchd has removed it: bootout returns before the job is gone, and starting a
    new copy before then fails with 5 (Input/output error)."""
    subprocess.run(["launchctl", "bootout", f"{_domain()}/{LABEL}"], capture_output=True)
    deadline = time.monotonic() + timeout
    while running() and time.monotonic() < deadline:
        time.sleep(0.2)


def uninstall():
    _stop()
    if os.path.exists(plist_path()):
        os.remove(plist_path())


def running():
    """Whether launchd has the agent loaded."""
    return subprocess.run(["launchctl", "print", f"{_domain()}/{LABEL}"], capture_output=True).returncode == 0
