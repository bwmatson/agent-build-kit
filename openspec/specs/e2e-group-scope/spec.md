# e2e-group-scope Specification

## Purpose
TBD - created by archiving change e2e-groups-hold-tests-and-stand-alone. Update Purpose after archive.

## Requirements

### Requirement: An e2e-test group holds tests, test support, docs and the changelog

A task group tagged `[e2e-test]` SHALL hold only: files under the repo's test paths (the toolchain profile's `is_test_path`, which covers the e2e test
directories), test fixtures and helpers (which live under test paths), documentation (`is_doc_path`: `docs/`, `.md`, `.rst`, `.txt`, `LICENSE*`), the
repo's changelog file, and any file the group declares as support. A group declares support with a line inside it, `Support: <paths> — <reason>`,
the paths in backticks, a path ending in `/` covering a directory. The reason SHALL be required, the line SHALL be refused outside an `[e2e-test]`
group, and `abk tags` SHALL reject a line without a reason. Product code SHALL be fixed outside the group, by a `[unit-test]` unit.

#### Scenario: A support file is declared

- **GIVEN** an `[e2e-test] [acceptance]` group with `Support: `scripts/seed-stack.sh`, `compose.e2e.yml` — the live tests start the stack with them`
- **WHEN** `abk tags` reads it
- **THEN** both paths are support of that group and no warning names them

#### Scenario: A Support line with no reason

- **WHEN** a `Support:` line has no reason, or sits in a `[unit-test]` group
- **THEN** `abk tags` reports an error at its line

### Requirement: `abk tags` and `abk check` warn of a task that names product code in an e2e-test group

For every task line of an `[e2e-test]` group, the commands SHALL read the backticked tokens that look like repo paths (they contain a `/` or end in a
file extension, have no space, are not URLs, flags or assignments; a trailing `:<line>` or `::<test id>` is dropped) and SHALL print, per path and
group, a warning (not an error) with the file and line when the path is none of: a test path of the repo's profile and project, a doc path, the repo's
changelog, a declared `Support:` path, or a file under `scripts/` named on a task line that also names a test path. The warning SHALL say the group
holds tests and that product code is fixed by a `[unit-test]` group which the pipeline files when a live test finds a defect. Paths not in
backticks, and tasks that describe a product change without naming a path, SHALL NOT be seen, which the documentation SHALL say.

#### Scenario: A task names a product file

- **GIVEN** an e2e-test group with the task "- [ ] 1.2 Fix the retry in `src/client/retry.py`"
- **WHEN** `abk tags` runs
- **THEN** it prints `warning: group 1: task 1.2 names src/client/retry.py, which is not a test path, a doc, the changelog or declared support` and exits as it did

#### Scenario: Test, docs and changelog paths

- **GIVEN** tasks that name `tests/e2e/test_route.py`, `docs/cli.md` and `CHANGELOG.md`
- **WHEN** `abk tags` runs
- **THEN** it prints no warning

#### Scenario: A script the group's test uses

- **GIVEN** the task "`tests/e2e/test_route.py` starts the stack with `scripts/seed-stack.sh`"
- **WHEN** `abk tags` runs
- **THEN** it prints no warning for the script, and prints one for it when it is named on a line with no test path and no `Support:` line

#### Scenario: A unit-test group

- **WHEN** a `[unit-test]` group names `src/client/retry.py`
- **THEN** nothing is printed

### Requirement: An e2e-test unit whose diff changes product code is stopped

After the tests and implementation commits, and again whenever the unit's branch changes, the build SHALL list the files the unit's branch changes against its base
before the checks run, and for a unit of tier `e2e-test` SHALL stop the unit when any file is not a test path of its project's profile, a doc path, the
repo's changelog or a `Support:` path of one of its groups. The stop SHALL name the files, SHALL be recorded as the unit's feedback with a source of
its own, and the feedback SHALL say: restore those files to their state on the base in this unit, keep the diff to tests and test support, and report the
defect as a product defect (the report is described below) so that the pipeline files its fix. The check SHALL read the group's `Support:` lines
from the plan, not from the branch, so the builder cannot allow itself a file. A unit that is not of tier `e2e-test` SHALL NOT be checked.

#### Scenario: A product file in the diff

- **GIVEN** an `[e2e-test]` unit whose branch changes `tests/e2e/test_route.py` and `src/app/route.py`
- **WHEN** the build reaches the checks
- **THEN** the unit is stopped, the reason names `src/app/route.py`, and no check runs

#### Scenario: Only tests, docs and the changelog

- **GIVEN** a diff of `tests/e2e/conftest.py`, `docs/e2e.md` and `CHANGELOG.md`
- **WHEN** the build reaches the checks
- **THEN** the unit goes on

#### Scenario: A declared support file

- **GIVEN** the group declares `scripts/seed-stack.sh` with `Support:` and the diff changes it
- **WHEN** the build reaches the checks
- **THEN** the unit goes on

#### Scenario: A unit-test unit

- **WHEN** a `[unit-test]` unit changes `src/app/route.py`
- **THEN** the check does not run

#### Scenario: The rework restores the files

- **GIVEN** a unit stopped for `src/app/route.py`, requeued with its feedback
- **WHEN** the rework restores the file and the build reaches the checks again
- **THEN** the unit goes on

### Requirement: The builder reports a product defect in a structured form

