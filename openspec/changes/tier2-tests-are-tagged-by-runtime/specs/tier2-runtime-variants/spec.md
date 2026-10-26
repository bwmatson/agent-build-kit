## ADDED Requirements

### Requirement: The scheduled run is one change per variant

A due repo SHALL get one scheduled change for each variant it runs: the base group, named `scheduled-e2e-<repo>-<date>-base`, and one for each runtime its resolved `e2e_runtimes` names, named `scheduled-e2e-<repo>-<date>-<runtime>`. A repo with no runtimes listed SHALL get only the base change. The due check and the open check SHALL be made for each repo and variant: a variant's due date SHALL be read from the latest change of that repo and variant, open or archived, so a variant never run is due at once while the others wait out their period, and at most one change of a (repo, variant) SHALL be open. A name with no variant suffix SHALL read as the base variant. A repo whose name begins another's, and a variant whose name begins another's, SHALL NOT be confused. A change SHALL name its variant in its proposal, its design and its task, and SHALL pass `abk check` and `abk tags`. Nothing about the variants SHALL be stored but the change names, and two writers at once SHALL write one change per variant.

#### Scenario: Three variants

- **GIVEN** a due repo whose `e2e_runtimes` is `acp` and `claude_code`
- **WHEN** a round runs
- **THEN** the changes `-base`, `-acp` and `-claude_code` of today are written

#### Scenario: A variant that was never run

- **GIVEN** a repo whose base and `claude_code` variants ran three days ago on a weekly schedule and a newly listed `acp`
- **WHEN** a round runs
- **THEN** only the `-acp` change is written

#### Scenario: One open does not stop the others

- **GIVEN** an open change of the `acp` variant and the other variants due
- **WHEN** a round runs
- **THEN** the others are written and the `acp` one reports `exists`

#### Scenario: An older name

- **GIVEN** an archived change `scheduled-e2e-<repo>-<date>` with no suffix
- **WHEN** the base variant's due date is read
- **THEN** that change counts as the base variant's

### Requirement: A scheduled split's unit runs its own split and waits, change open, while the split is held

The unit of a split's scheduled change SHALL run the whole marker restricted to its split on the default branch through the selection builder, and SHALL pass as a satisfied unit with a note naming the split and the counts. While the split is held its unit SHALL run nothing and SHALL be held planned with the split named, its change staying open, while the other splits' units run; it SHALL resume when the split is released. A failing test of a split SHALL be recorded for that split and fixed by one change, and SHALL hold only runs that execute that split; a failure in `rest` SHALL NOT hold another split's unit.

#### Scenario: Each unit runs its own split

- **GIVEN** the units of a `-rest` and a `-claude_code` change
- **WHEN** each reaches e2e-test
- **THEN** the first runs only the tests of no split and the second only the tests of the `claude_code` split

#### Scenario: A held split parks while the others run

- **GIVEN** `acp` held and the units of the `-rest`, `-claude_code` and `-acp` changes
- **WHEN** the units run
- **THEN** the first two run and pass, and the third is held planned waiting for e2e-test split `acp` with its change still open

#### Scenario: The split resumes

- **GIVEN** a parked `-acp` unit and `acp` released
- **WHEN** the next pass runs
- **THEN** the unit resumes, runs the `acp` tests and passes as satisfied

#### Scenario: A failure stays with its split

- **GIVEN** a failing test in `rest` recorded with its fix change open
- **WHEN** the unit of the `-claude_code` change reaches e2e-test
- **THEN** it is not held by that record
