## ADDED Requirements

### Requirement: A repo declares its e2e-test splits, and the tests in none are the split `rest`

`abk.yaml` SHALL take, under `tests`, a map `e2e_splits` from a split name to an entry with a `marker` and an optional `hold` of true or false, and a repo SHALL take its own `tests.e2e_splits` that, when set, replaces the top-level map for that repo. A split is a named subset of a repo's e2e-test tests chosen by its selector. A split name SHALL be lowercase letters, digits and underscores, and the name `rest` SHALL be reserved: `rest` is always declared, without being written, and holds the tests of no declared split; a `rest` entry MAY be written to carry `hold` (and `gate`, once the gate change defines it) and SHALL NOT carry a `marker`. A split with no marker, an empty marker, an unknown key, or the same marker as another split SHALL be refused when the configuration loads, naming the setting. A repo that declares no split SHALL have `rest` alone and SHALL behave as a repo with no split behaved before. The configuration SHALL name no runtime in this mechanism: a split's name and marker are the repo's, whatever it splits by. `abk config --show` SHALL show the splits.

#### Scenario: No splits declared

- **GIVEN** a configuration with no `tests.e2e_splits`
- **WHEN** a repo's splits are read
- **THEN** they are `rest` alone and every e2e-test command is the one the repo ran before

#### Scenario: Two splits

- **GIVEN** `tests.e2e_splits` of `claude_code` with marker `runtime_claude_code` and `acp` with marker `runtime_acp`
- **WHEN** a repo's splits are read
- **THEN** they are `claude_code`, `acp` and `rest`, each with its marker and its `hold`

#### Scenario: A repo's own splits

- **GIVEN** a top-level declaration of `acp` and one repo whose `tests.e2e_splits` declares `gpu`
- **WHEN** that repo's splits are read
- **THEN** they are `gpu` and `rest`, and another repo's are `acp` and `rest`

#### Scenario: What is refused

- **GIVEN** a split with no marker, a split named `rest` with a marker, a split with an unknown key, or two splits with one marker
- **WHEN** the configuration is loaded
- **THEN** it is refused with a message naming the setting and the value

#### Scenario: The old lists

- **GIVEN** `tests.runtimes_blocked`, `tests.runtimes_allowed` or `tests.e2e_runtimes` in the file
- **WHEN** the configuration is loaded
- **THEN** it is refused naming the setting that replaces it, because the lists have no alias

### Requirement: The selection is built over the declared splits and the profile translates the selector

One function SHALL build the e2e-test selection of a run from the repo's declared splits, the set of held splits and the one split to run alone, and every e2e-test command SHALL take it. With nothing held and no split asked for alone the selection SHALL be the repo's marker unchanged. A held split SHALL be left out; `rest` held SHALL leave out the tests of no declared split; a split asked for alone SHALL select only it, and `rest` asked for alone SHALL select the tests of no declared split. A name that is not a declared split or `rest`, and a split both held and asked for alone, SHALL be refused naming the splits there are. The toolchain profile SHALL translate a split's selector into what its test runner takes (the python profile turns a `marker` into the `-m` expression of the same text the runtime selection gave), SHALL list, without running them, the tests a selection holds, and SHALL report the selector kinds it supports. A profile that supports no selector kind, a split whose selector kind the profile does not support, and a repo whose e2e-test runs through its dev stack script SHALL run the whole selection and SHALL say why. The base re-run of a failed test SHALL keep the run's selection.

#### Scenario: Nothing held

- **GIVEN** a repo with splits `acp` and `claude_code`, none held
- **WHEN** the selection is built
- **THEN** it is the repo's marker alone and the commands are as they were

#### Scenario: A held split is left out

- **GIVEN** `acp` held
- **WHEN** the selection is built
- **THEN** it is the marker and `not` the marker of `acp`, and its left-out list names `acp`

#### Scenario: One split alone

- **GIVEN** a request to run `acp` alone, and another to run `rest` alone
- **WHEN** the selection is built
- **THEN** the first is the marker and the marker of `acp`, and the second is the marker with every declared split's marker left out

#### Scenario: `rest` held

