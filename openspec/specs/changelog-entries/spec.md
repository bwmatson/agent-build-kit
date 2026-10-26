# changelog-entries Specification

## Purpose
TBD - created by archiving change changelog-by-the-builder. Update Purpose after archive.

## Requirements

### Requirement: The agent that builds or reworks a unit writes its changelog entry to a stated convention

The prompts of the agents that build a unit, rework it and resolve a restack conflict
SHALL state the repository's changelog convention: where the entry goes, that a follow-up
to unreleased work edits that work's bullet, the entry's shape and content, and what must
never appear in it. On a conflict in the changelog the resolver SHALL be told to keep
both sides and fold bullets that describe one change.

#### Scenario: A follow-up to unreleased work

- **GIVEN** an unreleased bullet describing a feature
- **WHEN** a later unit corrects that feature before release
- **THEN** its prompt tells the agent to edit that bullet rather than add a second one

#### Scenario: A restack conflicts in the changelog

- **WHEN** the resolver is asked to settle a conflict in the changelog
- **THEN** it keeps both sides' bullets and folds any that describe one change

### Requirement: Unit-test checks the changelog's form

The ordinary test suite SHALL fail when the changelog contains a conflict marker, two
bullets with no blank line between them, a duplicated bullet, a bullet outside a
section, headings out of order, or text the repository forbids naming, so the agent sees
the failure in its checks before any review.

#### Scenario: Two bullets run together

- **WHEN** a unit's change leaves two bullets with no blank line between them
- **THEN** unit-test fails naming the file and the line

#### Scenario: A conflict marker is left behind

- **WHEN** the changelog contains a conflict marker
- **THEN** unit-test fails

#### Scenario: A well-formed entry

- **WHEN** the entry follows the convention
- **THEN** the check passes

### Requirement: Any managed repo can use the changelog convention and check

The workspace file SHALL let each repo name its changelog path or switch the feature off.
For a repo with it on, the build, rework, test-writing, resolver and review prompts SHALL
carry the changelog convention, from the repo's own section in `AGENTS.md` or `CLAUDE.md`
where it has one and from the framework's generic text otherwise, and unit-test SHALL run the
framework's changelog check on it. For a repo with it off, none of these SHALL apply.

#### Scenario: A repo with no section of its own

- **GIVEN** a repo whose conventions files have no changelog section and whose setting is on
- **WHEN** an agent is asked to build a unit in it
- **THEN** its prompt carries the framework's convention text

#### Scenario: A repo that keeps conventions in CLAUDE.md

- **GIVEN** a repo with a changelog section in `CLAUDE.md` and none in `AGENTS.md`
- **WHEN** a prompt is built for it
- **THEN** it carries that section

#### Scenario: A repo with the feature off

- **WHEN** a repo's setting is null
- **THEN** its prompts carry no convention and unit-test runs no changelog check

### Requirement: The changelog check is a framework command run in unit-test

The framework SHALL provide a command that checks a changelog's form (no conflict
markers, bullets separated by a blank line, no duplicated bullet, no bullet outside a
section, headings in order) and exits non-zero on a problem, and unit-test SHALL run it for
every repo with the feature on. A repo with the setting on and no changelog file yet SHALL
not fail unit-test for that.

#### Scenario: Two bullets run together

- **WHEN** a unit leaves two bullets with no blank line between them
- **THEN** unit-test fails naming the file and line

#### Scenario: No changelog file yet

- **GIVEN** a repo with the setting on and no changelog file
- **WHEN** unit-test runs
- **THEN** the check passes with a note