The build prompts for an `[e2e-test]` unit SHALL say that the unit holds tests and test support only, and the rework prompt used when the unit's
e2e-test step failed, or its diff was stopped for product files, SHALL tell the builder to decide first whether the fault is in the test or its
support (fix it in place, as before) or in the product under test; for a product fault it SHALL NOT edit product code and SHALL finish its account with a
fenced block marked `product-defect` holding JSON with `test` (the failing e2e-test identifier), `files` (the product files it believes are wrong),
`reproduction` (the smallest steps, request or inputs, with the expected and the actual result), `sketch` (optional: the body of a failing unit test
that reproduces it) and `repo` (optional, a declared repo, the unit's by default). The pipeline SHALL read the block deterministically, without a
model. A block that is present and unreadable, that names no product file, or whose test is not one the failure feedback names SHALL stop the unit
with the reason and file nothing.

#### Scenario: A product defect is reported

- **GIVEN** an e2e-test unit's rework whose account ends in a valid `product-defect` block
- **WHEN** the rework finishes
- **THEN** the pipeline reads the report and goes on as the next requirement says

#### Scenario: A test or helper fault

- **GIVEN** a rework whose account has no `product-defect` block
- **WHEN** it finishes
- **THEN** it is an ordinary rework: the fix is committed on this unit and the checks run, as before

#### Scenario: A report with only test paths

- **GIVEN** a block whose `files` are all test paths or docs
- **WHEN** it is read
- **THEN** the unit is stopped saying that is a fault in the test, to be fixed in place, and nothing is filed

#### Scenario: A broken block

- **GIVEN** a `product-defect` block that is not valid JSON, or lacks `test` or `reproduction`
- **WHEN** it is read
- **THEN** the unit is stopped with the reason and nothing is filed

### Requirement: A product defect gets one fix change, written without a model

When a valid report is read the pipeline SHALL append it to a record in the state directory and make sure one open change fixes the failing test's
defect, under a lock, named `fix-product-defect-<slug of the test id>` (cut and hashed when long, a numbered successor when an earlier one was
merged and archived), as the `fix-failing-*` and `fix-flaky-*` changes are. The change SHALL be written with no model: proposal, design, delta spec and a
`tasks.md` with one group `[<repo>] [unit-test] Reproduce <test> with a unit test, then fix it`, whose first task is a test reproducing the
defect (with the report's reproduction and sketch in its text) and whose second makes it pass, and a `Priority:` equal to the e2e-test unit's
priority. When an open change for that test already exists, the pipeline SHALL write nothing and use it. The tasks name the reported files as where the
builder believes the fault is, not as a contract.

#### Scenario: A defect is found

- **GIVEN** no change fixes `tests/e2e/test_route.py::test_stream`
- **WHEN** a valid report for it is read from unit `asr/10` of priority 2
- **THEN** `fix-product-defect-tests-e2e-test-route-py-test-stream` is written with one `[unit-test]` group of `Priority: 2` carrying the reproduction, and the run log says `would write` then `wrote`

#### Scenario: Two units, one defect

- **GIVEN** the change already exists and is open
- **WHEN** a second unit's report names the same test
- **THEN** nothing is written, the log says `exists: <change>`, and the second unit waits on it too

#### Scenario: The fix merged and the defect returned

- **GIVEN** an earlier fix change for the test was merged and archived
- **WHEN** a report names the test again
- **THEN** a numbered successor is written with a restating spec, as for the other fix changes

#### Scenario: A dry run

- **WHEN** `abk tick --dry-run` runs with a recorded defect
- **THEN** it prints `exists: <change>` or `would write: <change>` and writes nothing

### Requirement: The e2e-test unit waits on the fix and is requeued when it is in review

After filing, the pipeline SHALL give the unit's groups a `Needs:` line on group 1 of the fix change, clear the unit's stored failure feedback so the
wait-end rule resumes the unit rather than reworks it, and park the unit failed, gated on the fix, as it does for a failing test on the base. When
the fix's unit is in review (or merged or satisfied) the unit SHALL be requeued by the pipeline with no person, restacked onto it for the same
repo, and its e2e-test step run again. A unit of the fix change itself waits on nothing.

#### Scenario: The wait

- **GIVEN** a defect filed for unit `asr/10`
- **WHEN** the rework returns
- **THEN** `asr/10` is parked `failed, waiting on` the fix unit, its tasks carry the `Needs:` line, and its stored feedback is empty

#### Scenario: The fix enters review

- **WHEN** the fix change's unit is in review
- **THEN** `asr/10` is requeued with the reason `its wait ended`, resumes, and runs e2e-test again

#### Scenario: The fix does not help

- **GIVEN** the requeued unit's e2e-test step fails again for the same test
- **WHEN** a second report names it
- **THEN** the same open change is used (it is still open or its successor is written), and the unit waits again; the usual round limits apply to the rework, and no timer retries it

### Requirement: The skill and the documents say what an e2e-test group may hold

The `abk-authoring` skill source and `docs/` SHALL say what an `[e2e-test]` group may contain, that it always has a unit of its own, that product
fixes do not go in it, that the pipeline files a `[unit-test]` fix change when a live test finds a defect, how to declare support with `Support:`,
and how an author who already knows of the defect writes a `[unit-test]` group earlier in the same change (the chain orders it) or in another change that the e2e group names in a `Needs:` line; and the documents SHALL state the limits
of the path warning.

#### Scenario: The skill is read

- **WHEN** the skill's `[e2e-test]` paragraph is read
- **THEN** it names the contents, the stand-alone unit, the product-fix rule, `Support:` and the automatic fix change
