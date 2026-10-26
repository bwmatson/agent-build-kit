# Design

## What was checked, and where

Read-only against `origin/main` of the agent-build-kit checkout; paths are under `src/agent_build_kit/` unless they start with `tests/`.

- `cli/pipeline.py`: `_nothing_started_reason` returns the deadlock report, the full-queue report, the failed-and-blocked line or the bare
  `nothing ready to build`; the tick calls it when the round starts nothing and the pause marker is not a rate-limit pause. A usage pause
  returns earlier, after printing `pause_line`. `wait_reasons` (the reasons from `_evaluate_round`), `_waits_in` and `_record_waits` (writes the
  decision log through `pipeline/wait_log.py`) exist; `WaitReason` is in `pipeline/vocabulary.py`. `_blocked_lines` prints blocked units with
  what they wait on.
- `tests/integration/test_graph_unit.py`: `Ticked(returncode, output)`, `tick()` (capture, output kept in memory), `commits_on_branch` (a bare
  `git log main..BRANCH`), a `Scratch` whose `env` is `repr=False`. `test_build_unit.py`: its own `Ticked` with timestamped lines, `output_of`,
  `run_log`, `who_pushed`, `pushed_commits`. `test_telemetry_stack.py`: its own `Ticked` and `run_tick`, which builds the scratch inside the helper.
- `tests/live_build.py` is not on `origin/main`. It exists on the unit branch of `tier2-tests-are-tagged-by-runtime/16` and has the guarded
  `pushed_commits`. This change builds on what main has.
- `tests/time_split.py`: wrappers around the setup, call and teardown hooks, `pytest_terminal_summary` printing `ABK-TIME` lines, the scratch found
  through `item.funcargs`. `tests/conftest.py` lists the plugins in `pytest_plugins`.
- `pipeline/run_log.py` and `redaction.py`: `redact_text(text, where=...)` replaces known secret values; `register(name, value)` adds a value to the
  active set.
- `pipeline/wiring.py` keeps the full output of an e2e-test run in a file and cuts what the result carries to `E2E_OUTPUT_CHARS` (4000), which
  `pipeline/e2e.py` puts under `## e2e-test results` with `**Full output:** <path>`, the failed tests and a digest of each.

## The tick says why it built nothing

`_nothing_started_reason` keeps its branches and their order. Only the last return changes: `nothing ready to build` is followed by one line per
candidate unit. A candidate is a stored unit in `planned`, `held` or `failed`; a unit in review, merged, closed or satisfied is not. The line is
`  <unit> (<repo>): <reason>` with `, waits on <ids>` when `Wait.waits_on` is set, the reason being the `WaitReason` value. Reasons come from
`wait_reasons` with nothing started and nothing building, the same call the decision log uses, so they cannot differ from what `abk status` and
the log say. A tick that is `--only` restricted lists only its own units, as `wait_reasons` already leaves out what `--only` leaves out.

Bound: 10 units, a constant beside `_blocked_lines`, not a setting (a setting for a log line is more to document than it saves). The units shown are
in stored order, after those whose reason is `ready`, `slot`, `lease` or `backoff` (the ones a person can act on soonest). The rest is `  (+M more)`.
If computing the reasons raises, the tick prints the bare line alone and notes the failure on one line; a report line never fails a tick.

The first line stays `nothing ready to build`, exact, because tests, the status page and people grep for it. The usage-pause path is untouched: the pause line already
names the cause there. The reasons are the same lines the decision log gets, so there is one wording.

## One tick helper

New module `tests/scratch_tick.py` (the name does not collide with `live_build.py` or `runtime_scratch.py`):

- `TickResult` (pydantic, frozen): `returncode`, `lines` as `(seconds, text)`, `started`, `ended`, and a computed `output`. It replaces the three
  `Ticked` types.
