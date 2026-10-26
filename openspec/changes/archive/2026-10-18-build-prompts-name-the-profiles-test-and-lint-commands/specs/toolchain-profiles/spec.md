## ADDED Requirements

### Requirement: A toolchain profile may name the commands a build agent may run

A toolchain profile SHALL be able to provide an ordered list of agent commands, each with a purpose (`test`, `lint`,
`format` or `check`), a command as an argument list and a scope (`whole`, `file` or `node-id`), where the word `{path}`
stands for what the agent picks and appears exactly when the scope is not `whole`. The list SHALL be optional: a profile
that does not provide it gives no commands and behaves as before. `python-uv` and `node-npm` SHALL provide values. Code
outside the profiles, init and the runtimes SHALL name no ecosystem or product when it reads them.

#### Scenario: The python profile

- **WHEN** the commands of the `python-uv` profile are read
- **THEN** they include `uv run pytest -q` as test at whole scope, `uv run pytest -q {path}` at file scope, and
  `uv run pre-commit run --all-files` as check

#### Scenario: The node profile

- **WHEN** the commands of the `node-npm` profile are read
- **THEN** they include a test, a lint, a format and a check command, each starting `npx`

#### Scenario: A profile without the list

- **GIVEN** a profile registered without agent commands
- **WHEN** a repo uses it with no override
- **THEN** its effective commands are empty and nothing fails

#### Scenario: A placeholder that does not fit its scope

- **WHEN** a command at `whole` scope holds `{path}`, or one at `file` scope does not
- **THEN** it is refused

#### Scenario: The framework names no ecosystem

- **WHEN** the module that composes and renders the effective commands is scanned
- **THEN** it holds no profile name and no tool name

### Requirement: A repo may replace the commands in abk.yaml

`repos.<name>.agent_commands` SHALL take a list of commands (a string is split into arguments) and replace the profile
commands for that repo, an empty list meaning none. When absent the repo follows its profiles: the repo profile's commands,
then each project profile's, each once. An unknown key SHALL be refused, and `abk config --show` SHALL print the key.

#### Scenario: Default

- **WHEN** a repo sets no `agent_commands`
- **THEN** `abk config --show` prints `agent_commands: null` and the effective list is the profiles' commands

#### Scenario: Replaced

- **GIVEN** `agent_commands` holding one test command
- **THEN** the effective list is that command only

#### Scenario: Several projects

- **GIVEN** a repo with a project of another profile
- **THEN** the effective list is the repo profile's commands followed by the project's, a repeated command once

### Requirement: Every named command matches the build allow-list

A command named for an agent SHALL match a `Bash(...)` pattern of the tool list the build is started with
(`wiring.allowed_tools` for the repo, its forge and its projects), judged by the matcher the ACP runtime applies, which
refuses a line that chains another command. An `agent_commands` list in `abk.yaml` with a command that does not match SHALL
be refused when the configuration loads, naming the repo, the position, the command line and the allow-list. `abk doctor`
SHALL report the effective list of each repo: ok, info when there is none, and FAIL for a command outside the allow-list
(a profile's own list included, which is not a load error). The matcher SHALL live where it can be imported without the
protocol library.

#### Scenario: A command the list refuses

- **GIVEN** `agent_commands` holding `python -m pytest tests -q`, `ruff check .` or `uv run pytest -q; echo $?`
- **WHEN** the configuration loads
- **THEN** it fails naming the repo and that command

#### Scenario: A command it allows

- **GIVEN** `agent_commands` holding `uv run pytest -q` for a `python-uv` repo
- **THEN** the configuration loads

#### Scenario: A profile whose own command is outside its list

- **GIVEN** a profile providing a command its `allowed_tools` do not match
- **WHEN** `abk doctor` runs
- **THEN** it prints a FAIL naming the profile and the command, and the configuration still loads

#### Scenario: The built-in profiles

- **WHEN** every registered profile is checked
- **THEN** each of its commands matches its own `allowed_tools`

#### Scenario: Loading without the protocol library

- **GIVEN** the protocol library cannot be imported
- **WHEN** the configuration loads and the check runs
- **THEN** it works, and the ACP runtime's `allows` is the same function
