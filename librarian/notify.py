"""Pushover notifications, with the user's keys read from ~/.env when sending, so they never appear in logs, launch
agent files or process arguments (the same approach as the user's Stories project)."""
import os
import re
import urllib.parse
import urllib.request

PUSHOVER_URL = "https://api.pushover.net/1/messages.json"


def _environment(path):
    values = {}
    with open(path) as f:
        for line in f:
            found = re.match(r"^\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$", line)
            if found:
                values[found[1]] = re.sub(r"^(['\"])(.*)\1$", r"\2", found[2])
    return values


def pushover(env_path=None, url=PUSHOVER_URL):
    """A notify(title, message) function that sends through Pushover. It raises when sending fails."""
    def send(title, message):
        values = _environment(env_path or os.path.join(os.path.expanduser("~"), ".env"))
        user, token = values.get("PUSHOVER_USER_KEY"), values.get("PUSHOVER_API_KEY") or values.get("PUSHOVER_API_TOKEN")
        if not user or not token:
            raise RuntimeError("Pushover keys are missing from the home .env file")
        body = urllib.parse.urlencode({"token": token, "user": user, "title": title[:250],
                                       "message": message[:1024]}).encode()
        with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=30) as resp:
            resp.read()
    return send
