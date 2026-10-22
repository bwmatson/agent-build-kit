# Runbook: a change renames a repo's e2e marker and moves its e2e tests

For the person running a planning repo. A change that renames the pytest marker a repo's e2e-test tests carry (for example `live_model` to `e2e`) and moves them to their own folder (for example `tests/e2e/`) has steps a builder cannot do: the selector lives in `abk.yaml`, which only a person edits, and the pipeline's recorded failures name the old paths. Each step has an id and a deterministic check; once the change carries `Manual:` lines (`manual-steps-gate-units`) the tick runs the checks for you and `abk manual list` shows what is left; until then run them by hand. A step is done when its check exits 0. Below, `<old>` and `<new>` are the marker before and after, and `<folder>` is where the tests moved to.

## Before the change merges

1. Confirm what it waits on: `abk status` shows the change's first unit blocked on the units it must follow. Do not force it earlier; they edit the files it moves.
2. Nothing in `abk.yaml` changes yet. Until the merge the pipeline's e2e runs, a unit's and the scheduled one, select `-m <old>`.

## At the merge (in order, together)

1. **Flip the selector** (`flip-e2e-marker`; check: `abk config --show` shows `e2e_marker: <new>` for the repo). In `abk.yaml`, the repo's `tests.e2e_marker` goes from `<old>` to `<new>`. Do it right after the pull request merges. In between, an e2e run finds no tests and records "no e2e-test ran"; it does not fail. Edit with the timer stopped (see [landing-changes.md](landing-changes.md#2-editing-abkyaml-or-abklocalyaml)).
2. **Check the configuration** (`config-valid`; check: `abk doctor` reports 0 failed).
3. **Pull the repo's checkout** (`pull-checkout`; check: `<folder>` exists and the old folder holds nothing but `__init__.py`). If directories linger because of ignored `__pycache__`, delete them.
4. **One live collection** (`live-collect`; check: `pytest -m <new> --collect-only -q` from the project lists every moved module). Then run one moved test end to end and confirm it finds whatever it reads by path (a baselines folder read from the project root is unchanged).
5. **Recorded failures** (`stale-failure-records`; check: no record in `runs/preexisting-failures.jsonl` names a path under the old folder). The file keys a failure by test node id, so the old ids stop matching and a persisting failure is recorded again under its new path. Close or replan any fix unit that names an old path.

## What to expect

- Default pytest and CI (the run that leaves e2e out, such as `-m "not integration"`) collect no e2e tests: the repo's `conftest.py` leaves the marker out unless `-m` names it.
- Scoring-logic tests that moved with them carry the new marker too, so they stay out of default runs and CI, as before.
- Docs and run lines say `pytest -m <new> <folder>/...`.

## Back out

Revert the pull request and put `tests.e2e_marker: <old>` back in `abk.yaml`. No state outside the repo changes.
