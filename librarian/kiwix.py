"""Kiwix books: find them in the catalog, then download and check them.

The catalog (an OPDS feed) links each book to a Metalink file, which gives the book's size, its SHA-256 and the
mirrors that carry it, best first. A download resumes from its .part file, moves on to the next mirror when one
fails, and becomes the book's file only once its checksum matches. manifest.json records which file holds each
book, for the steps that read them.
"""
import hashlib
import http.client
import json
import os
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

CATALOG_URL = "https://opds.library.kiwix.org/catalog/v2/entries?lang=eng&count=5000"
ATOM = "{http://www.w3.org/2005/Atom}"
METALINK = "{urn:ietf:params:xml:ns:metalink}"
ACQUISITION = "http://opds-spec.org/acquisition/open-access"
ATTEMPTS = 3          # tries on one mirror (each resuming where the last stopped) before the next mirror
REPORT_EVERY = 30     # seconds between progress lines for one download


class FetchError(Exception):
    pass


@dataclass(frozen=True)
class Book:
    name: str
    flavour: str
    updated: str      # the catalog's date for this edition, YYYY-MM-DD
    metalink: str


@dataclass(frozen=True)
class File:
    name: str
    size: int
    sha256: str
    urls: tuple


def label(name, flavour):
    """How a book is named in messages and the manifest: "wikem_en_all nopic", or just the name."""
    return f"{name} {flavour}".strip()


def read_catalog(url=CATALOG_URL):
    """{(name, flavour): Book}, keeping the newest edition when the catalog lists several."""
    with urllib.request.urlopen(url, timeout=120) as resp:
        root = ET.parse(resp).getroot()
    books = {}
    for entry in root.iter(ATOM + "entry"):
        name, flavour = entry.findtext(ATOM + "name") or "", entry.findtext(ATOM + "flavour") or ""
        updated = (entry.findtext(ATOM + "updated") or "")[:10]
        link = next((link.get("href") for link in entry.findall(ATOM + "link") if link.get("rel") == ACQUISITION),
                    None)
        current = books.get((name, flavour))
        if name and link and (current is None or updated > current.updated):
            books[(name, flavour)] = Book(name, flavour, updated, link)
    return books


def read_metalink(url):
    with urllib.request.urlopen(url, timeout=120) as resp:
        root = ET.parse(resp).getroot()
    file = root.find(METALINK + "file")
    name = os.path.basename(file.get("name") or "")
    if not name.endswith(".zim") or name.startswith("."):
        raise FetchError(f"unexpected file name {file.get('name')!r} in {url}")
    sha256 = next((h.text or "").strip().lower() for h in file.findall(METALINK + "hash") if h.get("type") == "sha-256")
    urls = sorted(file.findall(METALINK + "url"), key=lambda u: int(u.get("priority") or 1_000_000))
    return File(name, int(file.findtext(METALINK + "size")), sha256, tuple((u.text or "").strip() for u in urls))


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 24):
            digest.update(chunk)
    return digest.hexdigest()


def _get(url, part, size, report):
    """Fetch url into part, carrying on from what part already holds."""
    have = os.path.getsize(part) if os.path.exists(part) else 0
    if have > size:  # not from this file: start over
        os.remove(part)
        have = 0
    if have == size:
        return
    req = urllib.request.Request(url, headers={"Range": f"bytes={have}-"} if have else {})
    with urllib.request.urlopen(req, timeout=60) as resp:
        if have and resp.status != 206:  # the mirror ignored the range
            have = 0
        with open(part, "ab" if have else "wb") as f:
            while chunk := resp.read(1 << 20):
                f.write(chunk)
                have += len(chunk)
                report(have)
    if have < size:
        raise ConnectionError(f"the connection closed after {have:,} of {size:,} bytes")


def download(file, folder, report=lambda have: None):
    """Download file into folder from the first mirror that delivers it, and check it."""
    dest = os.path.join(folder, file.name)
    part = dest + ".part"
    problems = []
    for url in file.urls:
        for _ in range(ATTEMPTS):
            try:
                _get(url, part, file.size, report)
                break
            except urllib.error.HTTPError as exc:  # this mirror doesn't have it
                problems.append(f"{url}: {exc}")
                exc.close()
                break
            except (OSError, http.client.HTTPException) as exc:  # dropped or timed out: resume
                problems.append(f"{url}: {exc}")
        if os.path.exists(part) and os.path.getsize(part) == file.size:
            break
    else:
        raise FetchError(f"no mirror delivered {file.name} ({problems[-1] if problems else 'no mirrors listed'})")
    if _sha256(part) != file.sha256:
        os.remove(part)
        raise FetchError(f"{file.name} failed its checksum, so it was deleted; try again")
    os.replace(part, dest)
    return dest


def fetch(sources, folder, catalog_url=CATALOG_URL, workers=4, log=print):
    """Download each (name, flavour) book into folder unless it is already there. Returns the problems, if any."""
    os.makedirs(folder, exist_ok=True)
    books = read_catalog(catalog_url)
    manifest_path = os.path.join(folder, "manifest.json")
    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
    except (OSError, ValueError):
        manifest = {}
    failures, lock = [], threading.Lock()

    def one(source):
        name = label(*source)
        book = books.get(source)
        if not book:
            failures.append(f"{name}: not in the Kiwix catalog")
            return
        try:
            file = read_metalink(book.metalink)
            if not os.path.exists(os.path.join(folder, file.name)):
                log(f"{name}: downloading {file.name} ({file.size / 1e9:.2f} GB)")
                last = [time.monotonic()]

                def report(have):
                    if time.monotonic() - last[0] >= REPORT_EVERY:
                        last[0] = time.monotonic()
                        log(f"{name}: {have / 1e9:.2f} of {file.size / 1e9:.2f} GB")
                download(file, folder, report)
                log(f"{name}: done")
            with lock:
                manifest[name] = {"file": file.name, "updated": book.updated, "sha256": file.sha256,
                                  "bytes": file.size}
                with open(manifest_path + ".tmp", "w") as f:
                    json.dump(manifest, f, indent=1, sort_keys=True)
                os.replace(manifest_path + ".tmp", manifest_path)
        except (FetchError, OSError, ET.ParseError, http.client.HTTPException, StopIteration, ValueError) as exc:
            failures.append(f"{name}: {exc or type(exc).__name__}")

    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(one, sources))
    return failures
