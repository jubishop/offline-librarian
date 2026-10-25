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
`bin/setup` then runs an executable `bin/setup-application`, when present, for
application dependencies such as `npm ci`.
QMD and direnv are optional; setup reports skipped features. Install td and
run `td init` as described in [task tracking](foundation/task-tracking.md).
Create `.envrc` only when the project needs environment settings, and review
it before running `direnv allow`; search does not need it.

## Checks

Follow the [check schedule](foundation/engineering-policy.md#checks).
`bin/check --full` runs `bin/check-application` after the foundation checks.
It runs the unit tests in `tests/` with the standard library's `unittest`,
treating unclosed resources as errors:

```sh
bin/check-application
python3 -B -m unittest tests.test_kiwix_fetch   # one test file
```

Tests that download run against a local web server, never the internet.

## Runtime and toolchain versions

The application requires Python 3.14 or later, declared in `pyproject.toml`
and checked by `librarian/__main__.py` before anything runs.
`.python-version` asks for the newest Python that meets that minimum. CI tests
3.14 and the latest stable release. `bin/librarian` and
`bin/check-application` run `python3`, or the interpreter in
`OFFLINE_LIBRARIAN_PYTHON`. Foundation commands keep their Python 3.9 or later
requirement. See the
[version policy](foundation/engineering-policy.md#runtime-and-toolchain-versions).

## Deployment

Nothing deploys yet. When the project first deploys, describe how it deploys,
how nonfunctional changes skip deployment, and the manual override, following
the [deployment policy](foundation/engineering-policy.md#deployment-decisions).

## Project Starter

`.project-starter.json` records the installed Project Starter release and the
hashes of its managed files. Update them with Project Starter's `bin/sync`,
and record any intentional local change as an override with its reason.
