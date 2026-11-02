"""The retrieval test sets (docs/design.md#decisions): does search find the articles a good answer needs?

evals/questions.json is the test set of emergency, medical and how-to questions, whose answers are almost all from
official and clinical sources. evals/howto.json is the how-to set, whose answers are from wikiHow, Stack Exchange,
iFixit, Wikipedia and other sources without an authority boost. Each question lists [source key, title pattern]
pairs; a result counts when its article comes from that source and its title matches. Scores each set on its own,
keyword search alone and keyword plus meaning, against the real library, as hit@1, hit@3, hit@8 and mean
reciprocal rank over the first eight results.

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
from librarian.library import (  # noqa: E402
    AUTHORITY, FUSION_K, KEYWORD_WEIGHT, MEANING_WEIGHT, Library, by_authority, fuse)

LABELS = {s.label: s.key for s in [*sources.SOURCES, *sources.DOCUMENTS]}
SETS = {"test set": "questions.json", "how-to": "howto.json"}


def load():
    """Each set's questions, by name."""
    sets = {}
    for name, file in SETS.items():
        with open(os.path.join(ROOT, "evals", file)) as f:
            sets[name] = json.load(f)
    return sets


def scores(ranks, limit):
    """hit@1, hit@3, hit@limit and mean reciprocal rank, from each question's first-hit rank or None."""
    n = len(ranks)
    hit = lambda c: sum(1 for r in ranks if r and r <= c) / n  # noqa: E731
    return hit(1), hit(3), hit(limit), sum(1 / r for r in ranks if r) / n


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


# The current setting first, then its neighbors in authority, k and keyword weight, and the setting before meaning
# search weighed authority. The test set expects official and clinical sources almost exclusively, so stronger
# authority scores higher on it by construction; the how-to set shows what that costs other sources' answers, so
# weigh the two before changing a setting (docs/design.md#implementation-choices).
SWEEP = [(FUSION_K, KEYWORD_WEIGHT, MEANING_WEIGHT, AUTHORITY), (10, 0.5, 1, 0), (10, 0.5, 1, 0.15),
         (10, 0.5, 1, 0.5), (10, 0.5, 1, 1), (20, 0.5, 1, 0.3), (60, 0.5, 1, 0.3), (10, 0.25, 1, 0.3),
         (10, 0.75, 1, 0.3), (10, 1, 1, 0.3), (60, 0.75, 1, 0)]


def sweep(home, sets, limit):
    """Score several settings (k, keyword weight, meaning weight, authority) on each set, ranking each question once."""
    library = Library(os.path.join(home, "library.sqlite"), meaning=meaning.Meaning(home, meaning.Embedder()))
    lists = {}
    for questions in sets.values():
        for item in questions:
            keyword = [pid for pid, _ in library.keyword_ranking(item["q"])]
            lists[item["q"]] = (keyword, library.meaning_candidates(item["q"]))
    real = library.ranking
    print(" " * 31 + "".join(f"  {f'{name}, {len(questions)} questions':-^26}" for name, questions in sets.items()))
    print(f"{'k':>3} {'keyword':>8} {'meaning':>8} {'authority':>9}"
          + f" {'hit@1':>6} {'hit@3':>6} {f'hit@{limit}':>6} {'MRR':>6}" * len(sets))
    for k, keyword_weight, meaning_weight, authority in SWEEP:
        row = f"{k:>3} {keyword_weight:>8} {meaning_weight:>8} {authority:>9}"
        for questions in sets.values():
            ranks = []
            for item in questions:
                keyword, candidates = lists[item["q"]]
                order = fuse([(keyword_weight, keyword), (meaning_weight, by_authority(candidates, authority))], k)
                library.ranking = lambda query, order=order: order  # search's per-article and shared-text rules
                ranks.append(first_hit(library.search(item["q"], limit=limit), item["expect"]))
            row += "".join(f" {score:6.2f}" for score in scores(ranks, limit))
        library.ranking = real
        print(row)
    library.close()
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--modes", default="keyword,both", help="keyword, both, or keyword,both")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--verbose", action="store_true", help="show each question's top results")
    parser.add_argument("--check", action="store_true", help="only check that every expected article exists")
    parser.add_argument("--sweep", action="store_true", help="score several fusion weights and authority strengths")
    args = parser.parse_args()
    sets = load()
    home = cli.home()
    if args.check:
        return check(home, [item for questions in sets.values() for item in questions])
    if args.sweep:
        return sweep(home, sets, args.limit)
    results = {}  # mode -> set name -> each question's first-hit rank
    for mode in args.modes.split(","):
        found = meaning.Meaning(home, meaning.Embedder()) if mode == "both" else None
        library = Library(os.path.join(home, "library.sqlite"), meaning=found)
        results[mode] = {}
        for name, questions in sets.items():
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
            results[mode][name] = ranks
        library.close()
    for name, questions in sets.items():
        print(f"\n{name}: {len(questions)} questions, first {args.limit} results")
        print(f"{'mode':8} {'hit@1':>6} {'hit@3':>6} {f'hit@{args.limit}':>6} {'MRR':>6}")
        for mode, ranks in results.items():
            print(f"{mode:8}" + "".join(f" {score:6.2f}" for score in scores(ranks[name], args.limit)))
        if len(results) == 2:
            keyword, both = (ranks[name] for ranks in results.values())
            for item, a, b in zip(questions, keyword, both):
                if a != b:
                    print(f"  {a or '-':>2} -> {b or '-':<2} {item['q']}")


if __name__ == "__main__":
    sys.exit(main())
