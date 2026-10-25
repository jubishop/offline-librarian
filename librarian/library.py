"""The library: one SQLite file holding every article, its passages and a full-text index over them.

Articles are stored compressed, and passages are offsets into their article's text. The full-text index (FTS5,
BM25) holds no text of its own. Keyword search follows Survival LLM's library/search.py (MIT License, Copyright
(c) 2026 Ronny Fernandez; see LICENSE.survival-llm): every word first, any word when that finds too little, and
sources weighted by how authoritative they are. When the passages also have vectors (librarian/meaning.py), the
keyword and meaning rankings are merged by reciprocal rank fusion. Results keep one passage per article,
and text that several books share appears once.
"""
import re
import sqlite3
import zlib
from dataclasses import dataclass

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources(id INTEGER PRIMARY KEY, key TEXT UNIQUE, label TEXT, topic TEXT, license TEXT,
                                   weight REAL, origin TEXT, articles INT DEFAULT 0, done INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS articles(id INTEGER PRIMARY KEY, source_id INT, title TEXT, url TEXT, text BLOB);
CREATE INDEX IF NOT EXISTS articles_title ON articles(title COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS articles_source ON articles(source_id);
CREATE TABLE IF NOT EXISTS passages(id INTEGER PRIMARY KEY, article_id INT, start INT, end INT, heading TEXT,
                                    hash BLOB);
CREATE INDEX IF NOT EXISTS passages_article ON passages(article_id);
CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(title, body, content='', contentless_delete=1,
                                                  tokenize='porter unicode61 remove_diacritics 2');
"""

STOPWORDS = set("""a about above after again against all am an and any are as at be because been before being below
between both but by can could did do does doing down during each few for from further had has have having he her here
hers herself him himself his how i if in into is it its itself just me more most my myself no nor not now of off on
once only or other our ours ourselves out over own same she should so some such than that the their theirs them
themselves then there these they this those through to too under until up very was we were what when where which
while who whom why will with would you your yours yourself yourselves""".split())


@dataclass(frozen=True)
class Passage:
    id: int
    article_id: int
    title: str
    heading: str
    source: str
    url: str
    text: str


@dataclass(frozen=True)
class Article:
    id: int
    title: str
    source: str
    url: str
    license: str
    text: str
    passages: tuple   # (passage id, start, end) in text


def connect(path, write=False):
    if not write:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    db = sqlite3.connect(path, isolation_level=None)
    db.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;" + SCHEMA)
    if "hash" not in [column[1] for column in db.execute("PRAGMA table_info(passages)")]:
        db.execute("ALTER TABLE passages ADD COLUMN hash BLOB")  # libraries built before vectors were keyed by text
    db.execute("CREATE INDEX IF NOT EXISTS passages_hash ON passages(hash)")
    return db


def query_words(query):
    """The words of a question worth searching for."""
    return [w for w in re.findall(r"[\w']+", query.lower()) if w not in STOPWORDS and len(w) > 1][:12]


FUSION_K = 60  # reciprocal rank fusion: each ranking adds 1 / (FUSION_K + rank)


class Library:
    def __init__(self, path, meaning=None):
        self.db = connect(path)
        self.meaning = meaning
        self.meaning_problem = None  # why the last search used keywords only, when meaning search was expected

    def close(self):
        self.db.close()

    def stats(self):
        """(articles, passages, sources) that are fully built."""
        sources, articles = self.db.execute(
            "SELECT COUNT(*), COALESCE(SUM(articles), 0) FROM sources WHERE done=1").fetchone()
        passages = self.db.execute("SELECT COALESCE(MAX(id), 0) FROM passages").fetchone()[0]
        return articles, passages, sources

    def _text(self, blob):
        return zlib.decompress(blob).decode("utf-8")

    def keyword_ranking(self, query, limit=300):
        """[(passage id, score)] best first, by BM25 weighted by each source's authority."""
        words = query_words(query)
        if not words:
            return []
        terms = ['"' + w.replace('"', "") + '"' for w in words]
        hits = []
        for joiner in (" ", " OR "):  # every word first; any word if that finds too little
            hits = self.db.execute(
                "SELECT rowid, rank FROM fts WHERE fts MATCH ? AND rank MATCH 'bm25(4.0, 1.0)' ORDER BY rank LIMIT ?",
                (joiner.join(terms), limit)).fetchall()
            if len(hits) >= 3 or len(words) == 1:
                break
        if not hits:
            return []
        weights = dict(self.db.execute(
            "SELECT p.id, s.weight FROM passages p JOIN articles a ON a.id = p.article_id "
            f"JOIN sources s ON s.id = a.source_id WHERE p.id IN ({','.join('?' * len(hits))})",
            [pid for pid, _ in hits]))
        # BM25 ranks are negative (lower is better), so a weight above 1 moves a source up.
        return sorted(((pid, rank * weights[pid]) for pid, rank in hits if pid in weights), key=lambda hit: hit[1])

    def passages(self, ids):
        """Passages by id, in the order given."""
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        rows = {r[0]: r for r in self.db.execute(
            "SELECT p.id, a.id, a.title, p.heading, s.label, a.url, a.text, p.start, p.end FROM passages p "
            f"JOIN articles a ON a.id = p.article_id JOIN sources s ON s.id = a.source_id WHERE p.id IN ({marks})",
            list(ids))}
        return [Passage(r[0], r[1], r[2], r[3], r[4], r[5], self._text(r[6])[r[7]:r[8]]) for i in ids
                if (r := rows.get(i))]

    def ranking(self, query):
        """Passage ids best first, by keyword and, when there are vectors, by meaning."""
        rankings = [[pid for pid, _ in self.keyword_ranking(query)]]
        self.meaning_problem = None
        if self.meaning is not None and self.meaning.available():
            from librarian.meaning import MeaningUnavailable
            try:
                rankings.append(self._passages_with(h for h, _ in self.meaning.ranking(query)))
            except MeaningUnavailable as exc:
                self.meaning_problem = f"Searched by keyword only: {exc}"
        if len(rankings) == 1:
            return rankings[0]
        fused = {}
        for ranking in rankings:
            for rank, pid in enumerate(ranking):
                fused[pid] = fused.get(pid, 0.0) + 1.0 / (FUSION_K + rank)
        return sorted(fused, key=fused.get, reverse=True)

    def _passages_with(self, hashes):
        """Passage ids whose embedding inputs have these hashes, in the hashes' order; hashes no passage has any
        more (from replaced editions) drop out."""
        hashes = list(hashes)
        found = {}
        for at in range(0, len(hashes), 500):
            part = hashes[at:at + 500]
            for pid, h in self.db.execute(
                    f"SELECT id, hash FROM passages WHERE hash IN ({','.join('?' * len(part))})", part):
                found.setdefault(h, []).append(pid)
        return [pid for h in hashes for pid in found.get(h, [])]

    def search(self, query, limit=8):
        """The best passages for a question, at most one per article."""
        ranking = self.ranking(query)
        found = {}
        for at in range(0, len(ranking), 500):  # passages of rebuilt books are gone; they drop out here
            ids = ranking[at:at + 500]
            found.update((pid, (article, h)) for pid, article, h in self.db.execute(
                f"SELECT id, article_id, hash FROM passages WHERE id IN ({','.join('?' * len(ids))})", ids))
        chosen, articles, texts = [], set(), set()
        for pid in ranking:
            if pid not in found:
                continue
            article, h = found[pid]
            if article in articles or (h is not None and h in texts):  # one per article; shared text once
                continue
            articles.add(article)
            # Every passage of a chosen article counts as seen, so another copy of the same document (zimgit's
            # collections share PDFs) can't come back through a different passage.
            texts.update(other for (other,) in self.db.execute("SELECT hash FROM passages WHERE article_id=?",
                                                                 (article,)))
            chosen.append(pid)
            if len(chosen) == limit:
                break
        return self.passages(chosen)

    def article(self, passage_id):
        """The whole article holding a passage."""
        row = self.db.execute(
            "SELECT a.id, a.title, s.label, a.url, s.license, a.text FROM passages p JOIN articles a "
            "ON a.id = p.article_id JOIN sources s ON s.id = a.source_id WHERE p.id=?", (passage_id,)).fetchone()
        if not row:
            return None
        parts = tuple(self.db.execute("SELECT id, start, end FROM passages WHERE article_id=? ORDER BY id", (row[0],)))
        return Article(row[0], row[1], row[2], row[3], row[4], self._text(row[5]), parts)
