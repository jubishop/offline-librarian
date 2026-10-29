# Project instructions

<!-- project-starter:begin -->
Project Starter manages this block; add project rules after it. Project rules
take precedence over this block and the foundation pages wherever they differ.

- Keep durable guidance and non-derivable context in [memory](memory/README.md),
  and designs, decisions, and research in [docs](docs/README.md). Before
  non-trivial work or writing memory, search with `bin/knowledge search "term"`
  or `bin/knowledge query "question" --no-rerank`, then read results with
  `bin/knowledge get <path> -l 80`. Markdown sources are authoritative.
- If configured QMD fails, tell the user immediately and attempt repair. If
  repair fails, pause knowledge-dependent work until the user approves a
  fallback; never silently substitute `rg` or direct reads. See
  [search failures](docs/foundation/knowledge-search.md#search-failures).
- Follow the [engineering policy](docs/foundation/engineering-policy.md):
  fewer dependencies, red-green tests for behavior changes, flaky tests fixed
  or filed as an issue right away, cohesive files and pages, checkout-isolated
  validation, and the latest stable toolchains.
- Deliver by [kind of change](docs/foundation/engineering-policy.md#kinds-of-change):
  commit text, such as Markdown and AI skill prose, directly on the default
  branch without checks; commit development code, such as tests, CI, and
  tooling, directly after its checks pass; and deliver production code through
  a pull request after its checks.
- Run [checks](docs/foundation/engineering-policy.md#checks) by change: the
  relevant checks while editing, and `bin/check --full` before merging or
  releasing production code unless an enforced CI gate runs it. Reuse passing
  results.
- Keep accepted decisions separate from proposals, preserve unrelated changes,
  and keep generated caches out of Git. Keep secrets out of public
  repositories only; a private one may commit them.
- Run `bin/setup` after cloning, `bin/doctor` to diagnose setup, and
  `bin/qmd-index` after uncommitted knowledge edits. Managed files listed in
  `.project-starter.json` change only through Project Starter or a recorded
  override with its reason.
<!-- project-starter:end -->

## Project

Offline Librarian answers questions offline from a local Kiwix library; see
the [README](README.md) and the [design](docs/design.md). Its command is
`bin/librarian`, `bin/setup` installs it into `.venv`, and
`bin/check-application` runs its tests; the
[development workflow](docs/development-workflow.md) has the details.

- Never commit library data, downloads, or indexes: several sources forbid
  redistribution.
- Tests never touch the internet: fake web servers stand in for Kiwix, Ollama
  and the document sites, and every test module imports `tests/offline.py`,
  which makes any other connection fail.
- Code adapted from Survival LLM keeps its notice and points to
  `LICENSE.survival-llm`.
- Install launch agents (`bin/librarian embed install`, `serve install`) only
  from the primary checkout: an agent runs the code it was installed from.
- Don't test `librarian ask`, `history add` or the browser page against the
  real library's history, since each saves to it: delete any test
  conversations afterwards with `bin/librarian history delete ID`.
