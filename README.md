# Offline Librarian

Ask questions offline from a local Kiwix library. Every question searches all
of it, by keyword and by meaning with EmbeddingGemma, and a local Ollama model
answers from the passages it found, showing each source. Use it from the
terminal, a browser page, or a pi skill.

It needs macOS or Linux, [uv](https://docs.astral.sh/uv/), and `pdftotext`
from poppler. Run `bin/setup` once to install its Python and packages. It is
being built in stages; see the [design](docs/design.md). So far it downloads
the books, builds the library, and searches it by keyword and by meaning:

```sh
bin/librarian fetch                    # every book, about 32 GB
bin/librarian build                    # text and keyword index
bin/librarian embed                    # meaning index; needs Ollama, takes days
bin/librarian search "how much bleach per gallon of water"
bin/librarian read 1234                # the article a passage comes from
```

`embed` gives every passage an EmbeddingGemma vector through
[Ollama](https://ollama.com), with `embeddinggemma-2:270m-bf16-text` unless
`--model` names another. The whole library takes about three days. Vectors
are keyed by the passage's text, so text that appears again, in another book
or a new edition, is never embedded twice. Until a passage has a vector, it is
found by keyword only. `search` uses the vectors whenever they exist, and says
so when Ollama can't be reached and it falls back to keywords. Ollama's address
comes from `OLLAMA_HOST`, as for Ollama itself.

To run it in the background instead, install the worker from this checkout:

```sh
bin/librarian embed install    # a launch agent; starts now and at every login
bin/librarian embed status     # progress, rate and time left
bin/librarian embed pause      # and resume
bin/librarian embed uninstall  # vectors made so far are kept
```

The worker runs at macOS's Background priority and waits whenever Ollama has
another model loaded, such as Qwen in pi, so chat keeps the GPU. It waits out
an unreachable Ollama, keeps the index current after later builds, and sends
a Pushover notification (with the keys in `~/.env`) when the first full pass
finishes or a pass fails. Builds and embedding from the terminal also run at
Background priority.

The library lives in `~/.local/share/offline-librarian`, or in
`$OFFLINE_LIBRARIAN_HOME` when that is set: the books in `zim/`, the
articles and their keyword index in `library.sqlite`, and the meaning index in
`vectors.f16` and `vectors.sqlite`, with the worker's logs beside them. Run `fetch` again to
resume an interrupted download; each file is checked against its SHA-256
before it is kept. Run `build` again after fetching newer books; it rebuilds
only the books whose file changed, plus any named with `--rebuild`, such as
`build --rebuild wikipedia`. `search --json` prints whole passages for
other programs.

Some of the conversion code is adapted from
[Survival LLM](https://github.com/anonnerdfrenzy/survival-llm), under its
[MIT License](LICENSE.survival-llm).

Offline Librarian is released under the [MIT License](LICENSE).

## Development

Run `bin/setup` after cloning; it needs Git and Python 3.9 or later. QMD and
direnv are optional, and setup reports skipped features. See the
[development workflow](docs/development-workflow.md) for this project's
commands and the [check schedule](docs/foundation/engineering-policy.md#checks)
for when to run `bin/check --documents-only`, `bin/check`, and
`bin/check --full`. The checks need ShellCheck; `bin/doctor` diagnoses setup.

Hosted projects record their primary remote in
[Git remotes](docs/git-remotes.md); `bin/setup` never publishes repositories.

## Knowledge

- [Memory](memory/README.md): durable guidance and non-derivable context.
- [Docs](docs/README.md): designs, decisions, research, and reference guides.
- [Task tracking](docs/foundation/task-tracking.md): install td, run `td init`
  in the primary checkout, and use `td status` or `td monitor` for progress.

Keep the existing issue tracker for shared work and link related issues from
td. This project uses [Project Starter](https://github.com/jubishop/project-starter);
`.project-starter.json` records its release.