- `run_tick(scratch, *, timeout=3600)` runs `abk tick` with `cwd=scratch.planning`, `env=scratch.env`, stdout and stderr merged, stamping lines as
  they arrive (the build test's reader thread). It records the result in a module-level registry keyed by the scratch's state directory and keeps
  the last three per scratch.
- `scratch_env_summary(env)` lists names with values for names that do not look secret (`TOKEN`, `KEY`, `SECRET`, `PASSWORD`, `CREDENTIAL`, `AUTH`) and
  names alone for those that do, each value passed through the redactor.
- `register_scratch(scratch)` puts a scratch in the registry so the dump finds it when it is not a fixture argument (the telemetry helper builds
  its scratch inside the test).
- `commits_on_unit_branch(scratch, branch, tick)` runs `git log main..<branch>` on the remote; on a missing branch it fails with: a first line of
  cause hints, the tick's return code and output, the per-unit reasons, the tail of the run log, the pause marker and who pushed.

A scratch is anything with `planning`, `remote`, `state`, `env` (a `Protocol`), so the three files keep their own `Scratch` classes and their own
setups. Merging the three setups is not done here.

## The dump

New plugin `tests/scratch_dump.py`, listed in `tests/conftest.py` beside `tests.time_split`. A `pytest_runtest_makereport` wrapper adds a section
named `SCRATCH STATE` to the report of any call, setup or teardown that failed, for a test marked `local_stack` that has a scratch.

Placement. Three places were weighed. `tests/time_split.py` is about time and reads one fixture (the ledger path); the dump reads a dozen sources
and would turn it into two plugins in one file. `tests/conftest.py` holds the plugin list and shared fixtures, and a hook there would be
neither importable for a `pytester` test nor easy to find. A module of its own is chosen: it is tested by `pytester`, and conftest only lists it.

Where it prints. A report section is printed by pytest inside the failure block of its test, after the traceback and the captured output, so it is
the last thing in that test's block. The e2e-test result is cut to 4000 characters and shows each failed test as a short digest, so the result cannot
carry a dump of any size; it carries the path of the full output, which holds it. What can reach the result is one line. So the section opens
with a line `cause hints: ...` (the last tick's return code, the pause marker's kind and reason or `no pause`, whether the branch exists, the
unit's state and wait reason), the guarded branch helper puts the same line first in its failure message (which pytest echoes in the short summary
and the digest), and the details follow. The dump itself is read in the saved log, which is redacted and bounded already.

Contents and bounds. Each item has its own cap in characters; the section is capped at 20 480 characters (20 KB) and the session at 61 440 (60 KB),
after which a failure gets one line saying its dump was left out and how many were.

| Item | Source | Cap |
|---|---|---|
| tick output | the last `TickResult` of this scratch | last 6000 characters, and its return code |
| per-unit reasons | latest record per unit in `decisions.jsonl` (a closed wait is not a reason) | 20 units, 200 characters a line |
| units | `runs/units.json`: id, state, branch, held_by, failure reason and cause | 20 units, 200 characters a line |
| pause marker | `paused.json` or `absent` | 1000 characters |
| leases and locks | lease directory, e2e-test lock holder | 10 lines |
| remote | `git ls-remote --heads` of the bare remote, the app repo's branches | 30 lines each |
| decision log | tail of `decisions.jsonl` | 15 lines, 300 characters |
| usage ledger | tail of `usage-ledger.jsonl`: kind, role, node, milliseconds | 15 lines, 300 characters |
| fake host | the requests it recorded: method, path, status | 30 lines |
| tick environment | `scratch_env_summary` | 40 names |

The per-unit reasons are read from the decision log and not recomputed by running the pipeline, so building the dump runs no tick, takes no lock and
writes nothing in the scratch.

Redaction. Values of environment names that look secret are added to the redactor with `register(name, value)` and the whole text goes through
`redact_text(text, where="scratch state")` before it is added to the report. If that raises, the dump is replaced by one line saying it was
withheld because redaction failed (the rule of the full-output file).

Best effort. The hook wraps everything it does; any exception is turned into one line `scratch state unavailable: <ExceptionType>` inside the section,
and a hook that cannot even do that adds nothing. It never changes the outcome of the test, never raises, and spawns only `git` commands with a
10-second timeout each.

## Conversion

The three live tests move to the shared helper in one group. The assertions that attach nothing today (to be re-checked against the file when the
group is built):

- graph test: `commits_on_branch` at the first and later uses (bare git error), `commits_on_branch(scratch) == first` after the quiet tick, the
  `thread_next(scratch) == (Node.AWAIT_REVIEW,)` checks after the quiet tick, and `thread_next(scratch) is None` after the merge.
- build test: `assert ticked.returncode == 0` in the forbidden-command test (~361), the `git rev-parse`/`merge-base` assertions of the same test
  (~377), the tip and reflog assertions (~307-312) and the report and ledger assertions (~426-453).
- telemetry test: the trace and metric assertions (~268-273, ~290-301, ~328-330), which print neither the tick nor the unit's reasons, and the
  `pushed` flag, which hides the missing-branch error.

A source scan test then fails any live test file that defines its own tick result type or runs `abk tick` itself.

## Relationship to other changes

- `an-e2e-scratch-tick-follows-the-installations-usage-limits`: it turns the usage guard off for scratch ticks and skips the test on a usage or
  rate-limit pause; its tick function lives in `live_build.py`. This change prints state for failures and skips nothing. When both exist, the skip
  runs on the shared tick result; they touch the same tick helper textually and neither needs the other. No `Needs`.
- `acp-tests-follow-the-graph-log`: reads the graph log in the ACP tests; this change does not touch what they assert.
- `tier2-time-is-recorded-per-test`: the `ABK-TIME` plugin. The new plugin sits beside it and shares nothing but the `scratch_ledger` path
  idea; its hooks do not order against it.
- `secrets-never-reach-stored-or-posted-output`: this change uses the redaction it describes and adds a printed output that goes through it.
- `tier2-tests-are-tagged-by-runtime` group 15 edits `test_build_unit.py` and creates `live_build.py` on the unit branch of group 16; this change
  edits the same test files and builds on what main has. The overlap is textual. The unit branch's `live_build.py` (its `tick`, `output_of`,
  `pushed_commits`) will be reconciled by its rebase: its functions become thin callers of `scratch_tick` or are replaced by it. No `Needs`.

## Decisions

- No `Needs:` between groups of this change; none across changes (no code of an unbuilt change is used).
- All four groups are `[unit-test]`: the product line, the helpers and the hook are tested with fakes, `pytester` and a hand-made scratch
  directory; the live confirmation is the next e2e-test run.
