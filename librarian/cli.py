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


def open_library(model=None):
    """The library, searching by meaning too when its passages have vectors; None after saying how to build one."""
    from librarian import meaning
    from librarian.library import Library
    if not os.path.exists(library_path()):
        print(f"There is no library at {library_path()} yet. Run librarian fetch, then librarian build.",
              file=sys.stderr)
        return None
    embedder = meaning.Embedder(model=model or meaning.DEFAULT_MODEL)
    return Library(library_path(), meaning=meaning.Meaning(home(), embedder))


def build(args, parser):
    from librarian import build as builder, priority
    priority.background()
    try:
        missing = builder.build(home(), workers=args.workers, rebuild=args.rebuild,
                                log=lambda line: print(line, flush=True))
    except FileNotFoundError:
        print("No books are downloaded yet. Run librarian fetch first.", file=sys.stderr)
        return 1
    except (RuntimeError, ValueError) as exc:
        print(f"Couldn't build: {exc}.", file=sys.stderr)
        return 1
    if missing:
        print(f"Not downloaded yet: {', '.join(missing)}. Run librarian fetch, then build again.")
    return 0


def embed(args, parser):
    from librarian import agent, meaning, notify, priority
    model = args.model or meaning.DEFAULT_MODEL
    if args.action == "status":
        report = meaning.status(home())
        print(f"state: {report['state']}{' (paused)' if report.get('paused') else ''}")
        print(f"embedded: {report['embedded']:,} passage texts")
        if report.get("pending") is not None:
            print(f"to go: {report['pending']:,}")
        if report.get("rate"):
            print(f"rate: {report['rate']} a second, about {report.get('hours_left') or 0} hours left")
        if report.get("yielding_to"):
            print(f"waiting while loaded: {', '.join(report['yielding_to'])}")
        if report.get("last_error"):
            print(f"last error: {report['last_error']}")
        print(f"updated: {report.get('updated', 'never')}")
        print(f"background worker: {'running' if agent.running() else 'not installed'}")
        return 0
    if args.action in ("pause", "resume"):
        (meaning.pause if args.action == "pause" else meaning.resume)(home())
        print("Paused: embedding stops after its current batch." if args.action == "pause"
              else "Resumed: embedding carries on.")
        return 0
    if args.action == "install":
        try:
            path = agent.install(home(), model)
        except RuntimeError as exc:
            print(f"Couldn't install the worker: {exc}.", file=sys.stderr)
            return 1
        print(f"Installed {path}. The worker embeds in the background at low priority, waits while Ollama has "
              f"another model loaded, and keeps the index current. Logs: {home()}/embed.log")
        return 0
    if args.action == "uninstall":
        agent.uninstall()
        print("Removed the background worker. Vectors made so far are kept.")
        return 0
    if not os.path.exists(library_path()):
        print("There is no library to embed yet. Run librarian build first.", file=sys.stderr)
        return 1
    priority.background()
    embedder = meaning.Embedder(model=model)
    log = lambda line: print(line, flush=True)  # noqa: E731
    if args.action == "worker":
        meaning.worker(home(), embedder, notify=notify.pushover(), log=log)
        return 0
    try:
        count = meaning.embed_library(home(), embedder, batch=args.batch, log=log)
    except meaning.MeaningUnavailable as exc:
        print(f"Stopped: {exc}. Run librarian embed again to carry on from here.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Stopped. Run librarian embed again to carry on from here.", file=sys.stderr)
        return 130
    print(f"Embedded {count:,} passages.")
    return 0


def search(args, parser):
    library = open_library(args.model)
    if not library:
        return 1
    hits = library.search(" ".join(args.question), limit=args.limit)
    if library.meaning_problem:
        print(library.meaning_problem, file=sys.stderr)
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


def ask(args, parser):
    from librarian import answer
    library = open_library()
    if not library:
        return 1
    model, think = answer.pi_settings()
    chat = answer.Chat(model=args.model or model, think=think if args.think is None else args.think == "on")
    passages, failed = [], False
    for event in answer.ask(library, " ".join(args.question), chat=chat):
        if event["type"] == "passages":
            passages = event["passages"]
            if event.get("search_problem"):
                print(event["search_problem"], file=sys.stderr)
        elif event["type"] == "thinking":
            print("Thinking…", file=sys.stderr, flush=True)
        elif event["type"] == "text":
            print(event["text"], end="", flush=True)
        elif event["type"] == "error":
            print(f"\nCouldn't answer: {event['message']}.", file=sys.stderr)
            failed = True
        elif event["type"] == "done":
            print()
            by_number = {p["n"]: p for p in passages}
            if event["cited"]:
                print("\nSources:")
                for n in event["cited"]:
                    p = by_number[n]
                    print(f"[{n}] {p['title']}, {p['source']}" + (f", {p['url']}" if p["url"] else ""))
    return 1 if failed else 0


