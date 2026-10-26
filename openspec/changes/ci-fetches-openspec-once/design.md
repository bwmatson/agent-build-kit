# Design

## What was checked, and where

Read-only: the kit's workflow file and sources at its main branch, and the log and annotations of the failing CI run (a CI run of the kit on
2026-10-15 UTC, the one this change is about).

- `.github/workflows/ci.yml` has three jobs (`pre-commit`, `test`, `integration`). `integration` sets up node 22, python 3.12 and uv, then runs
  `uv run --group dev pytest -m integration`. Nothing installs OpenSpec. The comment on the job says the tests run the real CLI through `npx`, pinned in
  `settings.py`.
- `openspec.command()` returns `openspec.command` from the active configuration when set, and otherwise
  `["npx", "--yes", f"{PACKAGE}@{settings.openspec_version}"]`, with `PACKAGE = "@fission-ai/openspec"` and `openspec_version` a setting in `settings.py`
  (`ABK_`-prefixed, so an environment variable can change it). `openspec.run` calls it with `check=False` and never raises on a status.
- The tests that run the CLI: `test_untouched_failure_change_validates.py` and `test_flake_fix_change_validates.py` (`openspec.run(["validate", ...])`),
  `test_scheduled_e2e_change_validates.py` (`abk check`, which runs the same validate) and `test_init_end_to_end.py` (`openspec init`, then
  `openspec.validate`). Three more integration files only write `openspec/<redacted>` and drive a real agent; they are not in scope.
- The failing log: `Process completed with exit code 1`, `5 failed, 6 passed in 106.52s`. `sh: 1: openspec: not found` with return code 127 in the
  untouched-failure test, the same text inside `abk init: openspec init failed`, `assert 1 == 0` in the `abk check` tests, and `Failed: test exceeded the
  time limit of 60 seconds` in the flake-fix test. No line of the job starts with `npm ERR`.
