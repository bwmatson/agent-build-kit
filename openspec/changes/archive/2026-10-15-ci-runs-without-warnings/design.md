# Design

## What was checked, and where

Read-only, against the log and annotations of a CI run of the kit on 2026-10-15 UTC (the run that failed its `integration` job), the kit's workflow and
sources at its main branch, and the release notes and `action.yml` files of the four actions at GitHub.

- Annotations of the three jobs: the Node 20 warning (the `integration` job lists four actions, the other two three), the cache warnings (restore in all
  three, save in two) and the notice that `ubuntu-latest` will move to Ubuntu 26 beginning October 19, 2026 (completing by November 19, 2026, per the
  runner-images announcement). The `punycode` `DEP0040` line appears under each of the four actions' setup steps and under the post steps of setup-uv
  and setup-python, in all three jobs.
- The job's own facts: runner image `ubuntu-24.04` (image version 20261012), runner version 2.337.0, Python 3.12.15, uv 0.13.1 installed by setup-uv.
- The `test` job's warnings summary: "8756 passed, 1 skipped, 6 warnings", the six being the six parametrizations named in the proposal.
- `.github/workflows/ci.yml`: three jobs, each `runs-on: ubuntu-latest`; `actions/checkout@v4`, `actions/setup-python@v5` with `python-version: "3.12"`,
  `astral-sh/setup-uv@v3` with `enable-cache: true`, and in `integration` `actions/setup-node@v4` with `node-version: "22"`. No other workflow file.

## The versions

Latest releases at the time of writing (2026-10-15), each with `using: node24` in its `action.yml` at that tag:

| Action | Written today | Node 24 since | Latest | `action.yml` runtime |
|---|---|---|---|---|
| `actions/checkout` | `@v4` | v5.0.0 | v7.0.1 (2026-07-20) | node24 |
| `actions/setup-node` | `@v4` | v5.0.0 | v7.1.0 (2026-10-08) | node24 |
| `actions/setup-python` | `@v5` | v6.0.0 | v7.0.0 (2026-07-20) | node24 |
| `astral-sh/setup-uv` | `@v3` | v7.0.0 | v10.3.0 (2026-10-09) | node24 |

All four need a runner of at least 2.327.1; the run's runner was 2.337.0.

### Breaking changes read from the release notes, and what each means here

**actions/checkout.** v5: node24, runner 2.327.1 or later. v6: credentials are persisted to a separate file instead of `.git/config`; nothing in the
three jobs pushes or fetches over an authenticated remote after checkout (UNVERIFIED: the builder greps the tests for a real remote). v7: refuses to check
out a fork's pull request for `pull_request_target` and `workflow_run`; the workflow triggers on `pull_request` and `push` only. No input is used.

**actions/setup-node.** v5: caches automatically when `package.json` has a `packageManager` field (`package-manager-cache: false` turns it off); v6 limits
automatic caching to npm; v7 moves to ESM and adds cache outputs. The repository's root has no `package.json` (the web UI's is under `web/`), so no
automatic caching applies; the only input used is `node-version`.

**actions/setup-python.** v6: node24, and reads `.python-version` and `Pipfile` more; v7: removes the `pip-install` input. The workflow gives
`python-version: "3.12"` and no other input, so nothing applies.

**astral-sh/setup-uv.** v4: fails when caching is on and there is nothing to upload (the uv cache directory is missing); every job runs `uv sync` or
`uv run` first, which creates it (UNVERIFIED for the post step; the builder reads the first run's log, and sets `ignore-nothing-to-cache: true` only if it
fails). v5: `enable-cache` defaults on for GitHub-hosted runners. v6: new default `cache-dependency-glob` (one cache invalidation) and `activate-environment`
and `working-directory` inputs. v7: node24. v8: **no more major or minor tags** (`@v8` does not exist; the repository's tag list has `v10.0.0` to
`v10.3.0` and no `v10`), and the old `manifest-file` format removed. v9: `prune-cache` defaults to false, so the cache may be larger. v10:
`enable-cache: auto` disables caching for `pull_request_target`, `workflow_run` and `release`; the workflow sets `enable-cache: true` explicitly and uses
neither event. The input `enable-cache: true` is still accepted. Nothing else the workflow sets changes meaning.

### Why exact release tags

The kit has no stated policy on pinning actions: `AGENTS.md` pins only dependencies it installs, and nothing in its docs or its improve-track prompts
mentions workflow actions (the dependency-update prompt scans Docker, npm, Python and pre-commit dependencies; UNVERIFIED that the `dependency-update-check`
skill it calls does not also read workflow files, since only its description was seen). The choice is therefore made here.