def page_addresses(port):
    """Addresses a browser on this Mac or the home network can open the page at."""
    from librarian import server
    names = server.allowed_hosts()
    shown = [f"http://localhost:{port}/"]
    shown += sorted(f"http://{n}:{port}/" for n in names if n.endswith(".local"))
    shown += sorted(f"http://{n}:{port}/" for n in names
                    if n.count(".") == 3 and not n.startswith(("127.", "169.254.")) and n.replace(".", "").isdigit())
    return shown


def serve(args, parser):
    import signal
    from librarian import agent, notify, server
    if args.action == "install":
        try:
            path = agent.install_server(home(), args.port)
        except RuntimeError as exc:
            print(f"Couldn't install the page server: {exc}.", file=sys.stderr)
            return 1
        print(f"Installed {path}. The page is always running at:")
        for address in page_addresses(args.port):
            print(f"  {address}")
        return 0
    if args.action == "uninstall":
        agent.uninstall(agent.SERVER)
        print("Removed the page server. Saved conversations are kept.")
        return 0
    if args.action == "status":
        running = agent.running(agent.SERVER)
        print(f"page server: {'running' if running else 'not installed'}")
        if running:
            for address in page_addresses(args.port):
                print(f"  {address}")
        return 0
    page = server.Server(home(), port=args.port, bind=args.bind, notify=notify.pushover(),
                         log=lambda line: print(line, flush=True))
    try:
        page.start()
    except OSError as exc:
        print(f"Couldn't start the page server on port {args.port}: {exc}.", file=sys.stderr)
        return 1

    def stop(signum, frame):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)  # launchd stops agents with SIGTERM: a clean stop, not a crash
    print(f"Serving the page at http://{'localhost' if args.bind in ('0.0.0.0', '127.0.0.1') else args.bind}:"
          f"{page.port}/", flush=True)
    try:
        signal.pause()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        page.stop()
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
    build_parser.add_argument("--rebuild", nargs="+", default=[], metavar="SOURCE",
                              help="build these sources again, such as wikipedia or se-cooking, after a fix")
    build_parser.set_defaults(run=build)

    search_parser = commands.add_parser("search", help="find the passages that best match a question",
                                        description="Find the passages that best match a question, one per article.")
    search_parser.add_argument("question", nargs="+")
    search_parser.add_argument("--limit", type=int, default=8, help="how many passages (default 8)")
    search_parser.add_argument("--json", action="store_true", help="print the passages as JSON")
    search_parser.add_argument("--model", help="the Ollama model that embedded the library")
    search_parser.set_defaults(run=search)

    embed_parser = commands.add_parser(
        "embed", help="index every passage by meaning, with Ollama",
        description="Give every passage an EmbeddingGemma vector through Ollama, so searches find passages by meaning "
                    "as well as by keyword. It waits while Ollama has another model loaded, and passages whose text "
                    "is already embedded are skipped. ACTION is run (the default: embed now, here), install (a "
                    "background worker that keeps the index current), uninstall, status, pause or resume.")
    embed_parser.add_argument("action", nargs="?", default="run",
                              choices=["run", "install", "uninstall", "status", "pause", "resume", "worker"])
    embed_parser.add_argument("--model", default=None, help="the Ollama embedding model (default: "
                                                            "embeddinggemma-2:270m-bf16-text)")
    embed_parser.add_argument("--batch", type=int, default=32, help="passages per request to Ollama (default 32)")
    embed_parser.set_defaults(run=embed)

    ask_parser = commands.add_parser("ask", help="answer a question from the library with a local model",
                                     description="Search the library, then have a local Ollama model answer from the "
                                                 "passages it found, citing them. The model and thinking follow "
                                                 "your pi settings unless given here.")
    ask_parser.add_argument("question", nargs="+")
    ask_parser.add_argument("--model", help="the Ollama chat model (default: pi's default model)")
    ask_parser.add_argument("--think", choices=["on", "off"], help="think before answering (default: as in pi)")
    ask_parser.set_defaults(run=ask)

    serve_parser = commands.add_parser(
        "serve", help="run the browser page",
        description="Run the browser page on every network this Mac is on (the home Wi-Fi, and Tailscale when it "
                    "is connected), with no password. ACTION is run (the default: serve here until stopped), "
                    "install (keep it always running, as a launch agent), uninstall or status.")
    serve_parser.add_argument("action", nargs="?", default="run", choices=["run", "install", "uninstall", "status"])
    serve_parser.add_argument("--port", type=int, default=8740, help="the port to listen on (default 8740)")
    serve_parser.add_argument("--bind", default="0.0.0.0", help="the address to listen on (default: all of them)")
    serve_parser.set_defaults(run=serve)

    read_parser = commands.add_parser("read", help="print the article a passage comes from",
                                      description="Print the whole article holding a passage, with its source and "
                                                  "license.")
    read_parser.add_argument("passage", type=int, help="a passage number from librarian search")
    read_parser.set_defaults(run=read)

    args = parser.parse_args(argv)
    return args.run(args, parser)
