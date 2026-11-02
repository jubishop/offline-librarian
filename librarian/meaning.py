"""Search by meaning: an EmbeddingGemma vector for every passage, made by Ollama.

Vectors are keyed by the hash of what was embedded (passages.input_hash), so a passage whose text appears again, in
another book or a new edition, reuses its vector. They live beside the library: vectors.f16 holds one float16 row
per vector, appended as they are made, and vectors.sqlite maps each hash to its row and keeps the model, the pause
switch, the status and which notifications were sent. A row counts only once it is recorded there, so an
interrupted run resumes cleanly.

Once a build has changed the library, an embedding run that has embedded everything drops the vectors no passage
uses any more, from replaced editions and rebuilt sources, and moves the last rows into the gaps, so the store stays
the size of the library. Searches read rows only while none are moving.

Embedding yields while Ollama has any other model loaded, so chat models keep the GPU, as the user's Stories index
does. The background worker (librarian embed worker) also waits out an unreachable Ollama; a run from the terminal
stops with an error instead.
"""
import fcntl
import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
import zlib
from contextlib import contextmanager
from datetime import datetime, timezone

import numpy as np

from librarian import passages

DEFAULT_MODEL = "embeddinggemma-2:270m-bf16-text"
QUERY_PROMPT = "task: search result | query: "   # EmbeddingGemma's retrieval prompt for questions
CHUNK = 10_000           # passages read from the library at a time, so no read transaction stays open for long
OUTAGE_NOTICE = 10 * 60  # seconds Ollama may be unreachable before the worker says so
COMPACT_BATCH = 50_000   # rows moved at a time while closing gaps; a search waits for one batch at most

