"""The monthly update, chosen by the user on 2026-10-25: fetch newer Kiwix editions of the books already downloaded,
rebuild only those books, and delete the superseded files so old copies don't fill the disk. The embedding worker
then embeds whatever text is new. Problems are reported once, through notify.
"""
import json
import os

from librarian import build, documents, kiwix, sources


def _manifest(zim):
    try:
        with open(os.path.join(zim, "manifest.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def prune(zim, log=print):
    """Delete the book files the manifest no longer names; returns their names."""
    current = {book["file"] for book in _manifest(zim).values()}
    removed = []
    for name in sorted(os.listdir(zim)):
        if name.endswith(".zim") and name not in current:
            os.remove(os.path.join(zim, name))
            removed.append(name)
            log(f"removed the superseded {name}")
    return removed


def update(home, catalog_url=kiwix.CATALOG_URL, workers=None, notify=None, log=print, document_sources=None):
    """Bring the downloaded books up to date and rebuild what changed. Returns the problems, if any."""
    zim = os.path.join(home, "zim")
    have = _manifest(zim)
    wanted = [source for source in sources.KIWIX if kiwix.label(*source) in have]
    failures = []
    try:
        failures += kiwix.fetch(wanted, zim, catalog_url=catalog_url, log=log)
    except (OSError, ValueError) as exc:  # the catalog itself couldn't be read
        failures.append(f"couldn't read the Kiwix catalog: {exc}")
    if document_sources is None:
        document_sources = [s for s in sources.DOCUMENTS if os.path.isdir(documents.folder(home, s))]
    failures += documents.fetch(home, document_sources, log=log)  # only what an earlier fetch missed
    try:
        build.build(home, workers=workers, documents_sources=document_sources, log=log)
    except Exception as exc:
        failures.append(f"the build failed: {exc}")
    else:
        prune(zim, log)
    if failures and notify:
        try:
            notify("Offline Librarian: the monthly update had problems", "\n".join(failures))
        except Exception as exc:  # no internet, or no keys
            log(f"couldn't send a notification ({exc})")
    return failures
