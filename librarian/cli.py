"""The librarian command."""
import argparse
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


def main(argv=None):
    parser = argparse.ArgumentParser(prog="librarian", description="Answer questions from an offline library.")
    commands = parser.add_subparsers(dest="command", required=True)
    fetch_parser = commands.add_parser("fetch", help="download the Kiwix books the library is built from",
                                       description="Download the Kiwix books the library is built from, or just "
                                                   "the ones named. Resumes partial downloads and checks each file.")
    fetch_parser.add_argument("books", nargs="*", metavar="BOOK", help="a Kiwix name, such as wikem_en_all")
    fetch_parser.add_argument("--catalog", default=kiwix.CATALOG_URL, help="the Kiwix catalog to read")
    args = parser.parse_args(argv)
    return fetch(args, fetch_parser)
