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

Follow the [check schedule](foundation/engineering-policy.md#checks). This
project has no application yet, so it has no `bin/check-application`, and
`bin/check --full` runs only the foundation checks. When application code
arrives, add `bin/check-application` and describe what it runs here.

## Runtime and toolchain versions

No application runtime is declared yet; the foundation tools under
[Setup](#setup) are the only requirements. When the project adds a runtime or
toolchain, list its minimum supported version and where it is declared,
following the
[version policy](foundation/engineering-policy.md#runtime-and-toolchain-versions).

## Deployment

Nothing deploys yet. When the project first deploys, describe how it deploys,
how nonfunctional changes skip deployment, and the manual override, following
the [deployment policy](foundation/engineering-policy.md#deployment-decisions).

## Project Starter

`.project-starter.json` records the installed Project Starter release and the
hashes of its managed files. Update them with Project Starter's `bin/sync`,
and record any intentional local change as an override with its reason.