STORE_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS vectors(hash BLOB PRIMARY KEY, row INTEGER UNIQUE) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS events(name TEXT PRIMARY KEY, at TEXT);
"""


class MeaningUnavailable(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status  # the HTTP status Ollama answered with, if it answered


class Busy(MeaningUnavailable):
    """Another embedding run holds the library."""


def ollama_host():
    return os.environ.get("OLLAMA_HOST") or "127.0.0.1:11434"


class Embedder:
    def __init__(self, host=None, model=DEFAULT_MODEL):
        host = host or ollama_host()
        self.base = (host if "://" in host else "http://" + host).rstrip("/")
        self.model = model

    def embed(self, texts):
        """Unit-length vectors for texts, one row each."""
        body = json.dumps({"model": self.model, "input": texts}).encode()
        req = urllib.request.Request(self.base + "/api/embed", data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                vectors = np.asarray(json.load(resp)["embeddings"], dtype=np.float32)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace").strip()
            exc.close()
            raise MeaningUnavailable(f"Ollama couldn't embed with {self.model}: {detail or exc}", exc.code) from None
        except (OSError, ValueError, KeyError) as exc:
            raise MeaningUnavailable(f"couldn't reach Ollama at {self.base} ({exc})") from None
        if len(vectors) != len(texts):
            raise MeaningUnavailable(f"Ollama returned {len(vectors)} vectors for {len(texts)} texts")
        return vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)

    def embed_query(self, question):
        return self.embed([QUERY_PROMPT + question])[0]

    def other_models(self):
        """Models other than this one that Ollama has loaded; none when it can't say."""
        try:
            with urllib.request.urlopen(self.base + "/api/ps", timeout=10) as resp:
                loaded = [m.get("name") or m.get("model") for m in json.load(resp).get("models", [])]
        except (OSError, ValueError, AttributeError):
            return []
        return [name for name in loaded if name and name != self.model]


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class VectorStore:
    """vectors.f16 and vectors.sqlite in home."""

    def __init__(self, home, write=False):
        self.vectors_path = os.path.join(home, "vectors.f16")
        self.lock_path = os.path.join(home, ".vectors.lock")
        db_path = os.path.join(home, "vectors.sqlite")
        if write:
            self.db = sqlite3.connect(db_path, isolation_level=None, timeout=30)
            self.db.executescript("PRAGMA journal_mode=WAL;" + STORE_SCHEMA)
        else:
            self.db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30, check_same_thread=False)

    def close(self):
        self.db.close()

    def get(self, key, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, json.dumps(value)))

    def rows(self):
        """How many rows are recorded (rows past them were written by a run that stopped before recording them)."""
        return self.db.execute("SELECT COALESCE(MAX(row) + 1, 0) FROM vectors").fetchone()[0]

    def known(self, hashes):
        found = set()
        hashes = list(hashes)
        for at in range(0, len(hashes), 500):
            part = hashes[at:at + 500]
            found.update(h for (h,) in self.db.execute(
                f"SELECT hash FROM vectors WHERE hash IN ({','.join('?' * len(part))})", part))
        return found

    def add(self, hashes, vectors, model):
        dim = self.get("dim")
        if dim is None:
            dim = int(vectors.shape[1])
            self.set("dim", dim)
            self.set("model", model)
        rows = self.rows()
        with open(self.vectors_path, "r+b" if os.path.exists(self.vectors_path) else "wb") as f:
            f.truncate(rows * dim * 2)  # drop rows a stopped run wrote but never recorded
            f.seek(rows * dim * 2)
            f.write(vectors.astype(np.float16).tobytes())
            f.flush()
            os.fsync(f.fileno())
        self.db.execute("BEGIN")
        self.db.executemany("INSERT INTO vectors(hash, row) VALUES(?, ?)",
                            [(h, rows + n) for n, h in enumerate(hashes)])
        self.db.execute("COMMIT")

    @contextmanager
    def _locked(self, operation):
        with open(self.lock_path, "a") as lock:
            fcntl.flock(lock, operation)  # released when the file closes
            yield

    def reading(self):
        """Hold while reading rows; searches share it, and no rows move until they are done."""
        return self._locked(fcntl.LOCK_SH)

    def moving(self):
        """Hold while moving rows or cutting the file, once no search is reading them."""
        return self._locked(fcntl.LOCK_EX)

    def drop(self, rows):
        """Forget the vectors in these rows, leaving gaps for compact to close."""
        with self.moving():
            self.db.execute("BEGIN")
            self.db.executemany("DELETE FROM vectors WHERE row = ?", ((row,) for row in rows))
            self.db.execute("COMMIT")

    def compact(self):
        """Close the gaps dropped vectors left by moving the last rows into them, then cut the file to the rows in
        use. Rows move a batch at a time, so searches wait only briefly. Each batch is written before it is recorded,
        so an interrupted compaction leaves every vector where its hash says, and the next one finishes the job."""
        count, rows = self.db.execute("SELECT COUNT(*), COALESCE(MAX(row) + 1, 0) FROM vectors").fetchone()
        dim = self.get("dim")
        if count < rows:  # then each row from count on has a gap below count to go to
            gaps = np.concatenate([np.arange(first, end) for first, end in self.db.execute(
                "SELECT prev + 1, MIN(row, ?) FROM (SELECT row, LAG(row, 1, -1) OVER (ORDER BY row) AS prev "
                "FROM vectors) WHERE row > prev + 1 AND prev + 1 < ?", (count, count))])
            last = [row for (row,) in self.db.execute("SELECT row FROM vectors WHERE row >= ? ORDER BY row", (count,))]
            for at in range(0, len(last), COMPACT_BATCH):
                old, new = last[at:at + COMPACT_BATCH], gaps[at:at + COMPACT_BATCH].tolist()
                with self.moving():
                    vectors = np.memmap(self.vectors_path, dtype=np.float16, mode="r+", shape=(rows, dim))
                    vectors[new] = vectors[old]
                    vectors.flush()
                    del vectors
                    self.db.execute("BEGIN")
                    self.db.executemany("UPDATE vectors SET row = ? WHERE row = ?", zip(new, old))
                    self.db.execute("COMMIT")
        if dim and os.path.exists(self.vectors_path) and os.path.getsize(self.vectors_path) > count * dim * 2:
            with self.moving(), open(self.vectors_path, "r+b") as f:
                f.truncate(count * dim * 2)
                os.fsync(f.fileno())

    def notify_once(self, notify, name, title, message):
        if notify and not self.db.execute("SELECT 1 FROM events WHERE name=?", (name,)).fetchone():
            notify(title, message)
            self.db.execute("INSERT INTO events(name, at) VALUES(?, ?)", (name, _now()))

    def forget(self, name):
        self.db.execute("DELETE FROM events WHERE name=?", (name,))


def pause(home):
    store = VectorStore(home, write=True)
    store.set("paused", True)
    store.close()


def resume(home):
    store = VectorStore(home, write=True)
    store.set("paused", False)
    store.close()


def status(home):
    """What embedding is doing: {"state", "embedded", "pending", "rate", "hours_left", "updated", ...}."""
    if not os.path.exists(os.path.join(home, "vectors.sqlite")):
        return {"state": "not started", "embedded": 0}
    store = VectorStore(home)
    try:
        report = {"state": "not started", **store.get("status", {})}
        report.update(embedded=store.rows(), paused=bool(store.get("paused", False)), model=store.get("model"))
        return report
    finally:
        store.close()


