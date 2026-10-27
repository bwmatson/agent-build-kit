## ADDED Requirements

### Requirement: Repo-wide guards read their files through one helper

Every test that scans the checkout's files for a rule (a document convention, a leak shape, a renamed module) SHALL obtain them from one test helper that yields tracked files, parameterised by the folders and root files it needs, by an optional suffix filter, and by whether it reads the specification folder. The helper SHALL derive the planning folders from the checkout's `abk.yaml` (`planning.specs_dir` and `planning.state_dir`, defaults `openspec` and `runs`), SHALL leave the specification folder out unless a guard asks for it, SHALL always leave the state folder out (a guard that needs one of its files names it as a root file), and SHALL always skip hidden folders, vendored folders and build output. Outside a git repository it SHALL walk the tree.

#### Scenario: Planning content is left out by default

- **GIVEN** a tree with `docs/a.md`, `openspec/changes/x/proposal.md` and `runs/notes.md`
- **WHEN** a guard asks for its Markdown files without the specification folder
- **THEN** only `docs/a.md` is yielded

#### Scenario: A guard reads the specification folder

- **GIVEN** the same tree
- **WHEN** a guard asks for the specification folder
- **THEN** `openspec/changes/x/proposal.md` is yielded as well, and `runs/notes.md` is not

#### Scenario: The planning folders come from the configuration

- **GIVEN** an `abk.yaml` with `planning.specs_dir: specs` and a tree with `specs/c.md` and `openspec/d.md`
- **WHEN** a guard asks without the specification folder
- **THEN** `openspec/d.md` is yielded and `specs/c.md` is not

### Requirement: A guard that walks the checkout by hand fails a meta-test

A test module that enumerates the checkout's files itself (`git ls-files`, or `rglob`/`glob` on the checkout root) without using the helper, and is not on the short list of modules that walk only `src/` or `tests/`, SHALL fail a meta-test that names its `path:line`.

#### Scenario: A hand-written walk

- **GIVEN** a test module that calls `ROOT.rglob("*.md")` and does not import the helper
- **WHEN** the meta-test runs
- **THEN** it fails naming the module and line

#### Scenario: A guard that uses the helper

- **GIVEN** a test module that imports the helper
- **WHEN** the meta-test runs
- **THEN** it passes the module

### Requirement: Document and code guards do not read planning content

The guards that police documents and code (a removed configuration key named outside its migration, the old statement of who merges, an old test-module name) SHALL NOT read the specification folder: archived changes, specifications and verdicts record history and requirements that name what those guards forbid. The public-content guards (`public-leak-test`) SHALL keep reading them.

#### Scenario: An archived change names a removed key

- **GIVEN** an archived change whose proposal names `review.enabled` to record its removal
- **WHEN** the removed-key guard runs
- **THEN** it passes, and the same sentence in `docs/` fails it

### Requirement: The suite does not read the checkout's environment file

A test SHALL NOT see settings from an ignored `.env` in the checkout: the environment-file lookup SHALL treat the checkout's own `.env` as absent for every test, and a test that starts a subprocess SHALL run it outside the checkout's directory when it asserts on default settings. A root other than the checkout is looked up as before.

#### Scenario: A developer's environment file is present

- **GIVEN** a `.env` in the checkout that sets `ABK_OTEL_ENABLED` and `ABK_GRAFANA_URL`
- **WHEN** the telemetry tests run
- **THEN** they pass, as they do in a checkout with no `.env`

#### Scenario: Another root keeps its file

- **GIVEN** a temporary root holding a `.env`
- **WHEN** the lookup runs for it
- **THEN** it returns that file
