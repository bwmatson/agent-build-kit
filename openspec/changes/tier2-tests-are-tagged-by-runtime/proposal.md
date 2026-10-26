## Why

Three of the kit's four live-stack tests drive a real ACP agent, and that agent's model backend is down: its provider's monthly budget is spent. Today an own-scope e2e-test run
executes the ACP test, it fails, the base re-run fails too, the failure is recorded as pre-existing, and the unit parks behind a `fix-failing-*` change nobody can fix; the
open-fix gate then holds every full-scope run of the repo behind that change. A budget is not a bug, and the other runtimes' tests, and the tests that need no agent, were
never the problem. Nothing says which runtime a test drives, so nothing can leave one out.

The fix is to say it: a tag per runtime, one selection every e2e-test command takes, a block that can be set and lifted, and a unit that waits for the tests it cannot run
instead of failing or passing without them. Claude Code is the runtime that is available most of the time, so most capability should be verified on it, with ACP keeping
what is its own.

## What Changes

The change is about e2e-test splits (the directory keeps its name: renaming it would orphan stored units). Its first groups were built with runtime names and are migrated by
`tier2-splits-replace-runtime-tags`; the groups that follow are written to the generic model. Where this text says "runtime", it is the kit's own choice of how to split.

- **A test is in at most one split.** A repo declares its splits (`tests.e2e_splits.<name>` with a `marker`); the tests in none are `rest`. The kit's own markers `runtime_<name>`
  (`runtime_claude_code`, `runtime_acp`) are registered and strict markers are on, so a typo fails collection; a live-stack test with two runtime tags fails the kit's own collection
  naming it. Membership is checked for any repo by `abk e2e-test check`.
- **One selection.** One builder makes the selection over the declared splits; the e2e-test, acceptance, own-scope repeat and base re-run commands and the post-merge check all take it,
  and the base re-run keeps it. A profile or a dev stack script that cannot express it runs whole and says so.
- **A hold, set by hand, in the configuration or by a gate.** `hold` on a split in `abk.yaml`; `e2e-held.json` in the state directory (reason, time, deadline on a gate entry only,
  source `command` or `gate`, who); the held set is both together and the configuration wins; an expired deadline lifts a gate's hold. `abk e2e-test hold|release|status` updates both together
  (both or neither), with no deadline on a hand-set hold, editing `abk.yaml` as text (comments kept, one backup) and refusing with the reason when it cannot. `abk status` and
  `abk doctor` show it.
- **A unit parks the tests it cannot run.** The splits that can run run. When the unit's own tests (or, under full scope, the marker) include a held split's, the unit passes what ran,
  waits planned with the split named, and resumes only that split when it is released. No rework round, no feedback, no failure record, no fix change, no success posted for tests that
  did not run. Post-merge verification is skipped for a held split and retried.
- **The gate and the record are per split.** The record carries the split of the failing test; an open fix holds only a run that executes that split. A held split never records a failure.
- **The kit's live tests are tagged and split.** The build and graph tests lose "acp" from their names; the build, graph and telemetry tests run on `claude_code` here, each parameter with one tag; what only ACP does stays in files that say acp. The ACP parameters of the build, graph and telemetry tests, the forbidden-command refusal
  test and the session-listing test are not part of this change: the separate change `acp-variants-of-the-runtime-tests` adds them when the `acp` split is released. A drift test fails an untagged agent-driving test and an ACP scenario with no
  Claude variant and no stated reason.
- **The scheduled run is one change per split** (each declared split plus `rest`): `scheduled-e2e-<repo>-<date>-<split>`, due and open per repo and split; a held split's change stays
  open, parked, while the others run.

## Impact

- agent-build-kit: `pyproject.toml` (markers, strict markers), a test plugin beside the time-limit one, `pipeline/wiring.py` (`E2eSession`, the scope decision, the gate's lookup),
  `graph/nodes.py` (the e2e-test node's park and resume), `pipeline/unit_store.py` (a cause and the parked fields), `pipeline/untouched_failures.py` (the record and the gate),
  `pipeline/verify.py`, `pipeline/e2e_schedule.py` (variants), `profiles/python_uv.py` and `profiles/base.py` (the selection, the base re-run, the listing hook), `config.py` (the
  `tests` block), a new module for the blocked set and one for the text edit, `cli/e2e_cmd.py` (new), `cli/pipeline.py` (`abk status`, the release step), `cli/doctor.py`, the kit's
  live tests, the configuration, runtimes and command documents, the three skills, the changelog.
- It builds on the merged code of `tier2-failures-in-untouched-tests-are-fixed-once` and `tier2-waits-on-open-base-failure-fixes` (the record, the gate, the park) and on groups 1
  and 2 of `tier2-runs-on-a-schedule` (own scope, the due check). Its scheduled variants groups extend the scheduled unit's route that group 3 of that change put on the default branch, and that change's group 4 (the tick that writes the due
  changes) should wait on this change's variants groups so the first scheduled run is already split.
- `a-runtimes-provider-has-usage-windows` ("a split's gate") writes the same state file (`source: gate`) and needs this change's held set and commands; `tier2-splits-replace-runtime-tags` migrates groups 1 to 5, 7 and 12 and the code of 8 and 10 from runtimes to splits.
- Priority 2: a spent model budget parks work that drives the ACP agent today, and the failures it causes are recorded as base failures that hold other runs.
