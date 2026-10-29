"""Saved conversations: one history on the Mac, kept by librarian ask and by pi through the skill's librarian
history add, and read by both.

They live in history.sqlite beside the library (docs/design.md#saved-conversations). A full-text index over every
question and answer finds conversations by their words; triggers keep it current, whichever code saves a message.
"""
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone

from librarian.library import query_words

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY, title TEXT, created TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, conversation_id TEXT, role TEXT, content TEXT,
                                    passages TEXT, cited TEXT, created TEXT);
CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id, id);
CREATE VIRTUAL TABLE IF NOT EXISTS message_words USING fts5(content, content='messages', content_rowid='id',
                                                            tokenize='porter unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS messages_indexed AFTER INSERT ON messages BEGIN
  INSERT INTO message_words(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS messages_unindexed AFTER DELETE ON messages BEGIN
  INSERT INTO message_words(message_words, rowid, content) VALUES ('delete', old.id, old.content);
END;
"""
# Most recently updated first; within a second, the one with the newest message.
RECENT = "updated DESC, (SELECT MAX(m.id) FROM messages m WHERE m.conversation_id = conversations.id) DESC"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class History:
    def __init__(self, home):
        self.db = sqlite3.connect(os.path.join(home, "history.sqlite"), isolation_level=None, timeout=30)
        indexed = self.db.execute("SELECT 1 FROM sqlite_master WHERE name='message_words'").fetchone()
        self.db.executescript("PRAGMA journal_mode=WAL;" + SCHEMA)
        if not indexed:  # a history saved before it could be searched
            self.db.execute("INSERT INTO message_words(message_words) VALUES('rebuild')")

    def close(self):
        self.db.close()

    def conversations(self, limit=200):
        return [{"id": i, "title": t, "updated": u} for i, t, u in self.db.execute(
            f"SELECT id, title, updated FROM conversations ORDER BY {RECENT} LIMIT ?", (limit,))]

    def find(self, name):
        """The ids of the conversations name could mean: "last" for the most recent, or an id or its start. More
        than one means name is too short to tell them apart."""
        name = name.lower()
        if name == "last":
            return [i for (i,) in self.db.execute(f"SELECT id FROM conversations ORDER BY {RECENT} LIMIT 1")]
        if not name or name.strip("0123456789abcdef"):
            return []
        return [i for (i,) in self.db.execute("SELECT id FROM conversations WHERE id LIKE ? ORDER BY id LIMIT 2",
                                              (name + "%",))]

    def search(self, words, limit=200):
        """Conversations whose questions and answers, between them, hold every word, most recent first."""
        terms = ['"' + w.replace('"', "") + '"' for w in query_words(words)]
        found = None
        for term in terms:
            having = {c for (c,) in self.db.execute(
                "SELECT m.conversation_id FROM message_words JOIN messages m ON m.id = message_words.rowid "
                "WHERE message_words MATCH ?", (term,))}
            found = having if found is None else found & having
        if not found:
            return []
        return [{"id": i, "title": t, "updated": u} for i, t, u in self.db.execute(
            f"SELECT id, title, updated FROM conversations WHERE id IN ({','.join('?' * len(found))}) "
            f"ORDER BY {RECENT} LIMIT ?", [*found, limit])]

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
        """Save a question and its answer, in a new conversation when conversation_id is None; return its id."""
        now = _now()
        self.db.execute("BEGIN")
        if conversation_id is None:
            conversation_id = self.start(question)
        self.db.execute("INSERT INTO messages(conversation_id, role, content, created) VALUES(?,?,?,?)",
                        (conversation_id, "user", question, now))
        self.db.execute("INSERT INTO messages(conversation_id, role, content, passages, cited, created) "
                        "VALUES(?,?,?,?,?,?)", (conversation_id, "assistant", answer, json.dumps(passages),
                                                json.dumps(cited), now))
        self.db.execute("UPDATE conversations SET updated=? WHERE id=?", (now, conversation_id))
        self.db.execute("COMMIT")
        return conversation_id

    def delete(self, conversation_id):
        self.db.execute("BEGIN")
        self.db.execute("DELETE FROM messages WHERE conversation_id=?", (conversation_id,))
        self.db.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))
        self.db.execute("COMMIT")
