"""Search by meaning: an EmbeddingGemma vector for every passage, made by Ollama.

The vectors live beside the library in three files: vectors.f16 (one float16 row per passage), vectors.ids (the
passage id of each row, as int64) and vectors.json (the model and its dimensions). Rows are only ever appended, in
passage id order, so an interrupted run resumes after the last id it saved. Passages of a rebuilt book get new ids,
and their old rows are ignored because those passages no longer exist.
"""
import json
import os
import time
import urllib.error
import urllib.request
import zlib

import numpy as np

DEFAULT_MODEL = "embeddinggemma-2:270m-bf16-text"
QUERY_PROMPT = "task: search result | query: "   # EmbeddingGemma's prompts for retrieval
CHUNK = 10_000  # passages read from the library at a time, so no read transaction stays open for long


class MeaningUnavailable(Exception):
    pass


def ollama_host():
    return os.environ.get("OLLAMA_HOST") or "127.0.0.1:11434"


def document_prompt(title, text):
    return f"title: {title or 'none'} | text: {text}"


class Embedder:
    def __init__(self, host=None, model=DEFAULT_MODEL):
        host = host or ollama_host()
        self.url = (host if "://" in host else "http://" + host).rstrip("/") + "/api/embed"
        self.model = model

    def embed(self, texts):
        """Unit-length vectors for texts, one row each."""
        body = json.dumps({"model": self.model, "input": texts}).encode()
        req = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                vectors = np.asarray(json.load(resp)["embeddings"], dtype=np.float32)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace").strip()
            exc.close()
            raise MeaningUnavailable(f"Ollama couldn't embed with {self.model}: {detail or exc}") from None
        except (OSError, ValueError, KeyError) as exc:
            raise MeaningUnavailable(f"couldn't reach Ollama at {self.url} ({exc})") from None
        if len(vectors) != len(texts):
            raise MeaningUnavailable(f"Ollama returned {len(vectors)} vectors for {len(texts)} texts")
        return vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)

    def embed_query(self, question):
        return self.embed([QUERY_PROMPT + question])[0]


def _paths(home):
    return (os.path.join(home, "vectors.f16"), os.path.join(home, "vectors.ids"), os.path.join(home, "vectors.json"))


def _saved_rows(home, dim):
    """How many complete rows are saved, trimming a row that a crash left half written."""
    vectors_path, ids_path, _ = _paths(home)
    if not os.path.exists(ids_path):
        return 0
    rows = min(os.path.getsize(ids_path) // 8, os.path.getsize(vectors_path) // (2 * dim))
    for path, width in ((ids_path, 8), (vectors_path, 2 * dim)):
        if os.path.getsize(path) != rows * width:
            os.truncate(path, rows * width)
    return rows


def embed_library(home, embedder, batch=32, log=print):
    """Embed every passage that has no vector yet. Returns how many were embedded."""
    from librarian import library
    vectors_path, ids_path, meta_path = _paths(home)
    meta = None
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            meta = json.load(f)
        if meta["model"] != embedder.model:
            raise MeaningUnavailable(f"the saved vectors were made with {meta['model']}; embed with that model, "
                                     f"or delete {vectors_path}, {ids_path} and {meta_path} to start over")
    last = 0
    if meta:
        rows = _saved_rows(home, meta["dim"])
        if rows:
            last = int(np.fromfile(ids_path, dtype=np.int64, count=1, offset=(rows - 1) * 8)[0])
    db = library.connect(os.path.join(home, "library.sqlite"))
    total = db.execute("SELECT COUNT(*) FROM passages WHERE id > ?", (last,)).fetchone()[0]
    done, started, reported = 0, time.monotonic(), time.monotonic()
    try:
        with open(vectors_path, "ab") as vectors_file, open(ids_path, "ab") as ids_file:
            while True:
                rows = db.execute(
                    "SELECT p.id, p.article_id, p.start, p.end, a.title FROM passages p "
                    "JOIN articles a ON a.id = p.article_id WHERE p.id > ? ORDER BY p.id LIMIT ?",
                    (last, CHUNK)).fetchall()
                if not rows:
                    break
                texts, article_id, article_text = [], None, ""
                for _, aid, start, end, title in rows:
                    if aid != article_id:
                        blob = db.execute("SELECT text FROM articles WHERE id=?", (aid,)).fetchone()[0]
                        article_id, article_text = aid, zlib.decompress(blob).decode("utf-8")
                    texts.append(document_prompt(title, article_text[start:end]))
                for at in range(0, len(rows), batch):
                    vectors = embedder.embed(texts[at:at + batch])
                    if meta is None:
                        meta = {"model": embedder.model, "dim": int(vectors.shape[1])}
                        with open(meta_path, "w") as f:
                            json.dump(meta, f)
                    vectors_file.write(vectors.astype(np.float16).tobytes())
                    ids_file.write(np.asarray([r[0] for r in rows[at:at + batch]], dtype=np.int64).tobytes())
                    vectors_file.flush()
                    ids_file.flush()
                    done += len(vectors)
                    if time.monotonic() - reported >= 60:
                        reported = time.monotonic()
                        rate = done / (reported - started)
                        log(f"{done:,} of {total:,} passages, {rate:.0f} a second, "
                            f"about {(total - done) / rate / 3600:.1f} hours left")
                last = rows[-1][0]
    finally:
        db.close()
    return done


class Meaning:
    """The saved vectors and the embedder that makes question vectors to compare with them."""

    def __init__(self, home, embedder):
        self.home, self.embedder = home, embedder
        self.vectors = self.ids = None
        vectors_path, ids_path, meta_path = _paths(home)
        if os.path.exists(meta_path):
            with open(meta_path) as f:
                meta = json.load(f)
            rows = min(os.path.getsize(ids_path) // 8, os.path.getsize(vectors_path) // (2 * meta["dim"]))
            if rows:
                self.vectors = np.memmap(vectors_path, dtype=np.float16, mode="r", shape=(rows, meta["dim"]))
                self.ids = np.memmap(ids_path, dtype=np.int64, mode="r", shape=(rows,))
                self.model = meta["model"]

    def available(self):
        return self.vectors is not None

    def ranking(self, question, limit=300):
        """[(passage id, similarity)] best first. Raises MeaningUnavailable when Ollama can't embed the question."""
        if self.vectors is None:
            return []
        if self.embedder.model != self.model:
            raise MeaningUnavailable(f"the vectors were made with {self.model}, not {self.embedder.model}")
        query = self.embedder.embed_query(question).astype(np.float32)
        scores = np.empty(len(self.ids), dtype=np.float32)
        for start in range(0, len(scores), 250_000):  # float16 rows, compared in float32 a slice at a time
            scores[start:start + 250_000] = self.vectors[start:start + 250_000].astype(np.float32) @ query
        best = np.argpartition(-scores, min(limit, len(scores) - 1))[:limit]
        best = best[np.argsort(-scores[best])]
        return [(int(self.ids[i]), float(scores[i])) for i in best]
