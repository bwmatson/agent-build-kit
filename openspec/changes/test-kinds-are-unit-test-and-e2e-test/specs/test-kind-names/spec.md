## ADDED Requirements

### Requirement: The two kinds of test are named unit-test and e2e-test everywhere abk writes or shows them

abk SHALL name its two kinds of test `unit-test` (the ordinary suite, run anywhere) and `e2e-test` (the suite that needs the real
local stack) in every place it writes or shows the kind: the tags of a task group's heading, the output of `abk tags`, `abk config`
and `abk status`, the settings it reads and prints, the lock file and output directory it creates, the run logs and the graph, the
metrics and spans it records, and the status context it posts to a forge. It SHALL use no other spelling for the kind.

#### Scenario: Tags in a heading

- **GIVEN** a task group headed `## 1. [app] [unit-test] Add the marker` and one headed `## 2. [app] [e2e-test] [acceptance] Drive it`
- **WHEN** `abk tags` reads the change
- **THEN** both are accepted, and the listing shows `[unit-test]` and `[e2e-test]`

#### Scenario: Settings and state use the new names

- **WHEN** a configuration is printed with `abk config`, and a unit of the e2e-test kind runs
- **THEN** the settings appear as `e2e_*` and `unit_test_*`, the lock is `runs/e2e.lock`, the full output is kept under `e2e-output/`,
  and the metrics are named `abk.e2e.*`

#### Scenario: The status context

- **WHEN** a unit's e2e-test result is posted to a forge as a commit status
- **THEN** the context is `local/e2e-test`

### Requirement: The old names appear in the framework only in the module that reads them

The framework's source, tests, documents and skills SHALL contain none of the old spellings (`unit-test`, `e2e-test`, `unit-test`, `e2e-test`,
in any case and in identifiers, file names and strings) outside the one module that holds the table of old and new names, the rename tool while it exists, and the tests of both, and a guard test SHALL fail naming the file and line of any other occurrence.

#### Scenario: A stray old name

- **GIVEN** a source file containing `e2e_marker`
- **WHEN** the guard test runs
- **THEN** it fails, naming the file and line

#### Scenario: The compatibility module is exempt

- **WHEN** the guard test runs over the compatibility module and its own tests
- **THEN** it finds nothing to report there

### Requirement: The rename is applied by a repeatable tool that works on a part of the tree

The framework SHALL carry a tool that rewrites the old spellings to the new ones, in identifiers, strings, comments, file names and
documents, from the compatibility module's table, over the paths it is given. Running it twice SHALL change nothing the second time.
With shims enabled it SHALL leave the old module or name importable as an alias for each module, class, function or constant it
renames, so code outside the paths it was given still imports; with shims removed it SHALL delete those aliases. It SHALL take a root, the framework
repository by default, so that it can also be run over another repository's Markdown and configuration, SHALL refuse a path outside
that root, SHALL report each file it changed, and with a dry-run option SHALL list what it would change and write nothing.

#### Scenario: Another repository's documents

- **GIVEN** a planning repository whose Markdown names `e2e_splits` and `unit-test`
- **WHEN** the tool runs with that repository as its root over its documents, without shims
- **THEN** the names are rewritten to `e2e_splits` and `unit-test`, no module is renamed, and a path outside that root is refused

#### Scenario: Idempotent

- **GIVEN** a tree the tool has already rewritten
- **WHEN** it runs again over the same paths
- **THEN** no file changes and it reports none

#### Scenario: A slice leaves the rest importing

- **GIVEN** the tool run with shims over one package, which renames a module and a class there
- **WHEN** a module in another package imports the old module and class names
- **THEN** the import succeeds and gives the renamed objects

#### Scenario: Shims removed

- **GIVEN** a tree rewritten with shims
- **WHEN** the tool runs with shims removed
- **THEN** every alias it left is gone, and an import of an old name fails
