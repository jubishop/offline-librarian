"""The librarian command."""
import argparse
import json
import os
import sys

from librarian import kiwix, sources


def home():
    """Where the library lives: $OFFLINE_LIBRARIAN_HOME, or ~/.local/share/offline-librarian."""
    return os.environ.get("OFFLINE_LIBRARIAN_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share", "offline-librarian")


def fetch(args, parser):
    wanted = sources.KIWIX
    if args.books:
        by_name = {}
        for source in sources.KIWIX:
            by_name[source[0]] = by_name[kiwix.label(*source)] = source
        unknown = [name for name in args.books if name not in by_name]
        if unknown:
            parser.error(f"not a library source: {', '.join(unknown)}")
        wanted = [by_name[name] for name in args.books]
    folder = os.path.join(home(), "zim")
    try:
        failures = kiwix.fetch(wanted, folder, catalog_url=args.catalog, log=lambda line: print(line, flush=True))
    except (OSError, ValueError) as exc:  # the catalog itself couldn't be read
        print(f"Couldn't read the Kiwix catalog: {exc}", file=sys.stderr)
        return 1
    for failure in failures:
        print(failure, file=sys.stderr)
    return 1 if failures else 0


def library_path():
    return os.path.join(home(), "library.sqlite")


def open_library():
    """The library, or None after saying how to build one."""
    from librarian.library import Library
    if not os.path.exists(library_path()):
        print(f"There is no library at {library_path()} yet. Run librarian fetch, then librarian build.",
              file=sys.stderr)
        return None
    return Library(library_path())


def build(args, parser):
    from librarian import build as builder
    try:
        missing = builder.build(home(), workers=args.workers, log=lambda line: print(line, flush=True))
    except FileNotFoundError:
        print("No books are downloaded yet. Run librarian fetch first.", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"Couldn't build: {exc}.", file=sys.stderr)
        return 1
    if missing:
        print(f"Not downloaded yet: {', '.join(missing)}. Run librarian fetch, then build again.")
    return 0


def search(args, parser):
    library = open_library()
    if not library:
        return 1
    hits = library.search(" ".join(args.question), limit=args.limit)
    if args.json:
        print(json.dumps([{"id": h.id, "title": h.title, "heading": h.heading, "source": h.source, "url": h.url,
                           "text": h.text} for h in hits], indent=1))
        return 0
    if not hits:
        print("Nothing in the library matches that.", file=sys.stderr)
    for hit in hits:
        heading = f" › {hit.heading}" if hit.heading and hit.heading != hit.title else ""
        text = " ".join(hit.text.split())
        print(f"[{hit.id}] {hit.title}{heading} ({hit.source})" + (f"\n{hit.url}" if hit.url else "")
              + f"\n{text[:400] + '…' if len(text) > 400 else text}\n")
    return 0


def read(args, parser):
    library = open_library()
    if not library:
        return 1
    article = library.article(args.passage)
    if not article:
        print(f"There is no passage {args.passage} in the library.", file=sys.stderr)
        return 1
    source = f"{article.source} | {article.url}" if article.url else article.source
    print(f"# {article.title}\nSource: {source}\nLicense: {article.license}\n\n{article.text}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="librarian", description="Answer questions from an offline library.")
    commands = parser.add_subparsers(dest="command", required=True)
    fetch_parser = commands.add_parser("fetch", help="download the Kiwix books the library is built from",
                                       description="Download the Kiwix books the library is built from, or just "
                                                   "the ones named. Resumes partial downloads and checks each file.")
    fetch_parser.add_argument("books", nargs="*", metavar="BOOK", help="a Kiwix name, such as wikem_en_all")
    fetch_parser.add_argument("--catalog", default=kiwix.CATALOG_URL, help="the Kiwix catalog to read")
    fetch_parser.set_defaults(run=fetch)

    build_parser = commands.add_parser("build", help="build the library from the downloaded books",
                                       description="Convert the downloaded books to text and index them. Books "
                                                   "already built from their current file are skipped.")
    build_parser.add_argument("--workers", type=int, help="processes converting pages (default: all but two cores)")
    build_parser.set_defaults(run=build)

    search_parser = commands.add_parser("search", help="find the passages that best match a question",
                                        description="Find the passages that best match a question, one per article.")
    search_parser.add_argument("question", nargs="+")
    search_parser.add_argument("--limit", type=int, default=8, help="how many passages (default 8)")
    search_parser.add_argument("--json", action="store_true", help="print the passages as JSON")
    search_parser.set_defaults(run=search)

    read_parser = commands.add_parser("read", help="print the article a passage comes from",
                                      description="Print the whole article holding a passage, with its source and "
                                                  "license.")
    read_parser.add_argument("passage", type=int, help="a passage number from librarian search")
    read_parser.set_defaults(run=read)

    args = parser.parse_args(argv)
    return args.run(args, parser)
