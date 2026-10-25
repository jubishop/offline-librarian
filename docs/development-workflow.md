---
status: current
---

# Development workflow

This page records this project's own commands and integrations. Shared rules
are in the [foundation pages](foundation/README.md).

## Setup

```sh
bin/setup
bin/doctor
bin/check --full
```

Setup needs Git and Python 3.9 or later, and checks also need ShellCheck.
`bin/setup` then runs `bin/setup-application`, which needs
[uv](https://docs.astral.sh/uv/) and `pdftotext` (poppler) and installs the
application's Python and packages into `.venv` from `uv.lock`.
QMD and direnv are optional; setup reports skipped features. Install td and
run `td init` as described in [task tracking](foundation/task-tracking.md).
Create `.envrc` only when the project needs environment settings, and review
it before running `direnv allow`; search does not need it.

## Checks

Follow the [check schedule](foundation/engineering-policy.md#checks).
`bin/check --full` runs `bin/check-application` after the foundation checks.
It runs the unit tests in `tests/` with the standard library's `unittest` in
`.venv`, treating unclosed resources as errors:

```sh
bin/check-application
.venv/bin/python -B -m unittest discover -s tests -p 'test_kiwix*'   # some files
```

Tests that download run against a local web server, never the internet. Tests
that build write small books with libzim and PDFs by hand, and read the PDFs
with the real `pdftotext`. CI installs `poppler-utils` for it.

## Runtime and toolchain versions

The application requires Python 3.14 or later, declared in `pyproject.toml`
and checked by `librarian/__main__.py` before anything runs. `.python-version`
pins 3.14 rather than the newest Python: libzim 3.13.1, which reads the
Kiwix books, publishes wheels only up to 3.14 (checked on 2026-10-25). When
libzim publishes wheels for a newer Python, change `.python-version` to
`>=3.14` again. CI uses that file through uv, so it tests 3.14 until then.
`bin/librarian` and `bin/check-application` run `.venv/bin/python`, or the
interpreter in `OFFLINE_LIBRARIAN_PYTHON`. Foundation commands keep their
Python 3.9 or later requirement. See the
[version policy](foundation/engineering-policy.md#runtime-and-toolchain-versions).

## Deployment

Nothing deploys yet. When the project first deploys, describe how it deploys,
how nonfunctional changes skip deployment, and the manual override, following
the [deployment policy](foundation/engineering-policy.md#deployment-decisions).

## Project Starter

`.project-starter.json` records the installed Project Starter release and the
hashes of its managed files. Update them with Project Starter's `bin/sync`,
and record any intentional local change as an override with its reason.
