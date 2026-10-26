# build-prompts Specification

## Purpose
TBD - created by archiving change build-prompts-name-the-profiles-test-and-lint-commands. Update Purpose after archive.

## Requirements

### Requirement: The build prompts name the commands the agent may run

The full prompts that tell a build agent to run tests or lint (tests, implementation, review feedback, checks fix, rework
and adapt) SHALL carry a section "Commands you may run", filled from the repo's effective agent commands, listing each with
its purpose, its scope and its command line, and saying that any other command will be refused. The commands SHALL come
from the profile object and the repo configuration, never from text typed per toolchain into the prompt. A continuation
prompt, which goes to a session that already holds the full prompt, and prompts that name no command to run SHALL not carry it.

#### Scenario: The tests prompt for a python repo

- **GIVEN** a `python-uv` repo with no override
- **WHEN** the tests prompt is built
- **THEN** it names `uv run pytest -q` and `uv run pre-commit run --all-files` and says other commands are refused

#### Scenario: Every full prompt

- **WHEN** each of the six full prompts is built for that repo
- **THEN** each holds the section once

#### Scenario: An override

- **GIVEN** `agent_commands` set for the repo
- **THEN** the section lists those commands and not the profile's

#### Scenario: A continuation

- **WHEN** a continuation prompt is built
- **THEN** it does not hold the section

#### Scenario: Another toolchain

- **GIVEN** a `node-npm` repo
- **THEN** the section lists its `npx` commands, and no word of the prompt template names that toolchain

### Requirement: The section is short and absent when there are no commands

The section SHALL add at most 600 characters. Whole lines SHALL be added in order until the next does not fit; a line is
never cut. With no effective commands the prompt SHALL be byte for byte what it was without this requirement.

#### Scenario: Within the bound

- **WHEN** the section is built for each built-in profile
- **THEN** it is under 600 characters

#### Scenario: Too many commands

- **GIVEN** commands that together pass the bound
- **THEN** the leading ones whole are listed, the rest are left out, and `abk doctor` warns

#### Scenario: No commands

- **GIVEN** a repo whose profile gives none and with no override
- **THEN** every prompt equals the rendering with an empty section, and holds no "Commands you may run"

### Requirement: A repo with no instruction file needs none for its agent to verify its work

A build in a repo whose worktree holds no instruction file that names the test runner SHALL still tell the agent which
commands to run, so the agent is not left to choose a command the allow-list refuses.

#### Scenario: The scratch app

- **GIVEN** the scratch application used by the build tests, a `python-uv` repo with no instruction file
- **WHEN** the tests prompt is built
- **THEN** every command it names matches the build allow-list
