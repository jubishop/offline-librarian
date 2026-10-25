# Offline Librarian

Ask questions offline from a local Kiwix library. Every question searches all
of it, by keyword and by meaning with EmbeddingGemma, and a local Ollama model
answers from the passages it found, showing each source. Use it from the
terminal, a browser page, or a pi skill.

It needs macOS or Linux and Python 3.14 or later. It is being built in
stages; see the [design](docs/design.md). So far it downloads the library's
Kiwix books:

```sh
bin/librarian fetch          # every book, about 32 GB
bin/librarian fetch wikem_en_all
```

Books go to `~/.local/share/offline-librarian/zim`, or to `zim` inside
`$OFFLINE_LIBRARIAN_HOME` when that is set. Run it again to resume an
interrupted download: each file is checked against its SHA-256 before it is
kept.

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
