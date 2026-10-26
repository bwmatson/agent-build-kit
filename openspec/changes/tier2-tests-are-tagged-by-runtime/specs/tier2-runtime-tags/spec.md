## ADDED Requirements

### Requirement: A live-stack test names the runtime it drives with at most one tag

An e2e-test test that drives one agent runtime SHALL carry exactly one marker `runtime_<name>`, where `<name>` is the key of that runtime under `runtimes` (`runtime_claude_code`, `runtime_acp`). A test with none SHALL be the untagged base: it needs no agent and always runs. Collection SHALL fail, naming each such test and its tags, for a live-stack test that carries two or more different runtime tags, wherever they come from (the test, its class, its module or a parameter). A scenario that needs two runtimes SHALL be written as two tests. A test that is not live-stack SHALL NOT be checked, and the same tag given twice SHALL count once.

#### Scenario: An untagged test is the base

- **GIVEN** a live-stack test with no runtime tag
- **WHEN** the tests are collected
- **THEN** it collects, and it is selected by the base group of every selection

#### Scenario: One tag

- **GIVEN** a live-stack test marked `runtime_claude_code`
- **WHEN** the tests are collected
- **THEN** it collects as a test of that runtime

#### Scenario: Two tags fail collection

- **GIVEN** a live-stack test marked `runtime_acp` on itself and `runtime_claude_code` on its module
- **WHEN** the tests are collected
- **THEN** collection fails with an error naming the test and both tags, and no test runs

#### Scenario: Each parameter carries its own tag

- **GIVEN** a parametrised live-stack test whose two parameters are tagged `runtime_claude_code` and `runtime_acp`
- **WHEN** the tests are collected
- **THEN** they collect as two items, each with its one tag, and a module tag added to the file makes both fail

#### Scenario: A test that is not live-stack is not checked

- **GIVEN** a test that is not marked live-stack and carries two runtime tags
- **WHEN** the tests are collected
- **THEN** it collects without error

### Requirement: The runtime tags are registered and a mistyped one fails collection

The tags `runtime_<name>` SHALL be registered markers, one for each runtime name the runtime registry knows and for the protocol runtime, and `dev_stack` SHALL be registered. Strict markers SHALL be on, so a marker that is not registered fails collection naming it. A test SHALL fail when the registered runtime tags and the runtime registry disagree.

#### Scenario: A typo

- **GIVEN** a test marked `runtime_typo`
- **WHEN** the tests are collected
- **THEN** collection fails naming the marker

#### Scenario: The tags follow the registry

- **GIVEN** the project's registered markers and the runtime registry
- **WHEN** the registered runtime tags are compared with the runtime names
- **THEN** they are the same set, and `dev_stack` is registered

### Requirement: One builder makes the selection every e2e-test command uses

One function SHALL build the e2e-test marker expression from the repo's e2e-test marker and the set of blocked runtimes, and optionally the one group to run alone (a runtime, or `base`). With nothing blocked the expression SHALL be the marker unchanged. With runtimes blocked it SHALL be the marker with each blocked runtime's tag excluded. For one runtime alone it SHALL be the marker and that tag, and for `base` alone the marker with every known runtime's tag excluded. A name that is not a known runtime, and the name `base` as a blocked runtime, SHALL be refused naming it. The e2e-test commands, the acceptance commands, the own-scope repeat commands, the base re-run of a failed test and the post-merge check SHALL all take the expression from it, and the base re-run SHALL keep it.

#### Scenario: Nothing blocked

- **GIVEN** no blocked runtime
- **WHEN** the selection is built for the marker `local_stack`
- **THEN** the expression is `local_stack`, and the commands are the ones built before this change

#### Scenario: A blocked runtime is left out

- **GIVEN** `acp` blocked
- **WHEN** the selection is built
- **THEN** the expression selects the marked tests that are untagged or tagged `runtime_claude_code`, and none tagged `runtime_acp`

#### Scenario: One group alone

- **GIVEN** a resume of the parked group `acp`, and a scheduled variant for `base`
- **WHEN** the selection is built for each
- **THEN** the first selects only `runtime_acp` tests and the second only the untagged ones

#### Scenario: The base re-run keeps the expression

- **GIVEN** a failed test of a run whose expression left `acp` out
- **WHEN** the test is run again on the base
- **THEN** the re-run command carries the same expression and keeps no other selection of the failed command

#### Scenario: A name nothing knows

- **GIVEN** a blocked set naming a runtime the registry and the configuration do not know
- **WHEN** the selection is built
- **THEN** it is refused naming the runtime

### Requirement: A run that cannot express the selection runs whole and says so

A toolchain profile that cannot express a marker expression (one without the hook, one whose e2e-test is not implemented) and a repo whose e2e-test runs through its dev stack script SHALL run the whole marker, and the log SHALL say that the selection could not be expressed and which blocked runtime it could not leave out.

#### Scenario: The dev stack script

- **GIVEN** a repo with a dev stack script and `acp` blocked
- **WHEN** its e2e-test step runs
- **THEN** the script runs as before and the log names `acp` as a runtime it could not leave out
