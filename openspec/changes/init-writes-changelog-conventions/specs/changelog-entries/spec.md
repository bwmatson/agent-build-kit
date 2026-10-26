## ADDED Requirements

### Requirement: Init puts the changelog convention, file and merge rule into each repo

For every repo in the workspace with the changelog feature on, `abk init` SHALL: write the
convention as a marked, versioned block into its `AGENTS.md`, else its `CLAUDE.md`, else a
new `AGENTS.md` (creating no `CLAUDE.md`); create the changelog at the configured path when
absent; and ensure `.gitattributes` has a union-merge rule for that path. It SHALL replace
only its own marked block on a later run, SHALL NOT rewrite any other line of any file,
SHALL NOT edit an existing changelog, SHALL NOT write a block where the repo has its own
changelog section, SHALL skip repos with the feature off, and SHALL leave every change
uncommitted. A second run on an unchanged repo SHALL change nothing.

#### Scenario: A repo with an AGENTS.md

- **WHEN** init runs
- **THEN** the block is appended to `AGENTS.md`, the rest of the file is unchanged, and a
  changelog and the merge rule exist

#### Scenario: A repo with only a CLAUDE.md

- **WHEN** init runs
- **THEN** the block goes into `CLAUDE.md` and no `AGENTS.md` is created

#### Scenario: A repo with neither

- **WHEN** init runs
- **THEN** `AGENTS.md` is created holding the block, and no `CLAUDE.md` is created

#### Scenario: A repo with a .gitattributes already

- **GIVEN** a `.gitattributes` with other rules and none for the changelog
- **WHEN** init runs
- **THEN** the rule is appended and the other lines are untouched

#### Scenario: Run again

- **WHEN** init runs a second time
- **THEN** nothing is written and the dry run says so

#### Scenario: A newer block text

- **GIVEN** a block written by an earlier version
- **WHEN** init runs
- **THEN** only the text between its markers is replaced

#### Scenario: A repo with the feature off

- **WHEN** init runs
- **THEN** nothing is written into that repo

### Requirement: Init and doctor say what would be written

`abk init --dry-run` SHALL list, for each repo, each of the three actions as written,
updated or left, without writing, and `abk doctor` SHALL warn when a repo with the feature
on has no union-merge rule for its changelog.

#### Scenario: Dry run

- **WHEN** init runs with `--dry-run`
- **THEN** it prints one line per repo and action and writes nothing

#### Scenario: A repo set up before this

- **GIVEN** a repo with a changelog and no merge rule
- **WHEN** doctor runs
- **THEN** it warns naming the repo and `abk init`
