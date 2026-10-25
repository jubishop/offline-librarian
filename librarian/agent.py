"""The launch agents that run Offline Librarian in the background: the embedding worker, which keeps the meaning
index current at the Background process type (like the user's Stories index), and the browser page's server.

Each starts at login and restarts after a crash. Install them from the permanent checkout: an agent runs the code
it was installed from.
"""
import os
import plistlib
import subprocess
import time

EMBED = "org.jubishop.offline-librarian.embed"
SERVER = "org.jubishop.offline-librarian.server"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def plist_path(label=EMBED):
    return os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents", f"{label}.plist")


def _domain():
    return f"gui/{os.getuid()}"


def _install(label, arguments, home, process_type, log_name):
    environment = {"OFFLINE_LIBRARIAN_HOME": home, "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                   "HOME": os.path.expanduser("~")}
    if os.environ.get("OLLAMA_HOST"):
        environment["OLLAMA_HOST"] = os.environ["OLLAMA_HOST"]
    agent = {
        "Label": label,
        "ProgramArguments": [os.path.join(ROOT, "bin", "librarian"), *arguments],
        "EnvironmentVariables": environment,
        "ProcessType": process_type,
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 60 if process_type == "Background" else 30,
        "WorkingDirectory": home,
        "StandardOutPath": os.path.join(home, f"{log_name}.log"),
        "StandardErrorPath": os.path.join(home, f"{log_name}-error.log"),
    }
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
    return _install(EMBED, ["embed", "worker", "--model", model], home, "Background", "embed")


def install_server(home, port):
    """Install (or reinstall) the page server, listening on port on every network the Mac is on."""
    return _install(SERVER, ["serve", "--port", str(port)], home, "Standard", "server")


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