**Recommended: the full release tag, `@vX.Y.Z`, for all four.** A floating major (`@v7`) is the habit that left four actions on Node 20 for a year, and
it is impossible for setup-uv, which stopped publishing major tags at v8 and recommends an immutable release or a commit. One written form for every
action is one test. Three of the four releases are marked immutable at GitHub (setup-node, setup-python, setup-uv); `actions/checkout` v7.0.1 is not
(its release has `immutable: false`), so its tag could in principle be moved.

**A full commit SHA with the tag in a comment** is the stronger form and costs a person a lookup per bump. It is accepted by the test, so a person who
wants it for `actions/checkout` can use it, but it is not required: this repository's workflow runs no secrets and publishes nothing, and the bump
process (below) is a human edit either way. The commits of the four exact tags, resolved for this change, are `3d3c42e5aac5ba805825da76410c181273ba90b1` (checkout v7.0.1),
`949feb2413d6458794dcd2491c4babbbce0c15c1` (setup-node v7.1.0), `5fda3b95a4ea91299a34e894583c3862153e4b97` (setup-python v7.0.0) and
`1c37ad07a6a961277cf70c0d37d6f313000f5884` (setup-uv v10.3.0); they are given for reference and not used.

A bump is a deliberate edit of a version in the workflow and of the minimum in the test's table (when a new action is added), with the release notes read,
as this change did. Nothing bumps them automatically: if the kit wants that, a Dependabot configuration for `github-actions` is a separate decision.

### The runner

`ubuntu-24.04` in all three jobs. The alternative was to test on Ubuntu 26 now (`ubuntu-26.04`). The announcement says Ubuntu 26.04 differs in kernel
(7.0 against 6.17) and systemd (259 against 255), and warns that workflows relying on 24.04-specific libraries or prebuilt binaries may be affected; the
suite spawns processes and uses `flock` and sockets, so it is exposed to exactly that kind of difference, and a surprise on October 19 would land on
main's status with no change in the diff. Pinning removes the surprise. Moving to 26 is then its own change, run once on a branch, and has a reason in its
title. UNVERIFIED: whether the suite passes on Ubuntu 26.04; it was not run there.

## The `punycode` warning

`DEP0040` is printed by Node when an action's bundled code loads the built-in `punycode` module, and it appears under the steps of the four actions. The new
releases moved to ESM and updated their dependencies, which is the usual cause of the module no longer being loaded; UNVERIFIED that it goes. A builder
verifies from the first run after the change: `grep -c DEP0040` in the run's log is 0 for every job. If a line remains it sits under the step of one named
action (the log prefixes each line with the step name), which says which release still carries it; that is then a note for that action's repository, not a
reason to fail this change.

## The cache warnings are GitHub's

`Failed to restore: Cache service responded with 400` and `Failed to save: <h2>Our services aren't available right now</h2>` are printed by the cache client
inside setup-uv when GitHub's cache service is unavailable, in the run that was failing for a GitHub-side reason. The repository does not cause them and
cannot fix them, and the jobs continued past them (they are warnings, and the job `test` passed). They are recorded here as expected during a GitHub
incident and are not asserted away.

What was read to see whether a setting could make an outage a silent skip, from the `action.yml` of setup-uv v10.3.0: the cache inputs are
`enable-cache` (`true`, `false`, `auto`), `restore-cache`, `save-cache` (`true`, `false`, `auto`), `cache-dependency-glob`, `cache-suffix`,
`cache-local-path`, `prune-cache`, `cache-python`, `ignore-nothing-to-cache` and `ignore-empty-workdir`. None turns a service error into silence:
`restore-cache: false` and `save-cache: false` stop the action from calling the service at all, which removes the warning on a bad day by also removing
the cache on every good one (a slower run each time, to hide a notice that appears rarely), and `ignore-nothing-to-cache` is about an empty cache
directory, not an unavailable service. `continue-on-error` does not apply: the warning is not a failing step. `actions/setup-node` has no cache input in
use (`cache` is not set), and `actions/setup-python` has none either. The settings are therefore left as they are, and a cache outage stays a warning and
never a failure, which is what was asked.

## The serializer warning

### What it is

`tests/graph/test_held_state_plain_text.py` reads what the nodes of a held unit wrote from the checkpoint file (`node_updates`), copies the values onto a
fully populated `UnitRun` with `model_copy(update=...)`, and runs the result through the real serializer (`blocked_on_load`). `model_copy` does not
validate, and the values it copies come from the graph's `__start__` write, where LangGraph stores the input as plain lists: a probe in a copy of the
kit's sources showed `__start__ groups list [1]`, `deferred list []` and `commits list []`. The state therefore holds lists in tuple fields, and pydantic's
serializer warns each time it dumps it. The warning reproduces locally with `pytest -W default tests/graph/test_held_state_plain_text.py -k populated_state`
(it is the same six parametrizations).