@contextmanager
def _library_and_vectors(home):
    """A read-only connection to the library, with the vector store attached as v."""
    db = sqlite3.connect(f"file:{os.path.join(home, 'library.sqlite')}?mode=ro", uri=True)
    try:
        db.execute("ATTACH DATABASE ? AS v", (f"file:{os.path.join(home, 'vectors.sqlite')}?mode=ro",))
        yield db
    finally:
        db.close()


def _pending(home, store):
    """How many distinct passage inputs have no vector yet."""
    with _library_and_vectors(home) as db:
        return db.execute("SELECT COUNT(DISTINCT p.hash) FROM passages p "
                          "WHERE NOT EXISTS (SELECT 1 FROM v.vectors WHERE v.vectors.hash = p.hash)").fetchone()[0]


def _unused(db):
    """The rows of the vectors that no passage in the library uses, given a connection from _library_and_vectors."""
    return [row for (row,) in db.execute(
        "SELECT row FROM v.vectors WHERE NOT EXISTS (SELECT 1 FROM passages p WHERE p.hash = v.vectors.hash)")]


def _last_build(library):
    """The id of the last build that changed the library and finished: "" until a new library's first build has
    finished, and None for a library built before builds were recorded. Each build has its own id, so a library
    rebuilt from scratch can't repeat one that was checked."""
    try:  # main.meta, since the vector store attached as v has a meta table too
        row = library.execute("SELECT value FROM main.meta WHERE key = 'build'").fetchone()
    except sqlite3.OperationalError:  # no meta table: built before builds were recorded
        return None
    return row[0] if row else ""


def _source_ranges(library):
    """(first, last) passage id of each built source, in the order to embed them: official and clinical sources
    first, so meaning search helps with them soonest, then the rest; smallest first within each, so Wikipedia comes
    last. Each source is built in one transaction, so its articles and their passages have contiguous ids."""
    ranges = []
    for source_id, in library.execute("SELECT id FROM sources WHERE done = 1 ORDER BY weight >= 1.3 DESC, articles, id"):
        low, high = library.execute("SELECT MIN(id), MAX(id) FROM articles WHERE source_id = ?", (source_id,)).fetchone()
        if low is None:
            continue
        first = library.execute("SELECT MIN(id) FROM passages WHERE article_id = ?", (low,)).fetchone()[0]
        last = library.execute("SELECT MAX(id) FROM passages WHERE article_id = ?", (high,)).fetchone()[0]
        if first is not None and last is not None:
            ranges.append((first, last))
    return ranges


