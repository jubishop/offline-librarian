"""Answer a question from the library with a local model: search first, in code, then have the model answer from
the numbered passages it found and cite them.

The model and thinking level follow the user's pi settings, so answers here behave like answers in pi. A follow-up
question is searched together with the question before it, since "what if it's a baby?" means little alone.
"""
import json
import os
import re
import urllib.error
import urllib.request

DEFAULT_MODEL = "qwen3.8:27b-mlx"
PASSAGES = 8

SYSTEM = """You are the Offline Librarian. You answer from an offline library of medical, emergency, survival, \
repair and reference articles, for someone who may have no internet and no other help.

Each question comes with numbered passages the library found for it. Answer from them:
- Put what to do first, in short numbered steps when there are steps. If the passages say to call emergency \
services, say that first.
- Use only facts from the passages. Give doses, amounts, times and distances exactly as the passage states them. \
Never invent a number.
- After each fact, cite the passage it came from by number in brackets, like [2]. Never cite a passage that \
doesn't say it.
- If you add anything not in a passage, mark it (from memory) instead of a citation.
- On safety, follow the official and clinical sources (MedlinePlus, CDC, Ready.gov, FEMA, NHS, WikEM, WikiMed, \
the military and WHO manuals) over Q&A sites, wikiHow and general Wikipedia. Don't repeat exceptions that weaken a \
safety rule, such as "if you must" run an engine indoors.
- If official sources disagree, say so and give both.

If the passages don't answer the question, start with: "The library doesn't cover this." Then give your best \
general answer, labeled clearly as from memory, not from the library, and keep the safety advice conservative."""


class ChatUnavailable(Exception):
    pass


def ollama_host():
    return os.environ.get("OLLAMA_HOST") or "127.0.0.1:11434"


def pi_settings(path=None):
    """(model, think) from pi's settings: its default model when pi uses Ollama, and thinking unless it is off."""
    path = path or os.path.join(os.path.expanduser("~"), ".pi", "agent", "settings.json")
    try:
        with open(path) as f:
            settings = json.load(f)
    except (OSError, ValueError):
        settings = {}
    model = settings.get("defaultModel") if settings.get("defaultProvider") == "ollama" else None
    return model or DEFAULT_MODEL, settings.get("defaultThinkingLevel", "medium") not in ("off", "none")


class Chat:
    def __init__(self, host=None, model=DEFAULT_MODEL, think=True):
        host = host or ollama_host()
        self.url = (host if "://" in host else "http://" + host).rstrip("/") + "/api/chat"
        self.model, self.think = model, think

    def stream(self, messages):
        """Yield ("thinking" | "text", chunk) as the model writes."""
        body = json.dumps({"model": self.model, "messages": messages, "stream": True, "think": self.think}).encode()
        req = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=900) as resp:
                for line in resp:
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    if event.get("error"):
                        raise ChatUnavailable(f"Ollama reported a problem: {event['error']}")
                    message = event.get("message") or {}
                    if message.get("thinking"):
                        yield "thinking", message["thinking"]
                    if message.get("content"):
                        yield "text", message["content"]
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace").strip()
            exc.close()
            raise ChatUnavailable(f"Ollama couldn't answer with {self.model}: {detail or exc}") from None
        except (OSError, ValueError) as exc:
            raise ChatUnavailable(f"couldn't reach Ollama at {self.url} ({exc})") from None


def _passages_prompt(passages, question):
    if not passages:
        return f"No passages in the library matched this question.\n\nQuestion: {question}"
    parts = []
    for p in passages:
        section = f", section: {p['heading']}" if p["heading"] and p["heading"] != p["title"] else ""
        parts.append(f"[{p['n']}] {p['title']} ({p['source']}{section})\n{p['text']}")
    return "Library passages:\n\n" + "\n\n".join(parts) + f"\n\nQuestion: {question}"


def cited(text, count):
    """The passage numbers an answer cites, in order, among 1..count."""
    found = []
    for group in re.findall(r"\[(\d+(?:\s*,\s*\d+)*)\]", text):
        for n in (int(x) for x in group.split(",")):
            if 1 <= n <= count and n not in found:
                found.append(n)
    return found


def ask(library, question, history=(), chat=None, limit=PASSAGES):
    """Yield the answer as events: {"type": "passages", "passages": [...]}, then {"type": "thinking"} once if the
    model thinks first, {"type": "text", "text": chunk} as it writes, and {"type": "done", "answer", "cited"}, or
    {"type": "error", "message"} if the model can't answer. history is the conversation so far, as
    [{"role": "user" | "assistant", "content"}]."""
    chat = chat or Chat()
    earlier = [m["content"] for m in history if m["role"] == "user"][-1:]
    hits = library.search(" ".join(earlier + [question]), limit=limit)
    passages = [{"n": n, "id": h.id, "title": h.title, "heading": h.heading, "source": h.source, "url": h.url,
                 "text": h.text} for n, h in enumerate(hits, 1)]
    yield {"type": "passages", "passages": passages, "search_problem": library.meaning_problem}
    messages = [{"role": "system", "content": SYSTEM}]
    messages += [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({"role": "user", "content": _passages_prompt(passages, question)})
    text, thinking = [], False
    try:
        for kind, chunk in chat.stream(messages):
            if kind == "thinking":
                if not thinking:
                    thinking = True
                    yield {"type": "thinking"}
                continue
            text.append(chunk)
            yield {"type": "text", "text": chunk}
    except ChatUnavailable as exc:
        yield {"type": "error", "message": str(exc)}
        return
    full = "".join(text)
    yield {"type": "done", "answer": full, "cited": cited(full, len(passages))}