- **GIVEN** `rest` held with `acp` and `claude_code` unheld
- **WHEN** the selection is built
- **THEN** it selects the tests of `acp` or `claude_code` only, and when every split including `rest` is held it selects nothing and says so

#### Scenario: A name nothing declares

- **GIVEN** a held name that is not declared
- **WHEN** the selection is built
- **THEN** it is refused naming the splits there are

#### Scenario: A profile that cannot express a selection

- **GIVEN** a split held in a repo whose profile reports no selector kind, or whose e2e-test runs through a dev stack script
- **WHEN** e2e-test runs
- **THEN** it runs whole, and its log names the held split, the profile or the script, and why it could not leave the split out

#### Scenario: A selector kind the profile lacks

- **GIVEN** a split whose selector kind the repo's profile does not report
- **WHEN** the selection is built
- **THEN** it is refused naming the profile, the kind and the kinds the profile supports

### Requirement: A test is in at most one split, found by listing and reported by `abk e2e-test check`

A test SHALL belong to at most one declared split, and a test in none SHALL be in `rest`. The framework SHALL find a test selected by two splits by listing each split's tests through the profile, SHALL NOT depend on a plugin of the repo for it, and SHALL report each such test with its identifier and both split names. `abk e2e-test check` SHALL, for a repo, list every split and `rest` with its marker and the number of tests it holds, SHALL report each selector the repo's test runner does not know, each test in two splits and each listing that fails (a failed listing SHALL NOT read as an empty split), SHALL exit 0 when it finds nothing, 1 when it finds something or when a declared split cannot be applied by the profile, and 2 for a repo it does not know, and SHALL change nothing on disk. A repo with no declared split SHALL pass with a line saying so. A repo's own collection plugin MAY remain as a convenience and SHALL NOT be what the framework relies on.

#### Scenario: Exclusive splits

- **GIVEN** two splits whose listings share no test
- **WHEN** `abk e2e-test check` runs
- **THEN** it prints one line per split and `rest` with its test count and exits 0

#### Scenario: A test in two splits

- **GIVEN** a test selected by both `acp` and `claude_code`
- **WHEN** `abk e2e-test check` runs
- **THEN** it prints the test's identifier and both split names and exits 1

#### Scenario: An unknown selector

- **GIVEN** a split whose marker the test runner does not register
- **WHEN** `abk e2e-test check` runs
- **THEN** it reports the selector as unknown and exits 1

#### Scenario: A listing that fails

- **GIVEN** a listing that fails for one split
- **WHEN** `abk e2e-test check` runs
- **THEN** the split is reported with the failure, never as holding no tests, and the exit is 1

#### Scenario: No plugin of the repo

- **GIVEN** fixture test files collected with no repo plugin loaded, one test carrying the markers of two splits
- **WHEN** the listing runs
- **THEN** the test is found in both splits

#### Scenario: No splits

- **GIVEN** a repo that declares no split
- **WHEN** `abk e2e-test check` runs
- **THEN** it says no split is declared and exits 0

### Requirement: The kit's own splits are an installation's configuration, and the framework names none

The kit's own `acp` and `claude_code` splits SHALL be documented as the `tests.e2e_splits` an installation writes in its `abk.yaml` for the kit's repo, with the markers `runtime_acp` and `runtime_claude_code` that the kit registers as its own choice. A test SHALL tie the documented example to the markers the kit registers. No code of the e2e-test mechanism SHALL name a split, a runtime, a `runtime_` marker or a provider, outside the provider table's own module, and a test SHALL fail when one does.

#### Scenario: The documented example

- **GIVEN** the example block in the kit's runtimes document
- **WHEN** it is loaded with the configuration model
- **THEN** it loads, and its markers are exactly the `runtime_` markers registered in the project file

#### Scenario: A name in the framework

- **GIVEN** a module of the e2e-test mechanism that names a runtime the registry knows, a `runtime_` marker or a provider
- **WHEN** the scan runs
- **THEN** the test fails naming the module and the name

#### Scenario: The provider table

- **GIVEN** the provider table's own module naming a provider
- **WHEN** the scan runs
- **THEN** the table is exempt and the test passes
