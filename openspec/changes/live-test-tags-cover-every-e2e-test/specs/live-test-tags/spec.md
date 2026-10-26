## ADDED Requirements

### Requirement: The drift test finds every live-stack module of the kit

The kit's drift test SHALL examine every Python file under `tests/`, at any depth and whatever its name, whose syntax marks a test `local_stack`, and SHALL name a file it cannot parse. A word `local_stack` in a string or comment SHALL NOT make a file live.

#### Scenario: A module in a subdirectory

- **GIVEN** a live module `tests/integration/runtimes/test_x.py` with a `local_stack` test that starts an agent and has no runtime tag
- **WHEN** the drift test runs
- **THEN** it names the test

#### Scenario: A helper module run by path

- **GIVEN** `tests/integration/replay_unit_x.py`, not named `test_*.py`, that marks a test `local_stack`
- **WHEN** the drift test runs
- **THEN** the file is among the live modules

#### Scenario: A string is not a mark

- **GIVEN** a file that holds `"@pytest.mark.local_stack"` only inside a string
- **WHEN** the live modules are listed
- **THEN** it is not among them

#### Scenario: A file that cannot be parsed

- **GIVEN** a file under `tests/` with a syntax error that mentions `local_stack`
- **WHEN** the drift test runs
- **THEN** it fails naming the file

### Requirement: Starting an agent is decided per test from a table of signals

A live-stack test SHALL count as starting an agent when it, a fixture it requests, or a function of its module it calls shows a signal of a single table: an import of a named shared helper that starts an agent, `runtime_scratch`, `run_tick`, `AcpRuntime` detection or model listing, a connection to an agent, `shutil.which` of an agent program, a read of the agent command setting, or the policy agent harness. A stand-in agent SHALL NOT count. An untagged test that starts an agent SHALL fail the drift test, naming it.

#### Scenario: A detection call

- **GIVEN** an untagged live test that calls `AcpRuntime().detect`
- **WHEN** the drift test runs
- **THEN** it names the test as starting an agent with no runtime tag

#### Scenario: A signal reached through a helper

- **GIVEN** an untagged live test that calls a function of its module which calls `AcpRuntime().detect`
- **WHEN** the drift test runs
- **THEN** it names the test

#### Scenario: A stand-in in the same module

- **GIVEN** a module with a test that installs a protocol stand-in and sends no prompt, and a test that lists the models of the installed agent
- **WHEN** the drift test runs
- **THEN** only the second test is named, and only while it is untagged

#### Scenario: A shared tick helper

- **GIVEN** an untagged live test that imports `tests.scratch_tick` and calls `run_tick`
- **WHEN** the drift test runs
- **THEN** it names the test

### Requirement: A runtime tag agrees with the runtime the test starts

A live-stack test with a runtime tag SHALL be named by the drift test when what it starts is another runtime: `claude` or the `claude_code` runtime under `runtime_acp`, a protocol agent under `runtime_claude_code`. A test of a protocol agent that adapts Claude (`claude-agent-acp`) is a protocol test. A test with no tag SHALL NOT be compared.

#### Scenario: A real claude tagged for ACP

- **GIVEN** a test tagged `runtime_acp` that builds its scratch installation with `runtime_scratch("claude_code", ...)`
- **WHEN** the drift test runs
- **THEN** it names the test, its tag and the runtime it starts

#### Scenario: A claude program tagged for ACP

- **GIVEN** a test tagged `runtime_acp` that calls `shutil.which("claude")`
- **WHEN** the drift test runs
- **THEN** it names the test

#### Scenario: A protocol agent tagged for Claude

- **GIVEN** a test tagged `runtime_claude_code` that reads the agent command setting
- **WHEN** the drift test runs
- **THEN** it names the test

#### Scenario: A correctly tagged parametrisation

- **GIVEN** a test parametrised over both runtimes, each parameter carrying its own tag
- **WHEN** the drift test runs
- **THEN** nothing is named

#### Scenario: A stub is not an agent

- **GIVEN** an untagged test that puts a `claude` stub on a scratch path
- **WHEN** the drift test runs
- **THEN** its tag is not compared

### Requirement: The installed-agent listing test is tagged for the ACP runtime

`tests/integration/test_init_runtime_live_stack.py`'s test that lists the models of the installed protocol agent and sends no prompt SHALL carry `runtime_acp`, and its module SHALL state in `ACP_ONLY_REASONS` why it has no Claude variant. The stand-in tests of that module SHALL carry no runtime tag.

#### Scenario: The listing test is tagged

- **GIVEN** the kit's `test_init_runtime_live_stack.py`
- **WHEN** it is collected
- **THEN** the listing test's runtime tags are exactly `runtime_acp`, and the reasons table holds a non-empty reason for it

#### Scenario: A stand-in test stays untagged

- **GIVEN** a test of the same module that installs a stand-in agent
- **WHEN** it is collected
- **THEN** it has no runtime tag and the drift test does not name it

### Requirement: The split names and the runtime markers cannot drift apart

The kit's tests SHALL fail when the splits derived from the registered `runtime_<name>` markers (`<name>` each, `rest` for no tag) differ from the splits of the example in `docs/agent-runtimes.md`, naming each extra marker and each extra split, and when a tagged live test is in more than one split. `abk e2e-test check` SHALL keep warning, without changing its exit status, about a group whose own test is in a split other than its `Split:` line.

#### Scenario: A marker with no split

- **GIVEN** a registered `runtime_foo` marker and no `foo` split in the documented example
- **WHEN** the test runs
- **THEN** it fails naming `foo`

#### Scenario: A split with no marker

- **GIVEN** a documented split with no registered marker of its name
- **WHEN** the test runs
- **THEN** it fails naming the split

#### Scenario: The product's check is unchanged

- **GIVEN** a group declared `rest` whose own test is in `acp`
- **WHEN** `abk e2e-test check` runs
- **THEN** it prints its warning and its exit status is the one it would have without it

### Requirement: Claude scenarios with no ACP sibling are listed, not refused

The drift module SHALL return the sorted list of Claude-tagged scenarios that have no ACP sibling and no entry in the module's optional table of Claude-only reasons, and the runtimes document SHALL carry that list. A scenario missing from the document, or listed there and no longer a gap, SHALL raise a warning naming it. A gap SHALL NOT fail any test.

#### Scenario: A Claude-only scenario

- **GIVEN** a scenario tagged `runtime_claude_code` with no `runtime_acp` sibling
- **WHEN** the gap list is computed
- **THEN** it is in the list as `file::scenario`, and no test fails

#### Scenario: A scenario with both runtimes

- **GIVEN** a scenario parametrised over both runtimes
- **WHEN** the gap list is computed
- **THEN** it is not in the list

#### Scenario: A new gap not in the document

- **GIVEN** a gap that the document's list does not hold
- **WHEN** the warning test runs
- **THEN** it raises a warning naming the scenario and does not fail

### Requirement: The documents say what the drift test checks and what it leaves out

`docs/agent-runtimes.md`, `AGENTS.md` and the changelog SHALL describe the discovery, the signals, the comparison of a tag with what the test starts, the split-name check and the gap list, and SHALL record that `<redacted>` and `<redacted>` have no equivalent test and no runtime markers and that adding them is a follow-up and not part of this rule.

#### Scenario: The other repos are recorded

- **GIVEN** the runtimes document
- **WHEN** its drift section is read
- **THEN** it says `<redacted>` and `<redacted>` have no drift test and no runtime markers, and that this is a follow-up
