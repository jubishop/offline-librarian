---
name: pool-workers-keep-their-own-environment
description: On Linux CI, multiprocessing workers don't see a test's later os.environ patches, so check environment-dependent conditions in the parent.
type: reference
---

# Pool workers keep their own environment

On Linux, Python 3.14's multiprocessing defaults to the forkserver start
method. Workers fork from a server process that keeps the environment, such
as `PATH`, from when the first pool started it. A test that patches
`os.environ` after an earlier build has run a pool changes only the parent.
macOS uses spawn, which reads the current environment, so such a test can pass
locally and fail in CI.

Check environment-dependent conditions in the build's own process before
starting workers, as `build._articles` does for `pdftotext`. To reproduce CI
locally, run the test under `multiprocessing.set_start_method("forkserver")`.

Evidence: on 2026-11-01 the first CI run of jubishop/offline-librarian#21
failed this way on a test that hid `pdftotext` by patching `PATH`.