So the lists come from the test building a state by copying, not from a node returning the wrong type: the nodes' own updates, which the sibling
tests in that file check, hold what they should. UNVERIFIED: that no production path puts a list in a tuple field of `UnitRun`; the builder reads where
the state is built for `invoke` and `__start__` and says so in the commit.

### Overlap with `checkpoint-plain-values`

`checkpoint-plain-values` (priority 4, already built) makes the held state a string and adds the test file this warning appears in. Its tasks and spec
are about the **held state being an enum the checkpoint blocks**, and about the allowed list; they say nothing about tuples or lists. The warning is a
by-product of the test that change added (`populated(UnitRun).model_copy(update=...)`), so the change does not cover it, and this one does not
duplicate any of its requirements: it adds a requirement about the state a test builds. The request that led to this change expected `checkpoint-plain-values` to cover the warning, and it does not. Its unit is already built, so raising its
priority from 4 would change nothing; the user does not need to. The fix is this change's group 2, which edits only files that exist.

### Overlap with `tests-run-without-warnings`

`tests-run-without-warnings` (priority 4, already built) turns one warning (the multi-threaded fork) into a failure through the plugin
`tests.fork_warning_guard`, because CPython drops the exception a `filterwarnings = error` entry would raise for that warning, and it left a blanket
`error` policy for later. The same pattern applies, with one difference: pydantic's warning is emitted from its Rust serializer through the warnings
module, so a `filterwarnings` entry may or may not turn it into an exception. This change therefore does both: it adds the scoped entry
`error:Pydantic serializer warnings:UserWarning` to `[tool.pytest.ini_options]`, and a test that proves, with `pytester`, that a test dumping a model with a
list in a tuple field fails under it. If the entry does not make it fail (UNVERIFIED), the builder uses the plugin form `fork_warning_guard` uses and the test
stays the same. It is scoped by message so it is not the blanket policy that change deferred. UNVERIFIED: that no other test in the suite raises this
warning; the CI summary shows only these six, and the builder runs the whole suite with the entry in place.

Local runs on Python 3.14 also print `ResourceWarning: unclosed database` for the same tests (five, from SQLite connections that the test helpers leave
open). The CI run (Python 3.12) does not show them, so they are outside this change; they would be the next warning if the suite moves to 3.14.

## The guard test

`tests/test_ci_workflows.py` parses each `.github/workflows/*.yml` with the kit's YAML reader, walks every job's `steps` and its `runs-on`:

- A table maps each action the kit uses to the first major that runs on Node 24 (`actions/checkout` 5, `actions/setup-node` 5, `actions/setup-python` 6,
  `astral-sh/setup-uv` 7). A reference below its minimum fails naming the file, the job and the step. An action absent from the table fails with
  "add `<action>` to the table with the first major that runs on Node 24", so a new action is a conscious entry and not a silent pass.
- A reference must be `owner/name@vX.Y.Z` or `owner/name@<40 hex>`: a floating major, a branch and `latest` fail. A local action (`./...`) and a
  `docker://` reference are skipped.
- `runs-on` as a string, a list or a matrix value must not end in `-latest`, and the three jobs must name `ubuntu-24.04`. The table of allowed runner
  labels is one constant, so a move to Ubuntu 26 is a one-line edit and a deliberate one.
- A `uses` and a `runs-on` that are expressions (`${{ ... }}`) fail, because the test cannot read them; the workflow has none today.
- The failure message ends with "see AGENTS.md, CI workflows", and a second test asserts that heading exists.

## No changelog

`AGENTS.md`'s changelog rule (read for this change) is for a pull request "that changes what someone using the tool sees". A workflow, a test and a
pytest option change nothing the tool does for anyone. No `CHANGELOG.md` entry; the policy goes in `AGENTS.md`, which is the doc agents and builders read.

## How to verify

CI cannot be run inside a test. A person opens the first main run after the change and checks that no job has an annotation other than GitHub-side ones:
no "Node.js 20 is deprecated" warning, no "ubuntu-latest will migrate" notice, no `DEP0040` line under any step (`gh run view <id> --log | grep -c
DEP0040` prints 0), and no "Pydantic serializer warnings" in the `test` job's summary, which should end with `0 warnings`. The cache-service warnings may
still appear during a GitHub incident and are not a failure of this change. `gh api repos/<repo>/check-runs/<job id>/annotations` lists the annotations
of one job.

## Overlap with the sibling change

`ci-fetches-openspec-once` edits the same workflow file in the `integration` job (a step) and `AGENTS.md`. The edits are on neighbouring lines; whichever
is built second may need a rebase. Neither depends on the other.

## Not included

Dependabot or any automatic bump of actions, a `-W error` policy for the whole suite, Ubuntu 26, the `ResourceWarning`s of Python 3.14, and any change to
the cache settings.
