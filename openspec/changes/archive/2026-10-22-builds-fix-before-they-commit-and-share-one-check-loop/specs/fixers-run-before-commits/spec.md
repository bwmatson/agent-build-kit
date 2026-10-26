## ADDED Requirements

### Requirement: A profile may declare the command that applies its fixers

A toolchain profile MAY declare `fix_command(files)`, which returns the command that applies the profile's formatters and auto-fixers to the given files (relative to the project's directory) or nothing when none of them
is a file the profile fixes. It SHALL be read tolerantly: a profile without the method SHALL get no fixer pass and its builds SHALL behave as they did. python-uv's SHALL be the repository's pre-commit hooks restricted to
those files; node-npm's SHALL be `npx oxfmt` to write the format and `npx oxlint --fix` for the fixable lint findings, over those of the files that are source files, and SHALL NOT run the type check.

#### Scenario: python-uv runs the hooks over the unit's files

- **GIVEN** the python-uv profile and the files `src/a.py` and `docs/x.md`
- **WHEN** its fix command is asked for
- **THEN** it is `uv run pre-commit run --files src/a.py docs/x.md`

#### Scenario: node-npm formats and fixes the source files only

- **GIVEN** the node-npm profile and the files `src/a.ts`, `README.md` and `src/b.tsx`
- **WHEN** its fix command is asked for
- **THEN** it runs `npx oxfmt` and then `npx oxlint --fix` over `src/a.ts` and `src/b.tsx` only, whatever either exits with, and never `tsc`

#### Scenario: node-npm has nothing to fix

- **GIVEN** the node-npm profile and only the files `README.md` and `package.json`
- **WHEN** its fix command is asked for
- **THEN** it returns nothing and no command is run

#### Scenario: A profile without the method behaves as today

- **GIVEN** a profile registered without `fix_command`
- **WHEN** a unit of a repo using it is built
- **THEN** no fixer runs, no line about fixers is logged and the commits and checks are as before this change

### Requirement: A repo may replace the fix command

A repo MAY set `repos.<name>.tests.fix_command` in `abk.yaml`, a list of arguments to which the file names, relative to the project's directory, are appended. When set and not empty it SHALL be run instead of the
profile's command; when it is the empty list the repo SHALL get no fixer pass; when it is unset the profile's command SHALL apply. It is a policy setting: it SHALL be read from `abk.yaml`, the same on every machine.

#### Scenario: A repo's own command replaces the profile's

- **GIVEN** a repo whose `tests.fix_command` is `[scripts/format.sh]`
- **WHEN** the fixers run over `src/a.py`
- **THEN** `scripts/format.sh src/a.py` is run in the project's directory and the profile's command is not

#### Scenario: The empty list turns the fixers off

- **GIVEN** a repo whose `tests.fix_command` is `[]`
- **WHEN** a commit is about to be made
- **THEN** no fixer runs and the commit is made as before this change

#### Scenario: Unset follows the profile

- **GIVEN** a repo with no `tests.fix_command`
- **WHEN** the fixers run
- **THEN** the profile's command is used

### Requirement: The fixers touch only the unit's own changed and untracked files

The fixers SHALL be passed the files of the unit's working tree that are modified, added, renamed or untracked, grouped by the project that owns each and run in that project's directory with the paths relative to it, less the
lock files and artifacts the commit step unstages. They SHALL NOT be passed a file the unit did not change and SHALL NOT be run over the whole repository. A file that the review policy protects SHALL NOT be passed;
when a pass changes a protected file that was not passed, that file SHALL be restored to its content before the pass. The log SHALL say a protected file was skipped or restored. With no changed file no command SHALL run.

#### Scenario: A file the unit did not change is left alone

- **GIVEN** a worktree where the unit changed `src/a.py` and the unformatted `src/old.py` is committed on the base
- **WHEN** the fixers run
- **THEN** only `src/a.py` is passed to the command and `src/old.py` is not rewritten

#### Scenario: An untracked file is reached

- **GIVEN** a new, untracked, unformatted `src/new.py`
- **WHEN** the fixers run before the commit
- **THEN** `src/new.py` is formatted and the commit holds the formatted file