- The same run's other jobs: `Failed to restore: Cache service responded with 400` in all three, and `Failed to save: <h2>Our services aren't available
  right now</h2>` in two. GitHub's own service was failing at that time. The run before and the run after on main passed.

UNVERIFIED: why `npx` reported `openspec: not found`. The usual cause of that text is that `npx` resolved the package into its cache but the binary link
was absent, for example after an interrupted install; it was not reproduced, and no `npm ERR` line confirms it. The design below is right whichever the
cause, because every cause is a failed or partial fetch.

## Choice: warm `npx`'s own cache, no new wiring

Three ways to make the fetch happen once were weighed.

**Recommended: (a) a warm-up step that runs the very command the tests run.** `npx --yes <package>@<pin> --version` fetches the package into `npx`'s
cache (under the runner's home), so the later `npx --yes <package>@<pin> validate ...` in a test finds it. The tests and `openspec.command()` are
unchanged: no setting, no environment variable, no `abk.yaml` entry, no new path to keep in step. It retries, it has a timeout of its own, and it
runs `--version` so it also proves the binary starts, which is exactly what failed.

**(b) `npm install --global <package>@<pin>` and point `openspec.command` at `openspec`.** The binary is then a plain executable and `npx` is out of the
path. It needs a way to hand the command to the tests: a new `ABK_`-prefixed setting that `command()` reads, documented in `docs/configuration.md` and
the changelog, or an `abk.yaml` fixture in each test. That is a framework surface added for a CI wobble. Rejected for now; it is the next step if (a) proves
not to be enough.

**(c) Cache npm's download cache with the setup-node `cache` input or `actions/cache`.** Rejected: setup-node's `cache: npm` needs a lock file and this repo has no
root `package.json`; a hand-keyed `actions/cache` adds a dependency on the same cache service that was failing in the incident, to save one small fetch
per run. One fetch per run, retried, is cheaper and has no extra failure mode.

UNVERIFIED: that a later `npx --yes <package>@<pin> ...` in another step reuses the entry the warm-up step created. It is how `npx` is documented to
behave (the cache entry is keyed by the package specs), and both steps run as the same user with the same home, but it was not run. The builder checks
it locally: warm with the script, then run `npx --yes --offline <package>@<pin> --version`; if that fails, the warm-up does not help and design (b)
becomes the task.

### The single source of the pin

The step does not spell the package or the version. It asks Python for them:

```
uv run --group dev python -c "from agent_build_kit.openspec import PACKAGE; from agent_build_kit.settings import settings; print(f'{PACKAGE}@{settings.openspec_version}')"
```

and passes the printed spec to the script as its one argument. A bump of `openspec_version` in `settings.py` therefore reaches CI with no other edit. A
unit test asserts that neither the package name nor the version string appears in the workflow or the script, and that the step runs the command above
(through `PACKAGE` and `settings`), so a hand-copied pin fails a test. UNVERIFIED: that `settings` reads no `.env` that would change the version in CI;
the file is not present in a checkout, so it reads the default.

### The warm-up script

`.github/scripts/warm-openspec.sh <spec>`, run with `bash -e`:

1. Up to 3 attempts. Each runs `timeout 120 npx --yes "$spec" --version`; a status of 0 ends the script with 0.
2. After a failed attempt it removes the `_npx` directory of npm's cache, where `npx` keeps its installed packages, and waits `OPENSPEC_RETRY_DELAY` seconds
   (default 10, multiplied by the attempt number; a test sets 0). It prints the attempt number and the error each time.
3. When the last attempt fails it prints one line, `the OpenSpec CLI is not installed: <spec> could not be fetched in 3 attempts`, with the GitHub
   `::error::` prefix, and exits 1.

Three attempts, two minutes each, is the bound: the step cannot run past about seven minutes, and the step's own `timeout-minutes: 10` is the backstop.
It lives in a script file and not inline in the YAML so a test can run it with a fake `npx` on `PATH`.

A GitHub outage that stops the package registry is not helped by retrying; the job then fails at this step, with the one message, before any test runs.
That is the intended outcome: a clear, early failure of one step instead of five tests.

## The tests say it once

`tests/openspec_cli.py` holds two functions and the message:

- `probe(run)` runs `openspec.run(["--version"], cwd=<a temporary directory>)` once. A status of 0 returns. An `OSError` (no `npx` on `PATH`) or any
  other status fails with `the OpenSpec CLI is not installed`, then the status and the last 5 lines of stderr.
- `require(result)` returns a `CompletedProcess` unchanged, unless its status is 127, which fails with the same message. A status of 1 from `validate`
  is the thing under test and stays an assertion in the test.

`tests/integration/conftest.py` has a session-scoped fixture `openspec_cli` that calls `probe`. The four files add
`pytestmark = [..., pytest.mark.usefixtures("openspec_cli")]` and pass their `openspec.run` and `abk check` results through `require`. A fixture that
fails once fails every test that requests it with the same text, so the run shows one reason four times (or five, counting both tests of a file), not
five different ones. It does not stop the session: the other integration tests do not need the CLI and still run.

Fail, not skip, because a skip would let main go green with the CLI test coverage gone; the existing `skipif(shutil.which("npx") is None)` on these
files stays, and is the one case a machine without node reports as skipped.

The probe is subject to the same 60-second limit as any test setup (the limit applies to each of setup, call and teardown); with the step above having
fetched the package, it takes a second. The limit is not raised.

UNVERIFIED: that the limit applies to a session fixture's first use in the way described. The builder reads `tests/time_limit.py` and, if a session
fixture's first call is charged to the first test, keeps it under the limit with the timeout the probe passes to `openspec.run`'s runner.

## How to verify

The tests cannot run CI. A person opens the first main run after the change and checks that the `integration` job has a step that fetches OpenSpec and
that its log shows one attempt, and that the test step's log shows no download of the package. The next transient failure of GitHub's services should end
in that step with the one message, before any test, and not in five tests with five messages.

## No changelog

`AGENTS.md`'s changelog rule is for a change that someone using the tool sees. This one changes a workflow, a script and tests; no `CHANGELOG.md`
entry, no change to `docs/`. The one sentence in `AGENTS.md` ("Running") says what the integration job does before its tests.

## Overlap with the sibling change

`ci-runs-without-warnings` edits `.github/workflows/ci.yml` as well (action versions and the runner label). The two touch neighbouring lines of the
integration job, so whichever is built second may need a rebase; neither depends on the other, and each leaves the other's lines as they are.

## Not included

A retry of the whole job, a `retry` action from the marketplace, installing OpenSpec globally (design b), a cache of npm's download directory, changing the pin or the
60-second limit, and any change to `openspec.py`.
