"""Sources that aren't Kiwix books (sources.DOCUMENTS): PDF manuals, web pages and the wikiHow dump. fetch()
downloads them into raw/<source key>/ beside the library, and articles() turns a source's files into articles
for the build.

Fetching and the wikiHow and life-table conversions are adapted from Survival LLM's library/fetch_manuals.py,
library/fetch_risk.py and library/build_library.py (MIT License, Copyright (c) 2026 Ronny Fernandez; see
LICENSE.survival-llm).
"""
import csv
import gzip
import hashlib
import http.client
import os
import re
import sys
import urllib.error
import urllib.request

from librarian import convert, passages, sources

# Some government sites refuse Python's and curl's own user agents.
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 15_0) AppleWebKit/605.1.15 (KHTML, like Gecko) "
              "Version/18.0 Safari/605.1.15")


def folder(home, source):
    return os.path.join(home, "raw", source.key)


def _get(url, part):
    """Fetch url into part, carrying on from what part already holds (urllib follows redirects)."""
    have = os.path.getsize(part) if os.path.exists(part) else 0
    headers = {"User-Agent": USER_AGENT, **({"Range": f"bytes={have}-"} if have else {})}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as resp:
        if have and resp.status != 206:
            have = 0
        with open(part, "ab" if have else "wb") as f:
            while chunk := resp.read(1 << 20):
                f.write(chunk)


def _usable(document, data_path):
    """Undo the Internet Archive's gzip and NHTSA's form-data wrapper, then check the file is what it should be."""
    with open(data_path, "rb") as f:
        data = f.read()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    if data.startswith(b"------") and b"%PDF" in data:
        data = data[data.index(b"%PDF"):data.rindex(b"%%EOF") + 5]
    with open(data_path, "wb") as f:
        f.write(data)
    if document.sha256:
        return hashlib.sha256(data).hexdigest() == document.sha256
    if document.kind == "pdf":
        return data.startswith(b"%PDF")
    return bool(data.strip())


def fetch(home, document_sources=None, log=print):
    """Download every document not already downloaded. Returns the problems, if any."""
    failures = []
    for source in sources.DOCUMENTS if document_sources is None else document_sources:
        os.makedirs(folder(home, source), exist_ok=True)
        for document in source.documents:
            dest = os.path.join(folder(home, source), document.file)
            if os.path.exists(dest):
                continue
            part = dest + ".part"
            problems = []
            for url in filter(None, (document.url, document.fallback)):
                try:
                    if not document.size:  # a resumed download only makes sense with a known size
                        if os.path.exists(part):
                            os.remove(part)
                    _get(url, part)
                    if document.size and os.path.getsize(part) < document.size:
                        raise ConnectionError(f"got {os.path.getsize(part):,} of {document.size:,} bytes")
                    if _usable(document, part):
                        os.replace(part, dest)
                        log(f"{source.key}: {document.title}")
                        break
                    problems.append(f"{url} didn't send the expected file")
                    os.remove(part)
                except urllib.error.HTTPError as exc:
                    problems.append(f"{url}: {exc}")
                    exc.close()
                except (OSError, http.client.HTTPException) as exc:
                    problems.append(f"{url}: {exc}")
            else:
                failures.append(f"{source.key}: {document.title}: {'; '.join(problems) or 'no address'}")
    return failures


def signature(home, source):
    """Which files a source's build came from, so a changed or added file rebuilds it."""
    parts = []
    for document in source.documents:
        path = os.path.join(folder(home, source), document.file)
        if os.path.exists(path):
            parts.append(f"{document.file}:{os.path.getsize(path)}:{int(os.path.getmtime(path))}")
    return "documents " + hashlib.sha256("|".join(parts).encode()).hexdigest()[:16] if parts else None


def _life_table(html):
    """The SSA life table as plain lines, with each yearly chance of dying also given in micromorts
    (one-in-a-million chances of death) per year and per day."""
    rows = re.findall(r"<tr[^>]*>\s*<td[^>]*>\s*(\d+)</td>\s*<td>\s*([\d.]+)</td>\s*<td>[^<]*</td>\s*<td>\s*([\d.]+)</td>"
                      r"\s*<td>\s*([\d.]+)</td>\s*<td>[^<]*</td>\s*<td>\s*([\d.]+)</td>", html)
    lines = ["How likely an American is to die within the next year at each age, from the Social Security period "
             "life table for 2023. A micromort is a one-in-a-million chance of death; micromorts per year = yearly "
             "chance x 1,000,000, and per day = per year / 365. Life expectancy is the average number of years left "
             "at that age."]
    for age, pm, em, pf, ef in rows:
        m, f = float(pm), float(pf)
        lines.append(f"Age {age}: men {m:.6f} a year ({m * 1e6:,.0f} micromorts a year, {m * 1e6 / 365:,.1f} a day; "
                     f"life expectancy {em} years); women {f:.6f} a year ({f * 1e6:,.0f} micromorts a year, "
                     f"{f * 1e6 / 365:,.1f} a day; life expectancy {ef} years)")
    return "\n\n".join(lines) if rows else ""


def _wikihow(path):
    """(title, url, text) for each guide in the 2018 wikiHow dump, its steps numbered."""
    csv.field_size_limit(sys.maxsize)
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            # The dump glues a counter onto titles ("How to Be an Organized Artist1").
            title = re.sub(r"(?<=[A-Za-z)])\d+$", "", (row.get("title") or "").strip()).strip()
            heads = [h.strip().rstrip(",").strip() for h in (row.get("headline") or "").split("\n")]
            heads = [h for h in heads if h]
            paras = [" ".join(p.split()) for p in re.split(r";?\n,", row.get("text") or "")]
            paras = [p.strip(" ;,") for p in paras if p.strip(" ;,")]
            if not title or not paras:
                continue
            if len(heads) == len(paras):
                steps = [f"{n}. {h}\n\n{p}" for n, (h, p) in enumerate(zip(heads, paras), 1)]
            else:
                steps = ["## Steps\n\n" + "\n".join(f"{n}. {h}" for n, h in enumerate(heads, 1))] if heads else []
                steps += ["## Details"] + paras
            url = "https://www.wikihow.com/" + title.replace("How to ", "", 1).replace(" ", "-")
            yield title, url, "\n\n".join(steps)


def articles(home, source):
    """(title, url, text, passages) for each article in a source's downloaded files."""
    for document in source.documents:
        path = os.path.join(folder(home, source), document.file)
        if not os.path.exists(path):
            continue
        if document.kind == "wikihow":
            found = _wikihow(path)
        else:
            with open(path, "rb") as f:
                data = f.read()
            if document.kind == "pdf":
                text = convert.pdf_to_text(data)
            elif document.kind == "life-table":
                text = _life_table(data.decode("utf-8", "replace"))
            else:
                text = convert.html_to_text(data, "web") or ""
            found = [(document.title, document.url, text)]
        for title, url, text in found:
            if len(text) >= convert.MIN_CHARS:
                yield (title, url, *passages.split_passages(text))

