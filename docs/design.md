---
status: current
---

# Design

Offline Librarian answers questions on this Mac with no internet. Every
question first searches a local library built from Kiwix and other offline
sources, by keyword and by meaning. A local Ollama model then answers from the
passages that search found, and every answer shows those passages and their
sources.

## Decisions

All of these were made by the user on 2026-10-25, while they evaluated
[Survival LLM](https://github.com/anonnerdfrenzy/survival-llm), an offline
survival assistant built on the same idea.

- **For one person, on one Mac.** There are no installers, Windows support,
  model picker, or self-updater. The user chose this over a public app or
  contributing upstream because it is much less work.
- **A library we build from Kiwix.** It uses Survival LLM's complete
  personal source list (see [Sources](#sources)) rather than Survival LLM's
  published downloads. A one-off build of about an afternoon was acceptable
  for control over the sources and independence from that project.
- **The code always searches first.** The model never decides whether to look
  something up. This follows Survival LLM issue
  [#1](https://github.com/anonnerdfrenzy/survival-llm/issues/1): in that
  project's committed eval logs, the models that answered best opened the
  library least. Nemotron 3.5 Super opened a relevant article for 4 of 22
  questions. Those logs predate a prompt change that asks models to look things
  up first, so the gap may be smaller there now, but searching in code
  removes the question.
- **Search by meaning over everything.** Every passage gets an EmbeddingGemma
  vector, alongside a full-text keyword index, so a question can reach the
  whole library by either route. The user accepted an index build of a couple
  of days, run in the background.
- **Three ways in.** A terminal command, a page in the browser, and a pi
  skill, all on one shared search-and-answer core. Answers default to
  `qwen3.8:27b-mlx`, the default model of the user's pi setup.
- **Public code, private library.** The repository is public under MIT. The
  library is never published or committed, since several sources forbid
  redistribution or commercial use.

## Sources

Survival LLM's full personal build, as listed in its `library/fetch_zims.py`,
`library/fetch_manuals.py`, `library/fetch_risk.py`, and `SOURCES.md`:

- **Kiwix ZIM files:** the zimgit collections (water, food preparation,
  medicine, knots, post-disaster), military medicine, NHS medicines, WikEM,
  CDC Travelers' Health, ten Stack Exchange sites, Appropedia, WikiMed,
  MedlinePlus with its licensed encyclopedia and drug pages, Ready.gov,
  iFixit, the USDA canning guide, WikiCiv, Energypedia, and Wikipedia's top
  one million articles. Gardenology is on Survival LLM's list but was missing
  from the Kiwix catalog on 2026-10-25.
- **PDF manuals:** U.S. military and FEMA survival and first-aid manuals,
  Nuclear War Survival Skills, the Emergency Response Guidebook, IFRC first-aid
  guidelines, and WHO emergency, childbirth, and drinking-water references.
- **Other files:** the 2018 wikiHow text dump, and U.S. government mortality
  statistics for estimating risks.

Survival LLM's code is MIT-licensed; any code copied from it keeps its
copyright notice.

## How a question is answered

1. Search the keyword index (SQLite FTS5, BM25) and the vector index
   (EmbeddingGemma, cosine similarity) for the question, and merge the two
   rankings.
2. Give the model the best passages, numbered, with their titles and sources.
3. Have it answer from those passages and cite them by number, saying plainly
   when the passages don't cover the question.
4. Show the answer with each cited passage, and let the reader open the full
   article.

The pi skill uses the same search command, and pi's own model writes the
answer.

## Measurements

These set the expected build times; recheck them when the build depends on
them.

| What | Result | Where and when |
| --- | --- | --- |
| Kiwix ZIM downloads for the list above | 32.5 GB, 28 of 29 files | Kiwix OPDS catalog, 2026-10-25 |
| Kiwix mirror speed | about 11.5 MB/s | Survival LLM's `fetch_zims.py`, measured October 2026 |
| Embedding speed | 53–61 passages of about 865 characters a second | `embeddinggemma-2:270m-bf16-text`, Ollama 0.40.10, M5 Pro, batches of 64, 2026-10-25 |
| Passages per article | 2,029,972 passages for 497,236 articles | Survival LLM's Essentials library, 2026-10-25 |

Survival LLM's Everything library installs at about five times the size of
Essentials (21.8 GB against 4.4 GB, from its `docs/library-packs.json`), which
suggests roughly 10 million passages for a library like ours. At the measured
speed, embedding them would take about two days. Faster embedding,
such as more parallel requests or running EmbeddingGemma through MLX
directly, has not been measured yet.

## Open questions

- How to make embedding faster, and how much it saves.
- Where the library lives on disk, and whether the ZIM files are kept after
  conversion.
- How to store and search about 10 million vectors quickly: a flat file
  searched with NumPy, or an approximate index.
- Which HTML-to-text converter to use: the standard library's parser, or lxml.