#### Scenario: Each project runs in its own directory

- **GIVEN** a repo with a project `web` at `web/` and changed files `web/src/a.ts` and `tools/b.py`
- **WHEN** the fixers run
- **THEN** the `web` project's profile command runs in `web/` over `src/a.ts` and the repo profile's command runs at the root over `tools/b.py`

#### Scenario: A protected file is skipped

- **GIVEN** a changed file the review policy protects and a changed file it does not
- **WHEN** the fixers run
- **THEN** only the second is passed, and the log says the protected file was skipped

#### Scenario: A fixer rewrites a protected file it was not given

- **GIVEN** a hook that also rewrites a protected file the unit did not change
- **WHEN** the fixers run
- **THEN** the protected file is restored to what it was, and the log says so

#### Scenario: No changed file, no command

- **GIVEN** a clean worktree
- **WHEN** the fixers run
- **THEN** no command is run and nothing is logged

### Requirement: The fixers' exit status is ignored, and they are bounded

The fixers SHALL decide whether they changed anything from the files, not from the exit status of the command, and SHALL run up to two passes per project, a second only when the first changed a file. A command that cannot be run
SHALL be logged and SHALL NOT stop the unit, count as a fix round or spend a model call. The log SHALL carry one line naming the files the fixers changed, or saying they changed nothing.

#### Scenario: A hook that edits a file exits non-zero

- **GIVEN** a hook that reformats a file and exits 1
- **WHEN** the fixers run
- **THEN** the file is formatted, the run is not treated as a failure and the log says `fixers changed 1 file(s)` with its name

#### Scenario: A second pass is made only after a change

- **GIVEN** a first pass that changes a file and a second that changes nothing
- **WHEN** the fixers run
- **THEN** two passes ran; and with a first pass that changes nothing, one pass ran

#### Scenario: A fixer that cannot run

- **GIVEN** a fix command whose program is missing
- **WHEN** the fixers run
- **THEN** the failure is logged, the build goes on to its check or commit, and no agent call is made for it

### Requirement: The pipeline runs the fixers before every commit it makes in a build

A build SHALL run the fixers, in the pipeline and with no agent, before the tests commit (in a stubbed build ahead of the static check, so that the check sees the formatted tree), before the implementation commit, before each
`fix: <title> (checks, round N)` commit, and, in a build that is not stubbed, before its tests commit and its implementation commit. What the commit holds SHALL be the fixers' output. The stubbed build's commit shapes
(`test:` then `feat:` per group, no `fix:` commit in the stub loop), its red check and its push gate SHALL be as they were.

#### Scenario: A hook reformats a file before the tests commit

- **GIVEN** a stubbed build whose tests agent leaves a file the repo's formatter would change
- **WHEN** the stub loop runs
- **THEN** the fixers format the file, the static check passes the first time, no agent call is made for it, and the `test:` commit holds the formatted file

#### Scenario: The same before the implementation commit

- **GIVEN** an implementation agent that leaves an unformatted file
- **WHEN** the implementation commit is made
- **THEN** the fixers have formatted it first and the `feat:` commit holds the formatted file

#### Scenario: The same before a fix commit

- **GIVEN** a checks-loop fix round whose agent leaves an unformatted file
- **WHEN** the `fix: <title> (checks, round N)` commit is made
- **THEN** the fixers have formatted it first and the commit holds the formatted file, and the next check finds nothing to reformat

#### Scenario: The old build

- **GIVEN** `builders.per_group_commits` off
- **WHEN** the tests commit and the implementation commit are made
- **THEN** the fixers ran before each and each commit holds the formatted files

#### Scenario: No fix commit in the stub loop

- **GIVEN** a stubbed build whose static check fails on something no fixer repairs, and whose agent fixes it
- **WHEN** the check then passes
- **THEN** the branch has no `fix:` commit and the tests commit holds the agent's fix and the fixers' output

#### Scenario: The commit gate remains the backstop

- **GIVEN** a hook that rewrites a staged file at commit time
- **WHEN** the commit is rejected and retried
- **THEN** it is retried without an agent as the commit gate already does
