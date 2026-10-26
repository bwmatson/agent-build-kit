# tasks-tag-rewrite Specification

## Purpose
TBD - created by archiving change open-changes-are-migrated-to-review-tiers. Update Purpose after archive.

## Requirements

### Requirement: `abk tags --fix` rewrites the old test-kind tags in open changes and changes nothing else

`abk tags --fix [CHANGE | --all]` SHALL replace, in the heading of each task group of the selected open changes, the tag `[unit-test]` with
`[unit-test]` and `[e2e-test]` with `[e2e-test]`, by editing the text of `tasks.md`. Every other byte of the file, line endings
included, SHALL be as it was, and a mention of `unit-test` or `e2e-test` anywhere but a heading's test-kind tag SHALL NOT be touched. It
SHALL print each change it rewrote and how many tags, report a change already in the new spelling as unchanged, and exit 0. With
`--dry-run` it SHALL print what it would rewrite and write nothing.

#### Scenario: A change with old tags

- **GIVEN** a `tasks.md` with headings `## 1. [app] [unit-test] Add it` and `## 2. [app] [e2e-test] [acceptance] Drive it`, and the sentence "this is a unit-test concern" in a task
- **WHEN** `abk tags --fix` runs for it
- **THEN** the headings read `[unit-test]` and `[e2e-test]`, the sentence and every other byte are unchanged, and the output says two tags were rewritten

#### Scenario: Windows line endings

- **GIVEN** a `tasks.md` whose lines end in carriage return and line feed
- **WHEN** the tags are fixed
- **THEN** the endings are still carriage return and line feed on every line

#### Scenario: Already rewritten

- **WHEN** `abk tags --fix` runs a second time
- **THEN** it reports the change unchanged and the file is not written

#### Scenario: A dry run

- **WHEN** `abk tags --fix --dry-run --all` runs
- **THEN** it lists the rewrites it would make and no file is written

### Requirement: `abk tags --fix` refuses, and writes nothing, when it cannot be sure of the result

For each change `abk tags --fix` SHALL parse the text it would write and compare it with the parse of the text it read. It SHALL
write the change only when both give the same groups in the same order with the same repo, flags, titles and tasks and the same test
kind. It SHALL refuse a change, print the reason and write nothing for it when the change has any other tag problem, when the file
cannot be read or written, or when the comparison differs. Other changes selected with it SHALL still be handled, and the exit
status SHALL be 1 when any was refused. The write SHALL be atomic.

#### Scenario: A change with another tag error

- **GIVEN** a `tasks.md` that has an old tag and a group tagged for a repo `abk.yaml` does not have
- **WHEN** `abk tags --fix` runs for it
- **THEN** the output names the repo problem, the file is unchanged, and the exit status is 1

#### Scenario: One change refused among several

- **GIVEN** `--all` over three changes, one of them refused
- **WHEN** the command runs
- **THEN** the other two are rewritten, the third is untouched and named, and the exit status is 1

#### Scenario: A read-only file

- **GIVEN** a `tasks.md` the user cannot write
- **WHEN** the command runs for it
- **THEN** it says the file is read-only and nothing is written

### Requirement: Only a person's command edits a `tasks.md`

No part of the pipeline, a tick, a replan, a planning pass, a build or a track SHALL write to a change's `tasks.md`. Tags SHALL be rewritten only by `abk tags --fix`, run by a person.

#### Scenario: A tick over old tags

- **GIVEN** open changes with old tags
- **WHEN** a tick, a replan and a planning pass run
- **THEN** every `tasks.md` is byte for byte what it was

### Requirement: Rewriting tags does not make a plan stale

The digest of a change's `tasks.md` that decides whether its plan is current SHALL ignore the spelling of the test-kind tag, and a plan recorded from a text that used the old spelling SHALL still count as current for the same text in the new one.

#### Scenario: After the rewrite

- **GIVEN** a change planned from a `tasks.md` with old tags
- **WHEN** `abk tags --fix` rewrites it and a tick runs
- **THEN** the tick makes no planner call for it and its plan is still current

### Requirement: `abk config --migrate` renames the old test-kind settings

`abk config --migrate` SHALL rename each old test-kind settings key in an abk.yaml to its new name, `unit_test_*` to `unit_test_*`,
`e2e_*` to `e2e_*`, `tests.e2e_marker`, `e2e_runtimes` and `e2e_splits`, in the workspace's blocks and in each repo's, keeping
each value, its end-of-line comment and the comment lines directly above it, by editing the file's text and changing no other byte.
It SHALL check that the result loads with the same settings before it writes, SHALL refuse, naming the file and the key and writing
nothing, when it cannot edit safely or when a file holds the old and the new spelling of one setting, and run again over its own
result SHALL change nothing. It SHALL make the change, ask and write once together with the other moves the command makes.

#### Scenario: Keys renamed

- **GIVEN** a file with `e2e_lock_wait_seconds: 600` and a comment at the end of that line
- **WHEN** `abk config --migrate` runs and the change is confirmed
- **THEN** the key reads `e2e_lock_wait_seconds: 600` with its comment, and no other byte of the file changed

#### Scenario: Both spellings

- **GIVEN** a file holding `e2e_schedule` and `e2e_schedule` in the same block
- **WHEN** the command runs
- **THEN** it refuses naming both keys and writes nothing

#### Scenario: Nothing to do

- **WHEN** the command runs over a file with only the new names
- **THEN** it says nothing needs migrating and writes nothing