class _Run:
    """One pass over the library, embedding every passage input without a vector."""

    def __init__(self, home, store, embedder, batch, log, worker, notify, yield_seconds, retry_seconds, sleep,
                 clock):
        self.home, self.store, self.embedder, self.batch, self.log = home, store, embedder, batch, log
        self.worker, self.notify, self.yield_seconds, self.retry_seconds = worker, notify, yield_seconds, retry_seconds
        self.sleep, self.clock = sleep, clock
        self.done, self.started, self.reported, self.pending = 0, clock(), clock(), 0

    def report(self, state, **extra):
        elapsed = max(self.clock() - self.started, 1e-9)
        rate = self.done / elapsed
        self.store.set("status", {"state": state, "pending": self.pending, "rate": round(rate, 1),
                                  "hours_left": round(self.pending / rate / 3600, 1) if rate else None,
                                  "updated": _now(), **extra})

    def gate(self):
        """Wait while paused (or stop, outside the worker) or while another model is loaded. False to stop."""
        waiting_for = None
        while True:
            if self.store.get("paused", False):
                if not self.worker:
                    self.log("Embedding is paused; run librarian embed resume to carry on.")
                    return False
                self.report("paused")
                self.sleep(self.yield_seconds)
                continue
            others = self.embedder.other_models()
            if not others:
                return True
            if others != waiting_for:
                self.log(f"waiting while {', '.join(others)} {'is' if len(others) == 1 else 'are'} loaded")
                waiting_for = others
            self.report("yielding", yielding_to=others)
            self.sleep(self.yield_seconds)

    def vectors(self, texts):
        """Vectors for texts, retrying an unreachable Ollama in the worker; None for a text Ollama refuses."""
        outage, wait = None, self.retry_seconds
        while True:
            try:
                vectors = self.embedder.embed(texts)
                if outage is not None:
                    self.store.forget("ollama-unavailable")
                return list(vectors)
            except MeaningUnavailable as exc:
                if exc.status == 400:  # Ollama refused the input itself: try each text alone, keep what works
                    if len(texts) == 1:
                        self.log(f"skipped a passage Ollama refused: {exc}")
                        return [None]
                    return [v for text in texts for v in self.vectors([text])]
                if not self.worker:
                    raise
                outage = outage if outage is not None else self.clock()
                self.report("waiting for Ollama", last_error=str(exc))
                if self.clock() - outage >= OUTAGE_NOTICE:
                    self.store.notify_once(self.notify, "ollama-unavailable", "Offline Librarian: Ollama unavailable",
                                           f"Embedding has waited more than 10 minutes: {exc}")
                self.sleep(wait)
                wait = min(wait * 2, 300)

    def run(self):
        model = self.store.get("model")
        if model and model != self.embedder.model:
            raise MeaningUnavailable(f"the saved vectors were made with {model}; embed with that model, or delete "
                                     f"vectors.f16 and vectors.sqlite in {self.home} to start over")
        library = sqlite3.connect(f"file:{os.path.join(self.home, 'library.sqlite')}?mode=ro", uri=True)
        try:
            if library.execute("SELECT 1 FROM passages WHERE hash IS NULL LIMIT 1").fetchone():
                raise MeaningUnavailable("the library was built before vectors were keyed by text; run "
                                         "librarian build to update it, then embed again")
            self.pending = _pending(self.home, self.store)
            planned, finished = set(_source_ranges(library)), set()
            # Plan again after each source, so a book built or rebuilt during this pass (which can take days) is
            # embedded in its turn instead of in the next pass.
            while ranges := [r for r in _source_ranges(library) if r not in finished]:
                if not set(ranges) <= planned:
                    planned |= set(ranges)
                    self.pending = _pending(self.home, self.store)
                first, last_id = ranges[0]
                finished.add((first, last_id))
                last = first - 1
                while rows := library.execute(
                        "SELECT p.id, p.article_id, p.start, p.end, a.title, p.hash FROM passages p "
                        "JOIN articles a ON a.id = p.article_id WHERE p.id > ? AND p.id <= ? ORDER BY p.id LIMIT ?",
                        (last, last_id, CHUNK)).fetchall():
                    last = rows[-1][0]
                    known = self.store.known({r[5] for r in rows})
                    todo, seen = [], set()
                    for row in rows:
                        if row[5] not in known and row[5] not in seen:
                            seen.add(row[5])
                            todo.append(row)
                    if todo and not self._embed_chunk(library, todo):
                        return self.done
            self.pending = 0
            self.report("current")
            self.drop_unused()
            return self.done
        finally:
            library.close()

    def drop_unused(self):
        """Once a build has changed the library, drop the vectors no passage uses any more and close their gaps. Only
        a finished build counts, so a library being rebuilt from scratch keeps every vector until its build is done.
        The build and the passages come from the library file as it is now, not the one this pass opened, which may
        have been deleted for such a rebuild since. The build is read before looking, so one that finishes meanwhile
        is looked at again on the next pass."""
        with _library_and_vectors(self.home) as db:
            build = _last_build(db)
            if build == "" or self.store.get("checked_build", "never") == build:
                return
            unused = _unused(db)
        if unused:
            self.store.drop(unused)
            self.log(f"dropped {len(unused):,} vectors no passage uses")
        self.store.compact()
        self.store.set("checked_build", build)

    def _embed_chunk(self, library, todo):
        texts, article_id, article_text = [], None, ""
        for _, aid, start, end, title, _ in todo:
            if aid != article_id:
                blob = library.execute("SELECT text FROM articles WHERE id=?", (aid,)).fetchone()[0]
                article_id, article_text = aid, zlib.decompress(blob).decode("utf-8")
            texts.append(passages.embedding_input(title, article_text[start:end]))
        for at in range(0, len(todo), self.batch):
            if not self.gate():
                return False
            vectors = self.vectors(texts[at:at + self.batch])
            kept = [(row[5], v) for row, v in zip(todo[at:at + self.batch], vectors) if v is not None]
            if kept:
                self.store.add([h for h, _ in kept], np.stack([v for _, v in kept]), self.embedder.model)
            self.done += len(kept)
            self.pending = max(self.pending - len(vectors), 0)
            self.report("embedding")
            if self.clock() - self.reported >= 60:
                self.reported = self.clock()
                status_now = self.store.get("status")
                self.log(f"{self.done:,} embedded, {self.pending:,} to go, {status_now['rate']:.0f} a second, "
                         f"about {status_now['hours_left'] or 0:.1f} hours left")
        return True


