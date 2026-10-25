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
- **Embedding shares the Mac the way Stories' index does.** On 2026-10-25 the
  user chose to run `librarian embed` the way their Stories project runs its
  embedding index: as a per-user launch agent with the Background process
  type, which resumes after a crash, reboot or login, has pause, resume and
  status commands, and pauses while Ollama has any non-embedding model, such
  as Qwen, loaded. The user asked that it not slow down the computer; macOS
  can't lower the priority of Ollama's GPU work, so yielding to chat models is
  what protects interactive use. The tradeoff is a longer build, depending on
  how much the user chats.
- **Builds run at Background priority too.** On 2026-10-25 the user chose to
  run `librarian build` at macOS's Background priority, on the efficiency
  cores with throttled disk access, so a build isn't noticeable. The tradeoff
  is a slower full build, estimated at several times the hour it takes at
  normal priority; full builds are rare.
- **Survival LLM's converter, adapted.** On 2026-10-25 the user confirmed
  keeping the code adapted from Survival LLM (MIT, with its notice in
  `LICENSE.survival-llm`) rather than writing a new converter. Its lxml-based
  conversion already handles MediaWiki reference sections, Stack Exchange
  answers and their authors, zimgit's numbered PDFs, translated WikEM pages,
  and WikiMed articles repeated in Wikipedia. It is used without trafilatura,
  its heaviest dependency: a page with no main content falls back to its whole
  body. PDFs go through poppler's `pdftotext`.
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
3. Have it answer from those passages and cite them by number. When they
   don't cover the question, it says "The library doesn't cover this," then
   gives its best general answer, labeled as not from the library. The user
   chose this on 2026-10-25 over answering only from the library or asking
   first: in an emergency, some guidance beats none.
4. Show the answer with each cited passage, and let the reader open the full
   article.

In pi, the user chose on 2026-10-25 to have pi's own model write the answer:
the skill tells it to run `librarian search --json` before every answer, to
search again with other words when the passages fall short, to read whole
articles with `librarian read`, and to cite what it used. Follow-ups then work
as in any pi conversation. Searching depends on the model following the
skill, and `/skill:offline-librarian` forces the skill to load; `librarian ask`
and the browser page search in code.

The skill is installed for pi only, linked from `~/.pi/agent/skills`, not
shared through `~/.agents/skills` with the user's other harnesses. The user
chose this on 2026-10-25 because cloud-based harnesses such as Claude Code and
Codex won't be working when the library is needed.

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

## Implementation choices

These were made while building, not by the user, and can change.

- **The library lives in `~/.local/share/offline-librarian`** (or
  `$OFFLINE_LIBRARIAN_HOME`). The ZIM files stay after the build, so a source
  can be rebuilt without downloading it again.
- **One SQLite file.** Articles are stored compressed, passages are offsets
  into them, and the FTS5 index stores no text of its own. Each source is
  built in one transaction, and only rebuilt when its file changes.

## Open questions

- How to make embedding faster, and how much it saves.
- How to store and search about 10 million vectors quickly: a flat file
  searched with NumPy, or an approximate index.
