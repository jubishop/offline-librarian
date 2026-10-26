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
bin/librarian ask "someone is shivering and confused after being in the cold"
```

`ask` searches the library first, then has a local Ollama model answer from
the passages it found, citing them by number, and lists the sources it cited.
The model and thinking follow your pi settings (`~/.pi/agent/settings.json`):
pi's default model when pi uses Ollama, otherwise `qwen3.8:27b-mlx`, with
thinking unless pi's level is off. `--model` and `--think on|off` override
them. When the library has nothing on a question, the answer says so and
labels its general answer as from memory.

`embed` gives every passage an EmbeddingGemma vector through
[Ollama](https://ollama.com), with `embeddinggemma-2:270m-bf16-text` unless
`--model` names another. The whole library takes about three days. It
embeds the official and clinical sources first (Ready.gov, MedlinePlus, CDC,
NHS, WikEM, the manuals), about an hour and a quarter, then the rest from
smallest to largest; Wikipedia, 87% of the passages, comes last. Vectors
are keyed by the passage's text, so text that appears again, in another book
or a new edition, is never embedded twice. Until a passage has a vector, it is
found by keyword only. `search` uses the vectors whenever they exist, and says
so when Ollama can't be reached and it falls back to keywords. Ollama's address
comes from `OLLAMA_HOST`, as for Ollama itself.

To run it in the background instead, install the worker from this checkout (as for `serve install`, the
launch agent runs the code it was installed from):

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

## Keep it current

```sh
bin/librarian update install   # on the 1st of each month at 3:00
bin/librarian update           # or now
```

`update` fetches newer Kiwix editions of the books you have, rebuilds only
those books, and deletes the superseded files. The embedding worker then
embeds whatever text is new; text that hasn't changed keeps its vectors. It
runs at Background priority, and launchd runs a missed month when the Mac
next wakes. Problems are sent through Pushover.

## Use it in a browser

```sh
bin/librarian serve install   # always running, from login on
bin/librarian serve status    # and the addresses to open
bin/librarian serve           # or just run it here until Ctrl-C
```

The page is at `http://localhost:8740/` on this Mac and at
`http://<name>.local:8740/` or the Mac's address from any device on the same
Wi-Fi, or on Tailscale when it is connected. There is no password. It asks
(answers stream in, cited, with follow-up questions), searches without the
AI, and opens any cited article with the passage highlighted. Conversations
are saved on the Mac in `history.sqlite`, shared by every device that opens
the page.

The server only answers requests addressed to this Mac's own names and
addresses, and only takes questions as JSON from its own page, so other web
pages can't use it through your browser. The page loads nothing from the
internet. If the server crashes and launchd restarts it, it says so through
Pushover, at most once an hour.

## Use it from pi

The [pi](https://github.com/badlogic/pi-mono) skill in
`skills/offline-librarian` has pi's model search the library before every
answer, read whole articles when the details matter, and cite what it used.
Link the skill into pi and the command onto your PATH from this checkout:

```sh
ln -s "$PWD/skills/offline-librarian" ~/.pi/agent/skills/offline-librarian
ln -s "$PWD/bin/librarian" ~/.local/bin/librarian
```

pi offers the skill for matching questions; `/skill:offline-librarian
QUESTION` forces it. It is meant for pi with a local model, which keeps
working when cloud-based assistants can't.

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