def embed_library(home, embedder, batch=32, log=print, worker=False, notify=None, yield_seconds=30,
                  retry_seconds=30, sleep=time.sleep, clock=time.monotonic):
    """Embed every passage input that has no vector yet; returns how many were embedded. Only one run at a time."""
    with open(os.path.join(home, ".embed.lock"), "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Busy("another embedding run is already going; see librarian embed status") from None
        store = VectorStore(home, write=True)
        try:
            return _Run(home, store, embedder, batch, log, worker, notify, yield_seconds, retry_seconds, sleep,
                        clock).run()
        finally:
            store.close()


def worker(home, embedder, notify=None, log=print, poll_seconds=600, sleep=time.sleep, passes=None):
    """Keep the meaning index current: embed what is missing, then look again every poll_seconds. Says once when
    the first full pass is done, and once when a pass fails, until one succeeds again. passes limits the passes
    (for a test); the launch agent runs it forever."""
    def safe_notify(title, message):
        try:
            notify(title, message)
        except Exception as exc:  # no internet, or no keys: the work goes on
            log(f"couldn't send a notification ({exc})")

    done_passes = 0
    while passes is None or done_passes < passes:
        done_passes += 1
        store = None
        try:
            embed_library(home, embedder, log=log, worker=True, notify=notify and safe_notify, sleep=sleep)
            store = VectorStore(home, write=True)
            store.forget("failed")
            if store.get("status", {}).get("state") == "current":
                store.notify_once(notify and safe_notify, "complete", "Offline Librarian: meaning index complete",
                                  f"All {store.rows():,} passage texts are embedded. The worker now keeps it current.")
        except Busy as exc:
            log(str(exc))
        except Exception as exc:
            log(f"embedding stopped: {exc}")
            store = VectorStore(home, write=True)
            store.notify_once(notify and safe_notify, "failed", "Offline Librarian: embedding stopped", str(exc))
        finally:
            if store:
                store.close()
        if passes is None or done_passes < passes:
            sleep(poll_seconds)


class Meaning:
    """The saved vectors and the embedder that makes question vectors to compare with them."""

    def __init__(self, home, embedder):
        self.home, self.embedder = home, embedder
        self.store, self.vectors, self.model = None, None, None
        if os.path.exists(os.path.join(home, "vectors.sqlite")):
            self.store = VectorStore(home)
            with self.store.reading():
                self.refresh()

    def refresh(self):
        """See the rows as they are now: those added since this was opened, and none past where a compaction cut
        the file. Call it while reading."""
        if self.store is None:
            return
        rows, dim = self.store.rows(), self.store.get("dim")
        self.model = self.store.get("model")
        if not (rows and dim):
            self.vectors = None
        elif self.vectors is None or len(self.vectors) != rows:
            self.vectors = np.memmap(self.store.vectors_path, dtype=np.float16, mode="r", shape=(rows, dim))

    def available(self):
        return self.vectors is not None

    def close(self):
        if self.store:
            self.store.close()

    def ranking(self, question, limit=300):
        """[(input hash, similarity)] best first. Raises MeaningUnavailable when the question can't be embedded."""
        if self.vectors is None:
            return []
        if self.embedder.model != self.model:
            raise MeaningUnavailable(f"the vectors were made with {self.model}, not {self.embedder.model}")
        query = self.embedder.embed_query(question).astype(np.float32)
        with self.store.reading():  # no rows move while they are compared and looked up
            self.refresh()
            if self.vectors is None:
                return []
            scores = np.empty(len(self.vectors), dtype=np.float32)
            for start in range(0, len(scores), 250_000):  # float16 rows, compared in float32 a slice at a time
                scores[start:start + 250_000] = self.vectors[start:start + 250_000].astype(np.float32) @ query
            best = np.argpartition(-scores, min(limit, len(scores) - 1))[:limit]
            best = best[np.argsort(-scores[best])]
            rows = [int(i) for i in best]
            hashes = dict(self.store.db.execute(
                f"SELECT row, hash FROM vectors WHERE row IN ({','.join('?' * len(rows))})", rows))
        return [(hashes[row], float(scores[row])) for row in rows if row in hashes]
