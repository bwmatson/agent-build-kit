# one-check-and-fix-loop Specification

## Purpose
TBD - created by archiving change builds-fix-before-they-commit-and-share-one-check-loop. Update Purpose after archive.

## Requirements

### Requirement: The stub loop and the checks loop share one check-and-fix routine

The stubbed build's static check loop (`stub_checks`, `fix_stub_checks`) and the checks loop that runs before review (`checks`, `fix_checks`) SHALL both be run by one shared routine, which runs the check, saves a failure as
feedback, counts the round, stops when `global_limits.max_check_rounds` is spent, calls the agent with the fix prompt, applies the loop's commit rule and stops when the fix round changed nothing. The routine SHALL take the check
as a callable returning `(ok, output)`, the fix prompt, the commit rule, the feedback source and the counter to use, and SHALL know nothing about tests. The stub loop SHALL pass the static checks (lint, format and types, no test
run) and no commit rule; the checks loop SHALL pass the unit-test run with its selection of tests and the commit `fix: <title> (checks, round N)`. Each node SHALL delegate to the routine and SHALL NOT repeat its steps.

#### Scenario: The stub loop uses the routine with the static checks

- **GIVEN** a stubbed unit whose static check fails
- **WHEN** `stub_checks` and `fix_stub_checks` run
- **THEN** both delegate to the shared routine, the check passed is the static checks and no test is run, the failure is saved with the source `stub-checks`, the round is counted in `stub_rounds` and the fix round makes no `fix:` commit

#### Scenario: The checks loop uses the same routine with the unit tests

- **GIVEN** a unit whose unit tests fail
- **WHEN** `checks` and `fix_checks` run
- **THEN** both delegate to the same routine, the check passed is the unit-test run, the failure is saved with the source `unit-test` and the `unit-test failed:` heading, the round is counted in `fix_rounds` and the fix round commits `fix: <title> (checks, round N)`

#### Scenario: A test asserts the delegation

- **GIVEN** the four nodes
- **WHEN** each runs against a fake routine
- **THEN** the routine is called by each with its own check, commit rule, source and counter, and a loop's behaviour is the routine's alone

#### Scenario: A parked flake is not a failure

- **GIVEN** a unit-test run that finds only a flake the unit waits on
- **WHEN** the routine runs the check
- **THEN** the unit is parked as `checks` parks it today and no failure is saved

### Requirement: A fix round that changes nothing while the checks fail still stops the unit

The routine SHALL stop a unit with "static checks failing and fix round N changed nothing" in the stub loop, and "checks failing and fix round N changed nothing, before review" in the checks loop, when the agent's round changes
neither the tree nor the branch's head, and the rounds spent stop SHALL be "static checks still failing after K fix round(s) on the tests" and "checks still failing after K fix round(s), before review" as before. The
rule SHALL be unchanged by this change: it is not relaxed, because the fixers (`fixers-run-before-commits`) run before the check in the stub loop and before each commit in the checks loop, so a hook repairing a file is no
longer a reason a check fails.

#### Scenario: A stub fix round that changes nothing

- **GIVEN** a stubbed unit whose static check fails on something no fixer repairs and whose agent edits nothing
- **WHEN** the fix round ends
- **THEN** the unit stops with "static checks failing and fix round 1 changed nothing"

#### Scenario: A checks fix round that changes nothing

- **GIVEN** a unit whose unit tests fail and whose agent changes nothing and commits nothing
- **WHEN** the fix round ends
- **THEN** the unit stops with "checks failing and fix round 1 changed nothing, before review"

#### Scenario: A formatter's edit no longer causes the stop

- **GIVEN** a stubbed unit whose only static-check complaint is a file the repo's formatter reformats
- **WHEN** the stub loop runs
- **THEN** the fixers format the file before the check, the check passes, no fix round is run and the unit is not stopped

#### Scenario: Rounds spent

- **GIVEN** `max_check_rounds` fix rounds that each change something and a check that still fails
- **WHEN** the next failure is saved
- **THEN** the unit stops with the "still failing after K fix round(s)" message of its loop

#### Scenario: A fixer-only change counts as a change

- **GIVEN** a checks-loop fix round whose agent edits nothing but whose fixers change a file before the commit
- **WHEN** the `fix:` commit is made
- **THEN** HEAD moved, the stop does not fire and the next check decides
