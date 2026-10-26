"""The retrieval test set (docs/design.md#decisions): does search find the articles a good answer needs?

Each question in evals/questions.json lists [source key, title pattern] pairs; a result counts when its article
comes from that source and its title matches. Scores keyword search alone and keyword plus meaning, against the
real library, as hit@1, hit@3, hit@8 and mean reciprocal rank over the first eight results.

Run: bin/eval-retrieval [--modes keyword,both] [--limit 8] [--verbose] [--check] [--sweep]
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from librarian import cli, meaning, sources  # noqa: E402
from librarian.library import Library  # noqa: E402

LABELS = {s.label: s.key for s in [*sources.SOURCES, *sources.DOCUMENTS]}


def first_hit(hits, expect):
    """The 1-based rank of the first result that is an expected article, or None."""
    for rank, hit in enumerate(hits, 1):
        key = LABELS.get(hit.source)
        if any(key == want_key and re.search(pattern, hit.title, re.I) for want_key, pattern in expect):
            return rank
    return None


def check(home, questions):
    """Say which expectations match no article, so a question isn't scored against an article the library lacks."""
    library = Library(os.path.join(home, "library.sqlite"))
    titles = {}
    missing = 0
    for item in questions:
        for key, pattern in item["expect"]:
            if key not in titles:
                titles[key] = [t for (t,) in library.db.execute(
                    "SELECT a.title FROM articles a JOIN sources s ON s.id = a.source_id WHERE s.key = ?", (key,))]
            count = sum(1 for t in titles[key] if re.search(pattern, t, re.I))
            if not count:
                missing += 1
                print(f"no article: {key} /{pattern}/  for: {item['q']}")
    print(f"{missing} expectations match no article")
    return 1 if missing else 0


SWEEP = [(60, 1, 1), (60, 0.7, 1), (60, 0.5, 1), (60, 1, 0.7), (20, 1, 1), (20, 0.7, 1), (10, 1, 1)]


def sweep(home, questions, limit):
    """Score several fusion settings (k, keyword weight, meaning weight), ranking each question once."""
    library = Library(os.path.join(home, "library.sqlite"), meaning=meaning.Meaning(home, meaning.Embedder()))
    lists = {}
    for item in questions:
        keyword = [pid for pid, _ in library.keyword_ranking(item["q"])]
        by_meaning = library._passages_with(h for h, _ in library.meaning.ranking(item["q"]))
        lists[item["q"]] = (keyword, by_meaning)
    real = library.ranking
    print(f"{'k':>3} {'keyword':>8} {'meaning':>8} {'hit@1':>6} {'hit@3':>6} {'hit@8':>6} {'MRR':>6}")
    for k, keyword_weight, meaning_weight in SWEEP:
        ranks = []
        for item in questions:
            fused = {}
            for weight, ranking in zip((keyword_weight, meaning_weight), lists[item["q"]]):
                for rank, pid in enumerate(ranking):
                    fused[pid] = fused.get(pid, 0.0) + weight / (k + rank)
            order = sorted(fused, key=fused.get, reverse=True)
            library.ranking = lambda query, order=order: order  # search's per-article and shared-text rules
            ranks.append(first_hit(library.search(item["q"], limit=limit), item["expect"]))
        library.ranking = real
        n = len(ranks)
        hit = lambda c: sum(1 for r in ranks if r and r <= c) / n  # noqa: E731
        print(f"{k:>3} {keyword_weight:>8} {meaning_weight:>8} {hit(1):6.2f} {hit(3):6.2f} {hit(limit):6.2f} "
              f"{sum(1 / r for r in ranks if r) / n:6.2f}")
    library.close()
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--modes", default="keyword,both", help="keyword, both, or keyword,both")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--verbose", action="store_true", help="show each question's top results")
    parser.add_argument("--check", action="store_true", help="only check that every expected article exists")
    parser.add_argument("--sweep", action="store_true", help="score several keyword and meaning fusion weights")
    args = parser.parse_args()
    with open(os.path.join(ROOT, "evals", "questions.json")) as f:
        questions = json.load(f)
    home = cli.home()
    if args.check:
        return check(home, questions)
    if args.sweep:
        return sweep(home, questions, args.limit)
    results = {}
    for mode in args.modes.split(","):
        found = meaning.Meaning(home, meaning.Embedder()) if mode == "both" else None
        library = Library(os.path.join(home, "library.sqlite"), meaning=found)
        ranks = []
        for item in questions:
            hits = library.search(item["q"], limit=args.limit)
            if library.meaning_problem:
                sys.exit(library.meaning_problem)
            ranks.append(first_hit(hits, item["expect"]))
            if args.verbose:
                print(f"[{mode}] {ranks[-1] or '-'}  {item['q']}")
                for hit in hits[:3]:
                    print(f"         {hit.title[:70]} ({hit.source})")
        results[mode] = ranks
        library.close()
    print(f"{len(questions)} questions, first {args.limit} results")
    print(f"{'mode':8} {'hit@1':>6} {'hit@3':>6} {'hit@8':>6} {'MRR':>6}")
    n = len(questions)
    for mode, ranks in results.items():
        hit = lambda k: sum(1 for r in ranks if r and r <= k) / n  # noqa: E731
        mrr = sum(1 / r for r in ranks if r) / n
        print(f"{mode:8} {hit(1):6.2f} {hit(3):6.2f} {hit(args.limit):6.2f} {mrr:6.2f}")
    if len(results) == 2:
        keyword, both = results.values()
        for item, a, b in zip(questions, keyword, both):
            if a != b:
                print(f"  {a or '-':>2} -> {b or '-':<2} {item['q']}")


if __name__ == "__main__":
    sys.exit(main())
