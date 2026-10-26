## ADDED Requirements

### Requirement: Any managed repo can use the changelog convention and check

The workspace file SHALL let each repo name its changelog path or switch the feature off.
For a repo with it on, the build, rework, test-writing, resolver and review prompts SHALL
carry the changelog convention, from the repo's own section in `AGENTS.md` or `CLAUDE.md`
where it has one and from the framework's generic text otherwise, and tier 1 SHALL run the
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
- **THEN** its prompts carry no convention and tier 1 runs no changelog check

### Requirement: The changelog check is a framework command run in tier 1

The framework SHALL provide a command that checks a changelog's form (no conflict
markers, bullets separated by a blank line, no duplicated bullet, no bullet outside a
section, headings in order) and exits non-zero on a problem, and tier 1 SHALL run it for
every repo with the feature on. A repo with the setting on and no changelog file yet SHALL
not fail tier 1 for that.

#### Scenario: Two bullets run together

- **WHEN** a unit leaves two bullets with no blank line between them
- **THEN** tier 1 fails naming the file and line

#### Scenario: No changelog file yet

- **GIVEN** a repo with the setting on and no changelog file
- **WHEN** tier 1 runs
- **THEN** the check passes with a note
