# review-policy Specification

## Purpose
TBD - created by archiving change review-policy-and-verdict-recorded-in-shadow. Update Purpose after archive.

## Requirements

### Requirement: A workspace configures review policy in a `review` section of abk.yaml

abk.yaml SHALL accept a `review` section holding the review policy, and each repo SHALL accept a `review` block of its own. The section
SHALL hold `enabled` (default false), `protected_paths` (default empty), `protected_defaults` (default true), `classes` (a mapping of a
class name to a list of path globs, default empty) and `auto_land` with `min_samples` (default 20) and `min_clean_rate` (default
0.95). A repo's block SHALL hold `protected_paths`. The section SHALL be validated with the rest of the configuration: an unknown key,
a value of the wrong type, a rate outside 0 to 1 or a sample count below 1 SHALL fail loading and name the key. A workspace with no
`review` section SHALL load with every default.

#### Scenario: Defaults

- **WHEN** a workspace configures no `review` section
- **THEN** it loads with `enabled` false, no extra protected paths, the framework's protected defaults on, no classes, 20 samples and
  a clean rate of 0.95

#### Scenario: An unknown key

- **GIVEN** a `review` section holding a key the framework does not define
- **WHEN** the configuration is loaded
- **THEN** loading fails naming the key

#### Scenario: A rate out of range

- **GIVEN** `auto_land.min_clean_rate: 1.5`
- **WHEN** the configuration is loaded
- **THEN** loading fails naming the key and the value

### Requirement: Protected paths are the framework's defaults plus the installation's, and never narrowed by a repo

The set of paths protected from landing without a person SHALL be, for a repo, the framework's default globs (database migrations, CI
and deploy configuration, container definitions, secrets and key material, ownership files) when `protected_defaults` is true, plus the
workspace's `protected_paths`, plus the repo's own `protected_paths`. `protected_defaults: false` SHALL leave only the workspace's and
the repo's lists. A repo's list SHALL add to the workspace's and SHALL NOT remove from it. A path SHALL be protected when any glob of
the set matches it, with the matcher the framework uses for path patterns elsewhere.

#### Scenario: A default

- **GIVEN** a repo with no `review` configuration
- **WHEN** a change touches `db/migrations/0042_add_index.sql`
- **THEN** the path is protected

#### Scenario: A repo adds to the workspace's list

- **GIVEN** a workspace list holding `deploy/**` and a repo list holding `src/billing/**`
- **WHEN** a change in that repo touches `deploy/up.sh` and `src/billing/charge.py`
- **THEN** both are protected, and `src/billing/charge.py` is not protected in another repo

#### Scenario: The defaults replaced

- **GIVEN** `protected_defaults: false` and a workspace list holding only `deploy/**`
- **WHEN** a change touches `db/migrations/0042_add_index.sql`
- **THEN** the path is not protected

### Requirement: A unit belongs to the first class whose paths match everything it changed

A unit SHALL belong to the first class, in the order the section lists them, whose globs match every path the unit changed, and
otherwise to the class named by its repo and test kind (`<repo>/<unit-test|e2e-test>`). A unit that changed no path SHALL belong to
its repo-and-kind class. A unit of the `integration-test` kind (a label that behaves as `unit-test`) SHALL belong to the `<repo>/unit-test` class, so no class is named for it. A class name SHALL NOT contain a slash.

#### Scenario: Every path matches

- **GIVEN** a class `docs` matching `**/*.md` and `docs/**`
- **WHEN** a unit changes only `README.md` and `docs/guide.md`
- **THEN** it belongs to `docs`

#### Scenario: One path does not match

- **GIVEN** the same class
- **WHEN** a unit changes `docs/guide.md` and `src/app.py`
- **THEN** it belongs to `<repo>/unit-test`

#### Scenario: An integration-test unit is classed as a unit-test

- **GIVEN** a unit of the `integration-test` kind whose changed paths match no listed class
- **WHEN** its class is looked up
- **THEN** it belongs to `<repo>/unit-test`, the class a unit of the `unit-test` kind with the same paths has

#### Scenario: The first listed class wins

- **GIVEN** two classes whose globs both match every changed path
- **WHEN** a unit changes those paths
- **THEN** it belongs to the one listed first

### Requirement: No agent can change the review policy

The policy SHALL be changed only by an edit to abk.yaml that a person makes. A build agent working in a unit's worktree and a track's
run SHALL be refused, by the command policy, a write to the abk.yaml or abk.local.yaml of the planning repo by the routes the policy
names (a file write, a shell redirect, an editor command, and the copy and in-place edit programs it lists). Because a command
cannot be parsed for every route, the pipeline SHALL also read both files before every build and track run and again after it, and a
run after which either file's contents differ SHALL fail, naming the file and showing the difference. The pipeline SHALL never write
the `review` section.

#### Scenario: A build agent edits the file

- **WHEN** a build agent tries to write the planning repo's abk.yaml
- **THEN** the policy hook denies it

#### Scenario: A track proposes a change

- **WHEN** a track's `propose` run writes files for a change
- **THEN** a write to abk.yaml is refused, and writes inside the change's own folder are allowed as before

#### Scenario: A route the command policy does not name

- **GIVEN** a build run during which the agent rewrites the planning repo's abk.yaml with `python3 -c "open(...,'w')"`, a command the policy does not refuse
- **WHEN** the run ends
- **THEN** the run fails, the failure names abk.yaml and shows what changed, and the unit does not go to review

#### Scenario: A person edits the file during a run

- **WHEN** a person edits abk.yaml while a build run is in progress
- **THEN** the run fails the same way, and the failure says the file changed during the run, so that the unit can be requeued once the edit is done

#### Scenario: Neither file changes

- **WHEN** a run ends with both files byte-identical to what they were before it
- **THEN** the check passes and adds no output

### Requirement: `abk doctor` checks the review policy

`abk doctor` SHALL report, for the `review` section, a class referenced by an unknown name, a glob that does not parse, a protected or
class glob that matches no file in any configured repo, and a `review` section with `enabled` false and any policy set. A problem that
would make the verdict wrong SHALL be a failure and the others a warning.

#### Scenario: A glob that matches nothing

- **GIVEN** a protected path `servcies/**` that matches no file in any repo
- **WHEN** `abk doctor` runs
- **THEN** it warns, naming the glob

### Requirement: The build-out flag leaves everything unchanged when off

With `review.enabled` false, abk SHALL NOT compute or record a verdict, SHALL NOT ask the planner for a review tier, and SHALL NOT ask
the reviewer for a classification, and the pipeline SHALL behave exactly as before this change.

#### Scenario: Flag off

- **GIVEN** `review.enabled` is false
- **WHEN** a unit is planned, built and approved
- **THEN** the planner and reviewer prompts are those of before, and no `runs/verdicts.json` entry is written
