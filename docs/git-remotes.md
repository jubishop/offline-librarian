---
status: current
---

# Git remotes

New hosted projects use their primary host, normally GitHub, as `origin`.
Honor explicit choices for other hosting arrangements. Adoption records this
project's actual URL below in place of the `your-account/your-project`
placeholder. Preserve existing custom settings.

| Remote | URL |
| --- | --- |
| `origin` | `git@github.com:jubishop/offline-librarian.git` |

Set up the primary repository as `origin` using the requested visibility.
Complete the initial commit and required checks before publishing it. Prefer
SSH URLs for GitHub: HTTPS pushes that change workflow files need a token with
the `workflow` scope.

A fresh clone needs no further remote setup: `origin` fetches from and pushes
to the primary host. Routine `bin/setup` stays local.
