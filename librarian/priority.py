"""macOS's Background priority, for the long jobs: efficiency cores and throttled disk, so the Mac stays responsive."""
import os


def background():
    """Run this process, and the processes it starts, at Background priority (macOS only; elsewhere a no-op)."""
    if hasattr(os, "PRIO_DARWIN_PROCESS"):
        os.setpriority(os.PRIO_DARWIN_PROCESS, 0, os.PRIO_DARWIN_BG)
