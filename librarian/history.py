"""The browser page's saved conversations: one history on the Mac, shared by every device that opens the page.

They live in history.sqlite beside the library. Anyone who can reach the page can read them; the user chose that
over keeping history in each browser (docs/design.md#the-browser-page).
"""
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY, title TEXT, created TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, conversation_id TEXT, role TEXT, content TEXT,
                                    passages TEXT, cited TEXT, created TEXT);
CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id, id);
"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class History:
    def __init__(self, home):
        self.db = sqlite3.connect(os.path.join(home, "history.sqlite"), isolation_level=None, timeout=30)
        self.db.executescript("PRAGMA journal_mode=WAL;" + SCHEMA)

    def close(self):
        self.db.close()

    def conversations(self, limit=200):
        return [{"id": i, "title": t, "updated": u} for i, t, u in self.db.execute(
            "SELECT id, title, updated FROM conversations ORDER BY updated DESC LIMIT ?", (limit,))]

    def conversation(self, conversation_id):
        row = self.db.execute("SELECT id, title, created, updated FROM conversations WHERE id=?",
                              (conversation_id,)).fetchone()
        if not row:
            return None
        messages = [{"role": r, "content": c, "passages": json.loads(p) if p else [],
                     "cited": json.loads(x) if x else [], "created": at} for r, c, p, x, at in self.db.execute(
            "SELECT role, content, passages, cited, created FROM messages WHERE conversation_id=? ORDER BY id",
            (conversation_id,))]
        return {"id": row[0], "title": row[1], "created": row[2], "updated": row[3], "messages": messages}

    def turns(self, conversation_id):
        """The conversation so far, as the answer engine takes it."""
        return [{"role": r, "content": c} for r, c in self.db.execute(
            "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY id", (conversation_id,))]

    def start(self, question):
        conversation_id = uuid.uuid4().hex
        now = _now()
        title = " ".join(question.split())
        self.db.execute("INSERT INTO conversations(id, title, created, updated) VALUES(?,?,?,?)",
                        (conversation_id, title[:117] + "…" if len(title) > 120 else title, now, now))
        return conversation_id

    def add_turn(self, conversation_id, question, answer, passages, cited):
        now = _now()
        self.db.execute("BEGIN")
        self.db.execute("INSERT INTO messages(conversation_id, role, content, created) VALUES(?,?,?,?)",
                        (conversation_id, "user", question, now))
        self.db.execute("INSERT INTO messages(conversation_id, role, content, passages, cited, created) "
                        "VALUES(?,?,?,?,?,?)", (conversation_id, "assistant", answer, json.dumps(passages),
                                                json.dumps(cited), now))
        self.db.execute("UPDATE conversations SET updated=? WHERE id=?", (now, conversation_id))
        self.db.execute("COMMIT")

    def exists(self, conversation_id):
        return self.db.execute("SELECT 1 FROM conversations WHERE id=?", (conversation_id,)).fetchone() is not None

    def drop_if_empty(self, conversation_id):
        """Forget a new conversation whose first answer never finished."""
        if not self.db.execute("SELECT 1 FROM messages WHERE conversation_id=?", (conversation_id,)).fetchone():
            self.db.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))
