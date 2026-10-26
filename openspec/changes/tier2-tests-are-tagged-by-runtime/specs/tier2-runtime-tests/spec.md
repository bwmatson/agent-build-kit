## ADDED Requirements

### Requirement: The kit's live-stack tests are tagged by the runtime they drive, with most capability checked on Claude

Each of the kit's live-stack tests that starts an agent SHALL carry exactly one runtime tag, the build test SHALL run for `claude_code` with its one tag on its parameter, the graph test SHALL run for `claude_code` the same way, and the telemetry test SHALL build its unit for `claude_code`. The ACP parameters of the build, graph and telemetry tests, the ACP agent's own refusal of a forbidden command and the listing of the build's session by the ACP agent are added by the separate change `acp-variants-of-the-runtime-tests` and are not required here; no test in this change is ACP-only. What only the ACP agent does SHALL be kept, when it is added, in files or helpers whose names say `acp`. A live test that starts no agent (the init-conventions test) SHALL stay untagged. The two scratch tests SHALL be named `test_build_unit.py` and `test_graph_unit.py`, and nothing tracked in the repository SHALL name the old modules, the changelog's history excepted.

#### Scenario: The build test on Claude

- **GIVEN** the build test
- **WHEN** it is collected
- **THEN** it has an item for `claude_code` tagged `runtime_claude_code`, and no item carries two runtime tags

#### Scenario: The graph test on Claude

- **GIVEN** the graph test
- **WHEN** it is collected
- **THEN** it has an item for `claude_code` tagged `runtime_claude_code`, no item for `acp`, and it calls no ACP-only step

#### Scenario: The old names are gone

- **WHEN** the tracked files are searched for `test_acp_build_unit` and `test_graph_acp_unit`
- **THEN** none is found outside the changelog's history

#### Scenario: The scratch setup follows the runtime

- **GIVEN** the helper asked for `acp` without an agent command set
- **WHEN** it builds the scratch installation
- **THEN** it fails naming the setting, and for `claude_code` it writes no `runtimes` entry

### Requirement: A drift test keeps the tags honest

A test SHALL fail, naming each, when a live-stack test that starts an agent (through the scratch helper, the agent-home helper or the agent command setting) has no runtime tag, and when a scenario has an ACP variant and no Claude variant without a stated reason in its module's table of reasons; an entry with an empty reason SHALL fail too. A scenario that needs two runtimes written as one test SHALL be refused by the collection check. The test SHALL NOT check that a scenario with a Claude variant has an ACP variant, and the table of reasons is empty until the ACP variants are added.

#### Scenario: An untagged agent-driving test

- **GIVEN** a live-stack test that uses the scratch helper and carries no runtime tag
- **WHEN** the drift test runs
- **THEN** it fails naming the test

#### Scenario: An ACP variant with no Claude variant

- **GIVEN** a scenario tagged `runtime_acp` with no `claude_code` sibling and no stated reason
- **WHEN** the drift test runs
- **THEN** it fails naming the scenario

#### Scenario: An ACP-only scenario with a reason

- **GIVEN** the same scenario with a stated reason in the module's table
- **WHEN** the drift test runs
- **THEN** it passes
