"""Build the library from the downloaded books: convert each page to text, cut it into passages, and index them.

Each book is built in one transaction, so searches never see half of one, and a book is built again only when the
manifest names a different file for it. Pages are converted in worker processes; the parent writes the database.
Adapted from Survival LLM's library/build_library.py (MIT License, Copyright (c) 2026 Ronny Fernandez; see
LICENSE.survival-llm).
"""
import fcntl
import json
import multiprocessing
import os
import re
import time
import zlib

from librarian import convert, kiwix, library, passages, sources

_ARCHIVE = _KIND = _SKIP = None   # per worker process


def _start_worker(path, kind, skip):
    global _ARCHIVE, _KIND, _SKIP
    from libzim.reader import Archive
    os.nice(10)  # leave the computer responsive during an hours-long build
    _ARCHIVE, _KIND, _SKIP = Archive(path), kind, re.compile(skip) if skip else None


def _convert(bounds):
    """[(title, path, text, passages)] and problems for the entries in range(*bounds)."""
    out, problems = [], []
    for i in range(*bounds):
        try:
            entry = _ARCHIVE._get_entry_by_id(i)
            if entry.is_redirect or (_SKIP and _SKIP.search(entry.path)) or re.match(r"(?i)h?ttps?:", entry.path):
                continue
            item = entry.get_item()
            mime = item.mimetype.split(";")[0]
            if mime == "application/pdf" and _KIND in ("pdf", "web"):
                text = convert.pdf_to_text(bytes(item.content))
                title = convert.pdf_title(entry.path, entry.title, text)
            elif mime == "text/html" and (_KIND != "se" or entry.path.startswith("questions/")):
                text = convert.html_to_text(bytes(item.content), _KIND)
                title = entry.title or entry.path
            else:
                continue
            if text and len(text) >= convert.MIN_CHARS:
                out.append((convert.clean_title(title), entry.path, *passages.split_passages(text)))
        except Exception as exc:  # one bad page must not stop a million-page build
            problems.append(f"entry {i} ({exc})")
    return out, problems


def _articles(path, source, workers, log):
    from libzim.reader import Archive
    count = Archive(path).entry_count
    step = 50 if source.kind == "pdf" else 1000
    ranges = [(start, min(start + step, count)) for start in range(0, count, step)]
    with multiprocessing.Pool(workers, initializer=_start_worker, initargs=(path, source.kind, source.skip)) as pool:
        for batch, problems in pool.imap(_convert, ranges):
            for problem in problems:
                log(f"{source.key}: skipped {problem}")
            yield from batch


def _drop(db, source_id):
    db.execute("DELETE FROM fts WHERE rowid IN (SELECT p.id FROM passages p JOIN articles a ON a.id = p.article_id "
               "WHERE a.source_id=?)", (source_id,))
    db.execute("DELETE FROM passages WHERE article_id IN (SELECT id FROM articles WHERE source_id=?)", (source_id,))
    db.execute("DELETE FROM articles WHERE source_id=?", (source_id,))
    db.execute("DELETE FROM sources WHERE id=?", (source_id,))


def _build_source(db, source, filename, path, workers, log):
    started = time.monotonic()
    log(f"{source.key}: building from {filename}")
    others = sorted(sources.SAME_ARTICLES - {source.key}) if source.key in sources.SAME_ARTICLES else []
    known = {title.lower() for (title,) in db.execute(
        "SELECT a.title FROM articles a JOIN sources s ON s.id = a.source_id "
        f"WHERE s.done = 1 AND s.key IN ({','.join('?' * len(others))})", others)} if others else set()
    db.execute("BEGIN")
    try:
        old = db.execute("SELECT id FROM sources WHERE key=?", (source.key,)).fetchone()
        if old:
            _drop(db, old[0])
        source_id = db.execute(
            "INSERT INTO sources(key, label, topic, license, weight, origin) VALUES(?,?,?,?,?,?)",
            (source.key, source.label, source.topic, source.license, source.weight, filename)).lastrowid
        next_passage = db.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM passages").fetchone()[0]
        count = 0
        for title, entry_path, text, cuts in _articles(path, source, workers, log):
            if title.lower() in known:
                continue
            article_id = db.execute("INSERT INTO articles(source_id, title, url, text) VALUES(?,?,?,?)",
                                    (source_id, title, source.url and source.url + entry_path,
                                     zlib.compress(text.encode("utf-8"), 6))).lastrowid
            ids = range(next_passage, next_passage + len(cuts))
            next_passage += len(cuts)
            db.executemany("INSERT INTO passages(id, article_id, start, end, heading) VALUES(?,?,?,?,?)",
                           [(pid, article_id, start, end, heading) for pid, (start, end, heading) in zip(ids, cuts)])
            db.executemany("INSERT INTO fts(rowid, title, body) VALUES(?,?,?)",
                           [(pid, f"{title} {heading}".strip(), text[start:end])
                            for pid, (start, end, heading) in zip(ids, cuts)])
            count += 1
            if count % 50_000 == 0:
                log(f"{source.key}: {count:,} articles, {time.monotonic() - started:.0f}s")
        db.execute("UPDATE sources SET articles=?, done=1 WHERE id=?", (count, source_id))
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    log(f"{source.key}: done, {count:,} articles in {time.monotonic() - started:.0f}s")


def build(home, workers=None, log=print):
    """Build every downloaded book into home/library.sqlite that isn't built from its current file yet.
    Returns the labels of the books that aren't downloaded."""
    zim = os.path.join(home, "zim")
    with open(os.path.join(zim, "manifest.json")) as f:
        manifest = json.load(f)
    workers = workers or max(1, (os.cpu_count() or 2) - 2)
    with open(os.path.join(home, ".build.lock"), "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("another build is already running") from None
        db = library.connect(os.path.join(home, "library.sqlite"), write=True)
        try:
            missing, changed = [], False
            for source in sources.SOURCES:
                book = manifest.get(kiwix.label(source.name, source.flavour))
                if not book:
                    missing.append(kiwix.label(source.name, source.flavour))
                    continue
                row = db.execute("SELECT done, origin FROM sources WHERE key=?", (source.key,)).fetchone()
                if row and row[0] and row[1] == book["file"]:
                    log(f"{source.key}: already built")
                    continue
                _build_source(db, source, book["file"], os.path.join(zim, book["file"]), workers, log)
                changed = True
            if changed:
                log("optimizing the search index")
                db.execute("INSERT INTO fts(fts) VALUES('optimize')")
                db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            return missing
        finally:
            db.close()
